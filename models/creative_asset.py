from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, ForeignKey, Index, Text
from sqlalchemy.orm import relationship
from datetime import datetime
from core.database import Base
from core.tenant import TenantMixin


class CreativeAsset(TenantMixin, Base):
    """素材库：上传的图片 / 视频，用于批量发布时引用

    上传后会调用 Facebook API 拿到 image_hash / video_id，
    真实发布创意时无需重新上传，直接引用即可。
    """

    __tablename__ = "creative_assets"

    id = Column(String(50), primary_key=True, index=True)
    name = Column(String(255), nullable=False, comment="素材名称（原始文件名）")

    # 素材类型
    asset_type = Column(String(20), nullable=False, comment="image / video")

    # 归属：可挂到某个主账号（BM）或具体广告账户；为空则为平台公共素材
    meta_account_id = Column(String(50), ForeignKey("meta_accounts.id"), nullable=True, index=True)
    # 注意：不建外键——ad_accounts.account_id 无唯一约束（同一 act_xxx 可挂多个 BM），
    # PostgreSQL 不允许外键引用非唯一列；此处为宽松归属，仅保留普通列 + 索引
    account_id = Column(String(50), nullable=True, index=True, comment="归属广告账户（act_xxx）")

    # 文件信息
    filename = Column(String(255), comment="服务器存储文件名")
    file_path = Column(String(512), comment="本地存储相对路径（UPLOAD_DIR 下）")
    url = Column(String(1024), comment="可访问的 URL（本地或对象存储）")

    # Facebook 引用标识（上传到 FB 后回填）
    fb_hash = Column(String(255), comment="图片 hash（AdImage）")
    fb_video_id = Column(String(255), comment="视频 id（AdVideo）")

    # 元信息
    width = Column(Integer)
    height = Column(Integer)
    size = Column(Integer, comment="字节数")
    mime_type = Column(String(100))
    duration = Column(Float, comment="视频时长（秒）")

    status = Column(String(20), default="ready", comment="ready / uploading / failed")
    error = Column(Text, comment="上传失败原因")

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    meta_account = relationship("MetaAccount", back_populates=None)

    __table_args__ = (
        Index("ix_creative_assets_tenant_meta", "tenant_id", "meta_account_id"),
        Index("ix_creative_assets_tenant_account", "tenant_id", "account_id"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "name": self.name,
            "asset_type": self.asset_type,
            "meta_account_id": self.meta_account_id,
            "account_id": self.account_id,
            "url": self.url,
            "fb_hash": self.fb_hash,
            "fb_video_id": self.fb_video_id,
            "width": self.width,
            "height": self.height,
            "size": self.size,
            "mime_type": self.mime_type,
            "duration": self.duration,
            "status": self.status,
            "error": self.error,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
