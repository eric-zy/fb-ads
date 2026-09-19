import os
import tempfile
import json
from urllib.parse import urlparse

from celery import shared_task
import requests
import uuid

from core.logger import logger
from services.request_signer import build_signature_headers

from config.settings import settings
from fb_connector.credential_store import DatabaseCredentialVault, report_meta_auth_failure
from services.meta import MetaAdsService, MetaClient

@shared_task(bind=True, name="fb_connector.fetch_insights", max_retries=3, default_retry_delay=60)
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
        if auth_failed:
            raise
        raise self.retry(exc=exc)

@shared_task(bind=True, name="fb_connector.create_campaign", max_retries=2, default_retry_delay=30)
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
        if row.status == "SUCCESS" and row.campaign_id:
            logger.info("[ConnectorCampaign] already success connector_task_id=%s campaign_id=%s", connector_task_id, row.campaign_id)
            return {"status": "SUCCESS", "connector_task_id": connector_task_id, "campaign_id": row.campaign_id, "objects": row.objects or {}, "idempotency_key": idempotency_key}
        row.status = "RUNNING"; row.step = row.step if row.step != "QUEUED" else "CAMPAIGN"; session.commit()
        logger.info("[ConnectorCampaign] status=RUNNING connector_task_id=%s step=%s", connector_task_id, row.step)
        token = DatabaseCredentialVault().get_access_token(credential_id)
        service = MetaAdsService(MetaClient(access_token=token))

        campaign_id = row.campaign_id
        if not campaign_id:
            campaign = service.create_campaign(account_id, payload.get("campaign") or {})
            campaign_id = campaign["id"]
            created.append(campaign_id)
            row.campaign_id = campaign_id
            row.step = "ADSET"
            session.commit()
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
        logger.info("[ConnectorCampaign] success connector_task_id=%s campaign_id=%s", connector_task_id, campaign_id)
        return {"status": "SUCCESS", "connector_task_id": connector_task_id, "campaign_id": campaign_id, "objects": object_map, "adset_ids": adset_ids, "ad_ids": ad_ids, "idempotency_key": idempotency_key}
    except Exception as exc:
        # 保留已创建对象 ID，补偿删除由后续审计/人工策略执行，避免误删用户资产。
        auth_failed = report_meta_auth_failure(credential_id, exc)
        logger.exception("[ConnectorCampaign] failed connector_task_id=%s retry=%s created=%s", connector_task_id, retries, created)
        session.rollback()
        row = row or session.get(ConnectorDeliveryTask, connector_task_id)
        if row:
            will_retry = retries < self.max_retries
            row.status = "RETRY" if will_retry else "FAILED"
            row.error_message = f"已创建对象={created}: {exc}"[:1000]
            session.commit()
            logger.info("[ConnectorCampaign] status=%s connector_task_id=%s error=%s", row.status, connector_task_id, row.error_message)
        if auth_failed:
            raise
        raise self.retry(exc=RuntimeError(f"投放步骤失败，已创建对象={created}: {exc}"))
    finally:
        session.close()

@shared_task(bind=True, name="fb_connector.upload_media", max_retries=3, default_retry_delay=30)
def upload_media_task(self, task_id: str, media_id: str, credential_id: str, account_id: str, asset_type: str, source_url: str, idempotency_key: str):
    """海外执行素材下载和 Meta 上传；生产环境应将结果写入 Connector 任务表并回调 SaaS。"""
    temp_path = None
    row = None
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
        row.status = "UPLOADING"; session.commit()
        logger.info("[ConnectorMedia] status=UPLOADING task_id=%s", task_id)
        # 防止把超大文件一次性读入内存，视频上传使用流式写入。
        logger.info(
            "[ConnectorMedia] download start task_id=%s connect_timeout=%ss read_timeout=%ss",
            task_id,
            settings.FB_VIDEO_CONNECT_TIMEOUT,
            settings.FB_VIDEO_UPLOAD_TIMEOUT,
        )
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
            suffix = ".mp4" if asset_type == "video" else ".bin"
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as target:
                temp_path = target.name
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        target.write(chunk)
                        bytes_written += len(chunk)
        logger.info(
            "[ConnectorMedia] download complete task_id=%s bytes=%s temp_path=%s",
            task_id,
            bytes_written,
            temp_path,
        )
        logger.info("[ConnectorMedia] credential lookup start task_id=%s credential_id=%s", task_id, credential_id)
        token = DatabaseCredentialVault().get_access_token(credential_id)
        logger.info("[ConnectorMedia] meta upload start task_id=%s account_id=%s asset_type=%s", task_id, account_id, asset_type)
        result = MetaAdsService(MetaClient(access_token=token)).upload_video(account_id, temp_path) if asset_type == "video" else MetaAdsService(MetaClient(access_token=token)).upload_image(account_id, temp_path)
        meta_asset_id = result.get("video_id") if asset_type == "video" else result.get("hash")
        row.status = "SUCCESS"; row.meta_asset_id = meta_asset_id; session.commit()
        logger.info(
            "[ConnectorMedia] success task_id=%s media_id=%s meta_asset_id=%s",
            task_id,
            media_id,
            meta_asset_id,
        )
        return {"status": "SUCCESS", "media_id": media_id, "idempotency_key": idempotency_key, "meta_asset_id": meta_asset_id}
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
            will_retry = retries < self.max_retries
            row.status = "RETRY" if will_retry else "FAILED"
            row.error_message = str(exc)[:1000]
            session.commit()
            logger.info(
                "[ConnectorMedia] status=%s task_id=%s error=%s",
                row.status,
                task_id,
                row.error_message,
            )
        if auth_failed:
            raise
        raise self.retry(exc=exc)
    finally:
        if temp_path:
            try:
                os.unlink(temp_path)
            except OSError:
                pass
        session.close()
