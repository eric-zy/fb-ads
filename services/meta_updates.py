"""Validate connector receipts before projecting a remote write locally."""
from datetime import datetime
from models import Campaign, AdGroup, Ad, CampaignInstance, AdSetInstance, AdInstance, CampaignStatus


def confirmed_fields(response, expected):
    result = response.get("result", response) if isinstance(response, dict) else {}
    if not isinstance(result, dict) or result.get("confirmed") is not True:
        raise ValueError("Meta 更新缺少确认回执，请同步对象状态后重试")
    for key, value in expected.items():
        if str(result.get(key)) != str(value):
            raise ValueError(f"Meta 更新未确认字段 {key}")
    return result


def project_status(db, account_id, object_type, remote_id, status, effective_status=None):
    canonical_model, remote_field = {"CAMPAIGN": (Campaign, "campaign_id"), "ADSET": (AdGroup, "ad_group_id"), "AD": (Ad, "ad_id")}[object_type]
    canonical = db.query(canonical_model).filter(getattr(canonical_model, remote_field) == remote_id).first()
    if canonical:
        parent_account = canonical.ad_account_id if object_type == "CAMPAIGN" else canonical.campaign.ad_account_id if object_type == "ADSET" else canonical.ad_group.campaign.ad_account_id
        if parent_account != account_id:
            raise ValueError("Meta 对象账户映射不一致")
        canonical.status = CampaignStatus(status) if object_type == "CAMPAIGN" else status
    instance_model = {"CAMPAIGN": CampaignInstance, "ADSET": AdSetInstance, "AD": AdInstance}[object_type]
    instance_field = {"CAMPAIGN": "meta_campaign_id", "ADSET": "meta_adset_id", "AD": "meta_ad_id"}[object_type]
    for instance in db.query(instance_model).filter(getattr(instance_model, instance_field) == remote_id).all():
        from services.delivery_actions import object_account_id
        if object_account_id(instance, object_type) != account_id:
            raise ValueError("实例与目标广告账户不一致")
        # Archive is a local view state, so a periodic remote read preserves it.
        if instance.status not in {"ARCHIVED", "DELETED"}:
            instance.status = status
        instance.meta_status = effective_status or status
        instance.last_synced_at = datetime.utcnow()
