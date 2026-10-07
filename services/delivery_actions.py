"""Shared object scope and state rules for published delivery actions."""
from datetime import datetime

from models import AdInstance, AdSetInstance, CampaignInstance, Campaign, AdGroup, Ad, AsyncTaskRecord
from models.campaign import CampaignStatus


OBJECT_MODELS = {"CAMPAIGN": CampaignInstance, "ADSET": AdSetInstance, "AD": AdInstance}
META_ID_FIELDS = {"CAMPAIGN": "meta_campaign_id", "ADSET": "meta_adset_id", "AD": "meta_ad_id"}


def object_account_id(obj, object_type):
    if object_type == "CAMPAIGN":
        return obj.ad_account_id
    if object_type == "ADSET":
        return obj.campaign_instance.ad_account_id
    return obj.adset_instance.campaign_instance.ad_account_id


def remote_deleted(obj):
    return obj.meta_status in {"DELETED", "PARENT_DELETED"}


def validate_action(obj, action):
    if action not in {"PAUSE", "ENABLE", "ARCHIVE", "DELETE", "RESTORE", "UPDATE_BUDGET"}:
        raise ValueError("不支持的投放操作")
    if remote_deleted(obj):
        raise ValueError("Meta 对象已删除，不能继续操作；重新投放请复制新建")
    if action == "RESTORE" and obj.status != "ARCHIVED":
        raise ValueError("只有本地归档对象可以取消归档，已删除对象不能恢复")
    if obj.status == "DELETED" and action != "DELETE":
        raise ValueError("历史本地移除对象只允许核对状态或提交 Meta 删除")


def deletion_state(obj):
    if remote_deleted(obj):
        return "REMOTE_DELETED"
    return "LOCAL_REMOVED" if obj.status == "DELETED" else None


def finish_action_task_record(db, action_row):
    record = db.query(AsyncTaskRecord).filter_by(task_id=action_row.task_id).first()
    if record:
        record.status = action_row.status
        record.result_summary = {"status": action_row.status.lower()}
        record.finished_at = action_row.finished_at


def mark_remote_deleted(obj, object_type, action_id=None, db=None):
    """Keep mapping/history; project parent deletion onto local descendants."""
    now = datetime.utcnow()

    def mark(row, inherited=False):
        row.status = row.desired_status = "DELETED"
        row.meta_status = "PARENT_DELETED" if inherited else "DELETED"
        row.deleted_at = row.last_synced_at = now
        row.archived_at = None
        row.last_error = None
        row.last_action_id = action_id

    mark(obj)
    adsets = obj.adsets if object_type == "CAMPAIGN" else [obj] if object_type == "ADSET" else []
    for adset in adsets:
        if object_type == "CAMPAIGN":
            mark(adset, True)
        for ad in adset.ads:
            mark(ad, True)
    if db is not None:
        model, field = {"CAMPAIGN": (Campaign, Campaign.campaign_id), "ADSET": (AdGroup, AdGroup.ad_group_id), "AD": (Ad, Ad.ad_id)}[object_type]
        canonical = db.query(model).filter(model.tenant_id == obj.tenant_id, field == getattr(obj, META_ID_FIELDS[object_type])).first()
        if canonical:
            account = canonical.ad_account_id if object_type == "CAMPAIGN" else canonical.campaign.ad_account_id if object_type == "ADSET" else canonical.ad_group.campaign.ad_account_id
            if account != object_account_id(obj, object_type):
                return
            canonical.status = CampaignStatus.DELETED if object_type == "CAMPAIGN" else "DELETED"
            groups = canonical.ad_groups if object_type == "CAMPAIGN" else [canonical] if object_type == "ADSET" else []
            for group in groups:
                group.status = "DELETED"
                for ad in group.ads:
                    ad.status = "DELETED"
