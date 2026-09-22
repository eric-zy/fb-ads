"""
素材库接口：图片 / 视频上传、列表、删除。
素材统一使用 OSS 浏览器直传 + 服务端校验 + 异步媒体处理。
素材就绪后按广告账户建立独立 Meta/Connector 映射。
权限：登录用户即可；素材默认进入租户共享素材库，投放或显式同步时再绑定广告账户。
"""
import os
import uuid
import mimetypes
from datetime import date, datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc, func, case, or_
from pydantic import BaseModel, Field
from typing import Optional, List

from core.database import get_db
from core.tenant import effective_tenant_id
from core.auth import get_current_active_user
from core.logger import logger
from models import CreativeAsset, AdAccount, MetaAssetBinding, CreativeAssetUsageEvent, CreativeAssetUsageDailyStat, CreativeAssetUsageAccountDailyStat, User, CreativeAssetGroup, MediaUploadSession
from models.creative_asset_group import creative_asset_group_members
from models.creative_asset_tag import creative_asset_tag_links
from config.settings import settings
from tasks.media_tasks import process_oss_asset_task, delete_oss_asset_task
from services.storage import AliyunOSSStorage, StorageError
from services.account_access import accessible_account_ids
from services.media_binding_service import ensure_asset_bindings, queue_pending_asset_bindings

router = APIRouter(prefix="/api/v1/media", tags=["素材库"])

ALLOWED_IMAGE = {"image/jpeg", "image/png", "image/gif", "image/webp"}
ALLOWED_VIDEO = {"video/mp4", "video/quicktime", "video/x-matroska", "video/webm"}
MAX_SIZE = getattr(settings, "MAX_UPLOAD_SIZE", 1024 * 1024 * 1024)


class MediaItem(BaseModel):
    id: str
    name: str
    created_by: Optional[str] = None
    visibility: str = "TENANT"
    group_id: Optional[str] = None
    tag_ids: Optional[List[str]] = None
    asset_type: str
    meta_account_id: Optional[str]
    account_id: Optional[str]
    url: Optional[str]
    fb_hash: Optional[str]
    fb_video_id: Optional[str]
    width: Optional[int]
    height: Optional[int]
    size: Optional[int]
    mime_type: Optional[str]
    duration: Optional[float]
    status: str
    retry_count: int = 0
    error: Optional[str]
    created_at: Optional[str]
    updated_at: Optional[str] = None
    binding_id: Optional[str] = None
    task_id: Optional[str] = None
    original_name: Optional[str] = None
    stored_name: Optional[str] = None
    object_key: Optional[str] = None
    storage_bucket: Optional[str] = None
    storage_region: Optional[str] = None
    storage_status: Optional[str] = None
    processing_status: Optional[str] = None
    thumbnail_key: Optional[str] = None
    cover_key: Optional[str] = None
    md5: Optional[str] = None
    sha256: Optional[str] = None
    uploader_name: Optional[str] = None
    uploader_email: Optional[str] = None
    uploaded_at: Optional[str] = None
    can_edit: bool = False
    binding_count: int = 0
    ready_binding_count: int = 0
    failed_binding_count: int = 0
    publish_count: int = 0
    successful_publish_count: int = 0
    last_published_at: Optional[str] = None
    usage_count: int = 0
    successful_usage_count: int = 0
    failed_usage_count: int = 0
    last_used_at: Optional[str] = None

    class Config:
        from_attributes = True

class AssetPrepareRequest(BaseModel):
    ad_account_ids: List[str]

class MediaUploadSessionRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    asset_type: str = Field(..., pattern="^(image|video)$")
    mime_type: str = Field(..., min_length=1, max_length=100)
    size: int = Field(..., gt=0, le=MAX_SIZE)
    md5: Optional[str] = Field(None, min_length=32, max_length=32, pattern="^[0-9a-fA-F]{32}$")
    sha256: str = Field(..., min_length=64, max_length=64, pattern="^[0-9a-fA-F]{64}$")
    account_id: Optional[str] = None
    meta_account_id: Optional[str] = None
    group_id: Optional[str] = None
    asset_id: Optional[str] = None


def _oss_extension(name: str, mime_type: str) -> str:
    ext = os.path.splitext(name)[1].lower().lstrip(".")
    allowed = {"jpg", "jpeg", "png", "gif", "webp", "mp4", "mov", "mkv", "webm"}
    if ext not in allowed:
        ext = (mimetypes.guess_extension(mime_type) or ".bin").lstrip(".").lower()
    return ext


def _oss_object_key(
    user: User,
    asset_id: str,
    name: str,
    md5: Optional[str],
    mime_type: str,
    sha256: str,
) -> str:
    now = datetime.utcnow()
    stamp = now.strftime("%Y%m%d%H%M%S")
    digest = (md5 or sha256)[:32].lower()
    stored_name = f"{user.id}_{stamp}_{digest}.{_oss_extension(name, mime_type)}"
    tenant_id = effective_tenant_id(user) or "unassigned"
    return f"{settings.OSS_BASE_PATH}/{tenant_id}/{user.id}/{settings.OSS_PLATFORM}/{now:%Y/%m/%d}/{asset_id}/{stored_name}"


def _multipart_upload_response(storage: AliyunOSSStorage, session: MediaUploadSession) -> dict:
    """Create fresh presigned URLs for every part of an active OSS upload."""
    if not session.upload_id or not session.part_size or not session.part_count:
        raise StorageError("OSS 分片上传会话参数不完整")
    uploaded_parts = storage.list_multipart_parts(session.object_key, session.upload_id)
    return {
        "upload_id": session.upload_id,
        "part_size": session.part_size,
        "part_count": session.part_count,
        "uploaded_parts": uploaded_parts,
        "parts": [
            storage.presign_upload_part(session.object_key, session.upload_id, part_number)
            for part_number in range(1, session.part_count + 1)
        ],
    }


@router.get("/{asset_id}/download-url")
def media_download_url(
    asset_id: str,
    kind: str = Query("original", pattern="^(original|thumbnail|cover)$"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    asset = _get_asset_or_404(db, asset_id, user)
    if not asset.object_key or asset.storage_status != "READY":
        raise HTTPException(status_code=409, detail="素材尚未完成 OSS 处理")
    key = asset.object_key
    if kind == "thumbnail" and asset.thumbnail_key:
        key = asset.thumbnail_key
    elif kind == "cover":
        # 封面生成失败时仍可使用 thumbnail；不能回退到视频 object_key，
        # 否则前端 <img> 只能显示空白占位图。
        key = asset.cover_key or asset.thumbnail_key
    if kind in {"thumbnail", "cover"} and not key:
        raise HTTPException(status_code=409, detail="素材缩略图尚未生成")
    try:
        url = AliyunOSSStorage().download_url(key)
    except StorageError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"asset_id": asset.id, "url": url, "expires_in": settings.OSS_DOWNLOAD_EXPIRE_SECONDS}


def _accessible_account_ids(db: Session, user: User) -> Optional[set[str]]:
    # 保留模块内名称，避免已有调用方和回归脚本变化；实际规则集中维护。
    return accessible_account_ids(db, user)


def _accessible_account_keys(db: Session, user: User) -> Optional[set[str]]:
    """返回统计事件可能使用的内部 ID 和 act_xxx 标识。"""
    account_ids = _accessible_account_ids(db, user)
    if account_ids is None:
        return None
    keys = set(account_ids)
    if account_ids:
        rows = db.query(AdAccount.id, AdAccount.account_id).filter(
            AdAccount.id.in_(account_ids)
        ).all()
        keys.update(value for row in rows for value in row if value)
    return keys


def _asset_query(db: Session, user: User):
    # 素材库按租户共享：created_by、visibility 和素材归属账户不参与可见性判断。
    # 用户是否能操作具体广告账户，仍由 _assert_account_access 单独校验。
    return db.query(CreativeAsset).filter(CreativeAsset.status != "ARCHIVED")


def _get_asset_or_404(db: Session, asset_id: str, user: User) -> CreativeAsset:
    asset = _asset_query(db, user).filter(CreativeAsset.id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="素材不存在或无权访问")
    return asset


def _assert_asset_edit_access(asset: CreativeAsset, user: User) -> None:
    if user.is_admin() or asset.created_by == user.id:
        return
    raise HTTPException(status_code=403, detail="素材已共享，只有上传人或管理员可以修改")


def _asset_response_list(db: Session, assets: list[CreativeAsset], user: Optional[User] = None) -> list[dict]:
    """批量补充上传人和日汇总统计，避免素材列表扫描使用事件。"""
    asset_ids = [asset.id for asset in assets]
    uploader_ids = {asset.created_by for asset in assets if asset.created_by}
    users = {}
    if uploader_ids:
        users = {
            user_id: (username, email)
            for user_id, username, email in db.query(User.id, User.username, User.email).filter(
                User.id.in_(uploader_ids)
            ).all()
        }
    binding_stats = {}
    usage_stats = {}
    if asset_ids:
        binding_filters = [MetaAssetBinding.asset_id.in_(asset_ids)]
        account_ids = _accessible_account_ids(db, user) if user else None
        if account_ids is not None:
            binding_filters.append(
                MetaAssetBinding.ad_account_id.in_(account_ids or {"__no_accounts__"})
            )
        binding_stats = {
            asset_id: (int(total or 0), int(ready or 0), int(failed or 0))
            for asset_id, total, ready, failed in db.query(
                MetaAssetBinding.asset_id,
                func.count(MetaAssetBinding.id),
                func.sum(case((MetaAssetBinding.status == "READY", 1), else_=0)),
                func.sum(case((MetaAssetBinding.status == "FAILED", 1), else_=0)),
            ).filter(*binding_filters).group_by(MetaAssetBinding.asset_id).all()
        }
        usage_stats = {
            asset_id: (int(total or 0), int(success or 0), int(failed or 0), last_used_at)
            for asset_id, total, success, failed, last_used_at in db.query(
                CreativeAssetUsageDailyStat.asset_id,
                func.sum(CreativeAssetUsageDailyStat.usage_count),
                func.sum(CreativeAssetUsageDailyStat.successful_usage_count),
                func.sum(CreativeAssetUsageDailyStat.failed_usage_count),
                func.max(CreativeAssetUsageDailyStat.last_used_at),
            ).filter(CreativeAssetUsageDailyStat.asset_id.in_(asset_ids)).group_by(CreativeAssetUsageDailyStat.asset_id).all()
        }
    result = []
    for asset in assets:
        data = asset.to_dict()
        username, email = users.get(asset.created_by, (None, None))
        binding_count, ready_binding_count, failed_binding_count = binding_stats.get(asset.id, (0, 0, 0))
        usage_count, successful_usage_count, failed_usage_count, last_used_at = usage_stats.get(asset.id, (0, 0, 0, None))
        data["uploader_name"] = username or ("已删除用户" if asset.created_by else "系统")
        data["uploader_email"] = email
        data["uploaded_at"] = asset.created_at.isoformat() + "Z" if asset.created_at else None
        data["can_edit"] = bool(user and (user.is_admin() or asset.created_by == user.id))
        data["binding_count"] = binding_count
        data["ready_binding_count"] = ready_binding_count
        data["failed_binding_count"] = failed_binding_count
        data["publish_count"] = usage_count
        data["successful_publish_count"] = successful_usage_count
        data["last_published_at"] = last_used_at.isoformat() + "Z" if last_used_at else None
        data["usage_count"] = usage_count
        data["successful_usage_count"] = successful_usage_count
        data["failed_usage_count"] = failed_usage_count
        data["last_used_at"] = last_used_at.isoformat() + "Z" if last_used_at else None
        result.append(data)
    return result


def _assert_account_access(db: Session, account_id: str, user: User) -> AdAccount:
    account = db.query(AdAccount).filter(AdAccount.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="广告账户不存在")
    account_ids = _accessible_account_ids(db, user)
    if account_ids is not None and account.id not in account_ids:
        raise HTTPException(status_code=403, detail="无权使用该广告账户")
    return account


def _upsert_asset_binding(db: Session, asset: CreativeAsset, account: AdAccount) -> MetaAssetBinding:
    """为素材和广告账户建立幂等映射，上传去重时也必须执行。"""
    binding = db.query(MetaAssetBinding).filter(
        MetaAssetBinding.asset_id == asset.id,
        MetaAssetBinding.ad_account_id == account.id,
    ).first()
    if not binding:
        binding = MetaAssetBinding(
            id=uuid.uuid4().hex,
            tenant_id=account.tenant_id,
            asset_id=asset.id,
            ad_account_id=account.id,
            meta_asset_type=asset.asset_type,
            status="PENDING",
        )
        db.add(binding)
    elif binding.status in ("FAILED", "EXPIRED"):
        binding.status = "PENDING"
        binding.error_message = None
        binding.error_code = None
        binding.connector_task_id = None
        binding.updated_at = datetime.utcnow()
    return binding


def _assert_group_access(db: Session, group_id: Optional[str], user: User) -> None:
    if not group_id:
        return
    group = db.query(CreativeAssetGroup).filter(CreativeAssetGroup.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="素材分组不存在")
    if user.is_admin() or group.owner_id == user.id:
        return
    member = db.execute(creative_asset_group_members.select().where(
        creative_asset_group_members.c.group_id == group_id,
        creative_asset_group_members.c.user_id == user.id,
    )).first()
    if not member or not member.can_edit:
        raise HTTPException(status_code=403, detail="无权向该素材分组上传素材")

@router.get("/{asset_id}/bindings")
def list_asset_bindings(
    asset_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    asset = _get_asset_or_404(db, asset_id, user)
    account_ids = _accessible_account_ids(db, user)
    binding_query = db.query(MetaAssetBinding).filter(MetaAssetBinding.asset_id == asset_id)
    if account_ids is not None:
        binding_query = binding_query.filter(
            MetaAssetBinding.ad_account_id.in_(account_ids or {"__no_accounts__"})
        )
    rows = binding_query.all()
    result = []
    for row in rows:
        item = row.to_dict()
        account = db.query(AdAccount).filter(AdAccount.id == row.ad_account_id).first()
        item["account_name"] = account.account_name if account else row.ad_account_id
        result.append(item)
    return result

@router.post("/{asset_id}/prepare")
def prepare_asset_bindings(
    asset_id: str,
    req: AssetPrepareRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """为目标广告账户建立素材映射占位，实际上传由异步任务执行。"""
    asset = _get_asset_or_404(db, asset_id, user)
    if asset.storage_status != "READY" or asset.processing_status != "READY":
        raise HTTPException(status_code=409, detail="素材尚未完成 OSS 处理，请等待素材状态变为 READY")
    if not req.ad_account_ids:
        raise HTTPException(status_code=400, detail="至少选择一个广告账户")
    account_ids = []
    for account_id in set(req.ad_account_ids):
        account_ids.append(_assert_account_access(db, account_id, user).id)
    created = ensure_asset_bindings(db, [asset_id], account_ids)
    db.commit()
    # 重新同步不仅建立占位记录，也必须为已有的 PENDING/失败记录重新派发上传任务。
    # READY 的绑定无需重复上传；UPLOADING/PROCESSING 由原任务继续处理，避免重复任务。
    queued = queue_pending_asset_bindings(created, db=db)
    return {
        "asset_id": asset_id,
        "status": "QUEUED" if queued else "READY",
        "bindings": [row.to_dict() for row in created],
        "queued_tasks": queued,
    }


@router.post("/{asset_id}/bindings/{binding_id}/retry")
def retry_asset_binding(
    asset_id: str,
    binding_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    asset = _get_asset_or_404(db, asset_id, user)
    binding = db.query(MetaAssetBinding).filter(
        MetaAssetBinding.id == binding_id,
        MetaAssetBinding.asset_id == asset_id,
    ).first()
    if not binding:
        raise HTTPException(status_code=404, detail="素材映射不存在或无权访问")
    _assert_account_access(db, binding.ad_account_id, user)
    binding.status = "FAILED"
    binding.error_message = None
    db.commit()
    queued = queue_pending_asset_bindings([binding], retry_failed=True, db=db)
    return {
        "status": "QUEUED" if queued else binding.status,
        "binding_id": binding.id,
        "task_id": queued[0]["task_id"] if queued else None,
    }


@router.post("/upload-sessions")
def create_media_upload_session(
    payload: MediaUploadSessionRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """创建 OSS 浏览器直传会话；大文件使用 Multipart 分片上传。"""
    allowed = ALLOWED_IMAGE if payload.asset_type == "image" else ALLOWED_VIDEO
    if payload.mime_type not in allowed:
        raise HTTPException(status_code=400, detail=f"素材类型与 MIME 不匹配: {payload.mime_type}")
    _assert_group_access(db, payload.group_id, user)
    account = _assert_account_access(db, payload.account_id, user) if payload.account_id else None
    tenant_id = account.tenant_id if account else effective_tenant_id(user)
    if not tenant_id:
        raise HTTPException(status_code=400, detail="当前用户未绑定租户")

    retry_asset = None
    if payload.asset_id:
        retry_asset = _get_asset_or_404(db, payload.asset_id, user)
        if not user.is_admin() and retry_asset.created_by != user.id:
            raise HTTPException(status_code=403, detail="无权重新上传该素材")
        if retry_asset.status not in {"FAILED", "PENDING", "UPLOADING"}:
            raise HTTPException(status_code=409, detail="当前素材不需要重新上传")
        if retry_asset.asset_type != payload.asset_type or retry_asset.size != payload.size:
            raise HTTPException(status_code=400, detail="重新上传的文件类型或大小与原素材不一致")
        if retry_asset.sha256 and retry_asset.sha256.lower() != payload.sha256.lower():
            raise HTTPException(status_code=400, detail="重新上传的文件内容与原素材不一致")

        # 同一素材只保留一个可写会话；旧 Multipart 会话及时中止，
        # 避免重试时继续占用 OSS 临时分片空间。
        old_sessions = db.query(MediaUploadSession).filter(
            MediaUploadSession.asset_id == retry_asset.id,
            MediaUploadSession.status == "UPLOADING",
        ).with_for_update().all()
        try:
            storage_for_abort = AliyunOSSStorage()
        except StorageError:
            storage_for_abort = None
        for old_session in old_sessions:
            if storage_for_abort and old_session.upload_mode == "multipart" and old_session.upload_id:
                try:
                    storage_for_abort.abort_multipart_upload(old_session.object_key, old_session.upload_id)
                except Exception as exc:
                    logger.warning("[MediaUpload] abort old multipart failed session_id=%s: %s", old_session.id, exc)
            old_session.status = "EXPIRED"
            old_session.error_message = "已被用户重新上传替换"

        retry_asset.storage_status = "UPLOADING"
        retry_asset.processing_status = "PENDING"
        retry_asset.status = "PENDING"
        retry_asset.error = None
        retry_asset.retry_count = (retry_asset.retry_count or 0) + 1
        db.flush()

    # 失败/中断的旧素材不能阻塞用户再次上传同一个文件。
    # 已完成 OSS 上传但仍在解析中的素材仍可复用，避免重复对象。
    existing = _asset_query(db, user).filter(
        CreativeAsset.sha256 == payload.sha256.lower(),
        CreativeAsset.size == payload.size,
        CreativeAsset.asset_type == payload.asset_type,
        CreativeAsset.status.in_(("PENDING", "PROCESSING", "READY")),
        CreativeAsset.storage_status != "UPLOADING",
    ).order_by(CreativeAsset.updated_at.desc()).first()
    if existing and not retry_asset:
        binding = _upsert_asset_binding(db, existing, account) if account else None
        db.commit()
        task_id = None
        if account and existing.processing_status == "READY" and binding.status == "PENDING":
            queued = queue_pending_asset_bindings([binding], db=db)
            task_id = queued[0]["task_id"] if queued else None
        return {
            "duplicate": True,
            "asset_id": existing.id,
            "status": existing.status,
            "asset": existing.to_dict(),
            "binding": binding.to_dict() if binding else None,
            "binding_id": binding.id if binding else None,
            "task_id": task_id,
        }

    # 浏览器中断后重新选择同一个文件时复用未完成会话，避免再次创建 OSS 对象。
    pending_session = db.query(MediaUploadSession).filter(
        MediaUploadSession.tenant_id == tenant_id,
        MediaUploadSession.created_by == user.id,
        MediaUploadSession.expected_sha256 == payload.sha256.lower(),
        MediaUploadSession.expected_size == payload.size,
        MediaUploadSession.status == "UPLOADING",
        MediaUploadSession.expires_at > datetime.utcnow(),
    ).order_by(MediaUploadSession.updated_at.desc()).first()
    if pending_session:
        pending_asset = db.query(CreativeAsset).filter(CreativeAsset.id == pending_session.asset_id).first()
        if pending_asset:
            binding = _upsert_asset_binding(db, pending_asset, account) if account else None
            db.commit()
            try:
                storage = AliyunOSSStorage()
                if pending_session.upload_mode == "multipart":
                    multipart = _multipart_upload_response(storage, pending_session)
                    upload = None
                else:
                    multipart = None
                    upload = storage.presign_put(pending_session.object_key, payload.mime_type)
            except StorageError as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            logger.info(
                "[MediaUpload] resumed asset_id=%s session_id=%s mode=%s parts=%s",
                pending_asset.id,
                pending_session.id,
                pending_session.upload_mode,
                pending_session.part_count or 1,
            )
            return {
                "duplicate": False,
                "resumed": True,
                "asset_id": pending_asset.id,
                "upload_session_id": pending_session.id,
                "binding_id": binding.id if binding else None,
                "object_key": pending_session.object_key,
                "upload": upload,
                "multipart": multipart,
                "expires_at": pending_session.expires_at.isoformat(),
            }

    asset_id = retry_asset.id if retry_asset else uuid.uuid4().hex
    object_key = retry_asset.object_key if retry_asset else _oss_object_key(
        user, asset_id, payload.name, payload.md5, payload.mime_type, payload.sha256
    )
    now = datetime.utcnow()
    asset = retry_asset or CreativeAsset(
        id=asset_id,
        tenant_id=tenant_id,
        name=payload.name,
        original_name=payload.name,
        created_by=user.id,
        visibility="TENANT",
        group_id=payload.group_id,
        asset_type=payload.asset_type,
        meta_account_id=payload.meta_account_id,
        account_id=payload.account_id,
        stored_name=os.path.basename(object_key),
        object_key=object_key,
        storage_bucket=settings.OSS_BUCKET,
        storage_region=settings.OSS_REGION,
        storage_status="UPLOADING",
        processing_status="PENDING",
        size=payload.size,
        mime_type=payload.mime_type,
        status="PENDING",
        md5=payload.md5.lower() if payload.md5 else None,
        sha256=payload.sha256.lower(),
    )
    use_multipart = payload.size >= settings.OSS_MULTIPART_THRESHOLD_BYTES
    part_size = settings.OSS_MULTIPART_PART_SIZE_BYTES if use_multipart else None
    part_count = ((payload.size + part_size - 1) // part_size) if part_size else None
    session = MediaUploadSession(
        id=uuid.uuid4().hex,
        tenant_id=tenant_id,
        asset_id=asset.id,
        object_key=object_key,
        upload_mode="multipart" if use_multipart else "single",
        part_size=part_size,
        part_count=part_count,
        expected_size=payload.size,
        expected_md5=payload.md5.lower() if payload.md5 else None,
        expected_sha256=payload.sha256.lower(),
        status="UPLOADING",
        expires_at=now + timedelta(seconds=settings.OSS_UPLOAD_EXPIRE_SECONDS),
        created_by=user.id,
    )
    binding = None
    if account and retry_asset:
        binding = _upsert_asset_binding(db, asset, account)
        binding.status = "PENDING"
        binding.processing_status = "PENDING"
        binding.error_code = None
        binding.error_message = None
    elif account:
        binding = MetaAssetBinding(
            id=uuid.uuid4().hex,
            tenant_id=tenant_id,
            asset_id=asset.id,
            ad_account_id=account.id,
            meta_asset_type=asset.asset_type,
            status="PENDING",
        )
    try:
        storage = AliyunOSSStorage()
        if use_multipart:
            session.upload_id = storage.initiate_multipart_upload(object_key, payload.mime_type)
            upload = None
            multipart = _multipart_upload_response(storage, session)
        else:
            upload = storage.presign_put(object_key, payload.mime_type)
            multipart = None
    except StorageError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    db.add(asset)
    db.add(session)
    if binding:
        db.add(binding)
    db.commit()
    logger.info(
        "[MediaUpload] session created asset_id=%s session_id=%s mode=%s part_size=%s part_count=%s",
        asset.id,
        session.id,
        session.upload_mode,
        session.part_size,
        session.part_count or 1,
    )
    return {
        "duplicate": False,
        "asset_id": asset.id,
        "upload_session_id": session.id,
        "binding_id": binding.id if binding else None,
        "object_key": object_key,
        "upload": upload,
        "multipart": multipart,
        "expires_at": session.expires_at.isoformat(),
    }


@router.get("/upload-sessions/{session_id}")
def get_media_upload_session(
    session_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Return multipart progress and fresh part URLs for a resumable upload."""
    session = db.query(MediaUploadSession).filter(
        MediaUploadSession.id == session_id,
        MediaUploadSession.tenant_id == effective_tenant_id(user),
        MediaUploadSession.created_by == user.id,
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="上传会话不存在")
    if session.status == "COMPLETED":
        return {"status": session.status, "asset_id": session.asset_id, "parts": []}
    if session.expires_at < datetime.utcnow():
        session.status = "EXPIRED"
        session.error_message = "上传会话已过期"
        asset = db.query(CreativeAsset).filter(CreativeAsset.id == session.asset_id).first()
        if asset and asset.storage_status == "UPLOADING":
            asset.storage_status = "FAILED"
            asset.status = "FAILED"
            asset.processing_status = "FAILED"
            asset.error = "OSS 上传会话已过期，请重新选择文件上传"
        db.commit()
        raise HTTPException(status_code=400, detail="上传会话已过期")
    response = {"status": session.status, "asset_id": session.asset_id, "upload_mode": session.upload_mode}
    if session.upload_mode == "multipart":
        try:
            storage = AliyunOSSStorage()
            response["uploaded_parts"] = storage.list_multipart_parts(session.object_key, session.upload_id)
            response["multipart"] = _multipart_upload_response(storage, session)
        except StorageError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
    return response


@router.post("/upload-sessions/{session_id}/complete")
def complete_media_upload_session(
    session_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """完成 OSS 上传并以 HeadObject 结果作为服务端事实来源。"""
    session = db.query(MediaUploadSession).filter(
        MediaUploadSession.id == session_id,
        MediaUploadSession.tenant_id == effective_tenant_id(user),
        MediaUploadSession.created_by == user.id,
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="上传会话不存在")
    if session.status == "COMPLETED":
        asset = db.query(CreativeAsset).filter(CreativeAsset.id == session.asset_id).first()
        return {"asset_id": session.asset_id, "status": "PROCESSING", "asset": asset.to_dict() if asset else None}
    if session.expires_at < datetime.utcnow():
        session.status = "EXPIRED"
        session.error_message = "上传会话已过期"
        asset = db.query(CreativeAsset).filter(CreativeAsset.id == session.asset_id).first()
        if asset and asset.storage_status == "UPLOADING":
            asset.storage_status = "FAILED"
            asset.status = "FAILED"
            asset.processing_status = "FAILED"
            asset.error = "OSS 上传会话已过期，请重新选择文件上传"
        db.commit()
        raise HTTPException(status_code=400, detail="上传会话已过期")
    try:
        storage = AliyunOSSStorage()
    except StorageError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if session.upload_mode == "multipart":
        if not session.upload_id or not session.part_count:
            raise HTTPException(status_code=400, detail="OSS 分片上传会话参数不完整")
        try:
            parts = storage.list_multipart_parts(session.object_key, session.upload_id)
        except Exception as exc:
            session.error_message = str(exc)[:500]
            db.commit()
            raise HTTPException(status_code=400, detail="OSS 分片状态无法读取，请稍后重试") from exc
        expected_parts = set(range(1, session.part_count + 1))
        actual_parts = {part["part_number"] for part in parts}
        if actual_parts != expected_parts:
            missing = sorted(expected_parts - actual_parts)
            session.error_message = f"OSS 分片尚未上传完成，缺少分片: {missing[:10]}"
            db.commit()
            raise HTTPException(status_code=400, detail=session.error_message)
        try:
            storage.complete_multipart_upload(session.object_key, session.upload_id, parts)
        except Exception as exc:
            session.error_message = str(exc)[:500]
            db.commit()
            raise HTTPException(status_code=400, detail="OSS 分片合并失败，请稍后重试") from exc
    try:
        head = storage.head(session.object_key)
    except Exception as exc:
        session.status = "FAILED"
        session.error_message = str(exc)[:500]
        db.commit()
        raise HTTPException(status_code=400, detail="OSS 对象不存在或无法校验") from exc
    if session.expected_size is not None and head.size != session.expected_size:
        session.status = "FAILED"
        session.error_message = "OSS 对象大小与上传声明不一致"
        db.commit()
        raise HTTPException(status_code=400, detail=session.error_message)
    asset = db.query(CreativeAsset).filter(CreativeAsset.id == session.asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="素材不存在")
    asset.storage_status = "READY"
    asset.processing_status = "PROCESSING"
    asset.status = "PROCESSING"
    session.status = "COMPLETED"
    session.completed_at = datetime.utcnow()
    db.commit()
    try:
        task = process_oss_asset_task.delay(asset.id)
        task_id = task.id
    except Exception as exc:
        logger.warning("[media] OSS 媒体处理任务投递失败 asset=%s: %s", asset.id, exc)
        asset.processing_status = "FAILED"
        asset.status = "FAILED"
        asset.error = "OSS 上传已完成，但素材处理任务投递失败，请点击刷新信息重试"
        db.commit()
        raise HTTPException(status_code=503, detail=asset.error) from exc
    return {"asset_id": asset.id, "status": asset.status, "task_id": task_id, "asset": asset.to_dict()}


@router.get("", response_model=List[MediaItem])
def list_media(
    meta_account_id: Optional[str] = None,
    account_id: Optional[str] = None,
    asset_type: Optional[str] = None,
    group_id: Optional[str] = None,
    tag_id: Optional[str] = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """素材列表，可按主账号 / 账户 / 类型过滤"""
    q = _asset_query(db, user)
    if meta_account_id:
        q = q.filter(CreativeAsset.meta_account_id == meta_account_id)
    if account_id:
        q = q.filter(CreativeAsset.account_id == account_id)
    if asset_type:
        q = q.filter(CreativeAsset.asset_type == asset_type)
    if group_id:
        q = q.filter(CreativeAsset.group_id == group_id)
    if tag_id:
        q = q.join(creative_asset_tag_links, creative_asset_tag_links.c.asset_id == CreativeAsset.id).filter(creative_asset_tag_links.c.tag_id == tag_id)
    items = q.order_by(desc(CreativeAsset.created_at)).all()
    return _asset_response_list(db, items, user)


@router.get("/{asset_id}/stats")
def get_media_stats(
    asset_id: str,
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """返回素材使用统计，支持按时间范围和广告账户拆分。"""
    _get_asset_or_404(db, asset_id, user)
    if start_date and end_date and start_date > end_date:
        raise HTTPException(status_code=400, detail="统计开始日期不能晚于结束日期")

    event_filters = [CreativeAssetUsageEvent.asset_id == asset_id]
    account_scope_keys = _accessible_account_keys(db, user)
    if account_scope_keys is not None:
        event_filters.append(
            CreativeAssetUsageEvent.ad_account_id.in_(account_scope_keys or {"__no_accounts__"})
        )
    if start_date:
        event_filters.append(CreativeAssetUsageEvent.occurred_at >= datetime.combine(start_date, datetime.min.time()))
    if end_date:
        event_filters.append(CreativeAssetUsageEvent.occurred_at < datetime.combine(end_date + timedelta(days=1), datetime.min.time()))

    summary_row = db.query(
        func.count(CreativeAssetUsageEvent.id),
        func.sum(case((CreativeAssetUsageEvent.status == "SUCCESS", 1), else_=0)),
        func.sum(case((CreativeAssetUsageEvent.status == "FAILED", 1), else_=0)),
        func.max(CreativeAssetUsageEvent.occurred_at),
    ).filter(*event_filters).one()
    account_daily_filters = [
        CreativeAssetUsageAccountDailyStat.asset_id == asset_id,
    ]
    if account_scope_keys is not None:
        account_daily_filters.append(
            CreativeAssetUsageAccountDailyStat.ad_account_id.in_(account_scope_keys or {"__no_accounts__"})
        )
    if start_date:
        account_daily_filters.append(CreativeAssetUsageAccountDailyStat.stat_date >= start_date)
    if end_date:
        account_daily_filters.append(CreativeAssetUsageAccountDailyStat.stat_date <= end_date)
    account_rows = db.query(
        CreativeAssetUsageAccountDailyStat.ad_account_id,
        func.sum(CreativeAssetUsageAccountDailyStat.usage_count),
        func.sum(CreativeAssetUsageAccountDailyStat.successful_usage_count),
        func.sum(CreativeAssetUsageAccountDailyStat.failed_usage_count),
        func.max(CreativeAssetUsageAccountDailyStat.last_used_at),
    ).filter(*account_daily_filters).group_by(CreativeAssetUsageAccountDailyStat.ad_account_id).all()
    account_row_keys = {value for value, *_ in account_rows if value}
    account_map = {}
    if account_row_keys:
        for account in db.query(AdAccount).filter(
            or_(AdAccount.id.in_(account_row_keys), AdAccount.account_id.in_(account_row_keys))
        ).all():
            account_map[account.id] = account
            account_map[account.account_id] = account

    total, success, failed, last_used_at = summary_row
    by_account = []
    for account_id, count, account_success, account_failed, account_last_used_at in account_rows:
        account = account_map.get(account_id)
        by_account.append({
            "ad_account_id": account_id,
            "account_name": account.account_name if account else (account_id or "未关联账户"),
            "usage_count": int(count or 0),
            "successful_usage_count": int(account_success or 0),
            "failed_usage_count": int(account_failed or 0),
            "last_used_at": account_last_used_at.isoformat() + "Z" if account_last_used_at else None,
        })

    daily_start = start_date or (datetime.utcnow().date() - timedelta(days=29))
    daily_end = end_date or datetime.utcnow().date()
    daily_filters = [
        CreativeAssetUsageDailyStat.asset_id == asset_id,
        CreativeAssetUsageDailyStat.stat_date >= daily_start,
        CreativeAssetUsageDailyStat.stat_date <= daily_end,
    ]
    if account_scope_keys is not None:
        daily_rows = db.query(
            CreativeAssetUsageAccountDailyStat.stat_date,
            func.sum(CreativeAssetUsageAccountDailyStat.usage_count),
            func.sum(CreativeAssetUsageAccountDailyStat.successful_usage_count),
            func.sum(CreativeAssetUsageAccountDailyStat.failed_usage_count),
        ).filter(
            CreativeAssetUsageAccountDailyStat.asset_id == asset_id,
            CreativeAssetUsageAccountDailyStat.ad_account_id.in_(account_scope_keys or {"__no_accounts__"}),
            CreativeAssetUsageAccountDailyStat.stat_date >= daily_start,
            CreativeAssetUsageAccountDailyStat.stat_date <= daily_end,
        ).group_by(CreativeAssetUsageAccountDailyStat.stat_date).order_by(
            CreativeAssetUsageAccountDailyStat.stat_date
        ).all()
    else:
        daily_rows = db.query(
            CreativeAssetUsageDailyStat.stat_date,
            CreativeAssetUsageDailyStat.usage_count,
            CreativeAssetUsageDailyStat.successful_usage_count,
            CreativeAssetUsageDailyStat.failed_usage_count,
        ).filter(*daily_filters).order_by(CreativeAssetUsageDailyStat.stat_date).all()
    daily = [{
        "date": str(day),
        "usage_count": int(count or 0),
        "successful_usage_count": int(success or 0),
        "failed_usage_count": int(failed or 0),
    } for day, count, success, failed in daily_rows]
    return {
        "asset_id": asset_id,
        "range_start": start_date.isoformat() if start_date else None,
        "range_end": end_date.isoformat() if end_date else None,
        "usage_count": int(total or 0),
        "successful_usage_count": int(success or 0),
        "failed_usage_count": int(failed or 0),
        "last_used_at": last_used_at.isoformat() + "Z" if last_used_at else None,
        "by_account": by_account,
        "daily": daily,
    }


@router.get("/stats/overview")
def get_media_stats_overview(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    asset_type: Optional[str] = Query(None),
    account_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """素材库级使用统计，按当前用户可见范围汇总。"""
    if start_date and end_date and start_date > end_date:
        raise HTTPException(status_code=400, detail="统计开始日期不能晚于结束日期")
    asset_query = _asset_query(db, user)
    if asset_type:
        asset_query = asset_query.filter(CreativeAsset.asset_type == asset_type)
    account = _assert_account_access(db, account_id, user) if account_id else None
    if account_id:
        asset_query = asset_query.filter(CreativeAsset.account_id == account_id)
    assets = asset_query.all()
    asset_ids = [asset.id for asset in assets]
    if not asset_ids:
        return {
            "asset_count": 0,
            "ready_asset_count": 0,
            "binding_count": 0,
            "ready_binding_count": 0,
            "usage_count": 0,
            "successful_usage_count": 0,
            "failed_usage_count": 0,
            "success_rate": 0,
            "top_assets": [],
        }

    account_ids = _accessible_account_ids(db, user)
    account_scope_keys = _accessible_account_keys(db, user)
    binding_filters = [MetaAssetBinding.asset_id.in_(asset_ids)]
    if account_ids is not None:
        binding_filters.append(
            MetaAssetBinding.ad_account_id.in_(account_ids or {"__no_accounts__"})
        )
    if account_id:
        binding_filters.append(MetaAssetBinding.ad_account_id == account_id)
    binding_count, ready_binding_count = db.query(
        func.count(MetaAssetBinding.id),
        func.sum(case((MetaAssetBinding.status == "READY", 1), else_=0)),
    ).filter(*binding_filters).one()
    if account:
        event_filters = [
            CreativeAssetUsageAccountDailyStat.asset_id.in_(asset_ids),
            CreativeAssetUsageAccountDailyStat.ad_account_id.in_({account.id, account.account_id}),
        ]
        if start_date:
            event_filters.append(CreativeAssetUsageAccountDailyStat.stat_date >= start_date)
        if end_date:
            event_filters.append(CreativeAssetUsageAccountDailyStat.stat_date <= end_date)
        total, success, failed = db.query(
            func.sum(CreativeAssetUsageAccountDailyStat.usage_count),
            func.sum(CreativeAssetUsageAccountDailyStat.successful_usage_count),
            func.sum(CreativeAssetUsageAccountDailyStat.failed_usage_count),
        ).filter(*event_filters).one()
        top_rows = db.query(
            CreativeAssetUsageAccountDailyStat.asset_id,
            func.sum(CreativeAssetUsageAccountDailyStat.usage_count),
            func.sum(CreativeAssetUsageAccountDailyStat.successful_usage_count),
        ).filter(*event_filters).group_by(
            CreativeAssetUsageAccountDailyStat.asset_id,
        ).order_by(func.sum(CreativeAssetUsageAccountDailyStat.usage_count).desc()).limit(10).all()
    elif account_scope_keys is not None:
        account_daily_filters = [
            CreativeAssetUsageAccountDailyStat.asset_id.in_(asset_ids),
            CreativeAssetUsageAccountDailyStat.ad_account_id.in_(account_scope_keys or {"__no_accounts__"}),
        ]
        if start_date:
            account_daily_filters.append(CreativeAssetUsageAccountDailyStat.stat_date >= start_date)
        if end_date:
            account_daily_filters.append(CreativeAssetUsageAccountDailyStat.stat_date <= end_date)
        total, success, failed = db.query(
            func.sum(CreativeAssetUsageAccountDailyStat.usage_count),
            func.sum(CreativeAssetUsageAccountDailyStat.successful_usage_count),
            func.sum(CreativeAssetUsageAccountDailyStat.failed_usage_count),
        ).filter(*account_daily_filters).one()
        top_rows = db.query(
            CreativeAssetUsageAccountDailyStat.asset_id,
            func.sum(CreativeAssetUsageAccountDailyStat.usage_count),
            func.sum(CreativeAssetUsageAccountDailyStat.successful_usage_count),
        ).filter(*account_daily_filters).group_by(
            CreativeAssetUsageAccountDailyStat.asset_id,
        ).order_by(func.sum(CreativeAssetUsageAccountDailyStat.usage_count).desc()).limit(10).all()
    else:
        daily_filters = [CreativeAssetUsageDailyStat.asset_id.in_(asset_ids)]
        if start_date:
            daily_filters.append(CreativeAssetUsageDailyStat.stat_date >= start_date)
        if end_date:
            daily_filters.append(CreativeAssetUsageDailyStat.stat_date <= end_date)
        total, success, failed = db.query(
            func.sum(CreativeAssetUsageDailyStat.usage_count),
            func.sum(CreativeAssetUsageDailyStat.successful_usage_count),
            func.sum(CreativeAssetUsageDailyStat.failed_usage_count),
        ).filter(*daily_filters).one()
        top_rows = db.query(
            CreativeAssetUsageDailyStat.asset_id,
            func.sum(CreativeAssetUsageDailyStat.usage_count),
            func.sum(CreativeAssetUsageDailyStat.successful_usage_count),
        ).filter(*daily_filters).group_by(
            CreativeAssetUsageDailyStat.asset_id,
        ).order_by(func.sum(CreativeAssetUsageDailyStat.usage_count).desc()).limit(10).all()
    assets_by_id = {asset.id: asset for asset in assets}
    top_assets = []
    for top_asset_id, asset_usage_count, asset_success_count in top_rows:
        asset = assets_by_id.get(top_asset_id)
        if not asset:
            continue
        top_assets.append({
            "asset_id": asset.id,
            "name": asset.name,
            "asset_type": asset.asset_type,
            "usage_count": int(asset_usage_count or 0),
            "successful_usage_count": int(asset_success_count or 0),
        })
    usage_count = int(total or 0)
    successful_usage_count = int(success or 0)
    return {
        "range_start": start_date.isoformat() if start_date else None,
        "range_end": end_date.isoformat() if end_date else None,
        "asset_count": len(assets),
        "ready_asset_count": sum(1 for asset in assets if asset.processing_status == "READY" or asset.status == "READY"),
        "binding_count": int(binding_count or 0),
        "ready_binding_count": int(ready_binding_count or 0),
        "usage_count": usage_count,
        "successful_usage_count": successful_usage_count,
        "failed_usage_count": int(failed or 0),
        "success_rate": round(successful_usage_count * 100 / usage_count, 2) if usage_count else 0,
        "top_assets": top_assets,
    }


@router.get("/{asset_id}", response_model=MediaItem)
def get_media(asset_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_active_user)):
    return _asset_response_list(db, [_get_asset_or_404(db, asset_id, user)], user)[0]


@router.delete("/{asset_id}")
def delete_media(
    asset_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """软删除素材，并异步清理 OSS 原始文件和衍生文件。"""
    asset = _get_asset_or_404(db, asset_id, user)
    _assert_asset_edit_access(asset, user)
    asset.status = "ARCHIVED"
    asset.storage_status = "DELETING"
    asset.deleted_at = datetime.utcnow()
    db.commit()
    task_id = delete_oss_asset_task.delay(asset.id).id
    return {"success": True, "status": "DELETING", "task_id": task_id}


@router.post("/{asset_id}/refresh-metadata")
def refresh_metadata(
    asset_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """重新解析 OSS 素材元数据，不触发 Meta 上传。"""
    asset = _get_asset_or_404(db, asset_id, user)
    _assert_asset_edit_access(asset, user)
    if not asset.object_key or asset.storage_status != "READY":
        raise HTTPException(status_code=409, detail="素材尚未完成 OSS 处理")
    asset.processing_status = "PROCESSING"
    asset.status = "PROCESSING"
    asset.error = None
    db.commit()
    task = process_oss_asset_task.delay(asset.id, True)
    return {"asset": asset.to_dict(), "status": "PROCESSING", "task_id": task.id}
