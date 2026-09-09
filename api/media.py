"""
素材库接口：图片 / 视频上传、列表、删除。
上传会同时保存本地文件并调用 Facebook 上传（拿到 image_hash / video_id），
供批量发布时引用，避免重复上传。
权限：登录用户即可（普通用户上传归自己账户；管理员可指定主账号）。
"""
import os
import uuid
import mimetypes
import hashlib
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc
from pydantic import BaseModel
from typing import Optional, List

from core.database import get_db
from core.auth import get_current_active_user
from core.logger import logger
from models import CreativeAsset, MetaAccount, AdAccount, MetaAssetBinding
from services.credential_service import CredentialError, CredentialService
from services.meta import MetaAdsService, MetaClient
from services.meta.errors import MetaApiError
from config.settings import settings
from tasks.campaign_tasks import retry_asset_binding_task
from tasks.media_tasks import upload_asset_task

router = APIRouter(prefix="/api/v1/media", tags=["素材库"])

ALLOWED_IMAGE = {"image/jpeg", "image/png", "image/gif", "image/webp"}
ALLOWED_VIDEO = {"video/mp4", "video/quicktime", "video/x-matroska", "video/webm"}
MAX_SIZE = getattr(settings, "MAX_UPLOAD_SIZE", 200 * 1024 * 1024)


class MediaItem(BaseModel):
    id: str
    name: str
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
    error: Optional[str]
    created_at: Optional[str]
    binding_id: Optional[str] = None
    task_id: Optional[str] = None

    class Config:
        from_attributes = True

class AssetPrepareRequest(BaseModel):
    ad_account_ids: List[str]

class AssetRetryRequest(BaseModel):
    binding_id: str

@router.get("/{asset_id}/bindings")
def list_asset_bindings(
    asset_id: str,
    db: Session = Depends(get_db),
    _: dict = Depends(get_current_active_user),
):
    asset = db.query(CreativeAsset).filter(CreativeAsset.id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="素材不存在")
    rows = db.query(MetaAssetBinding).filter(MetaAssetBinding.asset_id == asset_id).all()
    # 兼容异步改造前已上传到 Meta 的历史素材：旧流程只写 fb_hash/fb_video_id，
    # 没有创建账户级 binding。首次打开映射时补齐一条 READY 映射。
    if not rows and asset.account_id and (asset.fb_hash or asset.fb_video_id):
        account = db.query(AdAccount).filter(AdAccount.id == asset.account_id).first()
        if account:
            binding = MetaAssetBinding(
                id=uuid.uuid4().hex, asset_id=asset.id, ad_account_id=account.id,
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
    _: dict = Depends(get_current_active_user),
):
    """为目标广告账户建立素材映射占位，实际上传由异步任务执行。"""
    asset = db.query(CreativeAsset).filter(CreativeAsset.id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="素材不存在")
    if not req.ad_account_ids:
        raise HTTPException(status_code=400, detail="至少选择一个广告账户")
    created = []
    for account_id in set(req.ad_account_ids):
        account = db.query(AdAccount).filter(AdAccount.id == account_id).first()
        if not account:
            continue
        binding = db.query(MetaAssetBinding).filter(
            MetaAssetBinding.asset_id == asset_id,
            MetaAssetBinding.ad_account_id == account.id,
        ).first()
        if not binding:
            binding = MetaAssetBinding(
                id=uuid.uuid4().hex,
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
    return {"asset_id": asset_id, "status": "PENDING", "bindings": [row.to_dict() for row in created]}


@router.post("/{asset_id}/bindings/{binding_id}/retry")
def retry_asset_binding(
    asset_id: str,
    binding_id: str,
    db: Session = Depends(get_db),
    _: dict = Depends(get_current_active_user),
):
    binding = db.query(MetaAssetBinding).filter(
        MetaAssetBinding.id == binding_id,
        MetaAssetBinding.asset_id == asset_id,
    ).first()
    if not binding:
        raise HTTPException(status_code=404, detail="素材映射不存在")
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


@router.post("/upload", response_model=MediaItem)
async def upload_media(
    file: UploadFile = File(...),
    meta_account_id: Optional[str] = Form(None),
    account_id: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_active_user),
):
    """上传图片或视频素材

    - meta_account_id：归属的主账号（BM），用于 FB 上传
    - account_id：归属的广告账户（act_xxx），用于 FB 上传归属
    至少提供一个，FB 上传才会使用真实 token；否则降级为本地占位。
    """
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

    # 这里只校验账户归属；凭据解析和 Meta 写操作都放到 Worker。
    if account_id:
        account = db.query(AdAccount).filter(AdAccount.id == account_id).first()
        if not account:
            raise HTTPException(status_code=404, detail="广告账户不存在")
    elif meta_account_id:
        raise HTTPException(
            status_code=400,
            detail="Meta 素材必须指定广告账户；上传接口属于广告账户而非 BM",
        )
    else:
        raise HTTPException(status_code=400, detail="Meta 素材必须指定广告账户")

    # 同租户、同类型、同内容直接复用本地素材，避免重复占盘。
    existing = db.query(CreativeAsset).filter(
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
            binding = MetaAssetBinding(id=uuid.uuid4().hex, asset_id=existing.id, ad_account_id=account.id,
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
        asset_type=asset_type,
        meta_account_id=meta_account_id,
        account_id=account_id,
        filename=info["stored"],
        file_path=info["dest"],
        url=info["url"],
        size=info["size"],
        mime_type=info["mime"],
        status="PENDING",
        sha256=info["sha256"],
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    binding = MetaAssetBinding(id=uuid.uuid4().hex, asset_id=asset.id, ad_account_id=account.id,
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
    db: Session = Depends(get_db),
    _: dict = Depends(get_current_active_user),
):
    """素材列表，可按主账号 / 账户 / 类型过滤"""
    q = db.query(CreativeAsset)
    if meta_account_id:
        q = q.filter(CreativeAsset.meta_account_id == meta_account_id)
    if account_id:
        q = q.filter(CreativeAsset.account_id == account_id)
    if asset_type:
        q = q.filter(CreativeAsset.asset_type == asset_type)
    items = q.order_by(desc(CreativeAsset.created_at)).all()
    return [i.to_dict() for i in items]


@router.delete("/{asset_id}")
def delete_media(
    asset_id: str,
    db: Session = Depends(get_db),
    _: dict = Depends(get_current_active_user),
):
    """删除素材（同时删除本地文件）"""
    asset = db.query(CreativeAsset).filter(CreativeAsset.id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="素材不存在")
    if asset.file_path and os.path.exists(asset.file_path):
        try:
            os.remove(asset.file_path)
        except OSError:
            pass
    db.delete(asset)
    db.commit()
    return {"success": True}
