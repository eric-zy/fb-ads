"""广告账户主键、凭据解析与洞察链路回归测试。"""
import pytest

from core.enums import CredentialStatus
from models import AccountInsight, AdAccount, MetaAccount
from services.ad_account_resolver import resolve_ad_account
from services.ads_manager import AdsManager
from services.credential_service import CredentialService
from services.fb_connector_client import FBConnectorClient
from services.risk_detector import RiskDetector


@pytest.fixture(autouse=True)
def connector_available(monkeypatch):
    """让服务层测试只验证调用协议，不连接真实海外服务。"""
    monkeypatch.setattr(FBConnectorClient, "__init__", lambda self, **kwargs: None)


@pytest.fixture()
def bm_and_account(db):
    db.add(MetaAccount(id="bm1", name="测试BM", business_id="111"))
    db.add(
        AdAccount(
            id="acc1",
            business_id="bm1",
            account_id="act_1",
            connector_credential_id="connector-1",
            daily_spend_limit=10000,  # 100.00 元（最小货币单位）
        )
    )
    db.commit()
    return "bm1", "acc1", "act_1"


# --------------------------------------------------------------------------
# 标识解析
# --------------------------------------------------------------------------
def test_resolve_by_primary_key(db, bm_and_account):
    assert resolve_ad_account(db, "acc1").id == "acc1"


def test_resolve_requires_internal_primary_key(db, bm_and_account):
    """业务层只接受广告账户内部主键。"""
    assert resolve_ad_account(db, "act_1") is None


def test_resolve_unknown_returns_none(db):
    assert resolve_ad_account(db, "not-exist") is None
    assert resolve_ad_account(db, "") is None


# --------------------------------------------------------------------------
# 缺陷 B：凭据解析必须走 business_id
# --------------------------------------------------------------------------
def test_credential_resolve_uses_business_id(db, bm_and_account):
    """AdAccount 没有 meta_account_id 属性，应通过 business_id 找到 BM 凭据"""
    service = CredentialService(db)
    cred = service.create_for_meta("bm1", "plain-token-123")

    token, hit = service.resolve_token("acc1")
    assert token == "plain-token-123"
    assert hit is not None and hit.id == cred.id  # 命中凭据表而非全局兜底


def test_default_credential_takes_priority(db, bm_and_account):
    """显式指定的默认凭据优先于「最新一条 ACTIVE」的推导结果"""
    service = CredentialService(db)
    # replace_active=False：让两条凭据并存，才能验证"指定哪条用哪条"
    older = service.create_for_meta("bm1", "token-older", replace_active=False)
    service.create_for_meta("bm1", "token-newer", replace_active=False)

    meta = db.query(MetaAccount).filter(MetaAccount.id == "bm1").first()
    meta.default_credential_id = older.id
    db.commit()

    token, hit = service.resolve_token("acc1")
    assert hit.id == older.id
    assert token == "token-older"


def test_default_credential_does_not_fallback_when_unusable(db, bm_and_account):
    """默认凭据失效时直接报错，不按创建时间猜测其它凭据。"""
    service = CredentialService(db)
    target = service.create_for_meta("bm1", "token-target", replace_active=False)
    fallback = service.create_for_meta("bm1", "token-fallback", replace_active=False)

    meta = db.query(MetaAccount).filter(MetaAccount.id == "bm1").first()
    meta.default_credential_id = target.id
    db.commit()

    target.status = CredentialStatus.DISABLED.value
    db.commit()

    with pytest.raises(Exception, match="无可用凭据"):
        service.resolve_token("acc1")


def test_mark_invalid_by_account_marks_bm_credential(db, bm_and_account):
    service = CredentialService(db)
    cred = service.create_for_meta("bm1", "plain-token-123")

    service.mark_invalid_by_account("acc1", "Token 失效")
    db.refresh(cred)
    assert cred.status == CredentialStatus.INVALID.value
    assert cred.last_error == "Token 失效"


# --------------------------------------------------------------------------
# 缺陷 C：风控统计必须包含 events_created
# --------------------------------------------------------------------------
def test_execute_risk_actions_reports_events_created(db, bm_and_account, monkeypatch):
    """花费超限时既要暂停系列，也要返回新建的风险事件数"""
    monkeypatch.setattr(FBConnectorClient, "get_insights", lambda *a, **k: {"items": [{"spend": "90.00"}]})
    monkeypatch.setattr(FBConnectorClient, "pause_campaign", lambda *a, **k: True)

    result = RiskDetector(db).execute_risk_actions("acc1")

    assert "events_created" in result
    assert result["events_created"] == 1


def test_execute_risk_actions_rejects_meta_account_number(db, bm_and_account):
    """业务任务只接受 AdAccount.id，不再兼容 Meta 账户号。"""
    assert RiskDetector(db).execute_risk_actions("act_1") == {
        "campaigns_paused": 0,
        "accounts_frozen": 0,
        "events_created": 0,
    }


def test_execute_risk_actions_unknown_account(db, monkeypatch):
    result = RiskDetector(db).execute_risk_actions("not-exist")
    assert result == {"campaigns_paused": 0, "accounts_frozen": 0, "events_created": 0}


# --------------------------------------------------------------------------
# 缺陷 A：AdsManager.fetch_insights
# --------------------------------------------------------------------------
def test_fetch_insights_persists_by_primary_key(db, bm_and_account, monkeypatch):
    monkeypatch.setattr(
        FBConnectorClient,
        "get_insights",
        lambda *a, **k: {"items": [
            {
                "date_start": "2026-09-01",
                "spend": "10.50",
                "impressions": "1000",
                "clicks": "50",
                "actions": [{"action_type": "purchase", "value": "2"}],
            }
        ]},
    )

    count = AdsManager(db).fetch_insights("acc1", "2026-09-01", "2026-09-01")
    assert count == 1

    row = db.query(AccountInsight).filter(AccountInsight.date == "2026-09-01").first()
    assert row.ad_account_id == "acc1"  # 存主键
    assert row.spend == 1050            # 10.50 元 → 最小货币单位
    assert row.impressions == 1000
    assert row.clicks == 50
    assert row.conversions == 2
    assert row.ctr == pytest.approx(0.05)


def test_fetch_insights_is_idempotent(db, bm_and_account, monkeypatch):
    """重复拉取同一天应 upsert，不产生重复行"""
    payload = [
        {"date_start": "2026-09-01", "spend": "10.00", "impressions": "100", "clicks": "5"}
    ]
    monkeypatch.setattr(FBConnectorClient, "get_insights", lambda *a, **k: {"items": payload})

    AdsManager(db).fetch_insights("acc1", "2026-09-01", "2026-09-01")
    payload[0]["spend"] = "20.00"
    AdsManager(db).fetch_insights("acc1", "2026-09-01", "2026-09-01")

    rows = db.query(AccountInsight).filter(AccountInsight.ad_account_id == "acc1").all()
    assert len(rows) == 1
    assert rows[0].spend == 2000


def test_fetch_insights_unknown_account_returns_zero(db, monkeypatch):
    monkeypatch.setattr(FBConnectorClient, "get_insights", lambda *a, **k: {"items": [{"spend": "1"}]})
    assert AdsManager(db).fetch_insights("not-exist", "2026-09-01", "2026-09-01") == 0


def test_get_account_spend_today_converts_unit(db, bm_and_account, monkeypatch):
    """Meta 返回主单位，库内统一最小货币单位"""
    monkeypatch.setattr(
        FBConnectorClient, "get_insights", lambda *a, **k: {"items": [{"spend": "12.34"}]}
    )
    assert AdsManager(db).get_account_spend_today("acc1") == 1234


# --------------------------------------------------------------------------
# 缺陷 D：日报按 Meta 账户号查询曾恒返回空
# --------------------------------------------------------------------------
def test_sync_campaigns_uses_primary_key_and_connector(db, bm_and_account, monkeypatch):
    """业务层接收主键，Connector 请求使用 Meta 账户号。"""
    monkeypatch.setattr(
        FBConnectorClient,
        "list_campaigns",
        lambda *args: {"campaigns": [{"id": "c1", "name": "Campaign 1", "status": "ACTIVE"}]},
    )

    created, _updated = AdsManager(db).sync_campaigns("acc1")
    assert created == 1

    from models import Campaign

    campaign = db.query(Campaign).filter(Campaign.campaign_id == "c1").first()
    assert campaign is not None
    assert campaign.ad_account_id == "acc1"  # 外键存主键，而非 act_1


def test_sync_campaigns_unknown_account(db, monkeypatch):
    monkeypatch.setattr(FBConnectorClient, "list_campaigns", lambda *args: {"campaigns": []})
    assert AdsManager(db).sync_campaigns("not-exist") == (0, 0)


def test_daily_report_rejects_meta_account_number(db, bm_and_account):
    """日报查询只接受内部主键。"""
    from datetime import date

    from services.analytics import AnalyticsEngine

    db.add(
        AccountInsight(
            id="ins_1", ad_account_id="acc1", date=date(2026, 9, 1), spend=1050
        )
    )
    db.commit()

    engine = AnalyticsEngine(db)
    by_key = engine.generate_daily_report("acc1", date(2026, 9, 1))
    assert by_key["metrics"]["spend"] == 10.5
    assert engine.generate_daily_report("act_1", date(2026, 9, 1)) == {}
