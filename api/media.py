"""
素材库接口：图片 / 视频上传、列表、删除。
OSS 模式使用浏览器直传 + 服务端校验 + 异步媒体处理；本地模式保留旧上传兼容。
素材就绪后按广告账户建立独立 Meta/Connector 映射。
权限：登录用户即可（普通用户上传归自己账户；管理员可指定主账号）。
"""
import os
import uuid
import mimetypes
import hashlib
import struct
import json
import shutil
import subprocess
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc
from pydantic import BaseModel, Field
from typing import Optional, List

from core.database import get_db
from core.tenant import effective_tenant_id
from core.auth import get_current_active_user
from core.logger import logger
from models import CreativeAsset, MetaAccount, AdAccount, MetaAssetBinding, User, UserAccount, CreativeAssetGroup, MediaUploadSession
from models.account_group import account_group_accounts, account_group_users
from models.creative_asset_tag import creative_asset_tag_links
from services.credential_service import CredentialError, CredentialService
from services.meta import MetaAdsService, MetaClient
from services.meta.errors import MetaApiError
from config.settings import settings
from tasks.campaign_tasks import retry_asset_binding_task
from tasks.media_tasks import upload_asset_task, process_oss_asset_task, delete_oss_asset_task
from services.storage import AliyunOSSStorage, StorageError

router = APIRouter(prefix="/api/v1/media", tags=["素材库"])

ALLOWED_IMAGE = {"image/jpeg", "image/png", "image/gif", "image/webp"}
ALLOWED_VIDEO = {"video/mp4", "video/quicktime", "video/x-matroska", "video/webm"}
MAX_SIZE = getattr(settings, "MAX_UPLOAD_SIZE", 200 * 1024 * 1024)


class MediaItem(BaseModel):
    id: str
    name: str
    created_by: Optional[str] = None
    visibility: str = "ACCOUNT"
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

    class Config:
        from_attributes = True

class AssetPrepareRequest(BaseModel):
    ad_account_ids: List[str]

class AssetRetryRequest(BaseModel):
    binding_id: str


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


def _oss_extension(name: str, mime_type: str) -> str:
    ext = os.path.splitext(name)[1].lower().lstrip(".")
    allowed = {"jpg", "jpeg", "png", "gif", "webp", "mp4", "mov", "mkv", "webm"}
    if ext not in allowed:
        ext = (mimetypes.guess_extension(mime_type) or ".bin").lstrip(".").lower()
    return ext


def _oss_object_key(user: User, asset_id: str, name: str, md5: Optional[str], mime_type: str) -> str:
    now = datetime.utcnow()
    stamp = now.strftime("%Y%m%d%H%M%S")
    digest = (md5 or hashlib.sha256(asset_id.encode()).hexdigest())[:32].lower()
    stored_name = f"{user.id}_{stamp}_{digest}.{_oss_extension(name, mime_type)}"
    tenant_id = effective_tenant_id(user) or "unassigned"
    return f"{settings.OSS_BASE_PATH}/{tenant_id}/{user.id}/{settings.OSS_PLATFORM}/{now:%Y/%m/%d}/{asset_id}/{stored_name}"


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
    elif kind == "cover" and asset.cover_key:
        key = asset.cover_key
    try:
        url = AliyunOSSStorage().download_url(key)
    except StorageError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"asset_id": asset.id, "url": url, "expires_in": settings.OSS_DOWNLOAD_EXPIRE_SECONDS}


def _accessible_account_ids(db: Session, user: User) -> Optional[set[str]]:
    if user.is_admin():
        return None
    direct = {row[0] for row in db.query(UserAccount.account_id).filter(UserAccount.user_id == user.id).all()}
    grouped = db.query(account_group_accounts.c.account_id).join(
        account_group_users, account_group_users.c.group_id == account_group_accounts.c.group_id
    ).filter(account_group_users.c.user_id == user.id).all()
    return direct | {row[0] for row in grouped}


def _asset_query(db: Session, user: User):
    account_ids = _accessible_account_ids(db, user)
    q = db.query(CreativeAsset).filter(CreativeAsset.status != "ARCHIVED")
    if account_ids is not None:
        q = q.filter(
            (CreativeAsset.created_by == user.id)
            | ((CreativeAsset.visibility == "TENANT") & (CreativeAsset.tenant_id == effective_tenant_id(user)))
            | CreativeAsset.account_id.in_(account_ids or {"__no_accounts__"})
        )
    return q


def _get_asset_or_404(db: Session, asset_id: str, user: User) -> CreativeAsset:
    asset = _asset_query(db, user).filter(CreativeAsset.id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="素材不存在或无权访问")
    return asset


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
    rows = db.query(MetaAssetBinding).filter(MetaAssetBinding.asset_id == asset_id).all()
    # 兼容异步改造前已上传到 Meta 的历史素材：旧流程只写 fb_hash/fb_video_id，
    # 没有创建账户级 binding。首次打开映射时补齐一条 READY 映射。
    if not rows and asset.account_id and (asset.fb_hash or asset.fb_video_id):
        account = db.query(AdAccount).filter(AdAccount.id == asset.account_id).first()
        if account:
            binding = MetaAssetBinding(
                id=uuid.uuid4().hex, tenant_id=account.tenant_id, asset_id=asset.id, ad_account_id=account.id,
                meta_asset_id=asset.fb_video_id or asset.fb_hash,
                meta_asset_type=asset.asset_type, status="READY",
                processing_status="READY", uploaded_at=asset.created_at,
                last_verified_at=datetime.utcnow(),
            )
            db.add(binding); db.commit(); rows = [binding]
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
    if settings.MEDIA_STORAGE_PROVIDER == "oss" and asset.processing_status != "READY":
        raise HTTPException(status_code=409, detail="素材尚未完成 OSS 处理，请等待素材状态变为 READY")
    if not req.ad_account_ids:
        raise HTTPException(status_code=400, detail="至少选择一个广告账户")
    created = []
    queued = []
    for account_id in set(req.ad_account_ids):
        account = _assert_account_access(db, account_id, user)
        binding = db.query(MetaAssetBinding).filter(
            MetaAssetBinding.asset_id == asset_id,
            MetaAssetBinding.ad_account_id == account.id,
        ).first()
        if not binding:
            binding = MetaAssetBinding(
                id=uuid.uuid4().hex,
                tenant_id=account.tenant_id,
                asset_id=asset_id,
                ad_account_id=account.id,
                meta_asset_type=asset.asset_type,
                status="PENDING",
            )
            db.add(binding)
        elif binding.status in ("FAILED", "EXPIRED"):
            binding.status = "PENDING"
            binding.error_message = None
            binding.updated_at = datetime.utcnow()
        created.append(binding)
    db.commit()
    # 重新同步不仅建立占位记录，也必须为已有的 PENDING/失败记录重新派发上传任务。
    # READY 的绑定无需重复上传；UPLOADING/PROCESSING 由原任务继续处理，避免重复任务。
    for row in created:
        if row.status in ("PENDING", "FAILED", "EXPIRED") and not row.meta_asset_id:
            task = upload_asset_task.delay(row.id)
            queued.append({"binding_id": row.id, "task_id": task.id})
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
    binding.status = "PENDING"
    binding.error_message = None
    db.commit()
    task = retry_asset_binding_task.delay(binding.id)
    return {"status": "QUEUED", "binding_id": binding.id, "task_id": task.id}


def _save_local(file: UploadFile) -> dict:
    """保存上传文件到本地，返回存储信息"""
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    ext = os.path.splitext(file.filename or "file")[1].lower()
    stored = f"{uuid.uuid4().hex}{ext}"
    dest = os.path.join(settings.UPLOAD_DIR, stored)
    size = 0
    digest = hashlib.sha256()
    with open(dest, "wb") as f:
        while True:
            chunk = file.file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            digest.update(chunk)
            f.write(chunk)
    mime = file.content_type or mimetypes.guess_type(dest)[0] or "application/octet-stream"
    return {
        "stored": stored,
        "dest": dest,
        "size": size,
        "mime": mime,
        "url": f"/uploads/{stored}",
        "sha256": digest.hexdigest(),
    }


def _image_dimensions(path: str, mime: str) -> tuple[Optional[int], Optional[int]]:
    """读取常见图片尺寸，不依赖额外图像库。"""
    try:
        with open(path, "rb") as stream:
            header = stream.read(32)
            if mime == "image/png" and header[:8] == b"\x89PNG\r\n\x1a\n":
                return struct.unpack(">II", header[16:24])
            if mime == "image/gif" and header[:6] in (b"GIF87a", b"GIF89a"):
                return struct.unpack("<HH", header[6:10])
            if mime in {"image/jpeg", "image/jpg"} and header[:2] == b"\xff\xd8":
                stream.seek(2)
                while True:
                    marker_prefix = stream.read(1)
                    if not marker_prefix:
                        break
                    if marker_prefix != b"\xff":
                        continue
                    marker = stream.read(1)
                    while marker == b"\xff":
                        marker = stream.read(1)
                    if marker in {b"\xd8", b"\xd9"}:
                        continue
                    length_bytes = stream.read(2)
                    if len(length_bytes) != 2:
                        break
                    length = struct.unpack(">H", length_bytes)[0]
                    if marker[0] in set(range(0xC0, 0xC4)) | set(range(0xC5, 0xC8)) | set(range(0xC9, 0xCC)) | set(range(0xCD, 0xD0)):
                        data = stream.read(5)
                        return struct.unpack(">HH", data[1:5])
                    stream.seek(max(length - 2, 0), 1)
    except (OSError, struct.error, IndexError):
        pass
    return None, None


def _video_metadata(path: str) -> tuple[Optional[int], Optional[int], Optional[float]]:
    """通过可选 ffprobe 读取视频元数据；未安装时交给异步 Meta 流程处理。"""
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None, None, None
    try:
        result = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "stream=width,height,duration",
             "-of", "json", path],
            capture_output=True, text=True, timeout=10, check=True,
        )
        streams = json.loads(result.stdout).get("streams") or []
        video = next((item for item in streams if item.get("width") and item.get("height")), None)
        if not video:
            return None, None, None
        duration = float(video["duration"]) if video.get("duration") else None
        return int(video["width"]), int(video["height"]), duration
    except (OSError, ValueError, TypeError, subprocess.SubprocessError, json.JSONDecodeError):
        return None, None, None


@router.post("/upload-sessions")
def create_media_upload_session(
    payload: MediaUploadSessionRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """创建 OSS 直传会话；文件内容由浏览器直接上传到 OSS。"""
    if settings.MEDIA_STORAGE_PROVIDER != "oss":
        raise HTTPException(status_code=503, detail="OSS 素材存储未启用")
    allowed = ALLOWED_IMAGE if payload.asset_type == "image" else ALLOWED_VIDEO
    if payload.mime_type not in allowed:
        raise HTTPException(status_code=400, detail=f"素材类型与 MIME 不匹配: {payload.mime_type}")
    _assert_group_access(db, payload.group_id, user)
    if payload.account_id:
        account = _assert_account_access(db, payload.account_id, user)
    else:
        raise HTTPException(status_code=400, detail="素材必须指定广告账户")

    existing = _asset_query(db, user).filter(
        CreativeAsset.sha256 == payload.sha256.lower(),
        CreativeAsset.size == payload.size,
        CreativeAsset.asset_type == payload.asset_type,
        CreativeAsset.status != "ARCHIVED",
    ).order_by(CreativeAsset.updated_at.desc()).first()
    if existing:
        binding = _upsert_asset_binding(db, existing, account)
        db.commit()
        task_id = None
        if existing.processing_status == "READY" and binding.status == "PENDING":
            task_id = upload_asset_task.delay(binding.id).id
        return {
            "duplicate": True,
            "asset_id": existing.id,
            "status": existing.status,
            "asset": existing.to_dict(),
            "binding": binding.to_dict(),
            "binding_id": binding.id,
            "task_id": task_id,
        }

    asset_id = uuid.uuid4().hex
    object_key = _oss_object_key(user, asset_id, payload.name, payload.md5, payload.mime_type)
    now = datetime.utcnow()
    asset = CreativeAsset(
        id=asset_id,
        tenant_id=account.tenant_id,
        name=payload.name,
        original_name=payload.name,
        created_by=user.id,
        visibility="ACCOUNT",
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
    session = MediaUploadSession(
        id=uuid.uuid4().hex,
        tenant_id=account.tenant_id,
        asset_id=asset.id,
        object_key=object_key,
        expected_size=payload.size,
        expected_md5=payload.md5.lower() if payload.md5 else None,
        expected_sha256=payload.sha256.lower(),
        status="UPLOADING",
        expires_at=now + timedelta(seconds=settings.OSS_UPLOAD_EXPIRE_SECONDS),
        created_by=user.id,
    )
    try:
        upload = AliyunOSSStorage().presign_put(object_key, payload.mime_type)
    except StorageError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    db.add(asset)
    db.add(session)
    db.commit()
    return {
        "duplicate": False,
        "asset_id": asset.id,
        "upload_session_id": session.id,
        "object_key": object_key,
        "upload": upload,
        "expires_at": session.expires_at.isoformat(),
    }


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
        db.commit()
        raise HTTPException(status_code=400, detail="上传会话已过期")
    try:
        head = AliyunOSSStorage().head(session.object_key)
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


@router.post("/upload", response_model=MediaItem)
async def upload_media(
    file: UploadFile = File(...),
    meta_account_id: Optional[str] = Form(None),
    account_id: Optional[str] = Form(None),
    group_id: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """上传图片或视频素材

    - meta_account_id：归属的主账号（BM），用于 FB 上传
    - account_id：归属的广告账户（act_xxx），用于 FB 上传归属
    至少提供一个，FB 上传才会使用真实 token；否则降级为本地占位。
    """
    if settings.MEDIA_STORAGE_PROVIDER == "oss":
        raise HTTPException(status_code=409, detail="OSS 模式请使用直传上传会话接口")
    mime = file.content_type or ""
    is_image = mime in ALLOWED_IMAGE
    is_video = mime in ALLOWED_VIDEO
    if not (is_image or is_video):
        raise HTTPException(status_code=400, detail=f"不支持的文件类型: {mime}")

    # 大小预检
    if file.size and file.size > MAX_SIZE:
        raise HTTPException(status_code=400, detail="文件超过大小限制")

    info = _save_local(file)
    asset_type = "image" if is_image else "video"
    width, height = _image_dimensions(info["dest"], info["mime"]) if is_image else (None, None)
    duration = None
    if is_video:
        width, height, duration = _video_metadata(info["dest"])
        if width and height and (width < 600 or height < 600):
            try:
                os.remove(info["dest"])
            except OSError:
                pass
            raise HTTPException(status_code=400, detail="视频尺寸不能小于 600 × 600")
        if width and height and (width / height < 0.5 or width / height > 2.2):
            try:
                os.remove(info["dest"])
            except OSError:
                pass
            raise HTTPException(status_code=400, detail="视频比例不适合常用 Meta 广告版位")
        if duration and duration > 241:
            try:
                os.remove(info["dest"])
            except OSError:
                pass
            raise HTTPException(status_code=400, detail="视频时长不能超过 241 秒")
    if is_image and (not width or not height or width < 600 or height < 600):
        try:
            os.remove(info["dest"])
        except OSError:
            pass
        raise HTTPException(status_code=400, detail="图片无法解析或尺寸不能小于 600 × 600")
    if is_image and (width / height < 0.5 or width / height > 2.2):
        try:
            os.remove(info["dest"])
        except OSError:
            pass
        raise HTTPException(status_code=400, detail="图片比例不适合常用 Meta 广告版位")
    _assert_group_access(db, group_id, user)

    # 这里只校验账户归属；凭据解析和 Meta 写操作都放到 Worker。
    if account_id:
        account = _assert_account_access(db, account_id, user)
    elif meta_account_id:
        raise HTTPException(
            status_code=400,
            detail="Meta 素材必须指定广告账户；上传接口属于广告账户而非 BM",
        )
    else:
        raise HTTPException(status_code=400, detail="Meta 素材必须指定广告账户")

    # 同租户、同类型、同内容直接复用本地素材，避免重复占盘。
    existing = _asset_query(db, user).filter(
        CreativeAsset.sha256 == info["sha256"], CreativeAsset.asset_type == asset_type,
        CreativeAsset.status != "ARCHIVED",
    ).first()
    if existing:
        try:
            os.remove(info["dest"])
        except OSError:
            pass
        binding = db.query(MetaAssetBinding).filter(
            MetaAssetBinding.asset_id == existing.id, MetaAssetBinding.ad_account_id == account.id
        ).first()
        if not binding:
            binding = MetaAssetBinding(id=uuid.uuid4().hex, tenant_id=account.tenant_id, asset_id=existing.id, ad_account_id=account.id,
                                       meta_asset_type=asset_type, status="PENDING")
            db.add(binding); db.commit()
        if binding.status != "READY":
            upload_asset_task.delay(binding.id)
        data = existing.to_dict()
        data.update({"binding_id": binding.id})
        return data

    asset = CreativeAsset(
        id=str(uuid.uuid4()),
        name=file.filename or info["stored"],
        created_by=user.id,
        visibility="ACCOUNT",
        group_id=group_id,
        asset_type=asset_type,
        meta_account_id=meta_account_id,
        account_id=account_id,
        filename=info["stored"],
        file_path=info["dest"],
        url=info["url"],
        size=info["size"],
        mime_type=info["mime"],
        width=width,
        height=height,
        duration=duration,
        status="PENDING",
        sha256=info["sha256"],
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    binding = MetaAssetBinding(id=uuid.uuid4().hex, tenant_id=account.tenant_id, asset_id=asset.id, ad_account_id=account.id,
                               meta_asset_type=asset_type, status="PENDING")
    db.add(binding); db.commit()
    task = upload_asset_task.delay(binding.id)
    data = asset.to_dict()
    data.update({"binding_id": binding.id, "task_id": task.id})
    return data


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
    return [i.to_dict() for i in items]


@router.get("/{asset_id}", response_model=MediaItem)
def get_media(asset_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_active_user)):
    return _get_asset_or_404(db, asset_id, user).to_dict()


@router.delete("/{asset_id}")
def delete_media(
    asset_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """软删除素材，并异步清理 OSS 原始文件和衍生文件。"""
    asset = _get_asset_or_404(db, asset_id, user)
    asset.status = "ARCHIVED"
    asset.storage_status = "DELETING" if asset.object_key else "DELETED"
    asset.deleted_at = datetime.utcnow()
    db.commit()
    task_id = None
    if asset.object_key:
        task_id = delete_oss_asset_task.delay(asset.id).id
    elif asset.file_path and os.path.exists(asset.file_path):
        try:
            os.remove(asset.file_path)
        except OSError:
            pass
    return {"success": True, "status": "DELETING" if task_id else "DELETED", "task_id": task_id}


@router.post("/{asset_id}/refresh-metadata")
def refresh_metadata(
    asset_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """重新解析历史素材元数据，不触发 Meta 上传。"""
    asset = _get_asset_or_404(db, asset_id, user)
    if settings.MEDIA_STORAGE_PROVIDER == "oss":
        if not asset.object_key or asset.storage_status != "READY":
            raise HTTPException(status_code=409, detail="素材尚未完成 OSS 处理")
        asset.processing_status = "PROCESSING"
        asset.status = "PROCESSING"
        asset.error = None
        db.commit()
        task = process_oss_asset_task.delay(asset.id, True)
        return {"asset": asset.to_dict(), "status": "PROCESSING", "task_id": task.id}
    if not asset.file_path or not os.path.isfile(asset.file_path):
        raise HTTPException(status_code=400, detail="素材文件不存在，无法解析")
    if asset.asset_type == "image":
        width, height = _image_dimensions(asset.file_path, asset.mime_type or "")
        duration = None
    else:
        width, height, duration = _video_metadata(asset.file_path)
    if not width or not height:
        raise HTTPException(status_code=422, detail="无法解析素材尺寸，请检查容器媒体工具或文件格式")
    asset.width, asset.height, asset.duration = width, height, duration
    db.commit()
    db.refresh(asset)
    return asset.to_dict()
