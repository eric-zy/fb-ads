from datetime import datetime, timedelta
import hashlib

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from api import meta_accounts
from core.auth import AuthManager
from core.database import get_db
from main import auth_login
from models import MetaAccount, User
from services.meta import MetaSyncService


def make_user(db, **values):
    user = User(id='last-login-user', username='last-login-user', email='last-login@example.test',
                hashed_password=AuthManager.hash_password('test-password'), role='tenant_admin', **values)
    db.add(user)
    db.commit()
    return user


def login_client(db):
    app = FastAPI()
    app.add_api_route('/login', auth_login, methods=['POST'])
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def test_successful_login_records_and_updates_time(db):
    user = make_user(db)
    client = login_client(db)
    before = datetime.utcnow()
    response = client.post('/login', json={'username': user.username, 'password': 'test-password'})
    assert response.status_code == 200
    db.refresh(user)
    assert before <= user.last_login <= datetime.utcnow()
    assert response.json()['user']['last_login'] == user.last_login.isoformat()
    user.last_login = datetime.utcnow() - timedelta(days=3)
    db.commit()
    response = client.post('/login', json={'username': user.username, 'password': 'test-password'})
    db.refresh(user)
    assert response.status_code == 200
    assert user.last_login >= before


@pytest.mark.parametrize('disabled', [False, True])
def test_failed_or_disabled_login_does_not_change_time(db, disabled):
    previous = datetime(2026, 9, 1, 1, 2, 3)
    user = make_user(db, is_active=not disabled, last_login=previous)
    response = login_client(db).post('/login', json={
        'username': user.username, 'password': 'test-password' if disabled else 'wrong-password',
    })
    assert response.status_code == (403 if disabled else 401)
    db.refresh(user)
    assert user.last_login == previous


def test_legacy_password_upgrade_and_login_time_commit_together(db):
    user = make_user(db)
    user.hashed_password = hashlib.sha256(b'test-password').hexdigest()
    db.commit()
    response = login_client(db).post('/login', json={'username': user.username, 'password': 'test-password'})
    assert response.status_code == 200
    db.refresh(user)
    assert user.hashed_password.startswith('pbkdf2_sha256$')
    assert user.last_login is not None


def test_pending_account_scan_is_not_a_business_detail_route(db, monkeypatch):
    user = make_user(db)
    db.add(MetaAccount(id='pending-scan-bm', name='测试 BM', business_id='bm-123', status='ACTIVE'))
    db.commit()
    monkeypatch.setattr(MetaSyncService, 'fetch_ad_accounts_from_meta', lambda _self, _id: [
        {'id': 'act_999', 'name': '待导入账户', 'currency': 'USD', 'account_status': 1},
    ])
    app = FastAPI()
    app.include_router(meta_accounts.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[meta_accounts.require_admin] = lambda: user
    client = TestClient(app)
    response = client.get('/api/v1/meta-accounts/pending-ad-accounts')
    assert response.status_code == 200
    assert response.json()['accounts'][0]['id'] == 'act_999'
    assert response.json()['errors'] == []
    detail = client.get('/api/v1/meta-accounts/pending-scan-bm')
    assert detail.status_code == 200
    assert detail.json()['id'] == 'pending-scan-bm'


def test_pending_account_scan_reports_partial_failure(db, monkeypatch):
    user = make_user(db)
    db.add(MetaAccount(id='failed-scan-bm', name='失效 BM', business_id='bm-456', status='ACTIVE'))
    db.commit()
    def fail(_self, _id):
        raise ValueError('授权已失效')
    monkeypatch.setattr(MetaSyncService, 'fetch_ad_accounts_from_meta', fail)
    app = FastAPI()
    app.include_router(meta_accounts.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[meta_accounts.require_admin] = lambda: user
    response = TestClient(app).get('/api/v1/meta-accounts/pending-ad-accounts')
    assert response.status_code == 200
    assert response.json()['accounts'] == []
    assert response.json()['errors'][0]['error'] == '授权已失效'
