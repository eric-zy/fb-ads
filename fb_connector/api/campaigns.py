from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from datetime import datetime, timedelta
import uuid
from fb_connector.models import ConnectorDeliveryTask, connector_session_factory
from fb_connector.credential_store import report_meta_auth_failure
from core.logger import logger
from config.settings import settings

router = APIRouter(prefix="/internal/meta/campaigns", tags=["Meta Delivery"])

class CampaignCreateRequest(BaseModel):
    task_id: str = Field(..., min_length=1, max_length=64)
    credential_id: str = Field(..., min_length=1, max_length=50)
    account_id: str = Field(..., min_length=1, max_length=64)
    payload: dict
    idempotency_key: str = Field(..., min_length=8, max_length=128)

class CampaignListRequest(BaseModel):
    account_id: str = Field(..., min_length=1, max_length=64)
    credential_id: str = Field(..., min_length=1, max_length=50)

class CampaignPauseRequest(BaseModel):
    campaign_id: str = Field(..., min_length=1, max_length=64)
    credential_id: str = Field(..., min_length=1, max_length=50)
    idempotency_key: str = Field(..., min_length=8, max_length=128)

class ObjectRequest(BaseModel):
    object_type: str = Field(..., pattern="^(CAMPAIGN|ADSET|AD)$")
    object_id: str = Field(..., min_length=1, max_length=64)
    credential_id: str = Field(..., min_length=1, max_length=50)
    fields: dict = Field(..., min_length=1)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=128)

class ParentRequest(BaseModel):
    parent_id: str = Field(..., min_length=1, max_length=64)
    credential_id: str = Field(..., min_length=1, max_length=50)

class CleanupRequest(BaseModel):
    connector_task_id: str = Field(..., min_length=1, max_length=50)
    credential_id: str = Field(..., min_length=1, max_length=50)
    orphaned_only: bool = False


class ReconcileRequest(BaseModel):
    connector_task_id: str = Field(..., min_length=1, max_length=50)
    credential_id: str = Field(..., min_length=1, max_length=50)


class ReconcileConfirmation(BaseModel):
    group: str = Field(..., pattern="^(campaign|adsets|creatives|ads)$")
    client_key: str | None = Field(default=None, max_length=128)
    object_id: str = Field(..., min_length=1, max_length=128)


class ReconcileConfirmRequest(ReconcileRequest):
    confirmations: list[ReconcileConfirmation] = Field(..., min_length=1, max_length=20)


def _pending_reconcile_results(row, service) -> list[dict]:
    """把待对账标记转换成稳定的候选结果格式，供查询和确认接口共用。"""
    from fb_connector.tasks import _list_pending_candidates, _pending_remote_candidates

    objects = row.objects if isinstance(row.objects, dict) else {}
    pending = list(objects.get("pending") or [])
    cache = {}
    results = []
    for item in pending:
        group = item.get("group")
        parent_id = item.get("parent_id")
        cache_key = (group, parent_id)
        if cache_key not in cache:
            cache[cache_key] = _list_pending_candidates(
                service, group, parent_id, row.account_id
            )
        candidates = _pending_remote_candidates(cache[cache_key], item)
        results.append(
            {
                "group": group,
                "client_key": item.get("client_key"),
                "name": item.get("name"),
                "parent_id": parent_id,
                "submitted_at": item.get("submitted_at"),
                "can_auto_reconcile": len(candidates) == 1,
                "candidates": [
                    {
                        key: candidate.get(key)
                        for key in (
                            "id",
                            "name",
                            "created_time",
                            "status",
                            "effective_status",
                        )
                        if candidate.get(key) is not None
                    }
                    for candidate in candidates
                ],
            }
        )
    return results


def _delivery_task_is_stale(row: ConnectorDeliveryTask, now: datetime | None = None) -> bool:
    if row.status not in {"QUEUED", "RUNNING", "RETRY"}:
        return False
    timestamp = row.updated_at or row.created_at
    if not timestamp:
        return True
    return (now or datetime.utcnow()) - timestamp >= timedelta(
        seconds=settings.CONNECTOR_MEDIA_STALE_SECONDS
    )


def _cleanup_object_ids(row: ConnectorDeliveryTask, *, orphaned_only: bool = False) -> list[str]:
    """只返回本任务创建的对象；复用对象和孤儿清理范围明确分离。"""
    objects = row.objects or {}
    groups = ("orphaned",) if orphaned_only else ("ads", "creatives", "adsets", "orphaned")
    ids = [
        item.get("id")
        for group in groups
        for item in (objects.get(group) or [])
        if item.get("id") and not item.get("reused")
    ]
    requested_campaign = (row.request_payload or {}).get("campaign") or {}
    campaign_reused = bool(
        requested_campaign.get("existing_id") or requested_campaign.get("reuse_id")
    )
    if not orphaned_only and row.campaign_id and not campaign_reused:
        ids.append(row.campaign_id)
    return list(dict.fromkeys(ids))

@router.post("/cleanup")
async def cleanup_deployment(payload: CleanupRequest):
    from fb_connector.credential_store import DatabaseCredentialVault
    from services.meta.service import MetaAdsService
    from services.meta import MetaClient
    session = connector_session_factory()
    try:
        row = session.get(ConnectorDeliveryTask, payload.connector_task_id)
        if not row:
            raise HTTPException(status_code=404, detail="海外任务不存在")
        token = DatabaseCredentialVault().get_access_token(payload.credential_id)
        service = MetaAdsService(MetaClient(access_token=token))
        ids = _cleanup_object_ids(row, orphaned_only=payload.orphaned_only)
        errors = []
        for object_id in ids:
            try:
                service.delete_object(object_id)
            except Exception as exc:
                if report_meta_auth_failure(payload.credential_id, exc):
                    raise
                errors.append({"id": object_id, "error": str(exc)})
        return {"status": "SUCCESS" if not errors else "PARTIAL", "deleted": [x for x in ids if x not in {e["id"] for e in errors}], "errors": errors}
    except HTTPException:
        raise
    except Exception as exc:
        report_meta_auth_failure(payload.credential_id, exc)
        logger.exception("[ConnectorCampaignAPI] cleanup failed connector_task_id=%s", payload.connector_task_id)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        session.close()

@router.post("/deploy", status_code=202)
async def deploy_campaign(payload: dict):
    """完整 Campaign/AdSet/Creative/Ad 协议入口，复用幂等创建任务。"""
    required = ("task_id", "credential_id", "account_id", "idempotency_key", "campaign", "adsets")
    missing = [key for key in required if key not in payload]
    if missing:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"缺少字段: {', '.join(missing)}")
    request = CampaignCreateRequest(task_id=payload["task_id"], credential_id=payload["credential_id"], account_id=payload["account_id"], payload=payload, idempotency_key=payload["idempotency_key"])
    return await create_campaign(request)

def _meta_service(credential_id: str):
    from fb_connector.credential_store import DatabaseCredentialVault
    from services.meta.service import MetaAdsService
    from services.meta import MetaClient
    token = DatabaseCredentialVault().get_access_token(credential_id)
    return MetaAdsService(MetaClient(access_token=token))

@router.post("/adsets")
async def list_adsets(payload: ParentRequest):
    try:
        return {"parent_id": payload.parent_id, "adsets": _meta_service(payload.credential_id).list_adsets(payload.parent_id)}
    except Exception as exc:
        report_meta_auth_failure(payload.credential_id, exc)
        logger.exception("[ConnectorCampaignAPI] list adsets failed parent_id=%s", payload.parent_id)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@router.post("/ads")
async def list_ads(payload: ParentRequest):
    try:
        return {"parent_id": payload.parent_id, "ads": _meta_service(payload.credential_id).list_ads(payload.parent_id)}
    except Exception as exc:
        report_meta_auth_failure(payload.credential_id, exc)
        logger.exception("[ConnectorCampaignAPI] list ads failed parent_id=%s", payload.parent_id)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@router.post("/update-object")
async def update_object(payload: ObjectRequest):
    try:
        service = _meta_service(payload.credential_id)
        fields = payload.fields
        if set(fields) - {"status", "daily_budget"}:
            raise HTTPException(status_code=400, detail="只允许更新 status 或 daily_budget")
        if "status" in fields and fields["status"] not in {"ACTIVE", "PAUSED"}:
            raise HTTPException(status_code=400, detail="status 必须为 ACTIVE 或 PAUSED")
        if "daily_budget" in fields:
            try:
                fields["daily_budget"] = int(fields["daily_budget"])
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="daily_budget 必须为整数分")
            if fields["daily_budget"] <= 0:
                raise HTTPException(status_code=400, detail="daily_budget 必须为正数")
        if payload.object_type == "CAMPAIGN":
            result = service.update_campaign(payload.object_id, fields)
        elif payload.object_type == "ADSET":
            result = service.update_adset(payload.object_id, fields)
        else:
            if "daily_budget" in fields:
                raise HTTPException(status_code=400, detail="广告不支持更新 daily_budget")
            result = service.update_ad(payload.object_id, fields)
        return {"object_type": payload.object_type, "object_id": payload.object_id, "fields": fields, "result": result, "idempotency_key": payload.idempotency_key}
    except HTTPException:
        raise
    except Exception as exc:
        report_meta_auth_failure(payload.credential_id, exc)
        logger.exception("[ConnectorCampaignAPI] update object failed object_id=%s", payload.object_id)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@router.post("/list")
async def list_campaigns(payload: CampaignListRequest):
    try:
        from fb_connector.credential_store import DatabaseCredentialVault
        token = DatabaseCredentialVault().get_access_token(payload.credential_id)
        from services.meta.service import MetaAdsService
        from services.meta import MetaClient
        campaigns = MetaAdsService(MetaClient(access_token=token)).list_campaigns(payload.account_id)
        return {"account_id": payload.account_id, "credential_id": payload.credential_id, "campaigns": campaigns}
    except Exception as exc:
        report_meta_auth_failure(payload.credential_id, exc)
        logger.exception("[ConnectorCampaignAPI] list campaigns failed account_id=%s", payload.account_id)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@router.post("/pause")
async def pause_campaign(payload: CampaignPauseRequest):
    try:
        from fb_connector.credential_store import DatabaseCredentialVault
        from services.meta.service import MetaAdsService
        from services.meta import MetaClient
        token = DatabaseCredentialVault().get_access_token(payload.credential_id)
        result = MetaAdsService(MetaClient(access_token=token)).pause_campaign(payload.campaign_id)
        return {"campaign_id": payload.campaign_id, "credential_id": payload.credential_id, "result": result, "idempotency_key": payload.idempotency_key}
    except Exception as exc:
        report_meta_auth_failure(payload.credential_id, exc)
        logger.exception("[ConnectorCampaignAPI] pause campaign failed campaign_id=%s", payload.campaign_id)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@router.post("/create", status_code=202)
async def create_campaign(payload: CampaignCreateRequest):
    session = connector_session_factory()
    connector_task_id = None
    requeued_stale = False
    try:
        old = (
            session.query(ConnectorDeliveryTask)
            .filter(ConnectorDeliveryTask.idempotency_key == payload.idempotency_key)
            .with_for_update()
            .first()
        )
        if old:
            if old.status == "SUCCESS":
                return {"status": old.status, "connector_task_id": old.task_id, "task_id": payload.task_id, "idempotency_key": old.idempotency_key}
            if old.status != "FAILED" and not _delivery_task_is_stale(old):
                return {"status": old.status, "connector_task_id": old.task_id, "task_id": payload.task_id, "idempotency_key": old.idempotency_key}
            connector_task_id = old.task_id
            # 失败任务重试时允许修复后的协议重新创建 Creative/Ad。
            # Campaign/AdSet 仍保留，避免重复创建；如果协议已变化，旧的
            # Creative/Ad 引用可能对应错误的素材结构（例如把视频当成图片），
            # 必须清掉，否则 worker 会继续复用旧对象。
            payload_changed = (old.request_payload or {}) != (payload.payload or {})
            if old.status == "FAILED" and payload_changed:
                objects = dict(old.objects or {})
                # 参数修复后只重建 Creative/Ad，但不要丢失旧对象 ID：
                # 旧对象仍可能存在，必须留给显式 cleanup 操作处理，
                # 否则会形成 Connector 无法追踪的孤儿对象。
                orphaned = list(objects.get("orphaned") or [])
                orphaned.extend(
                    item for group in ("creatives", "ads")
                    for item in (objects.get(group) or [])
                    if item.get("id")
                )
                if orphaned:
                    objects["orphaned"] = orphaned
                objects["creatives"] = []
                objects["ads"] = []
                old.objects = objects
                logger.info(
                    "[ConnectorCampaignAPI] reset stale creative/ad objects "
                    "connector_task_id=%s task_id=%s",
                    old.task_id,
                    payload.task_id,
                )
            old.source_task_id = payload.task_id
            old.credential_id = payload.credential_id
            old.account_id = payload.account_id
            old.request_payload = payload.payload
            old.status = "QUEUED"
            old.step = old.step or "QUEUED"
            old.error_message = None
            old.updated_at = datetime.utcnow()
            requeued_stale = True
        else:
            connector_task_id = uuid.uuid4().hex
            session.add(ConnectorDeliveryTask(
                task_id=connector_task_id,
                idempotency_key=payload.idempotency_key,
                source_task_id=payload.task_id,
                credential_id=payload.credential_id,
                account_id=payload.account_id,
                request_payload=payload.payload,
                status="QUEUED",
                step="QUEUED",
            ))
        session.commit()
    finally:
        session.close()
    from fb_connector.tasks import create_campaign_task
    try:
        async_result = create_campaign_task.delay(connector_task_id, payload.credential_id, payload.account_id, payload.payload, payload.idempotency_key)
    except Exception as exc:
        failed_session = connector_session_factory()
        try:
            row = failed_session.get(ConnectorDeliveryTask, connector_task_id)
            if row:
                row.status = "FAILED"
                row.error_message = f"Worker 任务入队失败: {exc}"[:1000]
                failed_session.commit()
        finally:
            failed_session.close()
        logger.exception("[ConnectorCampaignAPI] enqueue failed connector_task_id=%s task_id=%s", connector_task_id, payload.task_id)
        raise HTTPException(status_code=503, detail="投放任务暂时无法入队") from exc
    logger.info(
        "[ConnectorCampaignAPI] %s connector_task_id=%s celery_task_id=%s task_id=%s account_id=%s",
        "requeued stale delivery task" if requeued_stale else "queued",
        connector_task_id,
        async_result.id,
        payload.task_id,
        payload.account_id,
    )
    return {"status": "QUEUED", "connector_task_id": connector_task_id, "task_id": payload.task_id, "idempotency_key": payload.idempotency_key}

@router.get("/create/{connector_task_id}")
async def delivery_status(connector_task_id: str):
    session = connector_session_factory()
    try:
        row = session.get(ConnectorDeliveryTask, connector_task_id)
        if not row: return {"status": "NOT_FOUND", "connector_task_id": connector_task_id}
        logger.info("[ConnectorCampaignAPI] status connector_task_id=%s status=%s step=%s", connector_task_id, row.status, row.step)
        return {"status": row.status, "step": row.step, "connector_task_id": row.task_id, "campaign_id": row.campaign_id, "objects": row.objects or {}, "error_message": row.error_message}
    finally: session.close()


@router.post("/reconcile")
async def reconcile_delivery(payload: ReconcileRequest):
    """只读检查未知提交结果，供运营确认后再重试任务。"""
    from services.meta import MetaClient
    from services.meta.service import MetaAdsService
    from fb_connector.credential_store import DatabaseCredentialVault

    session = connector_session_factory()
    try:
        row = session.get(ConnectorDeliveryTask, payload.connector_task_id)
        if not row:
            raise HTTPException(status_code=404, detail="海外任务不存在")
        if row.credential_id and row.credential_id != payload.credential_id:
            raise HTTPException(status_code=403, detail="凭据与任务不匹配")

        objects = row.objects if isinstance(row.objects, dict) else {}
        pending = list(objects.get("pending") or [])
        if not pending:
            return {
                "status": row.status,
                "connector_task_id": row.task_id,
                "pending": [],
                "message": "当前任务没有待对账对象",
            }

        token = DatabaseCredentialVault().get_access_token(
            row.credential_id or payload.credential_id
        )
        service = MetaAdsService(MetaClient(access_token=token))
        results = _pending_reconcile_results(row, service)
        return {
            "status": row.status,
            "connector_task_id": row.task_id,
            "campaign_id": row.campaign_id,
            "pending": results,
            "message": "仅返回候选，不会自动认领或删除 Meta 对象；确认后请重试原任务",
        }
    except HTTPException:
        raise
    except Exception as exc:
        report_meta_auth_failure(payload.credential_id, exc)
        logger.exception(
            "[ConnectorCampaignAPI] reconcile failed connector_task_id=%s",
            payload.connector_task_id,
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        session.close()


@router.post("/reconcile/confirm")
async def confirm_reconcile_delivery(payload: ReconcileConfirmRequest):
    """确认运营选定的 Meta 候选，只落库复用关系，不执行 Meta 写操作。"""
    from fb_connector.tasks import _confirm_pending_delivery_objects
    from services.meta import MetaClient
    from services.meta.service import MetaAdsService
    from fb_connector.credential_store import DatabaseCredentialVault

    session = connector_session_factory()
    try:
        row = session.get(ConnectorDeliveryTask, payload.connector_task_id)
        if not row:
            raise HTTPException(status_code=404, detail="海外任务不存在")
        if row.credential_id and row.credential_id != payload.credential_id:
            raise HTTPException(status_code=403, detail="凭据与任务不匹配")
        token = DatabaseCredentialVault().get_access_token(
            row.credential_id or payload.credential_id
        )
        service = MetaAdsService(MetaClient(access_token=token))
        confirmed = _confirm_pending_delivery_objects(
            session,
            row,
            service,
            row.account_id,
            [item.model_dump() for item in payload.confirmations],
        )
        remaining_pending = _pending_reconcile_results(row, service)
        return {
            "status": row.status,
            "connector_task_id": row.task_id,
            "confirmed": confirmed,
            "remaining_pending": remaining_pending,
            "message": "已确认本地复用关系，请继续执行原任务",
        }
    except HTTPException:
        raise
    except Exception as exc:
        report_meta_auth_failure(payload.credential_id, exc)
        logger.exception(
            "[ConnectorCampaignAPI] reconcile confirm failed connector_task_id=%s",
            payload.connector_task_id,
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        session.close()
