"""Job Service —— 批量任务创建与管理（设计文档第 17 / 29 节）

原则二：任务异步
    HTTP Request → Create Job → Return job_id → Worker Async Execute

创建 Job 时不调用任何 Meta API，只写库并派发 Celery 子任务后立即返回，
前端随后轮询 GET /api/v1/jobs/{id} 查看进度。
"""
import hashlib
import json
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from core.enums import ActionType, InstanceStatus, JobItemStatus, JobStatus
from core.logger import logger
from models import (
    AdAccount,
    CampaignInstance,
    CampaignJob,
    CampaignJobItem,
    CampaignTemplate,
    BusinessAssetAccess,
    MetaPage,
    MetaAssetBinding,
    CreativeAsset,
    Campaign,
    AdGroup,
    User,
    MetaTrackingAsset,
)
from services.account_access import accessible_account_ids
from services.meta_delivery_rules import (
    budget_bid_preflight_errors,
    conversion_event_preflight_errors,
    objective_optimization_preflight_errors,
    schedule_preflight_errors,
    tracking_asset_preflight_errors,
    tracking_asset_requirements,
)
from services.meta.page_access import page_account_access_error
from services.fb_connector_client import FBConnectorClient
from services.targeting_catalog import normalize_targeting, placement_preflight_errors, targeting_preflight_errors
from services.meta_audience_policy import resolve_required_exclusions
from services.media_binding_service import (
    ensure_asset_bindings,
    find_missing_asset_ids,
    queue_pending_asset_bindings,
)
from tasks.campaign_tasks import (
    execute_campaign_job,
    retry_failed_job_items,
)


class JobDispatchError(RuntimeError):
    """Celery 编排任务未能入队，且本地 Job 已明确落失败。"""


def _new_id() -> str:
    return uuid.uuid4().hex


def build_request_hash(
    template_id: Optional[str],
    ad_account_id: str,
    action: str,
    key_params: Optional[Dict[str, Any]] = None,
) -> str:
    """幂等键（设计文档第 29 节）

    同一模板 + 同一账户 + 同一动作 + 相同关键参数 → 相同 hash。
    用于识别"同一次操作"，避免超时重试导致重复创建。
    """
    payload = json.dumps(
        {
            "template_id": template_id,
            "ad_account_id": ad_account_id,
            "action": action,
            "params": key_params or {},
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class JobService:
    """批量任务服务"""

    def __init__(self, db: Session):
        self.db = db

    def _mark_dispatch_failed(self, job_id: str, exc: Exception) -> str:
        """把已落库但未成功入队的 Job 收敛到明确失败状态。"""
        message = f"Celery 任务入队失败: {exc}"[:1000]
        self.db.rollback()
        job = self.db.query(CampaignJob).filter(CampaignJob.id == job_id).first()
        if job:
            job.status = JobStatus.FAILED.value
            job.error_message = message
            job.finished_at = datetime.utcnow()
            self.db.query(CampaignJobItem).filter(
                CampaignJobItem.job_id == job_id,
                CampaignJobItem.status.in_([
                    JobItemStatus.PENDING.value,
                    JobItemStatus.RUNNING.value,
                ]),
            ).update(
                {
                    CampaignJobItem.status: JobItemStatus.FAILED.value,
                    CampaignJobItem.error_code: "TASK_ENQUEUE_FAILED",
                    CampaignJobItem.error_message: message,
                    CampaignJobItem.error_category: "TEMPORARY",
                },
                synchronize_session=False,
            )
            self.db.commit()
        return message

    # ------------------------------------------------------------------
    # 投放前置校验
    # ------------------------------------------------------------------
    def preflight_campaign(
        self, template_id: str, ad_account_ids: List[str], budget_override: Optional[float] = None,
        status: str = "PAUSED", created_by: Optional[str] = None,
        ad_group_mode: str = "NEW", ad_group_selections: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """返回可读的发布前检查结果；不创建 Job，不调用 Meta 写接口。"""
        from services.meta import AdAccountService

        errors: List[Dict[str, Any]] = []
        warnings: List[Dict[str, Any]] = []
        template = self.db.query(CampaignTemplate).filter(CampaignTemplate.id == template_id).first()
        if not template:
            return {"passed": False, "errors": [{"code": "TEMPLATE_NOT_FOUND", "message": "投放模板不存在"}], "warnings": [], "accounts": []}
        if template.status != "ACTIVE":
            errors.append({"code": "TEMPLATE_INACTIVE", "message": "投放模板不是 ACTIVE 状态"})
        if status not in (InstanceStatus.PAUSED.value, InstanceStatus.ACTIVE.value):
            errors.append({"code": "INVALID_STATUS", "message": "初始状态只能是 PAUSED 或 ACTIVE"})
        budget_type = str(template.budget_type or "DAILY").upper()
        budget = budget_override if budget_override is not None else (
            template.lifetime_budget if budget_type == "LIFETIME" else template.daily_budget
        ) or 0
        if budget <= 0:
            errors.append({"code": "INVALID_BUDGET", "message": "预算必须大于 0"})
        config = template.creative_config_json or {}
        errors.extend(schedule_preflight_errors(budget_type, config.get("schedule")))
        errors.extend(objective_optimization_preflight_errors(template.objective, template.optimization_goal, config))
        errors.extend(tracking_asset_preflight_errors(template.optimization_goal, config))
        errors.extend(conversion_event_preflight_errors(template.optimization_goal, config))
        errors.extend(budget_bid_preflight_errors(
            "模板",
            template.daily_budget,
            template.bid_strategy,
            (config.get("bidding") or {}).get("bid_amount") if isinstance(config.get("bidding"), dict) else None,
            (config.get("bidding") or {}).get("bid_constraints") if isinstance(config.get("bidding"), dict) else None,
        ))
        tracking_requirements = tracking_asset_requirements(template.optimization_goal, config)
        ad_group_mode = str(ad_group_mode or "NEW").upper()
        ad_group_selections = ad_group_selections or {}
        if ad_group_mode not in {"NEW", "EXISTING", "COPY"}:
            errors.append({"code": "INVALID_AD_GROUP_MODE", "message": "广告组来源只能是 NEW、EXISTING 或 COPY"})
        configured_adsets = config.get("adsets") if isinstance(config.get("adsets"), list) else []
        if ad_group_mode in {"EXISTING", "COPY"} and len(configured_adsets) > 1:
            errors.append({"code": "EXISTING_AD_GROUP_SINGLE_ONLY", "message": "复用或复制模式时，每个账户只能选择一个广告组"})
        page_id = str(config.get("page_id") or "")
        if not page_id:
            errors.append({"code": "PAGE_REQUIRED", "message": "模板未选择 Facebook Page"})
        elif not self.db.query(MetaPage).filter(MetaPage.page_id == page_id, MetaPage.status == "ACTIVE").first():
            errors.append({"code": "PAGE_UNAVAILABLE", "message": "Facebook Page 未同步、已失效或不属于当前租户"})
        creative_format = str(config.get("creative_format") or "SINGLE_IMAGE_VIDEO").upper()
        if creative_format == "CAROUSEL":
            # 兼容早期模板把轮播卡片写入 creatives 的快照；新结构只保存
            # carousel_cards，避免卡片被当成多个独立广告。
            creatives = config.get("carousel_cards") if isinstance(config.get("carousel_cards"), list) else (
                config.get("creatives") if isinstance(config.get("creatives"), list) else []
            )
            if not 2 <= len(creatives) <= 10:
                errors.append({
                    "code": "CREATIVE_CAROUSEL_CARD_COUNT",
                    "message": "轮播广告必须配置 2-10 张图片卡片",
                })
            invalid_cards = [
                str(index)
                for index, creative in enumerate(creatives, 1)
                if not isinstance(creative, dict)
                or str(creative.get("asset_type") or "image").lower() != "image"
                or not (creative.get("asset_id") or creative.get("image_hash"))
            ]
            if invalid_cards:
                errors.append({
                    "code": "CREATIVE_CAROUSEL_CARD_INVALID",
                    "message": f"轮播卡片 {', '.join(invalid_cards)} 必须使用有效图片素材",
                })
        else:
            creatives = config.get("creatives") if isinstance(config.get("creatives"), list) else [config]
        if not creatives or all(
            not isinstance(c, dict)
            or not (c.get("asset_id") or c.get("image_hash") or c.get("video_id"))
            for c in creatives
        ):
            errors.append({"code": "CREATIVE_REQUIRED", "message": "模板至少需要一个有效素材"})

        ids = list(dict.fromkeys(ad_account_ids or []))
        if tracking_requirements and ids:
            selected_asset_ids = {item["asset_id"] for item in tracking_requirements}
            asset_rows = self.db.query(MetaTrackingAsset).filter(
                MetaTrackingAsset.ad_account_id.in_(ids),
                MetaTrackingAsset.meta_asset_id.in_(selected_asset_ids),
                MetaTrackingAsset.status == "ACTIVE",
                MetaTrackingAsset.usable.is_(True),
            ).all()
            usable_by_account = {}
            for row in asset_rows:
                usable_by_account.setdefault(row.ad_account_id, set()).add(row.meta_asset_id)
            unavailable_items = []
            for account_id in ids:
                available_assets = usable_by_account.get(account_id, set())
                for requirement in tracking_requirements:
                    if requirement["asset_id"] not in available_assets:
                        unavailable_items.append({
                            "account_id": account_id,
                            "asset_id": requirement["asset_id"],
                            "optimization_goal": requirement["optimization_goal"],
                            "scope": requirement["scope"],
                            "reason": "事件源未同步、已失效或不属于该广告账户",
                        })
            if unavailable_items:
                errors.append({
                    "code": "TRACKING_ASSET_UNAVAILABLE",
                    "message": "所选 Pixel/数据集并非所有目标广告账户均可用，请同步资产或调整账户范围",
                    "items": unavailable_items,
                })
            stale_cutoff = datetime.utcnow() - timedelta(hours=24)
            stale_assets = [
                row for row in asset_rows
                if not row.last_synced_at or row.last_synced_at < stale_cutoff
            ]
            if stale_assets:
                stale_summary = "; ".join(
                    f"{row.meta_ad_account_id}/{row.meta_asset_id}"
                    for row in stale_assets[:10]
                )
                suffix = "等" if len(stale_assets) > 10 else ""
                warnings.append({
                    "code": "TRACKING_ASSET_STALE",
                    "message": f"{len(stale_assets)} 个已选事件源超过 24 小时未同步（{stale_summary}{suffix}），建议先刷新资产",
                    "items": [
                        {
                            "account_id": row.ad_account_id,
                            "asset_id": row.meta_asset_id,
                            "reason": "事件源同步已超过 24 小时",
                        }
                        for row in stale_assets
                    ],
                })
        # Custom Audience 不是跨账户可复用的字符串 ID。发布前先校验账户
        # 范围，避免任务进入队列后才由 Meta 返回权限/参数错误。
        target_accounts = self.db.query(AdAccount).filter(AdAccount.id.in_(ids)).all() if ids else []
        account_scope = {}
        for account in target_accounts:
            account_scope[str(account.id)] = str(account.id)
            account_scope[str(account.account_id).replace("act_", "")] = str(account.id)
            account_scope[str(account.account_id)] = str(account.id)
        targeting_configs = [("模板定向", template.targeting_json or {})]
        placement_configs = [("模板版位", template.placement_json or {})]
        for index, adset in enumerate(configured_adsets, 1):
            if isinstance(adset, dict):
                targeting_configs.append((f"广告组 {index} 定向", adset.get("targeting") or {}))
                placement_configs.append((f"广告组 {index} 版位", adset.get("placement") or {}))
                errors.extend(budget_bid_preflight_errors(
                    f"广告组 {index}",
                    adset.get("budget"),
                    adset.get("bid_strategy") or template.bid_strategy,
                    adset.get("bid_amount"),
                ))
        audience_errors = set()
        for label, raw_targeting in targeting_configs:
            errors.extend(targeting_preflight_errors(label, raw_targeting))
            try:
                targeting = normalize_targeting(raw_targeting)
            except ValueError as exc:
                audience_errors.add(("AUDIENCE_TARGETING_INVALID", f"{label}：{exc}"))
                continue
            for field in ("custom_audiences", "excluded_custom_audiences", "excluded_audiences"):
                for audience in targeting.get(field) or []:
                    audience_id = str(audience.get("id") or "").strip()
                    scoped = str(audience.get("ad_account_id") or audience.get("account_id") or "").strip()
                    if not scoped or audience.get("resolution") == "UNRESOLVED":
                        audience_errors.add(("AUDIENCE_SCOPE_REQUIRED", f"{label} 的受众 {audience_id} 必须绑定广告账户"))
                    elif scoped.replace("act_", "") not in account_scope and scoped not in account_scope:
                        audience_errors.add(("AUDIENCE_ACCOUNT_MISMATCH", f"{label} 的受众 {audience_id} 不属于本次投放账户"))
        errors.extend({"code": code, "message": message} for code, message in sorted(audience_errors))
        for label, placement in placement_configs:
            errors.extend(placement_preflight_errors(label, placement))

        audience_policy_by_account = {}
        now = datetime.utcnow()
        for account_id in ids:
            resolved = resolve_required_exclusions(self.db, account_id, now=now)
            snapshot = resolved["snapshot"]
            audience_policy_by_account[account_id] = snapshot
            for row in resolved["assets"]:
                status_text = str(row.delivery_status or "").upper()
                if row.sync_status in {"MISSING", "DELETED", "EXPIRED", "UNAVAILABLE"} or any(
                    marker in status_text for marker in ("DELETED", "EXPIRED", "UNAVAILABLE")
                ):
                    errors.append({
                        "code": "REQUIRED_AUDIENCE_POLICY_BLOCKED",
                        "message": f"账户 {row.meta_ad_account_id} 的强制排除受众 {row.meta_audience_id} 已失效或缺失，请更新策略",
                        "account_id": account_id,
                        "audience_id": row.meta_audience_id,
                    })
                elif not row.last_synced_at:
                    errors.append({
                        "code": "REQUIRED_AUDIENCE_NOT_SYNCED",
                        "message": f"账户 {row.meta_ad_account_id} 的强制排除受众 {row.meta_audience_id} 尚未完成同步",
                        "account_id": account_id,
                        "audience_id": row.meta_audience_id,
                    })
                elif row.last_synced_at < now - timedelta(days=7):
                    errors.append({
                        "code": "REQUIRED_AUDIENCE_STALE",
                        "message": f"账户 {row.meta_ad_account_id} 的强制排除受众同步已超过 7 天，请重新同步后再投放",
                        "account_id": account_id,
                        "audience_id": row.meta_audience_id,
                    })

        available, rejected = AdAccountService(self.db).filter_available_ids(
            ids,
            user_id=created_by,
            allow_paused_debug=status == InstanceStatus.PAUSED.value,
        )
        page = self.db.query(MetaPage).filter(
            MetaPage.page_id == page_id, MetaPage.status == "ACTIVE"
        ).first() if page_id else None
        if page:
            compatible = []
            for account_pk in available:
                account = self.db.query(AdAccount).filter(AdAccount.id == account_pk).first()
                reason = page_account_access_error(page, account) if account else "账户不存在"
                if reason:
                    rejected.append({"account_id": account_pk, "reason": reason})
                else:
                    compatible.append(account_pk)
            available = compatible

        # EXISTING 复用同账户的真实 Meta AdSet；COPY 只读取源广告组参数，
        # 目标账户仍由 Connector 新建 Campaign/AdSet，绝不跨账户复用 Meta ID。
        existing_ad_groups: Dict[str, dict] = {}
        if ad_group_mode in {"EXISTING", "COPY"} and available:
            valid_available = []
            source_visible = None
            if ad_group_mode == "COPY" and created_by:
                creator = self.db.query(User).filter(User.id == created_by).first()
                if creator:
                    source_visible = accessible_account_ids(self.db, creator)
            for account_pk in available:
                selection = ad_group_selections.get(account_pk) or {}
                local_id = str(selection.get("ad_group_id") or "").strip()
                if not local_id:
                    rejected.append({"account_id": account_pk, "reason": "请选择一个已同步广告组"})
                    continue
                source_query = (
                    self.db.query(AdGroup, Campaign)
                    .join(Campaign, AdGroup.campaign_id == Campaign.id)
                    .filter(AdGroup.id == local_id, AdGroup.tenant_id == template.tenant_id, Campaign.tenant_id == template.tenant_id)
                )
                if ad_group_mode == "EXISTING":
                    source_query = source_query.filter(Campaign.ad_account_id == account_pk)
                elif source_visible is not None:
                    source_query = source_query.filter(Campaign.ad_account_id.in_(source_visible or {"__no_accounts__"}))
                row = source_query.first()
                if not row:
                    rejected.append({"account_id": account_pk, "reason": "所选广告组不存在或无权访问"})
                    continue
                ad_group, campaign = row
                if str(ad_group.status or "").upper() in {"DELETED", "NOT_FOUND", "ARCHIVED"}:
                    rejected.append({"account_id": account_pk, "reason": "所选广告组已归档或已删除，请重新选择"})
                    continue
                if str(getattr(campaign.status, "value", campaign.status) or "").upper() in {"DELETED", "NOT_FOUND", "ARCHIVED"}:
                    rejected.append({"account_id": account_pk, "reason": "所选广告组的父广告系列已归档或已删除"})
                    continue
                stale_before = datetime.utcnow() - timedelta(hours=24)
                if not ad_group.updated_at or ad_group.updated_at < stale_before:
                    rejected.append({"account_id": account_pk, "reason": "所选广告组超过 24 小时未同步，请先同步 Meta"})
                    continue
                expected_external = str(selection.get("ad_group_external_id") or "").strip()
                if expected_external and expected_external != ad_group.ad_group_id:
                    rejected.append({"account_id": account_pk, "reason": "所选广告组信息已变化，请刷新后重新选择"})
                    continue
                existing_ad_groups[account_pk] = {
                    "id": ad_group.id,
                    "ad_group_id": ad_group.ad_group_id,
                    "name": ad_group.name,
                    "status": str(ad_group.status or "ACTIVE"),
                    "campaign_id": campaign.id,
                    "campaign_external_id": campaign.campaign_id,
                    "campaign_name": campaign.name,
                    "source_account_id": campaign.ad_account_id,
                }
                valid_available.append(account_pk)
            available = valid_available

        # Page/账户授权校验完成后再检查素材，避免已被剔除的账户同时出现
        # ASSET_SYNC_PENDING，给前端返回互相矛盾的预检结果。
        asset_ids = [str(item.get("asset_id")) for item in creatives if item.get("asset_id")]
        waiting_by_account = {}
        missing_asset_ids = find_missing_asset_ids(
            self.db,
            asset_ids,
            tenant_id=template.tenant_id,
        )
        if missing_asset_ids:
            errors.append(
                {
                    "code": "ASSET_NOT_FOUND",
                    "message": "存在不存在或无权访问的素材，请重新选择素材",
                    "items": [
                        {
                            "asset_id": asset_id,
                            "reason": "素材不存在或不属于当前租户",
                        }
                        for asset_id in missing_asset_ids
                    ],
                }
            )
        # 页面无效时不继续计算素材状态，避免同时返回页面错误和素材待同步。
        if page and asset_ids and available and not missing_asset_ids:
            # 预检本身负责首次建立账户级素材绑定并派发上传任务。
            # 这里只认领 PENDING，不自动重置 FAILED：文件格式、尺寸等确定性
            # 错误反复重试没有意义，前端需要把 Meta 的原始原因展示给用户。
            try:
                pending_bindings = ensure_asset_bindings(
                    self.db,
                    asset_ids,
                    available,
                    reset_failed=False,
                )
                queue_pending_asset_bindings(
                    pending_bindings,
                    retry_failed=False,
                    db=self.db,
                )
            except Exception as exc:
                # 队列/Redis 临时不可用时仍返回绑定状态，不把预检变成 500。
                logger.warning("[Preflight] 自动派发素材同步失败: %s", exc)

            binding_rows = self.db.query(MetaAssetBinding).filter(
                MetaAssetBinding.ad_account_id.in_(available),
                MetaAssetBinding.asset_id.in_(asset_ids),
            ).all()
            asset_rows = self.db.query(CreativeAsset).filter(CreativeAsset.id.in_(asset_ids)).all()
            asset_by_id = {row.id: row for row in asset_rows}
            account_rows = self.db.query(AdAccount).filter(AdAccount.id.in_(available)).all()
            account_by_id = {row.id: row for row in account_rows}
            binding_by_account_asset = {
                (row.ad_account_id, row.asset_id): row for row in binding_rows
            }
            ready_by_account = {}
            for row in binding_rows:
                if row.status == "READY" and row.meta_asset_id:
                    ready_by_account.setdefault(row.ad_account_id, set()).add(row.asset_id)
            missing_accounts = []
            failed_accounts = []
            for account_id in list(available):
                missing = sorted(set(asset_ids) - ready_by_account.get(account_id, set()))
                failed = []
                waiting = []
                for asset_id in missing:
                    binding = binding_by_account_asset.get((account_id, asset_id))
                    if binding and binding.status in {"FAILED", "EXPIRED"} and not binding.meta_asset_id:
                        failed.append({
                            "account_id": account_id,
                            "account_name": getattr(account_by_id.get(account_id), "account_name", None),
                            "asset_id": asset_id,
                            "asset_name": getattr(asset_by_id.get(asset_id), "name", None),
                            "asset_type": getattr(asset_by_id.get(asset_id), "asset_type", None),
                            "mime_type": getattr(asset_by_id.get(asset_id), "mime_type", None),
                            "asset_ids": [asset_id],
                            "reason": "素材同步失败",
                            "error_message": binding.error_message or binding.error_code,
                        })
                    else:
                        waiting.append(asset_id)
                if failed:
                    failed_accounts.extend(failed)
                if waiting:
                    waiting_by_account[account_id] = waiting
                    missing_accounts.append({
                        "account_id": account_id,
                        "account_name": getattr(account_by_id.get(account_id), "account_name", None),
                        "reason": "素材正在自动同步",
                        "asset_ids": waiting,
                    })
            if failed_accounts:
                errors.append({
                    "code": "ASSET_SYNC_FAILED",
                    "message": f"{len(failed_accounts)} 个账户的素材同步失败，请先重试素材绑定",
                    "items": failed_accounts,
                })
            if missing_accounts:
                warnings.append({
                    "code": "ASSET_SYNC_PENDING",
                    "message": f"{len(missing_accounts)} 个账户的素材将在投放前自动同步",
                    "items": missing_accounts,
                })

        account_results = [
            {
                "account_id": x,
                "status": "WAITING_ASSET_SYNC" if x in waiting_by_account else "READY",
                "audience_policy": audience_policy_by_account.get(x),
                **({"asset_ids": waiting_by_account[x]} if x in waiting_by_account else {}),
            }
            for x in available
        ]
        account_results += [{"account_id": x.get("account_id"), "status": "BLOCKED", "reason": x.get("reason")} for x in rejected]
        if rejected:
            # 不再静默剔除账户。预览必须明确阻断，用户处理或移除账户后
            # 重新预览，提交时的账户集合才会与快照一致。
            errors.append({"code": "ACCOUNTS_REJECTED", "message": f"{len(rejected)} 个账户不可投放，请处理后重新预览", "items": rejected})
        if not available:
            errors.append({"code": "NO_AVAILABLE_ACCOUNT", "message": "没有可投放的广告账户"})
        existing = self.db.query(CampaignInstance).filter(
            CampaignInstance.template_id == template_id,
            CampaignInstance.ad_account_id.in_(available),
            CampaignInstance.status != InstanceStatus.DELETED.value,
        ).count() if available else 0
        if existing:
            warnings.append({"code": "ALREADY_DEPLOYED", "message": f"{existing} 个账户已有该模板实例，提交后会跳过创建"})
        return {
            "passed": not errors,
            "template": {"id": template.id, "name": template.name, "objective": template.objective, "creative_count": len(creatives)},
            "errors": errors,
            "warnings": warnings,
            "accounts": account_results,
            "ready_account_ids": available,
            "ad_group_mode": ad_group_mode,
            "existing_ad_groups": existing_ad_groups,
            "audience_policy_by_account": audience_policy_by_account,
        }

    # 创建
    # ------------------------------------------------------------------
    @staticmethod
    def _key_params_for_hash(action: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """只有影响"操作语义"的参数才进入幂等键

        CREATE 不把预算等易变参数放进 hash：
        实例表 UNIQUE(template_id, ad_account_id) 已保证不会重复创建。
        """
        if action == ActionType.UPDATE_BUDGET.value:
            return {"budget": params.get("budget_override")}
        return {}

    def create_job(
        self,
        *,
        template_id: str,
        ad_account_ids: List[str],
        action_type: ActionType = ActionType.CREATE,
        params: Optional[Dict[str, Any]] = None,
        created_by: Optional[str] = None,
        scheduled_at: Optional[datetime] = None,
        parent_job_id: Optional[str] = None,
        edit_mode: Optional[str] = None,
    ) -> CampaignJob:
        """创建批量任务并派发到队列（立即返回，不阻塞 HTTP）

        Args:
            scheduled_at: 计划执行时间（UTC）。为空表示立即执行；
                传入未来时间则由 Celery 的 eta 机制延迟派发，
                Job 在此期间保持 QUEUED 状态（定时投放场景）。
        """
        template = (
            self.db.query(CampaignTemplate)
            .filter(CampaignTemplate.id == template_id)
            .first()
        )
        if not template:
            raise ValueError(f"投放模板不存在: {template_id}")
        if not ad_account_ids:
            raise ValueError("请至少选择一个广告账户")

        parent_job = None
        revision_no = 1
        if parent_job_id:
            parent_job = self.db.query(CampaignJob).filter(CampaignJob.id == parent_job_id).first()
            if not parent_job:
                raise ValueError("来源任务不存在")
            if parent_job.tenant_id != template.tenant_id:
                raise ValueError("来源任务与当前租户不一致")
            revision_no = (self.db.query(CampaignJob).filter(
                CampaignJob.parent_job_id == parent_job.id
            ).count() + 2) if parent_job.parent_job_id is None else (
                self.db.query(CampaignJob).filter(
                    (CampaignJob.id == parent_job.id) | (CampaignJob.parent_job_id == parent_job.parent_job_id)
                ).count() + 1
            )

        action_value = (
            action_type.value if isinstance(action_type, ActionType) else action_type
        )

        # 文档 §19：可投放判断统一由后端 AdAccountService 完成，
        # 前端/调用方不得自行拼接规则。此处把不可投放的账户直接剔除，
        # 避免把已禁用、凭据失效或 Meta 侧异常的账户派发给 Meta。
        from services.meta import AdAccountService

        params = params or {}
        preview_id = params.get("_preview_id")
        idempotency_key = params.get("_idempotency_key")
        if idempotency_key:
            existing = (
                self.db.query(CampaignJob)
                .filter(CampaignJob.idempotency_key == idempotency_key)
                .first()
            )
            if existing:
                return existing

        # Facebook Page 只属于“新建投放”校验。启停、归档、删除、恢复和改预算
        # 作用于已经存在的 Meta Campaign，不应因为历史模板没有 page_id 或 Page
        # 授权已变更而在 HTTP 层失败；实际写操作仍由 Connector/Meta 返回结果。
        page = None
        if action_value == ActionType.CREATE.value:
            page_id = (template.creative_config_json or {}).get("page_id")
            if not page_id:
                raise ValueError("投放模板未选择 Facebook 页面，请先编辑模板选择已同步页面")
            page = self.db.query(MetaPage).filter(
                MetaPage.page_id == str(page_id),
                MetaPage.status == "ACTIVE",
            ).first()
            if not page:
                raise ValueError("模板引用的 Facebook 页面已失效或不属于当前租户，请重新同步并选择页面")

        requested_status = params.get("status", InstanceStatus.PAUSED.value)
        # 投放账户资格由 AdAccountService 统一判断；用户支付状态不参与拦截。
        ad_account_ids, rejected = AdAccountService(self.db).filter_available_ids(
            ad_account_ids,
            user_id=created_by,
            allow_paused_debug=(
                action_type == ActionType.CREATE
                and requested_status == InstanceStatus.PAUSED.value
            ),
        )
        compatible_ids = []
        if page is not None:
            for account_pk in ad_account_ids:
                account = self.db.query(AdAccount).filter(AdAccount.id == account_pk).first()
                reason = page_account_access_error(page, account) if account else "账户不存在"
                if reason:
                    rejected.append({"account_id": account_pk, "reason": reason})
                else:
                    compatible_ids.append(account_pk)
        else:
            compatible_ids = list(ad_account_ids)
        ad_account_ids = compatible_ids
        if not ad_account_ids:
            detail = "；".join(f"{r['account_id']}: {r['reason']}" for r in rejected[:5])
            raise ValueError(f"所选账户均不可参与投放：{detail}")
        if rejected:
            logger.warning(
                f"[JobService] 剔除 {len(rejected)} 个不可投放账户: "
                + "；".join(f"{r['account_id']}({r['reason']})" for r in rejected[:5])
            )

        access_map = params.get("access_business_ids") or {}
        if not isinstance(access_map, dict):
            raise ValueError("access_business_ids 必须是对象")
        for account_id, business_id in access_map.items():
            if account_id not in ad_account_ids:
                continue
            allowed = self.db.query(BusinessAssetAccess.id).filter(
                BusinessAssetAccess.business_id == business_id,
                BusinessAssetAccess.asset_type == "AD_ACCOUNT",
                BusinessAssetAccess.asset_id == account_id,
                BusinessAssetAccess.status == "ACTIVE",
            ).first()
            if not allowed:
                raise ValueError(f"BM {business_id} 无权访问广告账户 {account_id}")
        # 保留被前置校验剔除的账户，供前端明确提示，不进入投放子任务。
        if rejected:
            params = dict(params)
            params["rejected_accounts"] = rejected
        key_params = self._key_params_for_hash(action_value, params)

        # 仅在时间为「未来」时才按定时处理，过去的时间退化为立即执行
        is_scheduled = scheduled_at is not None and scheduled_at > datetime.utcnow()

        job = CampaignJob(
            id=_new_id(),
            parent_job_id=parent_job_id,
            revision_no=revision_no,
            edit_mode=edit_mode,
            template_id=template_id,
            action_type=action_value,
            status=JobStatus.QUEUED.value if is_scheduled else JobStatus.PENDING.value,
            total_accounts=len(ad_account_ids),
            params=params,
            created_by=created_by,
            preview_id=preview_id,
            submitted_by=created_by,
            submitted_at=datetime.utcnow(),
            idempotency_key=idempotency_key,
            scheduled_at=scheduled_at if is_scheduled else None,
        )
        self.db.add(job)
        self.db.flush()

        for account_id in ad_account_ids:
            access_map = params.get("access_business_ids") or {}
            access_business_id = access_map.get(account_id)
            self.db.add(
                CampaignJobItem(
                    id=_new_id(),
                    job_id=job.id,
                    ad_account_id=account_id,
                    access_business_id=access_business_id,
                    status=JobItemStatus.PENDING.value,
                    request_hash=build_request_hash(
                        template_id, account_id, action_value, key_params
                    ),
                    request_payload={"template_id": template_id, "params": params},
                )
            )

        self.db.commit()
        self.db.refresh(job)

        # 异步派发：HTTP 请求到此结束，不等待 Meta API
        try:
            if is_scheduled:
                # 定时执行：由 Celery 的 eta 机制延迟投递，到点后才会真正执行
                async_result = execute_campaign_job.apply_async(args=[job.id], eta=scheduled_at)
                job.celery_task_id = async_result.id
                self.db.commit()
                logger.info(
                    f"[JobService] 创建定时任务 {job.id} 计划执行于 {scheduled_at.isoformat()} "
                    f"账户数={len(ad_account_ids)} celery_task={async_result.id}"
                )
            else:
                async_result = execute_campaign_job.delay(job.id)
                job.celery_task_id = async_result.id
                self.db.commit()
                logger.info(
                    f"[JobService] 创建任务 {job.id} action={action_value} "
                    f"账户数={len(ad_account_ids)} celery_task={async_result.id}"
                )
        except Exception as exc:
            message = self._mark_dispatch_failed(job.id, exc)
            logger.exception("[JobService] 任务 %s 入队失败", job.id)
            raise JobDispatchError(message) from exc
        return job

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    def get_job(self, job_id: str) -> Optional[CampaignJob]:
        return self.db.query(CampaignJob).filter(CampaignJob.id == job_id).first()

    def list_jobs(self, limit: int = 50, status: Optional[str] = None) -> List[CampaignJob]:
        query = self.db.query(CampaignJob)
        if status:
            query = query.filter(CampaignJob.status == status)
        return query.order_by(CampaignJob.created_at.desc()).limit(limit).all()

    def list_scheduled_jobs(self, limit: int = 50) -> List[CampaignJob]:
        """待执行的定时任务（按计划执行时间升序）"""
        return (
            self.db.query(CampaignJob)
            .filter(
                CampaignJob.scheduled_at.isnot(None),
                CampaignJob.status.in_([JobStatus.PENDING.value, JobStatus.QUEUED.value]),
            )
            .order_by(CampaignJob.scheduled_at.asc())
            .limit(limit)
            .all()
        )

    def get_job_detail(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Job 详情 + 子项列表（供前端轮询进度）"""
        job = self.get_job(job_id)
        if not job:
            return None
        return {
            **job.to_dict(),
            "items": [item.to_dict() for item in job.items],
        }

    # ------------------------------------------------------------------
    # 控制
    # ------------------------------------------------------------------
    @staticmethod
    def _revoke_celery_task(task_id: str) -> None:
        """撤销 Celery 中尚未执行的任务（失败不阻断本地状态更新）"""
        try:
            from celery_app import celery_app

            celery_app.control.revoke(task_id, terminate=False)
            logger.info(f"[JobService] 已撤销 Celery 任务 {task_id}")
        except Exception as e:
            logger.warning(f"[JobService] 撤销 Celery 任务 {task_id} 失败: {e}")

    def cancel_job(self, job_id: str) -> Optional[CampaignJob]:
        """取消任务：撤销未执行的 Celery 投递，未完成子项标记为 SKIPPED"""
        job = self.get_job(job_id)
        if not job:
            return None
        if job.status in (JobStatus.SUCCESS.value, JobStatus.FAILED.value):
            return job

        # 定时任务若尚未到执行时间，需撤销 Celery 中的 eta 投递
        if job.celery_task_id:
            self._revoke_celery_task(job.celery_task_id)

        job.status = JobStatus.CANCELLED.value
        self.db.query(CampaignJobItem).filter(
            CampaignJobItem.job_id == job_id,
            CampaignJobItem.status.in_(
                [JobItemStatus.PENDING.value, JobItemStatus.RUNNING.value]
            ),
        ).update(
            {CampaignJobItem.status: JobItemStatus.SKIPPED.value},
            synchronize_session=False,
        )
        self.db.commit()
        logger.info(f"[JobService] 任务 {job_id} 已取消")
        return job

    def retry_failed(
        self,
        job_id: str,
        item_ids: Optional[List[str]] = None,
        retry_mode: str = "CONTINUE",
    ) -> int:
        """按账户/任务项继续执行失败节点，不重新执行已成功账户。"""
        job = self.get_job(job_id)
        if not job:
            return 0
        query = (
            self.db.query(CampaignJobItem)
            .filter(
                CampaignJobItem.job_id == job_id,
                CampaignJobItem.status == JobItemStatus.FAILED.value,
            )
        )
        if item_ids:
            query = query.filter(CampaignJobItem.id.in_(item_ids))
        failed_count = query.count()
        if failed_count == 0:
            return 0
        retry_failed_job_items.delay(job_id, item_ids or None, retry_mode)
        return failed_count

    def cleanup_job_item(self, job_id: str, item_id: str) -> Optional[Dict[str, Any]]:
        """显式清理该任务项已创建的 Meta 对象；复用对象由 Connector 跳过。"""
        item = (
            self.db.query(CampaignJobItem)
            .filter(CampaignJobItem.id == item_id, CampaignJobItem.job_id == job_id)
            .first()
        )
        if not item:
            return None
        payload = item.response_payload if isinstance(item.response_payload, dict) else {}
        protocol = payload.get("protocol") or {}
        credential_id = protocol.get("credential_id")
        task_id = item.connector_task_id or (payload.get("connector") or {}).get("connector_task_id")
        cleanup_status = payload.get("cleanup_status")
        if cleanup_status == "COMPLETED":
            return {"status": "ALREADY_COMPLETED"}
        orphaned_only = item.status != JobItemStatus.FAILED.value
        if not credential_id or not task_id:
            return {"status": "NOT_REQUIRED", "reason": "没有可清理的海外任务"}
        result = FBConnectorClient().cleanup_deployment(
            task_id,
            credential_id,
            orphaned_only=orphaned_only,
        )
        payload = {
            **payload,
            "cleanup": result,
            "cleanup_status": "COMPLETED" if result.get("status") == "SUCCESS" else "PARTIAL",
            "cleanup_scope": "ORPHANED_ONLY" if orphaned_only else "CREATED_OBJECTS",
        }
        item.response_payload = payload
        self.db.commit()
        return result

    def reconcile_job_item(self, job_id: str, item_id: str) -> Optional[Dict[str, Any]]:
        """查询海外未知提交结果，并把候选快照保存到国内任务详情。"""
        item = (
            self.db.query(CampaignJobItem)
            .filter(
                CampaignJobItem.id == item_id,
                CampaignJobItem.job_id == job_id,
            )
            .first()
        )
        if not item:
            return None
        payload = item.response_payload if isinstance(item.response_payload, dict) else {}
        protocol = payload.get("protocol") or {}
        credential_id = protocol.get("credential_id")
        task_id = item.connector_task_id or (payload.get("connector") or {}).get("connector_task_id")
        if not credential_id or not task_id:
            return {"status": "NOT_REQUIRED", "reason": "没有可对账的海外任务"}
        result = FBConnectorClient().reconcile_deployment(task_id, credential_id)
        item.response_payload = {
            **payload,
            "reconcile": result,
            "reconcile_checked_at": datetime.utcnow().isoformat(),
        }
        self.db.commit()
        return result

    def confirm_reconcile_job_item(
        self,
        job_id: str,
        item_id: str,
        confirmations: list[dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """确认运营选择的海外 Meta 候选，并保存确认快照。"""
        item = (
            self.db.query(CampaignJobItem)
            .filter(
                CampaignJobItem.id == item_id,
                CampaignJobItem.job_id == job_id,
            )
            .first()
        )
        if not item:
            return None
        payload = item.response_payload if isinstance(item.response_payload, dict) else {}
        protocol = payload.get("protocol") or {}
        credential_id = protocol.get("credential_id")
        task_id = item.connector_task_id or (payload.get("connector") or {}).get("connector_task_id")
        if not credential_id or not task_id:
            return {"status": "NOT_REQUIRED", "reason": "没有可确认的海外任务"}
        result = FBConnectorClient().confirm_reconcile_deployment(
            task_id,
            credential_id,
            confirmations,
        )
        reconcile = payload.get("reconcile") if isinstance(payload.get("reconcile"), dict) else {}
        remaining_pending = result.get("remaining_pending") if isinstance(result, dict) else None
        item.response_payload = {
            **payload,
            "reconcile": {
                **reconcile,
                "pending": remaining_pending if isinstance(remaining_pending, list) else reconcile.get("pending", []),
                "message": result.get("message") if isinstance(result, dict) else reconcile.get("message"),
            },
            "reconcile_confirmation": result,
        }
        self.db.commit()
        return result

    def dispatch_now(self, job_id: str) -> Optional[CampaignJob]:
        """把定时任务提前为立即执行

        需先撤销原定的 eta 投递，否则到点后会重复执行一次。
        """
        job = self.get_job(job_id)
        if not job:
            return None
        if job.status in (
            JobStatus.SUCCESS.value,
            JobStatus.FAILED.value,
            JobStatus.CANCELLED.value,
        ):
            return job

        if job.celery_task_id:
            self._revoke_celery_task(job.celery_task_id)
            job.celery_task_id = None

        job.scheduled_at = None
        job.status = JobStatus.PENDING.value
        self.db.commit()

        try:
            async_result = execute_campaign_job.delay(job.id)
            job.celery_task_id = async_result.id
            self.db.commit()
        except Exception as exc:
            message = self._mark_dispatch_failed(job.id, exc)
            logger.exception("[JobService] 定时任务 %s 提前执行入队失败", job.id)
            raise JobDispatchError(message) from exc
        logger.info(f"[JobService] 定时任务 {job_id} 已提前执行 celery_task={async_result.id}")
        return job
