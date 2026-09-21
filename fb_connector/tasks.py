import os
import tempfile
import json
import time
import hashlib
from urllib.parse import urlparse

from fb_connector.celery_app import celery_app
import requests
import uuid
from datetime import datetime, timedelta
from redis import Redis
from redis.exceptions import LockError
from sqlalchemy import or_

from core.logger import logger
from core.enums import ErrorCategory
from services.request_signer import build_signature_headers

from config.settings import settings
from fb_connector.credential_store import DatabaseCredentialVault, report_meta_auth_failure
from services.meta import MetaAdsService, MetaClient
from services.meta.errors import MetaApiError


def _media_account_lock(account_id: str):
    """创建跨 media worker 的账户级 Redis 锁。"""
    redis_client = Redis.from_url(
        settings.CELERY_BROKER_URL,
        socket_connect_timeout=settings.REDIS_TIMEOUT,
        socket_timeout=settings.REDIS_TIMEOUT,
    )
    return redis_client.lock(
        f"fb_connector:media_account:{account_id}",
        timeout=settings.CONNECTOR_MEDIA_ACCOUNT_LOCK_TTL,
    )


def _connector_error_retryable(exc: Exception, auth_failed: bool = False) -> bool:
    """Only retry transport/rate-limit errors; validation errors are terminal."""
    return not auth_failed and (not isinstance(exc, MetaApiError) or exc.retryable)


def _deliver_callback_event(session, event) -> bool:
    """发送一条已落库的回调事件；失败时写入退避时间，不影响业务任务。"""
    if event.status == "SENT":
        return True
    now = datetime.utcnow()
    event.attempt_count = (event.attempt_count or 0) + 1
    event.status = "SENDING"
    event.updated_at = now
    session.commit()

    body = json.dumps(event.payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    headers = build_signature_headers(
        settings.SAAS_INTERNAL_SIGNING_KEY,
        "fb_connector",
        event.event_id,
        "POST",
        event.callback_path,
        body,
        event.idempotency_key,
    )
    headers["Content-Type"] = "application/json"
    callback = f"{settings.SAAS_CALLBACK_BASE_URL.rstrip('/')}{event.callback_path}"
    try:
        response = requests.post(
            callback,
            data=body,
            headers=headers,
            timeout=min(settings.FB_CONNECTOR_TIMEOUT, 10),
        )
        response.raise_for_status()
        event.status = "SENT"
        event.sent_at = datetime.utcnow()
        event.next_retry_at = None
        event.last_error = None
        event.updated_at = datetime.utcnow()
        session.commit()
        logger.info(
            "[ConnectorCallback] sent path=%s event_id=%s status=%s task_id=%s attempt=%s",
            event.callback_path,
            event.event_id,
            response.status_code,
            event.task_id,
            event.attempt_count,
        )
        return True
    except Exception as exc:
        delay = min(
            settings.CONNECTOR_CALLBACK_RETRY_MAX_SECONDS,
            settings.CONNECTOR_CALLBACK_RETRY_BASE_SECONDS
            * (2 ** min(max(event.attempt_count - 1, 0), 8)),
        )
        event.status = "RETRY"
        event.next_retry_at = datetime.utcnow() + timedelta(seconds=delay)
        event.last_error = str(exc)[:1000]
        event.updated_at = datetime.utcnow()
        session.commit()
        logger.warning(
            "[ConnectorCallback] send failed path=%s event_id=%s task_id=%s attempt=%s retry_in=%ss error=%s",
            event.callback_path,
            event.event_id,
            event.task_id,
            event.attempt_count,
            delay,
            exc,
        )
        return False


def _notify_saas_status(path: str, payload: dict, idempotency_key: str) -> bool:
    """先写入 Connector outbox，再尽快发送；回调失败不阻断 Meta 任务。"""
    if not settings.SAAS_CALLBACK_BASE_URL or not settings.SAAS_INTERNAL_SIGNING_KEY:
        return False
    from fb_connector.models import ConnectorCallbackEvent, connector_session_factory

    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    # 同一任务同一状态和同一 payload 使用稳定事件 ID，网络重试不会制造业务重复。
    request_id = uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"fb-connector:{path}:{idempotency_key}:{hashlib.sha256(body).hexdigest()}",
    ).hex
    session = connector_session_factory()
    try:
        event = session.get(ConnectorCallbackEvent, request_id)
        if not event:
            event = ConnectorCallbackEvent(
                event_id=request_id,
                task_id=str(payload.get("task_id") or "unknown"),
                event_type=str(payload.get("event") or "connector.status"),
                callback_path=path,
                idempotency_key=idempotency_key,
                payload=payload,
                status="PENDING",
                next_retry_at=None,
            )
            session.add(event)
            try:
                session.commit()
            except Exception:
                # 并发 Worker 可能同时产生同一状态事件；唯一 event_id 保证只保留一条。
                session.rollback()
                event = session.get(ConnectorCallbackEvent, request_id)
                if not event:
                    raise
        return _deliver_callback_event(session, event)
    except Exception as exc:
        logger.warning(
            "[ConnectorCallback] outbox failed path=%s event_id=%s task_id=%s error=%s",
            path,
            request_id,
            payload.get("task_id"),
            exc,
        )
        return False
    finally:
        session.close()


@celery_app.task(name="fb_connector.retry_saas_callbacks")
def retry_saas_callbacks(limit: int = 100):
    """定时投递失败回调，并恢复 Worker 中断时遗留的 SENDING 事件。"""
    from fb_connector.models import ConnectorCallbackEvent, connector_session_factory

    session = connector_session_factory()
    now = datetime.utcnow()
    recovered = 0
    sent = 0
    failed = 0
    try:
        stale_cutoff = now - timedelta(seconds=settings.CONNECTOR_CALLBACK_STALE_SECONDS)
        stale = (
            session.query(ConnectorCallbackEvent)
            .filter(
                ConnectorCallbackEvent.status == "SENDING",
                ConnectorCallbackEvent.updated_at < stale_cutoff,
            )
            .with_for_update(skip_locked=True)
            .limit(limit)
            .all()
        )
        for event in stale:
            event.status = "RETRY"
            event.next_retry_at = now
            event.last_error = event.last_error or "回调发送进程中断，自动恢复"
            event.updated_at = now
            recovered += 1
        session.commit()

        due = (
            session.query(ConnectorCallbackEvent)
            .filter(
                ConnectorCallbackEvent.status.in_(["PENDING", "RETRY"]),
                or_(
                    ConnectorCallbackEvent.next_retry_at.is_(None),
                    ConnectorCallbackEvent.next_retry_at <= now,
                ),
            )
            .order_by(ConnectorCallbackEvent.created_at.asc())
            .with_for_update(skip_locked=True)
            .limit(limit)
            .all()
        )
        for event in due:
            if _deliver_callback_event(session, event):
                sent += 1
            else:
                failed += 1
        return {"recovered": recovered, "sent": sent, "failed": failed}
    finally:
        session.close()


def _notify_media_status(row, *, media_id: str, account_id: str) -> bool:
    return _notify_saas_status(
        "/api/v1/internal/fb-connector/media-status",
        {
            "event": "media.status",
            "task_id": row.task_id,
            "media_id": media_id,
            "account_id": account_id,
            "status": row.status,
            "phase": row.phase,
            "meta_asset_id": row.meta_asset_id,
            "meta_thumbnail_hash": row.meta_thumbnail_hash,
            "uploaded_bytes": row.uploaded_bytes,
            "total_bytes": row.total_bytes,
            "error_message": row.error_message,
        },
        row.idempotency_key,
    )


def _notify_delivery_status(row, *, source_task_id: str | None = None) -> bool:
    return _notify_saas_status(
        "/api/v1/internal/fb-connector/delivery-status",
        {
            "event": "delivery.status",
            "task_id": row.task_id,
            "source_task_id": source_task_id or row.source_task_id,
            "account_id": row.account_id,
            "status": row.status,
            "step": row.step,
            "campaign_id": row.campaign_id,
            "objects": row.objects or {},
            "error_message": row.error_message,
        },
        row.idempotency_key,
    )


def _refresh_source_url(task_id: str, media_id: str, source_url: str) -> str:
    """在海外 Worker 真正开始下载前刷新国内 OSS 签名 URL。

    兼容未配置刷新回调的旧环境：刷新失败时保留原 URL，后续下载错误
    仍会进入 Celery 重试；生产配置完整时可避免队列等待导致 URL 过期。
    """
    if not settings.SAAS_CALLBACK_BASE_URL or not settings.SAAS_INTERNAL_SIGNING_KEY:
        return source_url

    path = "/api/v1/internal/fb-connector/media-source"
    request_id = uuid.uuid4().hex
    body = json.dumps(
        {"task_id": task_id, "media_id": media_id},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    headers = build_signature_headers(
        settings.SAAS_INTERNAL_SIGNING_KEY,
        "fb_connector",
        request_id,
        "POST",
        path,
        body,
        task_id,
    )
    headers["Content-Type"] = "application/json"
    callback = f"{settings.SAAS_CALLBACK_BASE_URL.rstrip('/')}{path}"
    try:
        response = requests.post(
            callback,
            data=body,
            headers=headers,
            timeout=settings.FB_CONNECTOR_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
        refreshed = payload.get("url") if isinstance(payload, dict) else None
        if not refreshed:
            raise RuntimeError("SaaS 素材刷新接口未返回 url")
        logger.info(
            "[ConnectorMedia] source URL refreshed task_id=%s media_id=%s expires_in=%s",
            task_id,
            media_id,
            payload.get("expires_in", ""),
        )
        return refreshed
    except Exception as exc:
        logger.warning(
            "[ConnectorMedia] source URL refresh failed task_id=%s media_id=%s error=%s; fallback to stored URL",
            task_id,
            media_id,
            exc,
        )
        return source_url


def _refresh_cover_url(task_id: str, media_id: str, cover_url: str) -> str:
    """刷新视频封面签名 URL；刷新失败时回退到任务中保存的 URL。"""
    if not settings.SAAS_CALLBACK_BASE_URL or not settings.SAAS_INTERNAL_SIGNING_KEY:
        return cover_url

    path = "/api/v1/internal/fb-connector/media-source"
    request_id = uuid.uuid4().hex
    body = json.dumps(
        {"task_id": task_id, "media_id": media_id},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    headers = build_signature_headers(
        settings.SAAS_INTERNAL_SIGNING_KEY,
        "fb_connector",
        request_id,
        "POST",
        path,
        body,
        task_id,
    )
    headers["Content-Type"] = "application/json"
    callback = f"{settings.SAAS_CALLBACK_BASE_URL.rstrip('/')}{path}"
    try:
        response = requests.post(
            callback,
            data=body,
            headers=headers,
            timeout=settings.FB_CONNECTOR_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
        refreshed = payload.get("cover_url") if isinstance(payload, dict) else None
        if not refreshed:
            raise RuntimeError("SaaS 素材刷新接口未返回 cover_url")
        logger.info(
            "[ConnectorMedia] cover URL refreshed task_id=%s media_id=%s expires_in=%s",
            task_id,
            media_id,
            payload.get("expires_in", ""),
        )
        return refreshed
    except Exception as exc:
        logger.warning(
            "[ConnectorMedia] cover URL refresh failed task_id=%s media_id=%s error=%s; fallback to stored URL",
            task_id,
            media_id,
            exc,
        )
        return cover_url


def _download_cover_file(task_id: str, media_id: str, cover_url: str) -> str:
    """下载视频封面到临时文件，限制大小避免封面 URL 被滥用占满磁盘。"""
    os.makedirs(settings.CONNECTOR_MEDIA_TEMP_DIR, exist_ok=True)
    with requests.get(
        cover_url,
        stream=True,
        timeout=(settings.FB_VIDEO_CONNECT_TIMEOUT, settings.FB_VIDEO_UPLOAD_TIMEOUT),
    ) as response:
        response.raise_for_status()
        content_length = _as_int(response.headers.get("Content-Length"))
        if content_length is not None and content_length > settings.CONNECTOR_MEDIA_MAX_DOWNLOAD_BYTES:
            raise RuntimeError("视频封面超过 Connector 本地临时磁盘保护上限")
        with tempfile.NamedTemporaryFile(
            delete=False,
            suffix=".jpg",
            dir=settings.CONNECTOR_MEDIA_TEMP_DIR,
        ) as target:
            path = target.name
            written = 0
            for chunk in response.iter_content(chunk_size=256 * 1024):
                if chunk:
                    written += len(chunk)
                    if written > settings.CONNECTOR_MEDIA_MAX_DOWNLOAD_BYTES:
                        raise RuntimeError("视频封面超过 Connector 本地临时磁盘保护上限")
                    target.write(chunk)
    logger.info(
        "[ConnectorMedia] cover download complete task_id=%s media_id=%s bytes=%s path=%s",
        task_id,
        media_id,
        written,
        path,
    )
    return path


@celery_app.task(name="fb_connector.recover_stale_media_tasks")
def recover_stale_media_tasks(limit: int = 100):
    """恢复 Worker 重启或强制终止后遗留的媒体上传任务。"""
    from fb_connector.models import ConnectorMediaTask, connector_session_factory

    cutoff = datetime.utcnow() - timedelta(seconds=settings.CONNECTOR_MEDIA_STALE_SECONDS)
    session = connector_session_factory()
    recovered = 0
    skipped = 0
    try:
        rows = (
            session.query(ConnectorMediaTask)
            .filter(
                ConnectorMediaTask.status.in_(("QUEUED", "UPLOADING", "RETRY")),
                ConnectorMediaTask.updated_at < cutoff,
            )
            .order_by(ConnectorMediaTask.updated_at.asc())
            .with_for_update(skip_locked=True)
            .limit(limit)
            .all()
        )
        for row in rows:
            if not row.credential_id or not row.account_id or not row.asset_type or not row.source_url:
                skipped += 1
                logger.warning(
                    "[ConnectorMediaRecovery] skip task_id=%s reason=missing_payload status=%s",
                    row.task_id,
                    row.status,
                )
                continue
            row.status = "QUEUED"
            row.error_message = None
            row.updated_at = datetime.utcnow()
            session.commit()
            try:
                upload_media_task.delay(
                    row.task_id,
                    row.media_id,
                    row.credential_id,
                    row.account_id,
                    row.asset_type,
                    row.source_url,
                    row.idempotency_key,
                    row.expected_md5,
                    row.cover_url,
                )
                recovered += 1
                logger.warning("[ConnectorMediaRecovery] requeued task_id=%s", row.task_id)
            except Exception as exc:
                session.rollback()
                row = session.get(ConnectorMediaTask, row.task_id)
                if row:
                    row.status = "FAILED"
                    row.error_message = f"恢复任务入队失败: {exc}"[:1000]
                    session.commit()
                logger.exception("[ConnectorMediaRecovery] enqueue failed task_id=%s", row.task_id)
        return {"recovered": recovered, "skipped": skipped}
    finally:
        session.close()

@celery_app.task(bind=True, name="fb_connector.fetch_insights", max_retries=3, default_retry_delay=60)
def fetch_insights_task(self, credential_id: str, account_id: str, days: int = 1):
    """海外拉取 Insights，并将结果签名回调 SaaS。"""
    # Celery 重试必须复用同一 request_id，SaaS 回调才能幂等去重。
    request_id = self.request.id or uuid.uuid4().hex
    try:
        logger.info(
            "[ConnectorInsights] start request_id=%s credential_id=%s account_id=%s days=%s retry=%s",
            request_id,
            credential_id,
            account_id,
            days,
            self.request.retries,
        )
        token = DatabaseCredentialVault().get_access_token(credential_id)
        rows = MetaAdsService(MetaClient(access_token=token)).get_insights(
            account_id,
            {"date_preset": f"last_{days}d", "level": "account"},
        )
        payload = {
            "event": "insights.completed",
            "request_id": request_id,
            "credential_id": credential_id,
            "account_id": account_id,
            "days": days,
            "items": rows,
        }
        callback = f"{settings.SAAS_CALLBACK_BASE_URL.rstrip('/')}/api/v1/internal/fb-connector/insights"
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        headers = build_signature_headers(
            settings.SAAS_INTERNAL_SIGNING_KEY,
            "fb_connector",
            request_id,
            "POST",
            "/api/v1/internal/fb-connector/insights",
            body,
        )
        headers["Content-Type"] = "application/json"
        logger.info("[ConnectorInsights] callback start request_id=%s rows=%s", request_id, len(rows))
        response = requests.post(callback, data=body, headers=headers, timeout=settings.FB_CONNECTOR_TIMEOUT)
        response.raise_for_status()
        logger.info("[ConnectorInsights] success request_id=%s rows=%s callback_status=%s", request_id, len(rows), response.status_code)
        return {"status": "SUCCESS", "account_id": account_id, "count": len(rows), "request_id": request_id}
    except Exception as exc:
        auth_failed = report_meta_auth_failure(credential_id, exc)
        logger.exception("[ConnectorInsights] failed request_id=%s account_id=%s error=%s", request_id, account_id, exc)
        if not _connector_error_retryable(exc, auth_failed):
            raise
        raise self.retry(exc=exc)

@celery_app.task(bind=True, name="fb_connector.create_campaign", max_retries=2, default_retry_delay=30)
def create_campaign_task(self, connector_task_id: str, credential_id: str, account_id: str, payload: dict, idempotency_key: str):
    """按 Campaign → AdSet → Creative → Ad 顺序执行 Meta 写操作。"""
    created = []
    from fb_connector.models import ConnectorDeliveryTask, connector_session_factory
    session = connector_session_factory()
    row = None
    retries = self.request.retries
    try:
        logger.info(
            "[ConnectorCampaign] start connector_task_id=%s account_id=%s retry=%s",
            connector_task_id,
            account_id,
            retries,
        )
        row = session.get(ConnectorDeliveryTask, connector_task_id)
        if not row:
            raise RuntimeError("投放任务不存在")
        credential_id = row.credential_id or credential_id
        account_id = row.account_id or account_id
        payload = row.request_payload or payload
        if row.status == "SUCCESS" and row.campaign_id:
            logger.info("[ConnectorCampaign] already success connector_task_id=%s campaign_id=%s", connector_task_id, row.campaign_id)
            _notify_delivery_status(row)
            return {"status": "SUCCESS", "connector_task_id": connector_task_id, "campaign_id": row.campaign_id, "objects": row.objects or {}, "idempotency_key": idempotency_key}
        row.status = "RUNNING"; row.step = row.step if row.step != "QUEUED" else "CAMPAIGN"; session.commit()
        _notify_delivery_status(row)
        logger.info("[ConnectorCampaign] status=RUNNING connector_task_id=%s step=%s", connector_task_id, row.step)
        token = DatabaseCredentialVault().get_access_token(credential_id)
        service = MetaAdsService(MetaClient(access_token=token))

        campaign_id = row.campaign_id
        if not campaign_id:
            campaign_payload = dict(payload.get("campaign") or {})
            reuse_campaign_id = campaign_payload.pop("existing_id", None) or campaign_payload.pop("reuse_id", None)
            if reuse_campaign_id:
                campaign_id = str(reuse_campaign_id)
                logger.info(
                    "[ConnectorCampaign] reuse campaign connector_task_id=%s campaign_id=%s",
                    connector_task_id,
                    campaign_id,
                )
            else:
                campaign = service.create_campaign(account_id, campaign_payload)
                campaign_id = campaign["id"]
                created.append(campaign_id)
            row.campaign_id = campaign_id
            row.step = "ADSET"
            session.commit()
            if not reuse_campaign_id:
                logger.info("[ConnectorCampaign] campaign created connector_task_id=%s campaign_id=%s", connector_task_id, campaign_id)

        object_map = {
            "adsets": list((row.objects or {}).get("adsets") or []),
            "creatives": list((row.objects or {}).get("creatives") or []),
            "ads": list((row.objects or {}).get("ads") or []),
        }

        def existing_id(group: str, client_key: str | None) -> str | None:
            if not client_key:
                return None
            return next((item.get("id") for item in object_map[group] if item.get("client_key") == client_key and item.get("id")), None)

        def remember(group: str, client_key: str | None, object_id: str, **extra) -> None:
            if existing_id(group, client_key):
                return
            object_map[group].append({"client_key": client_key, "id": object_id, **extra})

        adset_ids = [item.get("id") for item in object_map["adsets"] if item.get("id")]
        ad_ids = [item.get("id") for item in object_map["ads"] if item.get("id")]
        for raw_adset in payload.get("adsets") or []:
            adset = dict(raw_adset)
            creatives = adset.pop("creatives", []) or []
            adset_key = adset.get("client_key")
            adset_id = existing_id("adsets", adset_key)
            reuse_adset_id = adset.pop("existing_id", None) or adset.pop("reuse_id", None)
            if reuse_adset_id:
                adset_id = str(reuse_adset_id)
                remember("adsets", adset_key, adset_id, reused=True)
                logger.info(
                    "[ConnectorCampaign] reuse adset connector_task_id=%s client_key=%s id=%s",
                    connector_task_id,
                    adset_key,
                    adset_id,
                )
            if not adset_id:
                adset.pop("client_key", None)
                result = service.create_adset(account_id, {**adset, "campaign_id": campaign_id})
                adset_id = result["id"]
                created.append(adset_id)
                remember("adsets", adset_key, adset_id)
                row.objects = object_map
                row.step = "ADSET"
                session.commit()
                logger.info("[ConnectorCampaign] adset created connector_task_id=%s client_key=%s id=%s", connector_task_id, adset_key, adset_id)
            if adset_id not in adset_ids:
                adset_ids.append(adset_id)

            for raw_creative in creatives:
                creative = dict(raw_creative)
                ads = creative.pop("ads", []) or []
                creative_key = creative.pop("client_key", None)
                creative_id = existing_id("creatives", creative_key)
                if not creative_id:
                    creative_result = service.create_creative(account_id, creative)
                    creative_id = creative_result["id"]
                    created.append(creative_id)
                    remember("creatives", creative_key, creative_id)
                    row.objects = object_map
                    row.step = "CREATIVE"
                    session.commit()
                    logger.info("[ConnectorCampaign] creative created connector_task_id=%s client_key=%s id=%s", connector_task_id, creative_key, creative_id)

                for raw_ad in ads:
                    ad = dict(raw_ad)
                    ad_key = ad.pop("client_key", None)
                    ad.pop("adset_id", None)
                    ad.pop("creative", None)
                    ad_id = existing_id("ads", ad_key)
                    if not ad_id:
                        ad_result = service.create_ad(
                            account_id,
                            {**ad, "adset_id": adset_id, "creative": {"creative_id": creative_id}},
                        )
                        ad_id = ad_result["id"]
                        created.append(ad_id)
                        remember("ads", ad_key, ad_id, adset_id=adset_id)
                        row.objects = object_map
                        row.step = "AD"
                        session.commit()
                        logger.info("[ConnectorCampaign] ad created connector_task_id=%s client_key=%s id=%s", connector_task_id, ad_key, ad_id)
                    if ad_id not in ad_ids:
                        ad_ids.append(ad_id)

        for raw_ad in payload.get("ads") or []:
            ad = dict(raw_ad)
            ad_key = ad.pop("client_key", None)
            adset_id = ad.pop("adset_id", None) or (adset_ids[0] if adset_ids else None)
            ad_id = existing_id("ads", ad_key)
            if not ad_id:
                ad_result = service.create_ad(account_id, {**ad, "adset_id": adset_id})
                ad_id = ad_result["id"]
                created.append(ad_id)
                remember("ads", ad_key, ad_id, adset_id=adset_id)
                row.objects = object_map
                row.step = "AD"
                session.commit()
                logger.info("[ConnectorCampaign] root ad created connector_task_id=%s client_key=%s id=%s", connector_task_id, ad_key, ad_id)
            if ad_id not in ad_ids:
                ad_ids.append(ad_id)

        row.objects = object_map
        row.status = "SUCCESS"; row.step = "DONE"; session.commit()
        _notify_delivery_status(row)
        logger.info("[ConnectorCampaign] success connector_task_id=%s campaign_id=%s", connector_task_id, campaign_id)
        return {"status": "SUCCESS", "connector_task_id": connector_task_id, "campaign_id": campaign_id, "objects": object_map, "adset_ids": adset_ids, "ad_ids": ad_ids, "idempotency_key": idempotency_key}
    except Exception as exc:
        # 保留已创建对象 ID，补偿删除由后续审计/人工策略执行，避免误删用户资产。
        auth_failed = report_meta_auth_failure(credential_id, exc)
        logger.exception("[ConnectorCampaign] failed connector_task_id=%s retry=%s created=%s", connector_task_id, retries, created)
        session.rollback()
        row = row or session.get(ConnectorDeliveryTask, connector_task_id)
        if row:
            will_retry = retries < self.max_retries and _connector_error_retryable(exc, auth_failed)
            row.status = "RETRY" if will_retry else "FAILED"
            row.error_message = f"已创建对象={created}: {exc}"[:1000]
            session.commit()
            _notify_delivery_status(row)
            logger.info("[ConnectorCampaign] status=%s connector_task_id=%s error=%s", row.status, connector_task_id, row.error_message)
        if not _connector_error_retryable(exc, auth_failed):
            raise
        raise self.retry(exc=RuntimeError(f"投放步骤失败，已创建对象={created}: {exc}"))
    finally:
        session.close()


def _persist_media_progress(session, row, **values):
    """提交可恢复的上传检查点，避免 Worker 重启后丢失 Meta 会话和 offset。"""
    for key, value in values.items():
        if value is not None:
            setattr(row, key, value)
    row.updated_at = datetime.utcnow()
    session.commit()


def _as_int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _file_md5(file_path: str) -> str:
    digest = hashlib.md5()
    with open(file_path, "rb") as source:
        for chunk in iter(lambda: source.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _media_cache_dir() -> str:
    return os.path.join(settings.CONNECTOR_MEDIA_TEMP_DIR, "cache")


def _prune_media_cache() -> None:
    """删除过期/超额缓存，避免短期缓存占满 media worker 的 tmpfs。"""
    cache_dir = _media_cache_dir()
    os.makedirs(cache_dir, exist_ok=True)
    now = time.time()
    ttl = max(0, settings.CONNECTOR_MEDIA_CACHE_TTL_SECONDS)
    files = []
    for name in os.listdir(cache_dir):
        path = os.path.join(cache_dir, name)
        try:
            if not os.path.isfile(path):
                continue
            stat = os.stat(path)
            if ttl and now - stat.st_mtime > ttl:
                os.unlink(path)
                continue
            files.append((path, stat.st_mtime, stat.st_size))
        except OSError:
            continue

    max_bytes = max(0, settings.CONNECTOR_MEDIA_CACHE_MAX_BYTES)
    total = sum(item[2] for item in files)
    if max_bytes and total > max_bytes:
        for path, _, size in sorted(files, key=lambda item: item[1]):
            if total <= max_bytes:
                break
            try:
                os.unlink(path)
                total -= size
            except OSError:
                continue


def _find_cached_media(expected_md5: str | None) -> str | None:
    """按内容 MD5 查找并再次校验缓存，避免复用损坏的临时文件。"""
    if not expected_md5 or len(expected_md5) != 32:
        return None
    expected_md5 = expected_md5.lower()
    cache_dir = _media_cache_dir()
    try:
        candidates = [
            os.path.join(cache_dir, name)
            for name in os.listdir(cache_dir)
            if name.startswith(f"{expected_md5}.")
        ]
    except OSError:
        return None
    for path in candidates:
        try:
            if os.path.isfile(path) and _file_md5(path) == expected_md5:
                os.utime(path, None)
                return path
            if os.path.exists(path):
                os.unlink(path)
        except OSError:
            continue
    return None


def _cache_media_file(file_path: str, content_md5: str, suffix: str) -> str:
    cache_dir = _media_cache_dir()
    os.makedirs(cache_dir, exist_ok=True)
    cache_path = os.path.join(cache_dir, f"{content_md5.lower()}{suffix.lower()}")
    os.replace(file_path, cache_path)
    os.utime(cache_path, None)
    return cache_path


_IMAGE_UPLOAD_FORMATS = {
    ".jpg": (".jpg", "image/jpeg"),
    ".jpeg": (".jpeg", "image/jpeg"),
    ".png": (".png", "image/png"),
    ".gif": (".gif", "image/gif"),
}


def _image_upload_format(source_url: str, content_type: str | None = None) -> tuple[str, str]:
    """Return a Meta-compatible image suffix and MIME type."""
    source_suffix = os.path.splitext(urlparse(source_url).path)[1].lower()
    if source_suffix in _IMAGE_UPLOAD_FORMATS:
        return _IMAGE_UPLOAD_FORMATS[source_suffix]

    normalized_type = (content_type or "").split(";", 1)[0].strip().lower()
    for suffix, mime_type in _IMAGE_UPLOAD_FORMATS.values():
        if normalized_type == mime_type or (mime_type == "image/jpeg" and normalized_type == "image/jpg"):
            return suffix, mime_type

    raise MetaApiError(
        f"无法识别图片格式: suffix={source_suffix or '<none>'} content_type={normalized_type or '<none>'}",
        category=ErrorCategory.VALIDATION,
    )


def _upload_video_resumable(service, account_id: str, file_path: str | None, row, session, *, keep_file: bool = False) -> dict:
    """执行 Meta start → transfer → finish → processing 轮询流程。"""
    total_bytes = os.path.getsize(file_path) if file_path else _as_int(row.total_bytes)
    if not total_bytes:
        raise RuntimeError("无法确定视频素材大小，不能恢复 Meta 分片上传")
    if row.total_bytes and row.total_bytes != total_bytes:
        raise RuntimeError(
            f"素材大小在重试期间发生变化: expected={row.total_bytes} actual={total_bytes}"
        )
    if row.phase not in {"META_PROCESSING", "READY"} and not file_path:
        raise RuntimeError(
            f"Meta 分片任务处于 {row.phase or 'UNKNOWN'} 阶段，但本地素材文件不存在"
        )
    _persist_media_progress(
        session,
        row,
        total_bytes=total_bytes,
        uploaded_bytes=_as_int(row.uploaded_bytes, 0),
    )

    upload_session_id = row.upload_session_id
    video_id = row.meta_video_id
    if not upload_session_id or not video_id:
        if not file_path:
            raise RuntimeError(
                "Meta 转码轮询任务缺少上传会话或视频 ID，且本地素材已清理，无法恢复"
            )
        _persist_media_progress(session, row, phase="STARTING", status="UPLOADING")
        started = service.start_video_upload(account_id, total_bytes)
        upload_session_id = started.get("upload_session_id")
        video_id = started.get("video_id") or started.get("id")
        start_offset = _as_int(started.get("start_offset"), 0)
        end_offset = _as_int(started.get("end_offset"))
        if not upload_session_id or not video_id:
            raise RuntimeError(f"Meta 分片上传 start 响应缺少会话或视频 ID: {started}")
        if end_offset is None or end_offset <= start_offset:
            end_offset = min(
                total_bytes,
                start_offset + settings.FB_VIDEO_CHUNK_MAX_BYTES,
            )
        _persist_media_progress(
            session,
            row,
            phase="TRANSFERRING",
            status="UPLOADING",
            upload_session_id=upload_session_id,
            meta_video_id=video_id,
            start_offset=start_offset,
            end_offset=end_offset,
            uploaded_bytes=start_offset,
        )

    start_offset = _as_int(row.start_offset, _as_int(row.uploaded_bytes, 0)) or 0
    end_offset = _as_int(row.end_offset)
    if end_offset is None or end_offset <= start_offset:
        end_offset = min(
            total_bytes,
            start_offset + settings.FB_VIDEO_CHUNK_MAX_BYTES,
        )

    while start_offset < total_bytes:
        end_offset = min(
            max(end_offset, start_offset + 1),
            total_bytes,
            start_offset + settings.FB_VIDEO_CHUNK_MAX_BYTES,
        )
        result = service.transfer_video_chunk(
            account_id,
            file_path,
            upload_session_id,
            start_offset,
            end_offset,
        )
        next_start = _as_int(result.get("start_offset"), end_offset)
        next_end = _as_int(result.get("end_offset"))
        if next_start <= start_offset or next_start > total_bytes:
            raise RuntimeError(
                f"Meta 分片上传 offset 未前进: current={start_offset} "
                f"next={next_start} response={result}"
            )
        if next_end is None or next_end <= next_start:
            next_end = min(
                total_bytes,
                next_start + settings.FB_VIDEO_CHUNK_MAX_BYTES,
            )
        start_offset = next_start
        end_offset = next_end
        _persist_media_progress(
            session,
            row,
            phase="TRANSFERRING",
            status="UPLOADING",
            start_offset=start_offset,
            end_offset=end_offset,
            uploaded_bytes=start_offset,
        )
        logger.info(
            "[ConnectorMedia] transfer task_id=%s start_offset=%s end_offset=%s "
            "uploaded_bytes=%s total_bytes=%s",
            row.task_id,
            start_offset,
            end_offset,
            start_offset,
            total_bytes,
        )

    if row.phase not in {"META_PROCESSING", "READY"}:
        _persist_media_progress(session, row, phase="FINISHING", status="UPLOADING")
        finished = service.finish_video_upload(account_id, upload_session_id)
        video_id = finished.get("video_id") or finished.get("id") or video_id
        _persist_media_progress(
            session,
            row,
            phase="META_PROCESSING",
            status="UPLOADING",
            meta_video_id=video_id,
            uploaded_bytes=total_bytes,
        )
        logger.info(
            "[ConnectorMedia] finish task_id=%s upload_session_id=%s meta_video_id=%s",
            row.task_id,
            upload_session_id,
            video_id,
        )
        if file_path and not keep_file:
            try:
                os.unlink(file_path)
                logger.info(
                    "[ConnectorMedia] local source cleaned task_id=%s path=%s",
                    row.task_id,
                    file_path,
                )
            except OSError as exc:
                logger.warning(
                    "[ConnectorMedia] local source cleanup failed task_id=%s path=%s error=%s",
                    row.task_id,
                    file_path,
                    exc,
                )
        elif file_path:
            logger.info(
                "[ConnectorMedia] local source kept in cache task_id=%s path=%s",
                row.task_id,
                file_path,
            )

    if row.phase == "READY" and row.status == "SUCCESS":
        return {"video_id": video_id or row.meta_asset_id}

    deadline = time.monotonic() + settings.FB_VIDEO_PROCESSING_TIMEOUT
    while True:
        status_result = service.get_video_status(video_id)
        meta_status = str(status_result.get("status") or "unknown").lower()
        logger.info(
            "[ConnectorMedia] processing task_id=%s meta_video_id=%s status=%s",
            row.task_id,
            video_id,
            meta_status,
        )
        if meta_status in {"ready", "success", "completed", "complete"}:
            _persist_media_progress(
                session,
                row,
                phase="READY",
                status="SUCCESS",
                meta_asset_id=video_id,
                meta_video_id=video_id,
                uploaded_bytes=total_bytes,
                start_offset=total_bytes,
                end_offset=total_bytes,
            )
            return {"video_id": video_id}
        if meta_status in {"error", "failed", "failure", "rejected"}:
            raise RuntimeError(
                f"Meta 视频转码失败: video_id={video_id} status={meta_status}"
            )
        if time.monotonic() >= deadline:
            raise RuntimeError(
                f"Meta 视频转码轮询超时: video_id={video_id} "
                f"last_status={meta_status}"
            )
        row.updated_at = datetime.utcnow()
        session.commit()
        time.sleep(settings.FB_VIDEO_STATUS_POLL_INTERVAL)


@celery_app.task(bind=True, name="fb_connector.upload_media", max_retries=3, default_retry_delay=30)
def upload_media_task(self, task_id: str, media_id: str, credential_id: str, account_id: str, asset_type: str, source_url: str, idempotency_key: str, expected_md5: str | None = None, cover_url: str | None = None):
    """海外执行素材下载和 Meta 上传；生产环境应将结果写入 Connector 任务表并回调 SaaS。"""
    temp_path = None
    cover_path = None
    row = None
    account_lock = None
    account_lock_acquired = False
    image_content_type = None
    from fb_connector.models import ConnectorMediaTask, connector_session_factory

    parsed_source = urlparse(source_url)
    source_label = f"{parsed_source.hostname or 'unknown'}{parsed_source.path or '/'}"
    retries = self.request.retries
    logger.info(
        "[ConnectorMedia] start task_id=%s media_id=%s account_id=%s asset_type=%s retry=%s source=%s",
        task_id,
        media_id,
        account_id,
        asset_type,
        retries,
        source_label,
    )
    session = connector_session_factory()
    try:
        row = session.get(ConnectorMediaTask, task_id)
        if not row:
            raise RuntimeError("上传任务不存在")
        expected_md5 = (row.expected_md5 or expected_md5 or "").lower() or None
        cover_url = row.cover_url or cover_url
        if expected_md5 and (len(expected_md5) != 32 or any(char not in "0123456789abcdef" for char in expected_md5)):
            raise MetaApiError("素材 MD5 格式无效", category=ErrorCategory.VALIDATION)
        _prune_media_cache()
        account_id = row.account_id or account_id
        account_lock = _media_account_lock(account_id)
        account_lock_acquired = account_lock.acquire(blocking=False)
        if not account_lock_acquired:
            raise RuntimeError(
                f"广告账户已有其他素材上传任务运行中: account_id={account_id}"
            )
        logger.info(
            "[ConnectorMedia] account lock acquired task_id=%s account_id=%s",
            task_id,
            account_id,
        )
        if row.status == "SUCCESS" and row.meta_asset_id and (
            asset_type != "video" or row.meta_thumbnail_hash
        ):
            logger.info(
                "[ConnectorMedia] already success task_id=%s meta_asset_id=%s",
                task_id,
                row.meta_asset_id,
            )
            _notify_media_status(row, media_id=media_id, account_id=account_id)
            return {
                "status": "SUCCESS",
                "media_id": media_id,
                "idempotency_key": idempotency_key,
                "meta_asset_id": row.meta_asset_id,
                "meta_thumbnail_hash": row.meta_thumbnail_hash,
            }
        row.status = "UPLOADING"
        row.phase = row.phase if row.phase and row.phase not in {"QUEUED", "FAILED"} else "DOWNLOADING"
        row.error_message = None
        session.commit()
        _notify_media_status(row, media_id=media_id, account_id=account_id)
        logger.info(
            "[ConnectorMedia] status=UPLOADING task_id=%s phase=%s",
            task_id,
            row.phase,
        )
        source_required = asset_type != "video" or row.phase not in {"META_PROCESSING", "READY"}
        cache_reused = False
        if source_required:
            cached_path = _find_cached_media(expected_md5)
            if cached_path:
                temp_path = cached_path
                cache_reused = True
                if asset_type == "image":
                    cached_suffix = os.path.splitext(cached_path)[1].lower()
                    image_content_type = dict(_IMAGE_UPLOAD_FORMATS.values()).get(cached_suffix)
                logger.info(
                    "[ConnectorMedia] cache hit task_id=%s md5=%s path=%s",
                    task_id,
                    expected_md5,
                    cached_path,
                )
        if source_required and not cache_reused:
            source_url = _refresh_source_url(
                task_id,
                media_id,
                row.source_url or source_url,
            )
            if source_url != row.source_url:
                row.source_url = source_url
                session.commit()
        bytes_written = _as_int(row.total_bytes, 0) or 0
        if source_required and not cache_reused:
            # 防止把超大文件一次性读入内存，视频上传使用流式写入。
            logger.info(
                "[ConnectorMedia] download start task_id=%s connect_timeout=%ss read_timeout=%ss",
                task_id,
                settings.FB_VIDEO_CONNECT_TIMEOUT,
                settings.FB_VIDEO_UPLOAD_TIMEOUT,
            )
            os.makedirs(settings.CONNECTOR_MEDIA_TEMP_DIR, exist_ok=True)
            bytes_written = 0
            with requests.get(
                source_url,
                stream=True,
                timeout=(settings.FB_VIDEO_CONNECT_TIMEOUT, settings.FB_VIDEO_UPLOAD_TIMEOUT),
            ) as response:
                logger.info(
                    "[ConnectorMedia] download response task_id=%s status=%s content_length=%s",
                    task_id,
                    response.status_code,
                    response.headers.get("Content-Length"),
                )
                response.raise_for_status()
                content_length = _as_int(response.headers.get("Content-Length"))
                if (
                    asset_type == "video"
                    and content_length is not None
                    and content_length > settings.CONNECTOR_MEDIA_MAX_DOWNLOAD_BYTES
                ):
                    raise RuntimeError(
                        "视频素材超过 Connector 本地临时磁盘保护上限: "
                        f"size={content_length} max={settings.CONNECTOR_MEDIA_MAX_DOWNLOAD_BYTES}"
                    )
                if asset_type == "video":
                    suffix = ".mp4"
                else:
                    suffix, image_content_type = _image_upload_format(
                        source_url,
                        response.headers.get("Content-Type"),
                    )
                with tempfile.NamedTemporaryFile(
                    delete=False,
                    suffix=suffix,
                    dir=settings.CONNECTOR_MEDIA_TEMP_DIR,
                ) as target:
                    temp_path = target.name
                    content_md5 = hashlib.md5()
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            content_md5.update(chunk)
                            target.write(chunk)
                            bytes_written += len(chunk)
                            if (
                                asset_type == "video"
                                and bytes_written > settings.CONNECTOR_MEDIA_MAX_DOWNLOAD_BYTES
                            ):
                                raise RuntimeError(
                                    "视频素材超过 Connector 本地临时磁盘保护上限: "
                                    f"size>{settings.CONNECTOR_MEDIA_MAX_DOWNLOAD_BYTES}"
                                )
            actual_md5 = content_md5.hexdigest()
            if expected_md5 and actual_md5 != expected_md5:
                raise MetaApiError(
                    f"素材 MD5 校验失败: expected={expected_md5} actual={actual_md5}",
                    category=ErrorCategory.VALIDATION,
                )
            # 即使国内未传 MD5，也将本次下载结果按实际 MD5 缓存，
            # 便于同一任务重试时复用；后续新请求应优先传 expected_md5。
            expected_md5 = actual_md5
            row.expected_md5 = actual_md5
            temp_path = _cache_media_file(temp_path, actual_md5, suffix)
            cache_reused = True
            logger.info(
                "[ConnectorMedia] download complete task_id=%s bytes=%s md5=%s temp_path=%s",
                task_id,
                bytes_written,
                actual_md5,
                temp_path,
            )
            _persist_media_progress(session, row, expected_md5=actual_md5)
            if asset_type == "video":
                _persist_media_progress(
                    session,
                    row,
                    total_bytes=bytes_written,
                    phase=row.phase if row.phase not in {"QUEUED", "DOWNLOADING", "FAILED"} else "STARTING",
                    status="UPLOADING",
                )
            else:
                _persist_media_progress(session, row, phase="UPLOADING", status="UPLOADING")
        elif source_required and cache_reused:
            logger.info(
                "[ConnectorMedia] skip source download task_id=%s reason=md5_cache_hit path=%s",
                task_id,
                temp_path,
            )
        else:
            logger.info(
                "[ConnectorMedia] skip source download task_id=%s phase=%s "
                "reason=meta_processing_already_started",
                task_id,
                row.phase,
            )
        logger.info("[ConnectorMedia] credential lookup start task_id=%s credential_id=%s", task_id, credential_id)
        token = DatabaseCredentialVault().get_access_token(credential_id)
        logger.info("[ConnectorMedia] meta upload start task_id=%s account_id=%s asset_type=%s", task_id, account_id, asset_type)
        service = MetaAdsService(MetaClient(access_token=token))
        if asset_type == "video":
            result = _upload_video_resumable(
                service,
                account_id,
                temp_path,
                row,
                session,
                keep_file=cache_reused,
            )
            meta_asset_id = result.get("video_id")
            if not row.meta_thumbnail_hash:
                if not cover_url:
                    raise MetaApiError(
                        "视频上传成功但缺少封面 URL",
                        category=ErrorCategory.VALIDATION,
                    )
                cover_url = _refresh_cover_url(task_id, media_id, cover_url)
                cover_path = _download_cover_file(task_id, media_id, cover_url)
                thumbnail_result = service.upload_image(
                    account_id,
                    cover_path,
                    filename=f"{media_id}-cover.jpg",
                    content_type="image/jpeg",
                )
                _persist_media_progress(
                    session,
                    row,
                    meta_asset_id=meta_asset_id,
                    meta_thumbnail_hash=thumbnail_result.get("hash"),
                    phase="READY",
                    status="SUCCESS",
                )
        else:
            result = service.upload_image(
                account_id,
                temp_path,
                content_type=image_content_type,
            )
            meta_asset_id = result.get("hash")
            _persist_media_progress(
                session,
                row,
                phase="READY",
                status="SUCCESS",
                meta_asset_id=meta_asset_id,
            )
        meta_thumbnail_hash = row.meta_thumbnail_hash
        logger.info(
            "[ConnectorMedia] success task_id=%s media_id=%s meta_asset_id=%s meta_thumbnail_hash=%s phase=%s uploaded_bytes=%s total_bytes=%s",
            task_id,
            media_id,
            meta_asset_id,
            meta_thumbnail_hash,
            row.phase,
            row.uploaded_bytes,
            row.total_bytes,
        )
        _notify_media_status(row, media_id=media_id, account_id=account_id)
        return {
            "status": "SUCCESS",
            "media_id": media_id,
            "idempotency_key": idempotency_key,
            "meta_asset_id": meta_asset_id,
            "meta_thumbnail_hash": meta_thumbnail_hash,
        }
    except Exception as exc:
        auth_failed = report_meta_auth_failure(credential_id, exc)
        logger.exception(
            "[ConnectorMedia] failed task_id=%s media_id=%s retry=%s error=%s",
            task_id,
            media_id,
            retries,
            exc,
        )
        session.rollback()
        row = row or session.get(ConnectorMediaTask, task_id)
        if row:
            will_retry = retries < self.max_retries and _connector_error_retryable(exc, auth_failed)
            row.status = "RETRY" if will_retry else "FAILED"
            row.error_message = str(exc)[:1000]
            session.commit()
            _notify_media_status(row, media_id=media_id, account_id=account_id)
            logger.info(
                "[ConnectorMedia] status=%s task_id=%s error=%s",
                row.status,
                task_id,
                row.error_message,
            )
        if not _connector_error_retryable(exc, auth_failed):
            raise
        raise self.retry(exc=exc)
    finally:
        if temp_path and not cache_reused:
            try:
                os.unlink(temp_path)
            except OSError:
                pass
        if cover_path:
            try:
                os.unlink(cover_path)
            except OSError:
                pass
        if account_lock is not None and account_lock_acquired:
            try:
                account_lock.release()
                logger.info(
                    "[ConnectorMedia] account lock released task_id=%s account_id=%s",
                    task_id,
                    account_id,
                )
            except LockError:
                logger.warning(
                    "[ConnectorMedia] account lock release skipped task_id=%s account_id=%s",
                    task_id,
                    account_id,
                )


@celery_app.task(name="fb_connector.recover_stale_delivery_tasks")
def recover_stale_delivery_tasks(limit: int = 100):
    """恢复海外投放 Worker 重启后遗留的 RUNNING/RETRY 任务。"""
    from fb_connector.models import ConnectorDeliveryTask, connector_session_factory

    cutoff = datetime.utcnow() - timedelta(seconds=settings.CONNECTOR_MEDIA_STALE_SECONDS)
    session = connector_session_factory()
    recovered = 0
    skipped = 0
    try:
        rows = (
            session.query(ConnectorDeliveryTask)
            .filter(
                ConnectorDeliveryTask.status.in_(("QUEUED", "RUNNING", "RETRY")),
                ConnectorDeliveryTask.updated_at < cutoff,
            )
            .order_by(ConnectorDeliveryTask.updated_at.asc())
            .with_for_update(skip_locked=True)
            .limit(limit)
            .all()
        )
        for row in rows:
            if not row.credential_id or not row.account_id or not row.request_payload:
                skipped += 1
                logger.warning(
                    "[ConnectorDeliveryRecovery] skip connector_task_id=%s reason=missing_payload status=%s",
                    row.task_id,
                    row.status,
                )
                continue
            row.status = "QUEUED"
            row.error_message = None
            row.updated_at = datetime.utcnow()
            session.commit()
            try:
                create_campaign_task.delay(
                    row.task_id,
                    row.credential_id,
                    row.account_id,
                    row.request_payload,
                    row.idempotency_key,
                )
                recovered += 1
                logger.warning("[ConnectorDeliveryRecovery] requeued connector_task_id=%s", row.task_id)
            except Exception as exc:
                session.rollback()
                row = session.get(ConnectorDeliveryTask, row.task_id)
                if row:
                    row.status = "FAILED"
                    row.error_message = f"恢复任务入队失败: {exc}"[:1000]
                    session.commit()
                logger.exception("[ConnectorDeliveryRecovery] enqueue failed connector_task_id=%s", row.task_id)
        return {"recovered": recovered, "skipped": skipped}
    finally:
        session.close()
