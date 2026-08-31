# 项目启动流程

本文档说明 `fb-ads`（Meta Ads 批量投流系统）从零开始的完整启动流程。

架构总览：

```
用户 → Web 前端(5173) → FastAPI(8000) → PostgreSQL
                             │
                             ├─ Redis → Celery Worker（执行异步任务）
                             │            │
                             │            └→ MetaAdsService → Meta API
                             └─ Celery Beat（定时触发，独立进程）
```

需要同时运行的进程共 **4 个**：API、Worker、Beat、前端。

---

## 1. 环境依赖

| 组件 | 版本要求 | 说明 |
|---|---|---|
| Python | 3.10+ | 后端运行时 |
| PostgreSQL | 12+ | 主数据库（JSONB 字段依赖） |
| Redis | 6+ | Celery Broker / 结果后端 / 限流计数 |
| Node.js | 18+ | 前端构建（可选，仅开发前端时需要） |

Windows 环境说明：Redis 可由 WSL 提供（`localhost:6379`，Windows 侧可直接访问）。

---

## 2. 安装依赖

```bash
# 后端
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # Linux/Mac
pip install -r requirements.txt

# 前端（可选）
cd frontend
npm install
```

---

## 3. 配置环境变量

```bash
cp .env.example .env
```

必填项：

| 变量 | 说明 |
|---|---|
| `SECRET_KEY` | **极其重要**：JWT 签名 + Access Token 加密密钥。上线后不可随意更改，否则已加密凭据无法解密 |
| `DB_*` | 数据库连接参数 |
| `REDIS_*` | Redis 连接参数 |
| `CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND` | 默认 `redis://localhost:6379/0` `/1` |
| `FB_APP_ID` / `FB_APP_SECRET` | Meta 应用凭据 |

定时调度相关（供 Celery Beat 使用）：

```env
SCHEDULE_FETCH_INSIGHTS_CRON=0 */2 * * *    # 每 2 小时拉取洞察
SCHEDULE_RISK_CHECK_CRON=0 * * * *          # 每小时风控检查
SCHEDULE_REPORT_DAILY_CRON=0 8 * * *        # 每天 8 点日报告
SCHEDULE_REPORT_WEEKLY_CRON=0 9 * * 1       # 每周一 9 点周报告
```

CORS（前端独立部署时需要）：

```env
CORS_ORIGINS=http://localhost:3000,http://localhost:5173
```

---

## 4. 初始化数据库

数据库表结构由 **Alembic** 管理（不再依赖运行时 `create_all`）。

```bash
# 升级到最新版本
alembic upgrade head

# 查看当前版本 / 历史
alembic current
alembic history
```

> **Windows / PowerShell 提示**
>
> 若提示 `alembic : The term 'alembic' is not recognized...`，说明虚拟环境未激活，
> `alembic.exe` 所在目录（`venv\Scripts`）不在 PATH 中。二选一：
>
> ```powershell
> # 方式一：激活虚拟环境（注意 PowerShell 需允许脚本执行）
> .\venv\Scripts\Activate.ps1
> alembic upgrade head
>
> # 方式二：不激活，直接用 venv 的解释器调用（推荐，最稳妥）
> .\venv\Scripts\python.exe -m alembic upgrade head
> ```
>
> 本文件中所有 `alembic ...`、`celery ...`、`python ...` 命令均可按方式二改写。

### 存量库接入迁移

如果你的库是早期通过 `init_db()`（SQLAlchemy `create_all`）建的表，没有 Alembic 版本记录：

```bash
# 方式一：库里还没有新表（campaign_templates 等 8 张）
alembic upgrade head          # 直接补齐新表

# 方式二：库里已有新表（例如曾跑过 init_db），仅需补记版本号
alembic stamp head
```

> 判断依据：`SELECT * FROM campaign_templates LIMIT 1;` 能查到说明表已建。

### 生成新迁移

模型变更后：

```bash
alembic revision --autogenerate -m "描述变更"
alembic upgrade head
```

---

## 5. 迁移存量明文 Token（重要）

历史版本把 BM 的 Access Token 明文存在 `meta_accounts.access_token`。
按设计文档第 9 节的要求，Token 应加密存放在 `credentials` 表。

```bash
# 第 1 步：预览，确认影响范围（不写库）
python scripts/migrate_tokens_to_credentials.py --dry-run

# 第 2 步：执行加密迁移（明文字段暂保留，确保可回退）
python scripts/migrate_tokens_to_credentials.py

# 第 3 步：验证业务正常后，清空明文列
python scripts/migrate_tokens_to_credentials.py --purge
```

注意事项：

- 加密密钥由 `SECRET_KEY` 派生，**迁移前请确认 `SECRET_KEY` 已设为稳定值并备份**。
- 脚本幂等：已有 ACTIVE 凭据的 BM 会自动跳过；`--force` 可强制新增。
- `--purge` 只清空 `access_token`；`app_secret` 建议改用环境变量 `FB_APP_SECRET` 注入。

---

## 6. 启动服务

### 6.1 手动启动（4 个终端）

```bash
# 终端 1：API
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# 终端 2：Celery Worker（执行异步任务）
celery -A celery_app worker --loglevel=info --concurrency=4
# Windows 上 prefork 多进程会报 WinError 5，改用：
celery -A celery_app worker --loglevel=info --pool=solo

# 终端 3：Celery Beat（定时触发任务，必须启动）
celery -A celery_app beat --loglevel=info

# 终端 4：前端（可选）
cd frontend && npm run dev
```

> **Beat 与 Worker 必须成对启动**：Beat 只负责按 cron 把任务投递到队列，
> 没有 Worker 时任务会一直堆积在队列中不被执行。

等价的 CLI 命令：

```bash
python cli.py run-api
python cli.py run-worker     # 自动检测平台: Windows 用 --pool=solo，其他用 prefork(4)
python cli.py start-beat
```

### 6.2 Windows 一键脚本

双击根目录 `.bat` 脚本即可：

| 脚本 | 作用 |
|---|---|
| `start_all_win.bat` | 一键启动全部：API + Worker + Beat + 前端（4 个窗口） |
| `start_fb_ads.bat` | 仅启动 API |
| `start_celery_win.bat` | 仅启动 Worker（Windows 用 `--pool=solo`） |
| `start_beat_win.bat` | 仅启动 Beat 定时调度 |
| `start_frontend_win.bat` | 仅启动前端 |

---

## 7. 验证启动

```bash
# 系统状态（数据库连接、Redis、调度配置）
python cli.py status

# API 健康检查
curl http://localhost:8000/health

# 创建管理员（首次）
python cli.py create-admin
```

浏览器访问：

- 前端：http://localhost:5173
- API 文档：http://localhost:8000/docs

---

## 8. 首次投放验证流程

1. 创建 BM 主账号：`/api/v1/meta-accounts`
2. 添加广告账户（会校验账户归属该 BM）：`/api/v1/accounts`
3. 创建投放模板：`/api/v1/templates`
4. 提交批量投放：`POST /api/v1/jobs/campaign-create`
5. 轮询任务进度：`GET /api/v1/jobs/{job_id}`

前端对应页面：**批量投放**（选模板 → 选账户 → 提交 → 实时进度）。

---

## 9. 常见问题

**Q：定时任务没有执行？**
A：检查 Beat 进程是否启动（Windows 下看是否有 `FB-Ads Beat` 窗口）。
Beat 与 Worker 必须同时运行。

**Q：任务一直卡在 PENDING？**
A：Worker 未启动，或 Redis 不可达。执行 `python cli.py status` 检查 Redis 连接。

**Q：Token 解密失败 / 凭据报 INVALID？**
A：`SECRET_KEY` 发生过变更，导致历史密文无法解密。需重新录入凭据。

**Q：前端请求 401？**
A：全局鉴权中间件保护了所有 `/api/` 路径（登录接口除外），
请求需携带 `Authorization: Bearer <token>`。

**Q：alembic 报 `UnicodeDecodeError: 'gbk' codec`？**
A：`alembic.ini` 必须保持 ASCII 编码（不含中文），
Windows 下 configparser 按 GBK 读取配置文件。

**Q：Windows 下 Worker 报 `WinError 5 拒绝访问`？**
A：celery 5.x 的 prefork 进程池在 Windows 有兼容问题，使用 `--pool=solo`。
