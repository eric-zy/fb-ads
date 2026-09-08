"""Facebook Page 自动同步服务。"""
import uuid
from datetime import datetime
from typing import Dict, List

from sqlalchemy.orm import Session

from core.enums import CredentialStatus
from core.logger import logger
from models import Credential, MetaPage
from services.meta.client import MetaClient
from services.meta.errors import MetaApiError


class MetaPageSyncService:
    def __init__(self, db: Session):
        self.db = db

    def sync_credential(self, credential_id: str) -> Dict:
        credential = self.db.query(Credential).filter(Credential.id == credential_id).first()
        if not credential:
            raise MetaApiError("Meta 凭据不存在")
        if credential.status != CredentialStatus.ACTIVE.value or credential.is_expired():
            raise MetaApiError("Meta 凭据已失效，请重新授权")

        client = MetaClient(credential.get_access_token())
        params = {"fields": "id,name,access_token,tasks,category", "limit": 100}
        rows: List[dict] = []
        after = None
        for _ in range(20):
            if after:
                params["after"] = after
            payload = client._get("me/accounts", params)
            rows.extend(payload.get("data", []))
            after = (payload.get("paging") or {}).get("cursors", {}).get("after")
            if not after:
                break

        seen = set()
        synced = []
        for remote in rows:
            page_id = str(remote.get("id") or "").strip()
            page_token = remote.get("access_token")
            if not page_id or not page_token:
                continue
            seen.add(page_id)
            page = self.db.query(MetaPage).filter(MetaPage.page_id == page_id).first()
            if not page:
                page = MetaPage(id=uuid.uuid4().hex, page_id=page_id, tenant_id=credential.tenant_id)
                self.db.add(page)
            elif page.connection_id and page.connection_id != credential.connection_id:
                # 当前表结构按租户+Page 唯一，不能安全保存同一 Page 在多个 OAuth
                # 连接下的不同 Page Token。禁止后授权静默覆盖前一授权。
                logger.warning(
                    f"[meta_pages] Page {page_id} 已属于连接 {page.connection_id}，"
                    f"忽略连接 {credential.connection_id} 的覆盖"
                )
                continue
            page.page_name = remote.get("name") or page_id
            page.category = remote.get("category")
            page.tasks = remote.get("tasks") or []
            page.credential_id = credential.id
            page.connection_id = credential.connection_id
            page.status = CredentialStatus.ACTIVE.value
            page.last_error = None
            page.last_synced_at = datetime.utcnow()
            page.set_page_access_token(page_token)
            synced.append(page_id)

        # 本次授权已不再返回的页面不删除，标记失效，保留模板历史引用。
        existing = self.db.query(MetaPage).filter(MetaPage.credential_id == credential.id).all()
        for page in existing:
            if page.page_id not in seen:
                page.status = CredentialStatus.DISABLED.value
                page.last_error = "页面已不在当前 Meta 授权范围内"

        self.db.commit()
        logger.info(f"[meta_pages] 凭据 {credential.id} 同步页面 {len(synced)} 个")
        return {"credential_id": credential.id, "count": len(synced), "page_ids": synced}
