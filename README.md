# Facebook 广告自动化系统

## 🎯 项目概述

基于Facebook Python Business SDK的生产级广告自动化系统，包含以下核心功能：

- **广告管理**: 系列、广告组、广告的同步与管理
- **风险控制**: 多维度风险检测与自动化处理
- **数据分析**: 性能趋势分析、异常检测、欺诈评分
- **定时任务**: Celery + APScheduler实现的任务调度系统
- **报表系统**: 日报、周报、自动通知
- **API服务**: FastAPI提供的REST API接口

## 📋 项目结构

```
fb-ads-automation/
├── config/              # 配置管理
│   └── settings.py      # 应用配置
├── core/                # 核心模块
│   ├── database.py      # 数据库连接
│   ├── redis_client.py  # Redis客户端
│   └── logger.py        # 日志系统
├── models/              # 数据模型
│   ├── ad_account.py    # 账户模型
│   ├── campaign.py      # 系列模型
│   ├── ad_group.py      # 广告组模型
│   ├── ad.py            # 广告模型
│   ├── insights.py      # 洞察数据模型
│   └── risk_control.py  # 风控模型
├── services/            # 业务服务层
│   ├── fb_client.py     # Facebook API客户端
│   ├── ads_manager.py   # 广告管理服务
│   ├── risk_detector.py # 风险检测服务
│   ├── analytics.py     # 数据分析引擎
│   └── notifications.py # 通知服务
├── tasks/               # 异步任务
│   ├── celery_tasks.py  # Celery任务定义
│   ├── scheduler.py     # 任务调度器
│   └── __init__.py
├── main.py              # FastAPI应用入口
├── celery_app.py        # Celery应用配置
├── celery_worker.py     # Celery工作进程
├── cli.py               # CLI命令
├── .env.example         # 环境变量示例
└── requirements.txt     # 项目依赖
```

## 🚀 快速开始

### 1. 环境准备

```bash
# 克隆项目
git clone <repo-url>
cd fb-ads-automation

# 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Linux/Mac
# 或
venv\Scripts\activate  # Windows

# 安装依赖
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
# 复制示例配置
cp .env.example .env

# 编辑.env文件，填入你的配置
vi .env
```

必需配置：
- `FB_APP_ID`: Facebook应用ID
- `FB_APP_SECRET`: Facebook应用密钥
- `FB_ACCESS_TOKEN`: Facebook访问令牌
- `FB_ACCOUNT_ID`: 广告账户ID
- `DB_*`: 数据库连接参数
- `REDIS_*`: Redis连接参数

### 3. 初始化数据库

```bash
python cli.py init-database
```

### 4. 启动各个组件

#### 方式一：分别启动（开发环境）

```bash
# 终端1: 启动API服务器
python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000

# 终端2: 启动Celery Worker
celery -A celery_app worker --loglevel=info --concurrency=4

# 终端3: 启动任务调度器
python cli.py start-scheduler
```

#### 方式二：使用Docker Compose（生产环境推荐）

```bash
docker-compose up -d
```

### 5. 检查系统状态

```bash
python cli.py status
```

## 📊 核心功能说明

### 1. 广告管理 (`services/ads_manager.py`)

- **同步系列**: `sync_campaigns(account_id)` - 从Facebook同步最新系列数据
- **获取性能**: `get_campaign_performance()` - 获取系列性能指标
- **暂停低效**: `pause_low_performance_campaigns()` - 自动暂停低性能系列
- **获取花费**: `get_account_spend_today()` - 获取今日账户花费

### 2. 风险控制 (`services/risk_detector.py`)

**风险检测**：
- 异常花费检测
- 低质量广告检测
- 欺诈模式检测
- 政策违规检测

**自动化处理**：
- 暂停低效系列
- 冻结高风险账户
- 创建风险事件记录
- 发送风险告警通知

**配置参数**（.env）：
```env
RISK_DAILY_SPEND_LIMIT=10000        # 日花费上限
RISK_DAILY_CTR_THRESHOLD=0.02       # CTR下限
RISK_DAILY_CPC_THRESHOLD=5.0        # CPC上限
RISK_FRAUD_SCORE_THRESHOLD=0.7      # 欺诈评分阈值
RISK_ACCOUNT_FREEZE_DAYS=3          # 冻结天数
```

### 3. 数据分析 (`services/analytics.py`)

- **性能趋势**: `get_account_performance_trend()` - 获取长期性能趋势
- **异常检测**: `detect_spend_anomaly()` - 基于Isolation Forest的异常检测
- **欺诈评分**: `calculate_fraud_score()` - 综合评分模型
- **报表生成**: `generate_daily_report()` / `generate_weekly_report()`

### 4. 定时任务 (`tasks/scheduler.py`)

配置示例（Cron表达式）：

```env
SCHEDULE_FETCH_INSIGHTS_CRON=0 */2 * * *    # 每2小时
SCHEDULE_RISK_CHECK_CRON=0 * * * *          # 每小时
SCHEDULE_REPORT_DAILY_CRON=0 8 * * *        # 每天8点
SCHEDULE_REPORT_WEEKLY_CRON=0 9 * * 1       # 每周一9点
```

### 5. 通知服务 (`services/notifications.py`)

支持的通知渠道：
- **邮件**: SMTP邮件通知
- **钉钉**: DingTalk Webhook通知
- **Slack**: Slack Webhook通知

## 🔌 API文档

### 基础URL
`http://localhost:8000`

### 账户管理API

#### 同步系列
```
POST /api/v1/accounts/{account_id}/sync

Response:
{
  "status": "success",
  "account_id": "act_xxx",
  "created": 5,
  "updated": 3
}
```

#### 获取今日花费
```
GET /api/v1/accounts/{account_id}/spend-today

Response:
{
  "account_id": "act_xxx",
  "spend": 1234.56,
  "currency": "USD"
}
```

### 风控API

#### 检查账户风险
```
POST /api/v1/accounts/{account_id}/risk-check

Response:
{
  "status": "success",
  "account_id": "act_xxx",
  "actions_taken": {
    "campaigns_paused": 2,
    "accounts_frozen": 0
  }
}
```

#### 获取风险事件
```
GET /api/v1/accounts/{account_id}/risk-events?limit=50

Response:
{
  "account_id": "act_xxx",
  "events": [
    {
      "id": "risk_xxx",
      "event_type": "unusual_spend",
      "risk_level": "high",
      "title": "异常花费检测",
      "description": "...",
      "is_resolved": false,
      "created_at": "2024-01-01T12:00:00"
    }
  ]
}
```

#### 冻结账户
```
POST /api/v1/accounts/{account_id}/freeze

Body:
{
  "reason": "High fraud risk detected"
}

Response:
{
  "status": "success",
  "account_id": "act_xxx",
  "message": "Account frozen successfully"
}
```

### 数据分析API

#### 获取性能趋势
```
GET /api/v1/accounts/{account_id}/performance?days=30
```

#### 获取欺诈评分
```
GET /api/v1/accounts/{account_id}/fraud-score?window_days=7

Response:
{
  "account_id": "act_xxx",
  "fraud_score": 0.45,
  "risk_level": "medium",
  "threshold": 0.7
}
```

#### 获取日报告
```
GET /api/v1/accounts/{account_id}/daily-report?report_date=2024-01-01
```

#### 获取周报告
```
GET /api/v1/accounts/{account_id}/weekly-report
```

### 任务管理API

#### 提交拉取洞察任务
```
POST /api/v1/tasks/fetch-insights?account_id=act_xxx

Response:
{
  "status": "submitted",
  "task_id": "xxx-xxx-xxx",
  "account_id": "act_xxx"
}
```

#### 获取任务状态
```
GET /api/v1/tasks/{task_id}

Response:
{
  "task_id": "xxx-xxx-xxx",
  "status": "SUCCESS",
  "result": {...},
  "error": null
}
```

## 🛡️ 风控体系详解

### 风险等级
- `LOW`: 低风险
- `MEDIUM`: 中风险
- `HIGH`: 高风险
- `CRITICAL`: 严重风险

### 风险事件类型
- `UNUSUAL_SPEND`: 异常花费
- `LOW_QUALITY`: 低质量广告
- `HIGH_FRAUD`: 高欺诈风险
- `ACCOUNT_FROZEN`: 账户冻结
- `POLICY_VIOLATION`: 政策违规
- `SUSPICIOUS_PATTERN`: 可疑模式

### 风险评分模型

欺诈评分计算：
```python
fraud_score = (anomaly_score * 0.8) + (quality_ratio * 0.2)
```

- **异常得分** (80%): 基于Isolation Forest的花费异常检测
- **质量比例** (20%): 低质量广告占比

### 自动化处理流程

```
风险检测
  ↓
评分计算
  ↓
阈值判断
  ↓
自动化处理
  ├─ 暂停系列 (High)
  ├─ 冻结账户 (Critical)
  └─ 发送告警
  ↓
事件记录
  ↓
人工审核
```

## 📈 数据模型关系

```
AdAccount (账户)
  ├─ Campaign (系列)
  │  ├─ AdGroup (广告组)
  │  │  └─ Ad (广告)
  │  │     └─ AdInsight (广告洞察)
  │  └─ CampaignInsight (系列洞察)
  ├─ AccountInsight (账户洞察)
  └─ RiskEvent (风险事件)
```

## 🔧 开发指南

### 添加新的风控规则

```python
# services/risk_detector.py
def check_custom_rule(self, account_id: str) -> bool:
    """自定义风控规则"""
    # 实现检测逻辑
    pass
```

### 添加新的任务

```python
# tasks/celery_tasks.py
@shared_task(bind=True, max_retries=3)
def my_custom_task(self, account_id: str):
    """自定义任务"""
    # 实现任务逻辑
    pass
```

### 添加新的API端点

```python
# main.py
@app.get("/api/v1/custom/endpoint")
async def custom_endpoint(db: Session = Depends(get_db)):
    """自定义端点"""
    # 实现端点逻辑
    pass
```

## 📝 日志

日志输出位置：`logs/app.log`

日志格式：
- **控制台**: 文本格式，便于实时监控
- **文件**: JSON格式，便于日志分析

## 🐳 Docker部署

```yaml
# docker-compose.yml
version: '3.8'
services:
  postgres:
    image: postgres:14
    environment:
      POSTGRES_DB: fb_ads_db
      POSTGRES_PASSWORD: password
  
  redis:
    image: redis:7
  
  api:
    build: .
    command: python -m uvicorn main:app --host 0.0.0.0 --port 8000
    ports:
      - "8000:8000"
    depends_on:
      - postgres
      - redis
  
  worker:
    build: .
    command: celery -A celery_app worker --loglevel=info
    depends_on:
      - postgres
      - redis
  
  scheduler:
    build: .
    command: python cli.py start-scheduler
    depends_on:
      - postgres
      - redis
```

## 🤝 贡献指南

1. Fork项目
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启Pull Request

## 📄 许可

MIT License

## 📧 联系方式

- 项目维护者: eric-zy
- 问题反馈: GitHub Issues

---

**最后更新**: 2024年
