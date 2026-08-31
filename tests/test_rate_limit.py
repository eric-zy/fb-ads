"""限流管理器 / 发布频次验证器的单元测试

说明：
- 数据库相关用例统一使用 conftest 的 `db` fixture（SQLite + 事务回滚），
  不会写入开发/生产库，也不会因重复运行而主键冲突。
- RateLimitManager 基于 Redis，用例使用独立的测试 account_id 并在结束时清理。
"""
import pytest
from datetime import datetime, timedelta
from typing import Optional

from models import AdAccount, Campaign, MetaAccount, SystemStatus
from services.publish_frequency_validator import PublishFrequencyValidator
from services.rate_limit import RateLimitManager

# 独立的测试账户标识，避免与真实账户/其他用例互相干扰
RL_ACCOUNT = "act_unittest_rate_limit"


@pytest.fixture
def rate_limiter():
    limiter = RateLimitManager(RL_ACCOUNT)
    limiter.reset()
    yield limiter
    limiter.reset()


class TestRateLimitManager:
    """速率限制管理器测试（对应 RateLimitManager 实际 API）"""

    def test_check_limit_allows_when_under_limit(self, rate_limiter):
        """未达上限时允许请求"""
        assert rate_limiter.check_limit("minute") is True

    def test_check_limit_blocks_when_over_limit(self, rate_limiter):
        """达到上限（每分钟 10 次）后拒绝请求"""
        for _ in range(10):
            rate_limiter.increment("minute")

        assert rate_limiter.check_limit("minute") is False

    def test_increment_and_get_status(self, rate_limiter):
        """increment 累加计数，get_status 反映各窗口用量"""
        for _ in range(3):
            rate_limiter.increment("minute")

        status = rate_limiter.get_status()
        assert status["minute"]["used"] == 3
        assert status["minute"]["limit"] == rate_limiter.limits["minute"]
        assert status["minute"]["remaining"] == rate_limiter.limits["minute"] - 3

    def test_reset_clears_counters(self, rate_limiter):
        """reset 清空计数，之后重新允许请求"""
        for _ in range(10):
            rate_limiter.increment("minute")
        assert rate_limiter.check_limit("minute") is False

        assert rate_limiter.reset("minute") is True
        assert rate_limiter.check_limit("minute") is True

    def test_windows_are_independent(self, rate_limiter):
        """不同时间窗口互不影响"""
        for _ in range(10):
            rate_limiter.increment("minute")

        assert rate_limiter.check_limit("minute") is False
        assert rate_limiter.check_limit("hour") is True


def _make_business(db, pk: str, business_id: str) -> MetaAccount:
    """创建 BM。V1 起广告账户的 business_id 为 NOT NULL，必须先有归属 BM"""
    meta = MetaAccount(id=pk, name=f"BM {pk}", business_id=business_id)
    db.add(meta)
    db.flush()
    return meta


def _make_account(
    db,
    pk: str,
    account_id: str,
    business_id: str,
    system_status: SystemStatus = SystemStatus.ACTIVE,
    reason: Optional[str] = None,
):
    account = AdAccount(
        id=pk,
        business_id=business_id,
        account_id=account_id,
        account_name=f"Test Account {pk}",
        system_status=system_status.value,
        system_status_reason=reason,
        # 金额字段为最小货币单位
        daily_spend_limit=1000000,
        monthly_spend_limit=30000000,
    )
    db.add(account)
    db.flush()
    return account


def _make_campaigns(db, ad_account_id: str, count: int, within_hours: int = 1):
    for i in range(count):
        db.add(
            Campaign(
                id=f"{ad_account_id}_campaign_{i}",
                campaign_id=f"campaign_{ad_account_id}_{i}",
                ad_account_id=ad_account_id,
                name=f"Test Campaign {i}",
                status="ACTIVE",
                created_at=datetime.utcnow() - timedelta(hours=within_hours),
            )
        )
    db.flush()


class TestPublishFrequencyValidator:
    """发布频次验证器测试"""

    def test_validate_healthy_account(self, db):
        """健康账户：系统状态 ACTIVE 且低频次 → 健康"""
        _make_business(db, "ut_bm_healthy", "111_healthy")
        _make_account(db, "ut_acc_healthy", "act_ut_healthy", "ut_bm_healthy")

        validator = PublishFrequencyValidator(db)
        is_healthy, report = validator.validate_account_health("act_ut_healthy")

        assert is_healthy is True
        assert report["status"] == SystemStatus.ACTIVE.value
        assert report["is_active"] is True

    def test_validate_disabled_account(self, db):
        """系统侧禁用：直接判定不健康，不再统计频次"""
        _make_business(db, "ut_bm_frozen", "222_frozen")
        _make_account(
            db, "ut_acc_frozen", "act_ut_frozen", "ut_bm_frozen",
            system_status=SystemStatus.DISABLED, reason="High fraud risk",
        )

        validator = PublishFrequencyValidator(db)
        is_healthy, report = validator.validate_account_health("act_ut_frozen")

        assert is_healthy is False
        assert report["status"] == SystemStatus.DISABLED.value
        assert report["is_active"] is False
        assert report["system_status_reason"] == "High fraud risk"

    def test_validate_missing_account(self, db):
        """账户不存在时返回 not_found，而不是抛异常"""
        validator = PublishFrequencyValidator(db)
        is_healthy, report = validator.validate_account_health("act_ut_not_exist")

        assert is_healthy is False
        assert report["status"] == "not_found"

    def test_frequency_calculation(self, db):
        """时间窗口内创建的系列被正确统计（24h 内 5 个属于 safe）"""
        _make_business(db, "ut_bm_freq", "333_freq")
        _make_account(db, "ut_acc_freq", "act_ut_freq", "ut_bm_freq")
        _make_campaigns(db, "ut_acc_freq", 5, within_hours=1)

        validator = PublishFrequencyValidator(db)
        report = validator.check_campaign_publish_frequency("act_ut_freq", 24)

        assert report["campaigns_created"] == 5
        assert report["status"] == "safe"
        assert report["risk_level"] == "safe"

    def test_frequency_ignores_out_of_window_campaigns(self, db):
        """窗口外的系列不纳入统计"""
        _make_business(db, "ut_bm_old", "444_old")
        _make_account(db, "ut_acc_old", "act_ut_old", "ut_bm_old")
        _make_campaigns(db, "ut_acc_old", 3, within_hours=48)

        validator = PublishFrequencyValidator(db)
        report = validator.check_campaign_publish_frequency("act_ut_old", 24)

        assert report["campaigns_created"] == 0
        assert report["status"] == "safe"

    def test_frequency_accepts_internal_id(self, db):
        """兼容：用内部主键查询同样能统计到"""
        _make_business(db, "ut_bm_inner", "555_inner")
        _make_account(db, "ut_acc_inner", "act_ut_inner", "ut_bm_inner")
        _make_campaigns(db, "ut_acc_inner", 2, within_hours=1)

        validator = PublishFrequencyValidator(db)
        report = validator.check_campaign_publish_frequency("ut_acc_inner", 24)

        assert report["campaigns_created"] == 2
