import os
import tempfile
from celery import shared_task
import requests
import uuid
from services.request_signer import build_signature_headers

from config.settings import settings
from fb_connector.credential_store import DatabaseCredentialVault
from services.meta import MetaAdsService, MetaClient

@shared_task(name="fb_connector.fetch_insights")
def fetch_insights_task(credential_id: str, account_id: str, days: int = 1):
    """海外拉取 Insights，并将结果签名回调 SaaS。"""
    token = DatabaseCredentialVault().get_access_token(credential_id)
    rows = MetaAdsService(MetaClient(access_token=token)).get_insights(account_id, {"date_preset": f"last_{days}d", "level": "account"})
    payload = {"event": "insights.completed", "request_id": uuid.uuid4().hex, "credential_id": credential_id, "account_id": account_id, "days": days, "items": rows}
    callback = f"{settings.SAAS_CALLBACK_BASE_URL.rstrip('/')}/api/v1/internal/fb-connector/insights"
    body = __import__("json").dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    headers = build_signature_headers(settings.SAAS_INTERNAL_SIGNING_KEY, "fb_connector", payload["request_id"], "POST", "/api/v1/internal/fb-connector/insights", body)
    headers["Content-Type"] = "application/json"
    response = requests.post(callback, data=body, headers=headers, timeout=settings.FB_CONNECTOR_TIMEOUT)
    response.raise_for_status()
    return {"status": "SUCCESS", "account_id": account_id, "count": len(rows)}

@shared_task(bind=True, name="fb_connector.create_campaign", max_retries=2, default_retry_delay=30)
def create_campaign_task(self, connector_task_id: str, credential_id: str, account_id: str, payload: dict, idempotency_key: str):
    """按 Campaign → AdSet → Creative → Ad 顺序执行 Meta 写操作。"""
    created = []
    from fb_connector.models import ConnectorDeliveryTask, connector_session_factory
    session = connector_session_factory()
    row = session.get(ConnectorDeliveryTask, connector_task_id)
    try:
        token = DatabaseCredentialVault().get_access_token(credential_id)
        service = MetaAdsService(MetaClient(access_token=token))
        row.status = "RUNNING"; row.step = "CAMPAIGN"; session.commit()
        campaign = service.create_campaign(account_id, payload.get("campaign") or {})
        campaign_id = campaign["id"]; created.append(campaign_id)
        row.campaign_id = campaign_id; row.step = "ADSET"; session.commit()
        adset_ids = []
        for item in payload.get("adsets") or []:
            result = service.create_adset(account_id, {**item, "campaign_id": campaign_id})
            adset_ids.append(result["id"]); created.append(result["id"])
        ad_ids = []
        row.step = "AD"; session.commit()
        for item in payload.get("ads") or []:
            result = service.create_ad(account_id, {**item, "adset_id": item.get("adset_id") or (adset_ids[0] if adset_ids else None)})
            ad_ids.append(result["id"]); created.append(result["id"])
        row.status = "SUCCESS"; row.step = "DONE"; session.commit()
        return {"status": "SUCCESS", "connector_task_id": connector_task_id, "campaign_id": campaign_id, "adset_ids": adset_ids, "ad_ids": ad_ids, "idempotency_key": idempotency_key}
    except Exception as exc:
        # 保留已创建对象 ID，补偿删除由后续审计/人工策略执行，避免误删用户资产。
        if row:
            row.status = "FAILED"; row.error_message = f"已创建对象={created}: {exc}"[:1000]; session.commit()
        raise self.retry(exc=RuntimeError(f"投放步骤失败，已创建对象={created}: {exc}"))
    finally:
        session.close()

@shared_task(bind=True, name="fb_connector.upload_media", max_retries=3, default_retry_delay=30)
def upload_media_task(self, task_id: str, media_id: str, credential_id: str, account_id: str, asset_type: str, source_url: str, idempotency_key: str):
    """海外执行素材下载和 Meta 上传；生产环境应将结果写入 Connector 任务表并回调 SaaS。"""
    temp_path = None
    row = None
    from fb_connector.models import ConnectorMediaTask, connector_session_factory
    session = connector_session_factory()
    try:
        row = session.get(ConnectorMediaTask, task_id)
        if not row:
            raise RuntimeError("上传任务不存在")
        row.status = "UPLOADING"; session.commit()
        # 防止把超大文件一次性读入内存，视频上传使用流式写入。
        with requests.get(source_url, stream=True, timeout=settings.FB_VIDEO_UPLOAD_TIMEOUT) as response:
            response.raise_for_status()
            suffix = ".mp4" if asset_type == "video" else ".bin"
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as target:
                temp_path = target.name
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        target.write(chunk)
        token = DatabaseCredentialVault().get_access_token(credential_id)
        result = MetaAdsService(MetaClient(access_token=token)).upload_video(account_id, temp_path) if asset_type == "video" else MetaAdsService(MetaClient(access_token=token)).upload_image(account_id, temp_path)
        meta_asset_id = result.get("video_id") if asset_type == "video" else result.get("hash")
        row.status = "SUCCESS"; row.meta_asset_id = meta_asset_id; session.commit()
        return {"status": "SUCCESS", "media_id": media_id, "idempotency_key": idempotency_key, "meta_asset_id": meta_asset_id}
    except Exception as exc:
        row = session.get(ConnectorMediaTask, task_id)
        if row:
            row.status = "FAILED"; row.error_message = str(exc)[:1000]; session.commit()
        raise self.retry(exc=exc)
    finally:
        if temp_path:
            try:
                os.unlink(temp_path)
            except OSError:
                pass
        session.close()
