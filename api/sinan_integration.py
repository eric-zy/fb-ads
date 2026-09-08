import uuid
from datetime import datetime
import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from core.auth import require_admin
from core.database import get_db
from models import SinanCredential, User
from services.integrations.sinan_client import SinanClient

router = APIRouter(prefix='/api/v1/integrations/sinan', tags=['司南接入'])
class ConfigRequest(BaseModel):
    base_url: str = 'https://api.sinan-partner.com'
    app_id: str
    account: str
    password: str
    menu_id: str

def _row(db, user):
    return db.query(SinanCredential).filter(SinanCredential.tenant_id == user.tenant_id).first()

async def _login(row):
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        res = await client.post(row.base_url.rstrip('/') + '/auth/login/v1', params={'app_id': row.app_id}, json={'account': row.get_account(), 'password': row.get_password(), 'app_id': row.app_id})
        data = res.json()
        if data.get('code') != 0: raise ValueError(data.get('message') or '司南登录失败')
        cookies = res.cookies
        access = cookies.get('access_token') or data.get('data', {}).get('access_token') or ''
        refresh = cookies.get('refresh_token') or data.get('data', {}).get('refresh_token') or ''
        row.set_tokens(access, refresh)
        check = await client.get(row.base_url.rstrip('/') + '/delivery/drama/info/v1', params={'app_id': row.app_id, 'drama_id': '1'}, headers={'distributor-menu-id': row.menu_id})
        if check.status_code >= 400: raise ValueError('司南登录成功但业务接口校验失败')
        row.status = 'ACTIVE'; row.last_error = None; row.last_verified_at = datetime.utcnow()
        return data.get('data', {}).get('user_id')

@router.get('/status')
def status(db: Session = Depends(get_db), user: User = Depends(require_admin)):
    row = _row(db, user); return row.to_dict() if row else {'configured': False, 'verified': False}

def _client(db, user):
    row = _row(db, user)
    if not row or row.status != 'ACTIVE': raise HTTPException(403, '司南账号未验证')
    return SinanClient(row.base_url, row.app_id, row.get_access_token(), row.get_refresh_token(), row.menu_id)

@router.post('/promotions/query')
async def promotions_query(payload: dict, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    try:
        return (await _client(db, user).promotion_list(payload.get('page', 1), payload.get('page_size', 20))).get('data', {})
    except HTTPException: raise
    except Exception as exc:
        raise HTTPException(502, f'司南推广链查询失败：{exc}')

@router.get('/promotions/{promotion_id}')
async def promotion_detail(promotion_id: str, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    return (await _client(db, user).promotion_detail(promotion_id)).get('data', {})

@router.post('/content/search')
async def content_search(payload: dict, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    return (await _client(db, user).content_list(payload.get('content_type', 'SHORT_VIDEO'), payload.get('keyword', ''), payload.get('page', 1), payload.get('page_size', 20))).get('data', {})

@router.post('/config')
async def save_config(payload: ConfigRequest, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    row = _row(db, user) or SinanCredential(id=uuid.uuid4().hex)
    row.base_url, row.app_id, row.menu_id = payload.base_url, payload.app_id, payload.menu_id
    row.set_account(payload.account); row.set_password(payload.password); row.status = 'VERIFYING'
    if not row.tenant_id: row.tenant_id = user.tenant_id
    db.add(row)
    try: await _login(row)
    except Exception as exc: row.status='INVALID'; row.last_error=str(exc); db.commit(); raise HTTPException(400, '司南账号验证失败')
    db.commit(); return row.to_dict()

@router.post('/test-login')
async def test_login(db: Session = Depends(get_db), user: User = Depends(require_admin)):
    row = _row(db, user)
    if not row: raise HTTPException(404, '请先配置司南账号')
    try: await _login(row)
    except Exception as exc: row.status='INVALID'; row.last_error=str(exc); db.commit(); raise HTTPException(400, '司南账号验证失败')
    db.commit(); return row.to_dict()
