"""Domestic deletion checkpoint and reconciliation shared by both task paths."""
from services.delivery_actions import META_ID_FIELDS
from services.fb_connector_client import FBConnectorError


def delete_remote_object(connector, obj, object_type, credential_id, account_id, key, *, confirm_only=False):
    try:
        result = connector.delete_object(
            object_type, getattr(obj, META_ID_FIELDS[object_type]), credential_id, account_id,
            idempotency_key=key, confirm_only=confirm_only,
        )
    except FBConnectorError as exc:
        # Proxy/network failures can hide an already applied deletion.
        uncertain = exc.status_code is None or exc.status_code >= 500
        return {"status": "UNKNOWN" if uncertain else "FAILED", "error": str(exc)}
    if result.get("status") == "SUCCESS" and result.get("remote_status") == "DELETED":
        return result
    if result.get("status") in {"FAILED", "NOT_DELETED"}:
        return {**result, "status": "FAILED", "error": result.get("error") or "Meta 对象仍未删除"}
    return {**result, "status": "UNKNOWN", "error": result.get("error") or "等待确认 Meta 删除结果"}
