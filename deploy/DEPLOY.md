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
| api | 自构建（python:3.12-slim） | uvicorn main:app |
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
CORS_ORIGINS=http://<服务器IP>     # 先用 IP 直连，不部署域名
FB_APP_ID/FB_APP_SECRET/FB_ACCESS_TOKEN=<Meta 应用凭据>
```

> 注意：设了 REDIS_PASSWORD 后，`CELERY_BROKER_URL` 与 `CELERY_RESULT_BACKEND` 也要带密码，格式 `redis://:密码@redis:6379/0`。

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
```bash
docker compose exec api alembic upgrade head
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

    client_max_body_size 200m;

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
nginx 限制。确认 `deploy/nginx/nginx.conf` 有 `client_max_body_size 200m;`（已配），与后端 `MAX_UPLOAD_SIZE` 一致。

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
