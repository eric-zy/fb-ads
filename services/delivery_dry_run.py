"""只读取本地快照并展开投放对象；不初始化 Meta 客户端或派发任务。"""
from sqlalchemy.orm import Session

from models import AdAccount, AdGroup, Campaign, CampaignTemplate, MetaAssetBinding, PublishPreview
from services.connector_campaign_builder import build_connector_payload
from services.media_usage import extract_asset_ids
from services.instagram_identity import instagram_account_access_error


def build_delivery_dry_run(db: Session, preview: PublishPreview, template: CampaignTemplate) -> dict:
    request = preview.request_snapshot or {}
    policy_by_account = (preview.result_snapshot or {}).get("audience_policy_by_account", {})
    asset_ids = extract_asset_ids(template.creative_config_json)
    accounts = db.query(AdAccount).filter(AdAccount.id.in_(preview.account_ids)).all()
    account_by_id = {account.id: account for account in accounts}
    plans, errors = [], []
    for account_id in preview.account_ids:
        account = account_by_id.get(account_id)
        plan = {"account_id": account_id, "account_name": getattr(account, "account_name", account_id), "errors": []}
        try:
            if not account:
                raise ValueError("广告账户已不存在，请重新预检")
            instagram_error = instagram_account_access_error(db, account, template.creative_config_json or {})
            if instagram_error:
                raise ValueError(instagram_error)
            bindings = db.query(MetaAssetBinding).filter(
                MetaAssetBinding.ad_account_id == account_id,
                MetaAssetBinding.asset_id.in_(asset_ids),
                MetaAssetBinding.status == "READY",
            ).all() if asset_ids else []
            binding_ids = {row.asset_id for row in bindings if row.meta_asset_id}
            if set(asset_ids) - binding_ids:
                raise ValueError("素材尚未完成该账户的 Meta 映射，请等待同步完成或重试失败素材")
            selection = (request.get("ad_group_selections") or {}).get(account_id) or {}
            mode = request.get("ad_group_mode", "NEW")
            reuse, copy_source = {}, None
            if mode in {"EXISTING", "COPY"}:
                row = db.query(AdGroup, Campaign).join(Campaign, AdGroup.campaign_id == Campaign.id).filter(
                    AdGroup.id == selection.get("ad_group_id"),
                    AdGroup.tenant_id == template.tenant_id,
                    Campaign.tenant_id == template.tenant_id,
                ).first()
                if not row:
                    raise ValueError("所选广告组已不存在，请重新预检")
                group, campaign = row
                if mode == "EXISTING":
                    reuse = {"existing_campaign_id": campaign.campaign_id, "existing_ad_group_id": group.ad_group_id}
                else:
                    copy_source = {"name": group.name, "targeting": group.targeting, "daily_budget": group.daily_budget,
                                   "bid_strategy": group.bid_strategy, "bid_amount": group.bid_amount}
            payload = build_connector_payload(
                template, account.account_id,
                budget_override=request.get("budget_override"), status=request.get("status", "PAUSED"),
                asset_bindings={row.asset_id: row.meta_asset_id for row in bindings},
                asset_types={row.asset_id: row.meta_asset_type for row in bindings},
                asset_thumbnail_hashes={row.asset_id: row.meta_thumbnail_hash for row in bindings if row.meta_thumbnail_hash},
                required_excluded_audience_ids=(policy_by_account.get(account_id) or {}).get("required_excluded_audience_ids", []),
                copy_ad_group=copy_source, **reuse,
            )
            adsets = payload["adsets"]
            plan.update(payload=payload, campaign_count=0 if reuse else 1,
                        adset_count=0 if reuse else len(adsets),
                        ad_count=sum(len(creative.get("ads", [])) for adset in adsets for creative in adset.get("creatives", [])),
                        reused_adset_id=reuse.get("existing_ad_group_id"))
        except (ValueError, TypeError, KeyError) as exc:
            plan["errors"].append(str(exc))
            errors.append({"account_id": account_id, "message": str(exc)})
        plans.append(plan)
    warnings = []
    if request.get("sinan_promotion_id"):
        warnings.append("司南推广链的名称与状态会在实际执行时重新查询，本次展示模板中的对象名称。")
    return {"mode": "DRY_RUN", "preview_id": preview.id, "will_write_meta": False,
            "passed": not errors and bool(plans), "accounts": plans, "errors": errors, "warnings": warnings}
