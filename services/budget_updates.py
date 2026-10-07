"""Budget writes keep selected instance IDs and per-object receipts."""
from decimal import Decimal, InvalidOperation
from models import Campaign, AdGroup
from core.money import exponent_for
from services.meta_updates import confirmed_fields


def apply_budget_updates(db, item, instances, account, connector, credential_id, amount):
    try:
        value = Decimal(str(amount))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("预算必须为有效金额")
    if not value.is_finite() or value <= 0 or value * 100 != (value * 100).to_integral_value():
        raise ValueError("预算必须为正数，最多两位小数")
    if exponent_for(account.currency) != 2:
        raise ValueError("该币种的 Meta 预算单位尚未验证，请在 Meta 平台调整预算")
    # This path supports the verified two-decimal currencies only.
    budget = int(value * 100)
    if not instances:
        raise ValueError("没有选中的广告系列实例")
    remote_campaigns = {str(row["id"]): row for row in connector.list_campaigns(account.account_id, credential_id)["campaigns"]}
    targets = []
    for instance in instances:
        remote = remote_campaigns.get(instance.meta_campaign_id)
        if not remote:
            raise ValueError(f"Meta 广告系列 {instance.meta_campaign_id} 不存在，请同步后重试")
        if str(remote.get("status")) in {"DELETED", "ARCHIVED"}:
            raise ValueError("已删除或归档的 Meta 对象不能调整预算")
        if int(remote.get("lifetime_budget") or 0):
            raise ValueError("该广告系列使用总预算，请使用对应预算类型编辑")
        if int(remote.get("daily_budget") or 0):
            targets.append(("CAMPAIGN", instance.meta_campaign_id))
            continue
        groups = connector.list_adsets(instance.meta_campaign_id, credential_id)["adsets"]
        active_groups = [row for row in groups if row.get("status") not in {"DELETED", "ARCHIVED"}]
        if not active_groups:
            raise ValueError("该广告系列没有可调整预算的广告组，未发送 Meta 更新")
        for group in active_groups:
            if int(group.get("lifetime_budget") or 0):
                raise ValueError("广告组使用总预算，不能直接改为日预算")
            targets.append(("ADSET", str(group["id"])))
    receipts = dict((item.response_payload or {}).get("budget_results") or {})
    for object_type, remote_id in dict.fromkeys(targets):
        key = f"{object_type}:{remote_id}"
        if receipts.get(key, {}).get("status") == "SUCCESS":
            continue
        try:
            response = connector.update_object(object_type, remote_id, credential_id, {"daily_budget": budget},
                idempotency_key=f"budget:{item.id}:{object_type}:{remote_id}:{budget}")
            confirmed = confirmed_fields(response, {"daily_budget": budget})
            model, field = (Campaign, "campaign_id") if object_type == "CAMPAIGN" else (AdGroup, "ad_group_id")
            entity = db.query(model).filter(getattr(model, field) == remote_id).first()
            if entity:
                entity_account = entity.ad_account_id if object_type == "CAMPAIGN" else entity.campaign.ad_account_id
                if entity_account != account.id:
                    raise ValueError("预算对象的本地账户映射不一致")
                entity.daily_budget = budget
            receipts[key] = {"status": "SUCCESS", "daily_budget": budget, "result": confirmed}
        except Exception as exc:
            receipts[key] = {"status": "FAILED", "error": str(exc)[:1000]}
            item.response_payload = {**(item.response_payload or {}), "budget_results": receipts}
            db.commit()
            raise
        item.response_payload = {**(item.response_payload or {}), "budget_results": receipts}
        # Each acknowledged remote change remains visible if a later target fails.
        db.commit()
    return receipts
