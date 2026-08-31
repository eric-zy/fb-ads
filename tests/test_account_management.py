"""账号统一管理测试：BM 主账号 / 凭据 / 广告账户 三层分离

验证要点（设计文档第 9 节）：
- Access Token 加密进 credentials 表，**不落** meta_accounts 主表
- 对外接口默认只返回脱敏 Token；查看明文需显式 confirm 且写审计日志
- 轮换（rotate）后旧凭据转 DISABLED，新凭据立即生效
- 过期凭据不允许直接启用，必须先轮换
- 广告账户可按 BM 过滤、可转移归属、支持批量操作
- 归属校验 Token 由凭据解析，不依赖 BM 主表明文

隔离方式：独立 SQLite 内存库 + 真实 JWT 鉴权，不触碰开发/生产库。
"""
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import main
from core.database import Base, get_db
from core.enums import CredentialStatus
from models import AdAccount, AuditLog, Credential, MetaAccount, SystemStatus, User
from services.credential_service import CredentialService

# --------------------------------------------------------------------------
# 隔离的测试应用：内存 SQLite + 真实 JWT
# --------------------------------------------------------------------------
engine = create_engine(
    "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

_ORIGINAL_OVERRIDES = dict(main.app.dependency_overrides)

ADMIN_ID = "test-admin-001"
ADMIN_EMAIL = "admin@test.local"


def _override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def isolated_db():
    """每个用例重建内存库，并隔离 dependency_overrides"""
    Base.metadata.create_all(bind=engine)
    main.app.dependency_overrides.clear()
    main.app.dependency_overrides[get_db] = _override_get_db

    db = TestingSessionLocal()
    db.add(
        User(
            id=ADMIN_ID,
            email=ADMIN_EMAIL,
            username="admin",
            hashed_password="not-used",
            role="admin",
            is_active=True,
            is_verified=True,
        )
    )
    db.commit()
    db.close()

    yield

    main.app.dependency_overrides.clear()
    main.app.dependency_overrides.update(_ORIGINAL_OVERRIDES)
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    """已通过鉴权的管理员客户端"""
    token = main._create_access_token(ADMIN_ID, ADMIN_EMAIL, "admin")
    c = TestClient(main.app)
    c.headers.update({"Authorization": f"Bearer {token}"})
    return c


@pytest.fixture
def anon_client():
    """未鉴权客户端"""
    return TestClient(main.app)


def _make_meta(client, token: str = "EAAA-fake-token-0123456789") -> dict:
    resp = client.post(
        "/api/v1/meta-accounts",
        json={
            "name": "测试 BM",
            "business_id": f"bm_{uuid.uuid4().hex[:8]}",
            "access_token": token,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ==========================================================================
# 鉴权
# ==========================================================================
def test_requires_authentication(anon_client):
    """未带 Token 访问三层管理接口一律被中间件拦截"""
    assert anon_client.get("/api/v1/meta-accounts").status_code == 401
    assert anon_client.get("/api/v1/credentials").status_code == 401
    assert anon_client.get("/api/v1/accounts").status_code == 401


# ==========================================================================
# 凭据分离存储
# ==========================================================================
def test_token_not_stored_in_meta_account(client):
    """Access Token 加密进凭据表，BM 主表根本不再有明文列"""
    plain = "EAAA-secret-token-abcdef123456"
    meta = _make_meta(client, plain)

    db = TestingSessionLocal()
    try:
        row = db.query(MetaAccount).filter(MetaAccount.id == meta["id"]).first()
        # V1 起 meta_accounts 已移除 access_token / app_secret 列
        assert not hasattr(row, "access_token"), "BM 主表不应再有明文 Token 列"
        assert not hasattr(row, "app_secret"), "BM 主表不应再有 app_secret 列"

        cred = db.query(Credential).filter(
            Credential.meta_account_id == meta["id"]
        ).first()
        assert cred is not None, "凭据表应写入记录"
        assert cred.status == CredentialStatus.ACTIVE.value
        assert cred.access_token_encrypted != plain, "落库必须是密文"
        assert cred.get_access_token() == plain, "应能解密回原文"
    finally:
        db.close()

    # 响应体不含明文，只有脱敏值
    assert meta["credential_masked"] != plain
    assert "access_token" not in meta


def test_credential_list_is_masked(client):
    """凭据列表默认脱敏，明文需显式 confirm"""
    meta = _make_meta(client, "EAAA-list-mask-9876543210")
    cred_id = meta["credential_id"]

    resp = client.get("/api/v1/credentials", params={"meta_account_id": meta["id"]})
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    assert "access_token" not in items[0]
    assert items[0]["access_token_masked"].endswith("3210")

    # 未确认 → 拒绝
    resp = client.post(f"/api/v1/credentials/{cred_id}/reveal", json={})
    assert resp.status_code == 400

    # 确认后返回明文，并写审计日志
    resp = client.post(f"/api/v1/credentials/{cred_id}/reveal", json={"confirm": True})
    assert resp.status_code == 200
    assert resp.json()["access_token"] == "EAAA-list-mask-9876543210"

    db = TestingSessionLocal()
    try:
        logged = (
            db.query(AuditLog)
            .filter(
                AuditLog.action == "REVEAL_CREDENTIAL",
                AuditLog.resource_id == cred_id,
            )
            .first()
        )
        assert logged is not None, "查看明文必须留痕"
    finally:
        db.close()


def test_rotate_credential(client):
    """轮换后旧凭据转 DISABLED，新凭据生效"""
    meta = _make_meta(client, "EAAA-old-token-1111111111")
    old_id = meta["credential_id"]

    resp = client.post(
        f"/api/v1/credentials/{old_id}/rotate",
        json={"access_token": "EAAA-new-token-2222222222", "keep_old": True},
    )
    assert resp.status_code == 200, resp.text
    new_id = resp.json()["id"]

    resp = client.get("/api/v1/credentials", params={"meta_account_id": meta["id"]})
    statuses = {c["id"]: c["status"] for c in resp.json()}
    assert statuses[old_id] == CredentialStatus.DISABLED.value
    assert statuses[new_id] == CredentialStatus.ACTIVE.value

    # 解析到的是新 Token
    db = TestingSessionLocal()
    try:
        token, _ = CredentialService(db).resolve_token_for_meta(meta["id"])
        assert token == "EAAA-new-token-2222222222"
    finally:
        db.close()


def test_disable_enable_and_expired_guard(client):
    """停用 / 启用正常；已过期凭据不允许直接启用"""
    meta = _make_meta(client)
    cred_id = meta["credential_id"]

    assert client.post(f"/api/v1/credentials/{cred_id}/disable").status_code == 200
    assert client.get(f"/api/v1/credentials/{cred_id}").json()["status"] == "DISABLED"

    assert client.post(f"/api/v1/credentials/{cred_id}/enable").status_code == 200
    assert client.get(f"/api/v1/credentials/{cred_id}").json()["status"] == "ACTIVE"

    # 标记为已过期后再启用应被拒绝
    db = TestingSessionLocal()
    try:
        from datetime import datetime, timedelta

        cred = db.query(Credential).filter(Credential.id == cred_id).first()
        cred.expires_at = datetime.utcnow() - timedelta(days=1)
        db.commit()
    finally:
        db.close()

    resp = client.post(f"/api/v1/credentials/{cred_id}/enable")
    assert resp.status_code == 400
    assert "rotate" in resp.json()["detail"].lower()


def test_meta_account_reports_credential_health(client):
    """BM 列表返回凭据健康状态；无凭据时标识为 NONE"""
    meta = _make_meta(client)
    assert meta["credential_status"] == "ACTIVE"
    assert meta["credential_source"] == "CREDENTIALS"
    assert meta["has_credential"] is True

    # 新建一个不传 Token 的 BM
    resp = client.post(
        "/api/v1/meta-accounts",
        json={"name": "无凭据 BM", "business_id": f"bm_{uuid.uuid4().hex[:8]}"},
    )
    assert resp.status_code == 201, resp.text
    bare = resp.json()
    assert bare["credential_status"] == "NONE"
    assert bare["credential_source"] == "NONE"
    assert bare["has_credential"] is False

    listed = client.get("/api/v1/meta-accounts").json()
    assert {m["credential_status"] for m in listed} == {"ACTIVE", "NONE"}


# ==========================================================================
# 广告账户：归属过滤 / 转移 / 批量
# ==========================================================================
def _make_account(client, business_id: str) -> dict:
    """创建广告账户。V1 起 business_id 必填"""
    resp = client.post(
        "/api/v1/accounts",
        json={
            "account_id": f"act_{uuid.uuid4().hex[:10]}",
            "account_name": "测试账户",
            "business_id": business_id,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_account_requires_business(client):
    """归属 BM 为必填：缺少 business_id 直接 400"""
    resp = client.post(
        "/api/v1/accounts",
        json={"account_id": "act_no_bm", "account_name": "无归属账户"},
    )
    assert resp.status_code == 422  # Pydantic 校验失败


def test_duplicate_account_in_same_bm_rejected(client):
    """同一 BM 内不允许重复账户（唯一键 business_id + account_id）"""
    meta = _make_meta(client)
    account_id = f"act_{uuid.uuid4().hex[:10]}"

    first = client.post(
        "/api/v1/accounts",
        json={"account_id": account_id, "business_id": meta["id"], "account_name": "A"},
    )
    assert first.status_code == 201, first.text

    dup = client.post(
        "/api/v1/accounts",
        json={"account_id": account_id, "business_id": meta["id"], "account_name": "B"},
    )
    assert dup.status_code == 400
    assert "已存在" in dup.json()["detail"]


def test_same_account_can_belong_to_multiple_bm(client):
    """同一个 act_xxx 允许挂到不同 BM（跨 BM 唯一，非全局唯一）"""
    meta_a = _make_meta(client)
    meta_b = _make_meta(client)
    account_id = f"act_{uuid.uuid4().hex[:10]}"

    ra = client.post(
        "/api/v1/accounts",
        json={"account_id": account_id, "business_id": meta_a["id"], "account_name": "A"},
    )
    rb = client.post(
        "/api/v1/accounts",
        json={"account_id": account_id, "business_id": meta_b["id"], "account_name": "B"},
    )
    assert ra.status_code == 201, ra.text
    assert rb.status_code == 201, rb.text
    assert ra.json()["id"] != rb.json()["id"]


def test_account_filter_by_bm_and_total_count(client):
    """支持按 BM 过滤，总数通过 X-Total-Count 返回"""
    meta_a = _make_meta(client)
    meta_b = _make_meta(client)
    acc_a = _make_account(client, business_id=meta_a["id"])
    _make_account(client, business_id=meta_b["id"])

    resp = client.get("/api/v1/accounts", params={"business_id": meta_a["id"]})
    assert resp.status_code == 200
    ids = [a["account_id"] for a in resp.json()]
    assert ids == [acc_a["account_id"]]
    assert resp.headers["X-Total-Count"] == "1"


def test_transfer_and_bulk_transfer(client):
    """单个转移与批量转移归属"""
    meta_a = _make_meta(client)
    meta_b = _make_meta(client)
    acc = _make_account(client, business_id=meta_a["id"])

    # 单个转移到另一个 BM
    resp = client.post(
        f"/api/v1/accounts/{acc['id']}/transfer", json={"business_id": meta_b["id"]}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["business_id"] == meta_b["id"]

    # 批量转移回原 BM
    resp = client.post(
        "/api/v1/accounts/bulk",
        json={
            "action": "transfer",
            "account_ids": [acc["id"]],
            "business_id": meta_a["id"],
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success_count"] == 1 and body["failed_count"] == 0

    resp = client.get("/api/v1/accounts", params={"business_id": meta_a["id"]})
    assert resp.json()[0]["business_id"] == meta_a["id"]


def test_transfer_rejects_unassign(client):
    """V1 中 business_id 为 NOT NULL，不允许通过 transfer 解除归属"""
    meta = _make_meta(client)
    acc = _make_account(client, business_id=meta["id"])

    resp = client.post(
        f"/api/v1/accounts/{acc['id']}/transfer", json={"business_id": None}
    )
    assert resp.status_code == 400
    assert "system_status" in resp.json()["detail"]


def test_bulk_freeze_unfreeze_delete(client):
    """批量禁用 / 启用 / 删除，且单条失败不影响其余"""
    meta = _make_meta(client)
    a1 = _make_account(client, business_id=meta["id"])
    a2 = _make_account(client, business_id=meta["id"])
    ids = [a1["id"], a2["id"]]

    resp = client.post(
        "/api/v1/accounts/bulk",
        json={"action": "freeze", "account_ids": ids, "reason": "批量冻结测试"},
    )
    assert resp.json()["success_count"] == 2

    db = TestingSessionLocal()
    try:
        assert all(
            db.query(AdAccount).filter(AdAccount.id == i).first().system_status
            == SystemStatus.DISABLED.value
            for i in ids
        )
    finally:
        db.close()

    resp = client.post(
        "/api/v1/accounts/bulk", json={"action": "unfreeze", "account_ids": ids}
    )
    assert resp.json()["success_count"] == 2

    # 批量删除（含一个不存在的 ID，验证部分失败不影响其余）
    resp = client.post(
        "/api/v1/accounts/bulk", json={"action": "delete", "account_ids": ids + ["not-exist"]}
    )
    body = resp.json()
    assert body["success_count"] == 2 and body["failed_count"] == 1
    assert body["errors"][0]["error"] == "账户不存在"

    db = TestingSessionLocal()
    try:
        assert db.query(AdAccount).filter(AdAccount.id.in_(ids)).count() == 0
    finally:
        db.close()


def test_bulk_rejects_unknown_action(client):
    """未知批量动作直接 400"""
    resp = client.post(
        "/api/v1/accounts/bulk", json={"action": "explode", "account_ids": ["x"]}
    )
    assert resp.status_code == 400


def test_delete_meta_account_clears_credentials(client):
    """删除 BM 时清理其名下凭据，且名下有账户时拒绝删除"""
    meta = _make_meta(client)
    _make_account(client, business_id=meta["id"])

    resp = client.delete(f"/api/v1/meta-accounts/{meta['id']}")
    assert resp.status_code == 400
    assert "广告账户" in resp.json()["detail"]

    # 删除账户后可删除 BM，凭据一并清理
    client.post(
        "/api/v1/accounts/bulk",
        json={
            "action": "delete",
            "account_ids": [a["id"] for a in client.get("/api/v1/accounts").json()],
        },
    )
    resp = client.delete(f"/api/v1/meta-accounts/{meta['id']}")
    assert resp.status_code == 200

    db = TestingSessionLocal()
    try:
        assert (
            db.query(Credential)
            .filter(Credential.meta_account_id == meta["id"])
            .count()
            == 0
        )
    finally:
        db.close()


# ==========================================================================
# 可投放账户池（文档 §19）
# 判断规则必须由后端统一计算，前端不得自行拼接
# ==========================================================================
def test_available_for_deployment(client):
    """凭据 / BM / 系统状态都正常 → 进入可投放账户池"""
    meta = _make_meta(client)
    acc = _make_account(client, business_id=meta["id"])

    resp = client.get("/api/v1/accounts/available-for-deployment")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    assert body["accounts"][0]["id"] == acc["id"]
    # 自带 BM 与凭据上下文，投放模块可直接使用
    assert body["accounts"][0]["business"]["id"] == meta["id"]
    assert body["accounts"][0]["credential"]["status"] == "ACTIVE"
    assert "access_token" not in body["accounts"][0]["credential"]


def test_disabled_account_excluded_from_pool(client):
    """系统侧禁用 → 不进入可投放账户池"""
    meta = _make_meta(client)
    acc = _make_account(client, business_id=meta["id"])

    client.post(f"/api/v1/accounts/{acc['id']}/freeze", params={"reason": "风控"})
    body = client.get("/api/v1/accounts/available-for-deployment").json()
    assert body["total"] == 0


def test_disabled_business_excluded_from_pool(client):
    """BM 禁用 → 其下账户全部不进入可投放账户池"""
    meta = _make_meta(client)
    _make_account(client, business_id=meta["id"])
    assert client.get("/api/v1/accounts/available-for-deployment").json()["total"] == 1

    client.post(f"/api/v1/meta-accounts/{meta['id']}/disable")
    body = client.get("/api/v1/accounts/available-for-deployment").json()
    assert body["total"] == 0


def test_disabled_credential_excluded_from_pool(client):
    """凭据被停用 → 该 BM 下的账户不再进入可投放账户池"""
    meta = _make_meta(client)
    _make_account(client, business_id=meta["id"])
    assert client.get("/api/v1/accounts/available-for-deployment").json()["total"] == 1

    cred_id = meta["credential_id"]
    assert client.post(f"/api/v1/credentials/{cred_id}/disable").status_code == 200

    body = client.get("/api/v1/accounts/available-for-deployment").json()
    assert body["total"] == 0


def test_available_pool_filter_by_business(client):
    """可投放账户池支持按 BM 过滤"""
    meta_a = _make_meta(client)
    meta_b = _make_meta(client)
    _make_account(client, business_id=meta_a["id"])
    _make_account(client, business_id=meta_b["id"])

    resp = client.get(
        "/api/v1/accounts/available-for-deployment",
        params={"business_id": meta_a["id"]},
    )
    assert resp.json()["total"] == 1


# ==========================================================================
# 同步规则（文档 §24）：Upsert 不覆盖 system_status
# ==========================================================================
def test_sync_does_not_overwrite_system_status(client):
    """Meta 同步把账户状态改为 ACTIVE，管理员的 DISABLED 必须保留"""
    meta = _make_meta(client)
    acc = _make_account(client, business_id=meta["id"])

    # 管理员禁用
    client.post(f"/api/v1/accounts/{acc['id']}/freeze", params={"reason": "禁止投放"})

    db = TestingSessionLocal()
    try:
        from services.meta import MetaSyncService

        business = db.query(MetaAccount).filter(MetaAccount.id == meta["id"]).first()
        # 直接调用 Upsert，模拟 Meta 返回该账户为正常状态
        MetaSyncService(db)._upsert_ad_account(
            business,
            {
                "id": acc["account_id"],
                "name": "Meta 侧名称",
                "account_status": 1,
                "amount_spent": "12345",
                "currency": "USD",
            },
        )
        db.commit()

        row = db.query(AdAccount).filter(AdAccount.id == acc["id"]).first()
        # Meta 侧字段被覆盖
        assert row.account_name == "Meta 侧名称"
        assert row.amount_spent == 12345  # 最小货币单位，按整数存储
        # 系统侧状态**不受同步影响**
        assert row.system_status == SystemStatus.DISABLED.value
        assert row.system_status_reason == "禁止投放"
    finally:
        db.close()


def test_sync_upsert_creates_then_updates(client):
    """Upsert 语义：首次创建，再次调用则更新同一条（不产生重复）"""
    meta = _make_meta(client)

    db = TestingSessionLocal()
    try:
        from services.meta import MetaSyncService

        business = db.query(MetaAccount).filter(MetaAccount.id == meta["id"]).first()
        raw = {"id": "act_upsert_001", "name": "账户V1", "currency": "USD"}

        MetaSyncService(db)._upsert_ad_account(business, raw)
        db.commit()
        first_id = (
            db.query(AdAccount).filter(AdAccount.account_id == "act_upsert_001").first().id
        )

        MetaSyncService(db)._upsert_ad_account(business, {**raw, "name": "账户V2"})
        db.commit()

        rows = db.query(AdAccount).filter(AdAccount.account_id == "act_upsert_001").all()
        assert len(rows) == 1, "Upsert 不应产生重复记录"
        assert rows[0].id == first_id
        assert rows[0].account_name == "账户V2"
    finally:
        db.close()


# ==========================================================================
# 金额单位（文档 §9）
# ==========================================================================
def test_amount_stored_in_minor_units(client):
    """金额以最小货币单位（分）存储与返回"""
    meta = _make_meta(client)
    resp = client.post(
        "/api/v1/accounts",
        json={
            "account_id": f"act_{uuid.uuid4().hex[:10]}",
            "account_name": "金额测试",
            "business_id": meta["id"],
            "daily_spend_limit": 100000,   # $1000.00
            "monthly_spend_limit": 3000000,  # $30000.00
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["daily_spend_limit"] == 100000
    assert body["monthly_spend_limit"] == 3000000

    db = TestingSessionLocal()
    try:
        row = db.query(AdAccount).filter(AdAccount.id == body["id"]).first()
        assert isinstance(row.daily_spend_limit, int)
        assert row.daily_spend_limit == 100000
    finally:
        db.close()
