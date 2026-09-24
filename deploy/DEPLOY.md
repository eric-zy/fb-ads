# FB-Ads 线上 Docker 部署文档（CentOS，0 → 1）

面向一台全新 CentOS 服务器的完整部署流程。照做即可起服务。

---

## 0. 架构概览

```
                 ┌───────────┐
   用户 ──80/443──│  nginx    │  前端静态 + 反代 /api、/uploads
                 └─────┬─────┘
                       │
              ┌────────┴────────┐
              │                 │
        ┌─────▼─────┐    ┌──────▼──────┐
        │  api       │    │ celery-     │
        │ (uvicorn)  │    │ worker/beat │
        └─────┬──────┘    └──────┬──────┘
              │                  │
        ┌─────┴──────────────────┴─────┐
        │ redis  ◄── broker/backend/限流 │
        └────────────────────────────────┘
              │
        ┌─────▼─────┐
        │ postgres  │  业务数据
        └───────────┘
```

| 服务 | 镜像 | 说明 |
|---|---|---|
| nginx | 自构建（多阶段 node build + nginx） | 80 端口，托管前端 + 反代后端 |
| api | 自构建（python:3.12-slim + ffmpeg/ffprobe） | uvicorn main:app |
| celery-worker | 同 api 镜像 | `celery -A celery_app worker` |
| celery-beat | 同 api 镜像 | `celery -A celery_app beat` 定时调度 |
| redis | redis:7-alpine | broker + result backend + 限流 |
| postgres | postgres:16-alpine | 主数据库 |

部署文件位置：`deploy/`（Dockerfile、docker-compose.yml、nginx.conf、.env.example）。

---

## 1. 服务器准备（CentOS 7/8/9 Stream）

### 1.1 系统更新
```bash
sudo yum update -y            # CentOS 7
# CentOS 8/9 用：sudo dnf update -y
sudo yum install -y git curl wget vim tar
```

### 1.2 安装 Docker
官方一键脚本（最省事）：
```bash
curl -fsSL https://get.docker.com | sudo bash
sudo systemctl enable --now docker
docker --version && docker compose version   # 验证
```

> CentOS 7 默认装的 docker 可能不带 compose v2。若 `docker compose version` 报错，手动装插件：
> ```bash
> sudo mkdir -p /usr/libexec/docker/cli-plugins
> sudo curl -fsSL -o /usr/libexec/docker/cli-plugins/docker-compose \
>   https://github.com/docker/compose/releases/download/v2.24.0/docker-compose-linux-x86_64
> sudo chmod +x /usr/libexec/docker/cli-plugins/docker-compose
> ```

### 1.3 防火墙放行（仅 80/443）
```bash
sudo firewall-cmd --permanent --add-service=http
sudo firewall-cmd --permanent --add-service=https
sudo firewall-cmd --reload
```

> 数据库、Redis **不对外暴露**（compose 未映射端口），仅在 docker 内网通信。

### 1.4 时间同步（Celery 定时任务依赖准确时间）
```bash
sudo timedatectl set-timezone Asia/Singapore
sudo systemctl enable --now chronyd 2>/dev/null || sudo systemctl enable --now crond
```

### 1.5 创建部署目录
```bash
sudo mkdir -p /opt/fb-ads
sudo chown $USER:$USER /opt/fb-ads
```

---

## 2. 上传代码

把项目代码传到 `/opt/fb-ads`（不含 `venv/`、`venv_broken_wsl/`、`node_modules/`、`dist/`、`logs/`、`__pycache__/`，镜像构建会自带）。

本地打包（在开发机执行）：
```bash
cd /e/workSpace
tar --exclude='fb-ads/venv' --exclude='fb-ads/venv_broken_wsl' \
    --exclude='fb-ads/frontend/node_modules' --exclude='fb-ads/frontend/dist' \
    --exclude='fb-ads/logs' --exclude='fb-ads/__pycache__' \
    --exclude='*.pyc' \
    -czf fb-ads.tar.gz fb-ads
scp fb-ads.tar.gz user@<服务器IP>:/tmp/
```

服务器解压：
```bash
cd /opt
tar -xzf /tmp/fb-ads.tar.gz
mv fb-ads fb-ads      # 若已存在则覆盖
ls /opt/fb-ads/deploy/    # 应见 Dockerfile / docker-compose.yml / .env.example
```

> 也可用 `git clone` 拉仓库，前提是代码已托管。

---

## 3. 配置 .env

```bash
cd /opt/fb-ads/deploy
cp .env.example .env
vim .env
```

**必改项**（生产强要求）：
```ini
SECRET_KEY=<用 openssl rand -hex 32 生成>
DB_PASSWORD=<强密码>
REDIS_PASSWORD=<强密码>
CELERY_BROKER_URL=redis://:你的REDIS_PASSWORD@redis:6379/0
CELERY_RESULT_BACKEND=redis://:你的REDIS_PASSWORD@redis:6379/1
CORS_ORIGINS=http://49.232.238.163:8094     # 当前 IP 直连地址
FB_ACCESS_MODE=connector
FB_CONNECTOR_BASE_URL=<海外 Connector 地址>
FB_CONNECTOR_SIGNING_KEY=<与海外 Connector 一致>
CONNECTOR_SERVICE_TOKEN=<与海外 Connector 一致>
SAAS_CALLBACK_BASE_URL=<国内 SaaS 回调地址>
FRONTEND_BASE_URL=http://49.232.238.163:8094
ADS_OSS_ACCESS_KEY_ID=<阿里云 RAM AccessKey ID>
ADS_OSS_ACCESS_KEY_SECRET=<阿里云 RAM AccessKey Secret>
ADS_OSS_BUCKET=q8picaaa
ADS_OSS_REGION=cn-beijing
```

> 注意：设了 REDIS_PASSWORD 后，`CELERY_BROKER_URL` 与 `CELERY_RESULT_BACKEND` 也要带密码，格式 `redis://:密码@redis:6379/0`。
> Connector 模式下 Meta App Secret、OAuth 回调和 Meta Access Token 只配置在海外 Connector，国内 SaaS 不再配置 `FB_ACCESS_TOKEN`。
> 当前素材服务强制使用阿里云 OSS，至少要配置 `ADS_OSS_ACCESS_KEY_ID`、`ADS_OSS_ACCESS_KEY_SECRET`、`ADS_OSS_BUCKET`、`ADS_OSS_REGION`。

大文件素材使用 OSS Multipart 浏览器直传：`OSS_MULTIPART_THRESHOLD_BYTES` 控制切换阈值，
`OSS_MULTIPART_PART_SIZE_BYTES` 控制分片大小（不得小于 5MiB）。默认均为 16MiB；前端最多并发上传 4 个分片，
单片失败会自动重试，服务端在合并前会从 OSS 查询已上传分片。
Worker 每 5 分钟对账超时上传会话：完整分片会自动合并，已过期的 Multipart 会话会执行 Abort，
避免浏览器关闭后遗留 OSS 临时分片；建议同时在 OSS Bucket 配置“未完成 Multipart Upload”生命周期规则作为兜底。

Connector 媒体 Worker 会将已校验的素材按 SHA256 短期缓存；同一素材跨广告账户再次投放时，
会通过 Redis 内容锁避免并发重复下载。`CONNECTOR_MEDIA_CONTENT_LOCK_TTL` 控制锁租期，
`CONNECTOR_MEDIA_CONTENT_LOCK_WAIT` 控制等待其他 Worker 完成下载的最长时间。

`FB_VIDEO_FILE_URL_UPLOAD=true` 时，所有视频任务优先让 Meta 直接拉取 OSS 签名 URL。Meta 明确拒绝远程 URL 时自动回退到本地分片，
超时或限流不会盲目回退，以避免远端已接收后重复创建视频。
`FB_VIDEO_FILE_URL_UPLOAD_ACCOUNTS` 保持为空即可覆盖全部账户；任务状态中的
`upload_mode` 会记录 `DIRECT_URL`、`RESUMABLE` 或 `RESUMABLE_FALLBACK`。

生产 Connector 会将 `/tmp/fb-connector-media/cache` 挂载到 `connector_media_cache` 持久卷，
Worker 重启后仍可按 SHA256 复用已校验素材；临时下载文件仍保留在 3GiB tmpfs 中。

生成密钥：
```bash
openssl rand -hex 32
```

---

## 4. 构建镜像并启动

```bash
cd /opt/fb-ads/deploy
docker compose build          # 首次构建约 5-10 分钟（装 pandas/scikit-learn）
docker compose up -d          # 后台启动所有服务
docker compose ps             # 查看状态，应全部 Up
```

期望输出（示例）：
```
NAME                   IMAGE             STATUS
fb-ads-db-1            postgres:16       Up (healthy)
fb-ads-redis-1         redis:7           Up
fb-ads-api-1           fbads-api         Up
fb-ads-celery-worker-1 fbads-api         Up
fb-ads-celery-beat-1   fbads-api         Up
fb-ads-nginx-1         fbads-nginx       Up
```

---

## 5. 初始化数据库与管理员

### 5.1 跑数据库迁移
生产部署脚本会自动执行幂等迁移：每次部署都会运行 `python -m alembic upgrade head`，已执行的版本会自动跳过，未执行的版本按链路补齐。迁移成功后才切换 API、Worker 和 Beat，避免代码与表结构不一致。

数据库迁移统一由 `deploy/deploy.sh` 自动执行。脚本会启动并等待 PostgreSQL 健康检查，重新构建 API 镜像以带入最新迁移文件，检查迁移前版本，执行 `python -m alembic upgrade head`，再输出迁移后的当前版本。任一步失败都会停止，不会继续重启业务容器。

API/Worker 共用的后端镜像已内置 `ffmpeg`，其中包含 `ffprobe`，用于服务端解析视频尺寸、比例和时长。部署脚本会在迁移前执行 `ffprobe -version` 校验。

仅在排障时手动执行：
```bash
docker compose up -d db redis
docker compose run --rm api python -m alembic upgrade head
docker compose run --rm api python -m alembic current
```

包含投放实例幂等约束的版本会在迁移前检查本地 Campaign/AdSet/Ad 映射是否存在重复；
检查失败时部署会停止，不会重启 API、Worker 或 Beat。处理重复映射后再重新执行部署：

```bash
docker compose run --rm api python scripts/check_reconciliation_duplicates.py
```

> 若 `alembic` 提示找不到，改用项目的初始化命令：
> ```bash
> docker compose exec api python cli.py init-database
> ```

### 5.2 创建管理员账户
```bash
docker compose exec api python cli.py create-admin \
    --email admin@your-domain.com \
    --password your-strong-password
```

---

## 6. 验证

```bash
# 健康检查
curl http://localhost/api/v1/auth/login -X POST \
    -H "Content-Type: application/json" \
    -d '{"email":"admin@your-domain.com","password":"your-strong-password"}'
# 返回 access_token 即成功

# 浏览器打开
http://<服务器IP>          # 应见登录页
```

日志排查：
```bash
docker compose logs -f api
docker compose logs -f celery-worker
docker compose logs -f nginx
```

### 6.1 Meta 自定义受众同步验收

自定义受众同步由国内 API 入队、Celery Worker 执行，必须同时确认 API 与 Worker 使用同一套 Redis Broker/Result Backend。

```bash
# 1. 确认 Worker 已注册任务
docker compose exec celery-worker python -c "import celery_app; assert 'meta.sync_custom_audiences' in celery_app.celery_app.tasks; print('meta.sync_custom_audiences registered')"

# 2. 触发同步后，使用返回的 task_id 查询状态
curl -H "Authorization: Bearer <access_token>" \
  -X POST http://localhost/api/v1/meta-audiences/<account_pk>/sync

curl -H "Authorization: Bearer <access_token>" \
  http://localhost/api/v1/tasks/<task_id>

# 3. 按任务名过滤 Worker 日志
docker compose logs --tail=200 celery-worker | grep "meta_audiences"
```

验收状态：`PENDING → STARTED → SUCCESS`；Meta/Connector 请求失败时应进入 `RETRY`，达到重试上限后为 `FAILURE`。重复点击同一账户的同步按钮，在已有活动任务期间应返回 `ALREADY_QUEUED`，不会新增并发任务。

---

## 7. HTTPS（暂不部署）

> 当前先用 IP 直接 HTTP 访问：浏览器打开 `http://<服务器IP>` 即可。
> 待有域名后再按本节启用 HTTPS。

### 方案 A：Let's Encrypt（有域名 + 公网可达）

```bash
# 装 certbot
sudo dnf install -y epel-release && sudo dnf install -y certbot
# 先停 nginx 释放 80
docker compose stop nginx
# 申请证书（替换 your-domain.com）
sudo certbot certonly --standalone -d your-domain.com
# 证书在 /etc/letsencrypt/live/your-domain.com/

# 挂载证书到 nginx：修改 docker-compose.yml 的 nginx 服务
#   ports: ["80:80", "443:443"]
#   volumes:
#     - /etc/letsencrypt/live/your-domain.com:/etc/letsencrypt/live/your-domain.com:ro
#     - /etc/letsencrypt/archive:/etc/letsencrypt/archive:ro
```

修改 `deploy/nginx/nginx.conf` 增加 443 server：
```nginx
server {
    listen 443 ssl;
    server_name your-domain.com;

    ssl_certificate     /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;

    client_max_body_size 1g;

    location / {
        root /usr/share/nginx/html;
        try_files $uri $uri/ /index.html;
    }
    location /api/ {
        proxy_pass http://api:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
    location /uploads/ {
        proxy_pass http://api:8000;
    }
}

# 80 跳 443
server {
    listen 80;
    server_name your-domain.com;
    return 301 https://$host$request_uri;
}
```

重启 nginx：
```bash
docker compose up -d --build nginx
```

自动续期（crontab）：
```bash
sudo crontab -e
# 0 3 * * * certbot renew --quiet && docker compose -f /opt/fb-ads/deploy/docker-compose.yml restart nginx
```

### 方案 B：无域名 / 内网
跳过本节，直接用 HTTP。或用自签证书：
```bash
openssl req -x509 -newkey rsa:2048 -nodes -days 365 \
  -keyout selfsigned.key -out selfsigned.crt \
  -subj "/CN=<服务器IP>"
```

---

## 8. 日常运维

### 8.1 查看日志
```bash
docker compose logs -f --tail=100 api
docker compose logs -f --tail=100 celery-worker
docker compose logs -f --tail=100 celery-beat
# 应用日志文件（持久化在 logs volume）
docker compose exec api tail -f /app/logs/app.log
```

### 8.2 重启 / 停止
```bash
docker compose restart api           # 仅重启 API
docker compose restart celery-worker celery-beat
docker compose down                  # 停止全部（数据卷保留）
docker compose up -d                 # 重新启动
```

### 8.3 更新代码（发版）
```bash
cd /opt/fb-ads
git pull   # 或重新上传代码包覆盖

cd deploy
docker compose build api celery-worker celery-beat nginx
docker compose up -d                  # 自动滚动重启变更的服务
docker compose exec api alembic upgrade head   # 若有新迁移
```

### 8.4 数据库备份与恢复
```bash
# 备份
docker compose exec db pg_dump -U $DB_USER $DB_NAME > backup_$(date +%F).sql

# 恢复
cat backup_2026-08-31.sql | docker compose exec -T db psql -U $DB_USER $DB_NAME
```

定时备份（crontab）：
```bash
# 每天凌晨 2 点备份，保留 14 天
0 2 * * * cd /opt/fb-ads/deploy && docker compose exec -T db pg_dump -U fbads fb_ads_db > /backup/fb_$(date +\%F).sql && find /backup -name "fb_*.sql" -mtime +14 -delete
```

### 8.5 进入容器调试
```bash
docker compose exec api bash
docker compose exec db psql -U $DB_USER $DB_NAME
docker compose exec redis redis-cli
```

### 8.6 资源占用
```bash
docker stats                          # 实时
docker compose top                    # 进程
```

---

## 9. 常见问题

### Q1：`docker compose build` 装 pandas/scikit-learn 很慢或失败
国内服务器可配镜像加速：
```bash
sudo mkdir -p /etc/docker
sudo tee /etc/docker/daemon.json <<EOF
{"registry-mirrors":["https://docker.mirrors.ustc.edu.cn"]}
EOF
sudo systemctl restart docker
```
pip 加速：在 `deploy/Dockerfile` 的 `pip install` 后加 `-i https://pypi.tuna.tsinghua.edu.cn/simple`。

### Q2：Celery worker 日志报 `Received unregistered task`
任务模块未注册。确认 `celery_app.py` 末尾的 `import tasks.celery_tasks / tasks.campaign_tasks / tasks.meta_sync_tasks` 正常。重启 worker：
```bash
docker compose restart celery-worker
```

### Q3：登录 401 "邮箱或密码错误"
重新创建 admin：
```bash
docker compose exec api python cli.py create-admin --email admin@your-domain.com --password new-password
```

### Q4：上传文件 413 Request Entity Too Large
nginx 限制。确认 `deploy/nginx/nginx.conf` 有 `client_max_body_size 1g;`（已配），与后端 `MAX_UPLOAD_SIZE` 一致。

### Q5：风控页接口 429
限流命中。Redis 限流计数器可清除：
```bash
docker compose exec redis redis-cli FLUSHDB
```
（仅清当前 db；若限流密码已设，加 `-a 你的REDIS_PASSWORD`）

### Q6：磁盘满（pandas/scikit-learn 镜像较大）
镜像约 1.5-2GB。确保 `/var/lib/docker` 所在分区 ≥ 20GB。清理无用镜像：
```bash
docker image prune -a -f
```

---

## 10. 目录与卷速查

| 路径 | 说明 |
|---|---|
| `/opt/fb-ads/` | 项目代码 |
| `/opt/fb-ads/deploy/.env` | 环境变量 |
| docker volume `pgdata` | Postgres 数据（持久） |
| docker volume `redisdata` | Redis 持久化 |
| docker volume `uploads` | 用户上传素材 |
| docker volume `logs` | 应用日志（/app/logs/app.log） |

查看卷实际位置：
```bash
docker volume inspect fb-ads_pgdata | grep Mountpoint
```

---

## 附：快速一键部署（TL;DR）

```bash
# 1. 装 docker
curl -fsSL https://get.docker.com | sudo bash && sudo systemctl enable --now docker

# 2. 传代码到 /opt/fb-ads（略）

# 3. 配 .env
cd /opt/fb-ads/deploy && cp .env.example .env && vim .env

# 4. 构建启动
docker compose build && docker compose up -d

# 5. 初始化 + 建 admin
docker compose exec api alembic upgrade head
docker compose exec api python cli.py create-admin --email admin@xx.com --password xx

# 6. 验证（浏览器打开 http://<服务器IP>）
curl http://localhost/
```
