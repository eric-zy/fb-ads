#!/usr/bin/env python
"""
速率限制和发布频次检测的示例和集成指南
"""

from services.rate_limit import RateLimitManager
from services.publish_frequency_validator import PublishFrequencyValidator
from services.fb_client_rate_limit import RateLimitAwareFacebookClient
from core.database import SessionLocal

print("="*60)
print("Facebook 速率限制和发布频次检测示例")
print("="*60)

# ============================================================
# 示例1: 检查API速率限制状态
# ============================================================
print("\n[示例1] 检查API速率限制状态")
print("-" * 60)

account_id = "act_your_account_id"
rate_limiter = RateLimitManager(account_id)
status = rate_limiter.get_status()

print(f"账户: {account_id}")
print(f"每分钟限制: {status['minute']['current_count']}/{status['minute']['limit']}")
print(f"每小时限制: {status['hour']['current_count']}/{status['hour']['limit']}")
print(f"每天限制: {status['day']['current_count']}/{status['day']['limit']}")

# ============================================================
# 示例2: 检查发布频次
# ============================================================
print("\n[示例2] 检查发布频次")
print("-" * 60)

db = SessionLocal()
validator = PublishFrequencyValidator(db)

# 检查过去24小时的发布频次
freq_report = validator.check_campaign_publish_frequency(account_id, 24)

print(f"过去24小时的发布统计:")
print(f"  - 创建系列数: {freq_report.get('campaigns_created', 0)}")
print(f"  - 发布频次状态: {freq_report.get('frequency_status', 'unknown')}")
print(f"  - 推荐限制: {freq_report.get('recommended_limit', 'N/A')}")

if freq_report.get('frequency_status') == 'critical':
    print("  ⚠️  警告: 发布频次过高!")
elif freq_report.get('frequency_status') == 'high_risk':
    print("  ⚠️  注意: 发布频次较高")
elif freq_report.get('frequency_status') == 'warning':
    print("  📌 提示: 发布频次接近限制")

# ============================================================
# 示例3: 获取安全建议
# ============================================================
print("\n[示例3] 获取安全建议")
print("-" * 60)

recommendations = validator.recommend_action(account_id)

print(f"整体状态: {recommendations['overall_status']}")
print(f"建议行动:")

for action in recommendations.get('actions', []):
    print(f"  - [{action['priority'].upper()}] {action['type']}")
    print(f"    原因: {action['reason']}")
    print(f"    消息: {action['message']}")

# ============================================================
# 示例4: 获取安全的发布间隔
# ============================================================
print("\n[示例4] 获取安全的发布间隔")
print("-" * 60)

interval_info = validator.get_safe_publish_interval(account_id)
recommended_interval = interval_info.get('recommended_interval_seconds', 0)

print(f"建议的发布间隔: {recommended_interval:.1f} 秒")
print(f"说明: {interval_info.get('message', 'N/A')}")

if recommended_interval > 0:
    print(f"\n建议在每次API调用之间至少等待 {recommended_interval:.1f} 秒")

# ============================================================
# 示例5: 使用带速率限制的Facebook客户端
# ============================================================
print("\n[示例5] 使用带速率限制的Facebook客户端")
print("-" * 60)

fb_client = RateLimitAwareFacebookClient()

# 安全地获取系列数据（自动处理速率限制）
campaigns = fb_client.get_campaigns_safe(account_id)
print(f"成功获取 {len(campaigns)} 个系列")

for campaign in campaigns[:3]:  # 显示前3个
    print(f"  - {campaign.get('name', 'Unknown')} (ID: {campaign.get('id', 'N/A')})")

# ============================================================
# 示例6: 集成到工作流中
# ============================================================
print("\n[示例6] 集成到工作流中")
print("-" * 60)

print("""
推荐的工作流:

1. 在每次API调用前检查速率限制:
   is_allowed, info = rate_limiter.check_rate_limit('minute')
   if not is_allowed:
       delay = rate_limiter.should_retry(attempt)[1]
       time.sleep(delay)

2. 在批量操作前检查发布频次:
   frequency = validator.check_campaign_publish_frequency(account_id, 24)
   if frequency['frequency_status'] in ['high_risk', 'critical']:
       # 暂停或减缓操作
       pass

3. 定期检查账户健康状况:
   is_healthy, report = validator.validate_account_health(account_id)
   if not is_healthy:
       # 停止所有发布操作
       pass

4. 在部署新功能前获取安全建议:
   recommendations = validator.recommend_action(account_id)
   # 按照建议进行调整
""")

db.close()
print("\n" + "="*60)
print("示例完成")
print("="*60)
