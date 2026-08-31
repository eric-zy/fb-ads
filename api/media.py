"""
素材库接口：图片 / 视频上传、列表、删除。
上传会同时保存本地文件并调用 Facebook 上传（拿到 image_hash / video_id），
供批量发布时引用，避免重复上传。
权限：登录用户即可（普通用户上传归自己账户；管理员可指定主账号）。
"""
import os
import uuid
import mimetypes
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc
from pydantic import BaseModel
from typing import Optional, List

from core.database import get_db
from core.auth import get_current_active_user
from core.logger import logger
from models import CreativeAsset, MetaAccount, AdAccount
from services.credential_service import CredentialError, CredentialService
from services.fb_client import fb_client
from config.settings import settings

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

    class Config:
        from_attributes = True


def _save_local(file: UploadFile) -> dict:
    """保存上传文件到本地，返回存储信息"""
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    ext = os.path.splitext(file.filename or "file")[1].lower()
    stored = f"{uuid.uuid4().hex}{ext}"
    dest = os.path.join(settings.UPLOAD_DIR, stored)
    size = 0
    with open(dest, "wb") as f:
        while True:
            chunk = file.file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            f.write(chunk)
    mime = file.content_type or mimetypes.guess_type(dest)[0] or "application/octet-stream"
    return {
        "stored": stored,
        "dest": dest,
        "size": size,
        "mime": mime,
        "url": f"/uploads/{stored}",
    }


@router.post("/upload", response_model=MediaItem)
async def upload_media(
    file: UploadFile = File(...),
    meta_account_id: Optional[str] = None,
    account_id: Optional[str] = None,
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

    # 解析用于 FB 上传的 token / account
    # BM 主表自 V1 起不再存明文 Token，统一由 CredentialService 解析
    access_token = settings.FB_ACCESS_TOKEN
    fb_account = account_id or (f"act_{meta_account_id}" if meta_account_id else None)
    if meta_account_id:
        try:
            access_token, _ = CredentialService(db).resolve_token_for_meta(meta_account_id)
        except CredentialError:
            # 凭据不可用时回退全局配置，保持原有行为
            logger.warning(f"[media] BM {meta_account_id} 凭据不可用，回退全局 Token")

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
        status="uploading",
    )

    # 调用 FB 上传
    if asset_type == "image":
        res = fb_client.upload_image(fb_account or "act_0", access_token, info["dest"])
        asset.fb_hash = res.get("hash")
    else:
        res = fb_client.upload_video(fb_account or "act_0", access_token, info["dest"])
        asset.fb_video_id = res.get("video_id")

    if res.get("error"):
        asset.status = "failed"
        asset.error = res["error"]
    else:
        asset.status = "ready"

    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset.to_dict()


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
