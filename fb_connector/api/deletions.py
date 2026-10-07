"""Explicit media deletion with durable receipts and read-only reconciliation."""
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError

from core.enums import ErrorCategory
from fb_connector.models import ConnectorObjectDeletion, connector_session_factory
from fb_connector.credential_store import report_meta_auth_failure
from services.meta.errors import MetaApiError
from config.settings import settings

router = APIRouter()


class ObjectDeletionRequest(BaseModel):
    object_type: str = Field(..., pattern="^(CAMPAIGN|ADSET|AD)$")
    object_id: str = Field(..., min_length=1, max_length=128)
    credential_id: str = Field(..., min_length=1, max_length=50)
    account_id: str = Field(..., min_length=1, max_length=64)
    idempotency_key: str = Field(..., min_length=8, max_length=128)
    confirm_only: bool = False


def _service(credential_id):
    from fb_connector.api.campaigns import _meta_service
    service = _meta_service(credential_id)
    # An uncertain DELETE must be reconciled, never retried by the HTTP layer.
    service.max_retries = 0
    return service


def _result(row):
    return {"status": "UNKNOWN" if row.status == "SUBMITTING" else row.status,
            "object_type": row.object_type, "object_id": row.object_id,
            "error": row.error_message, **(row.result_payload or {})}


@router.post("/delete-object")
def delete_object(payload: ObjectDeletionRequest):
    session = connector_session_factory()
    try:
        row = session.get(ConnectorObjectDeletion, payload.idempotency_key)
        if row and (row.object_type, row.object_id, row.credential_id, row.account_id) != (
            payload.object_type, payload.object_id, payload.credential_id, payload.account_id
        ):
            raise HTTPException(409, "删除幂等键对应的对象或账户不一致")
        if row and row.status in {"SUCCESS", "FAILED"}:
            return _result(row)
        try:
            service = _service(payload.credential_id)
        except Exception as exc:
            return {"status": "UNKNOWN" if row or payload.confirm_only else "FAILED", "error": f"无法加载授权凭据：{exc}"[:1000]}
        # Unreadable objects may also mean lost permissions. Never infer a
        # successful deletion from NOT_FOUND or a failed read.
        try:
            remote = service.get_delivery_object(payload.object_id)
            if str(remote.get("account_id", "")).removeprefix("act_") != payload.account_id.removeprefix("act_"):
                raise HTTPException(409, "Meta 对象不属于目标广告账户")
        except HTTPException:
            raise
        except Exception as exc:
            report_meta_auth_failure(payload.credential_id, exc)
            if row:
                row.status = "UNKNOWN"
                row.error_message = f"无法核实 Meta 删除结果：{exc}"[:1000]
                session.commit()
                return _result(row)
            return {"status": "UNKNOWN" if payload.confirm_only else "FAILED", "error": f"无法读取 Meta 对象，未执行删除：{exc}"[:1000]}

        if remote.get("status") == "DELETED" or remote.get("effective_status") == "DELETED":
            if not row:
                row = ConnectorObjectDeletion(**payload.model_dump(exclude={"confirm_only"}), status="SUCCESS")
                session.add(row)
            row.status = "SUCCESS"
            row.error_message = None
            row.result_payload = {"remote_status": "DELETED", "confirmed_by": "META_READ"}
            session.commit()
            return _result(row)
        if row or payload.confirm_only:
            # A SUBMITTING receipt can still be executing in another request.
            # Read-only checks must not mark it failed or overwrite that write.
            submitting = row and row.status == "SUBMITTING" and row.updated_at > datetime.utcnow() - timedelta(seconds=max(int(settings.FB_API_TIMEOUT) + 60, 300))
            return {"status": "UNKNOWN" if submitting else "NOT_DELETED",
                    "remote_status": remote.get("status"), "error": "尚未确认 Meta 删除；未再次发送删除请求"}

        row = ConnectorObjectDeletion(**payload.model_dump(exclude={"confirm_only"}), status="SUBMITTING")
        session.add(row)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            # A concurrent copy won the receipt. No second mutation.
            return {"status": "UNKNOWN", "error": "同一删除请求正在执行，请核对结果"}
        try:
            result = service.delete_object(payload.object_id)
            if result is True or isinstance(result, dict) and result.get("success") is True:
                row.status = "SUCCESS"
                row.result_payload = {"remote_status": "DELETED", "confirmed_by": "META_ACK"}
            else:
                row.status = "UNKNOWN"
                row.error_message = "Meta 未明确确认删除成功，请核对远端状态"
        except Exception as exc:
            report_meta_auth_failure(payload.credential_id, exc)
            definite = isinstance(exc, MetaApiError) and exc.category in {
                ErrorCategory.AUTH, ErrorCategory.PERMISSION, ErrorCategory.VALIDATION, ErrorCategory.RATE_LIMIT
            }
            row.status = "FAILED" if definite else "UNKNOWN"
            row.error_message = str(exc)[:1000]
        session.commit()
        return _result(row)
    finally:
        session.close()
