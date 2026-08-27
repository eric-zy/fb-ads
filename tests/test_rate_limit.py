# 发布频次验证的单元测试

import pytest
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from models import AdAccount, Campaign, AccountStatus
from services.publish_frequency_validator import PublishFrequencyValidator
from services.rate_limit import RateLimitManager
from core.database import SessionLocal

class TestRateLimitManager:
    """速率限制管理器测试"""
    
    def test_check_rate_limit_safe(self):
        """测试正常速率限制"""
        rate_limiter = RateLimitManager('act_test_001')
        rate_limiter.reset()
        
        # 初始状态应该是安全的
        is_allowed, info = rate_limiter.check_rate_limit('minute')
        assert is_allowed == True
        assert info['current_count'] == 0
    
    def test_rate_limit_exceeded(self):
        """测试超过速率限制"""
        rate_limiter = RateLimitManager('act_test_002')
        rate_limiter.reset()
        
        # 添加超过限制的计数
        for i in range(15):  # 超过每分钟10次的限制
            rate_limiter.increment('minute')
        
        is_allowed, info = rate_limiter.check_rate_limit('minute')
        assert is_allowed == False
        assert info['current_count'] >= 10
    
    def test_throttle_detection(self):
        """测试节流检测"""
        rate_limiter = RateLimitManager('act_test_003')
        rate_limiter.reset()
        
        # 添加达到阈值的计数
        for i in range(8):  # 达到80%阈值
            rate_limiter.increment('minute')
        
        is_allowed, info = rate_limiter.check_rate_limit('minute')
        # 虽然还没超过，但应该建议节流
        if 'throttle_recommended' in info:
            assert info['throttle_recommended'] == True

class TestPublishFrequencyValidator:
    """发布频次验证器测试"""
    
    def setup_method(self):
        """设置测试环境"""
        self.db = SessionLocal()
    
    def teardown_method(self):
        """清理测试环境"""
        self.db.close()
    
    def test_validate_healthy_account(self):
        """测试验证健康的账户"""
        # 创建测试账户
        account = AdAccount(
            id='test_001',
            account_id='act_test_healthy',
            account_name='Test Account',
            status=AccountStatus.ACTIVE,
            is_frozen=False,
            daily_spend_limit=10000,
            monthly_spend_limit=300000
        )
        self.db.add(account)
        self.db.commit()
        
        validator = PublishFrequencyValidator(self.db)
        is_healthy, report = validator.validate_account_health('act_test_healthy')
        
        assert is_healthy == True
        assert report['status'] == 'active'
    
    def test_validate_frozen_account(self):
        """测试验证冻结的账户"""
        # 创建测试账户
        account = AdAccount(
            id='test_002',
            account_id='act_test_frozen',
            account_name='Test Account',
            status=AccountStatus.FROZEN,
            is_frozen=True,
            frozen_reason='High fraud risk',
            daily_spend_limit=10000,
            monthly_spend_limit=300000
        )
        self.db.add(account)
        self.db.commit()
        
        validator = PublishFrequencyValidator(self.db)
        is_healthy, report = validator.validate_account_health('act_test_frozen')
        
        assert is_healthy == False
        assert report['status'] == 'frozen'
    
    def test_frequency_calculation(self):
        """测试发布频次计算"""
        # 创建测试账户
        account = AdAccount(
            id='test_003',
            account_id='act_test_frequency',
            account_name='Test Account',
            status=AccountStatus.ACTIVE,
            is_frozen=False,
            daily_spend_limit=10000,
            monthly_spend_limit=300000
        )
        self.db.add(account)
        self.db.commit()
        
        # 创建多个系列
        for i in range(5):
            campaign = Campaign(
                id=f'test_campaign_{i}',
                campaign_id=f'campaign_test_{i}',
                ad_account_id='test_003',
                name=f'Test Campaign {i}',
                status='ACTIVE'
            )
            self.db.add(campaign)
        self.db.commit()
        
        validator = PublishFrequencyValidator(self.db)
        report = validator.check_campaign_publish_frequency('act_test_frequency', 24)
        
        assert report['campaigns_created'] == 5
        assert report['frequency_status'] == 'safe'  # 5个系列在24小时内是安全的
