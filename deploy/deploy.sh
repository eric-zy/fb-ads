#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [[ ! -f .env ]]; then
  echo "[deploy] missing deploy/.env; copy .env.example and fill production values first" >&2
  exit 1
fi
if grep -Eiq 'change-me|replace-with|example\.com|your-secret|your_app|your_access' .env; then
  echo "[deploy] placeholder value detected in deploy/.env" >&2
  exit 1
fi

compose=(docker compose -f docker-compose.yml)
if [[ -f ../frontend/dist/index.html ]]; then
  echo "[deploy] using prebuilt frontend/dist static assets"
  compose+=( -f docker-compose.frontend-dist.yml )
else
  echo "[deploy] frontend/dist/index.html not found; frontend image will build from source"
fi

# API/Worker/Beat 共用 fbads-api:latest，只构建一次，避免三个服务并行生成重复镜像。
"${compose[@]}" build api nginx

echo "[deploy] 校验 SaaS 运行配置：Connector / OSS / 生产密钥..."
"${compose[@]}" run --rm --no-deps api python -c 'from config.settings import settings; settings.validate_runtime_config(); print("runtime config ok")'

echo "[deploy] 校验 API 容器媒体工具：ffprobe..."
"${compose[@]}" run --rm api ffprobe -version >/dev/null

"${compose[@]}" up -d --wait db redis

# upgrade head 是幂等操作：已执行的版本会跳过，未执行的版本会按链路补齐。
# 这里不依赖 current 的文本输出判断是否需要迁移，避免连接异常、多个 head
# 或 Alembic 输出格式变化导致误判并漏执行迁移。
echo "[deploy] 迁移前数据库版本："
"${compose[@]}" run --rm api python -m alembic current || {
  echo "[deploy] 无法读取数据库当前版本，终止部署。" >&2
  exit 1
}

echo "[deploy] 检查投放实例重复映射："
"${compose[@]}" run --rm api python scripts/check_reconciliation_duplicates.py

echo "[deploy] 执行数据库迁移：python -m alembic upgrade head"
"${compose[@]}" run --rm api python -m alembic upgrade head

echo "[deploy] 校验数据库当前版本："
"${compose[@]}" run --rm api python -m alembic current
echo "[deploy] 数据库迁移完成。"

# 数据库结构确认后再切换 API/Worker/Beat，避免出现 ORM 已更新而表结构未更新的窗口。
echo "[deploy] 启动 API/Worker/Beat/Nginx，并等待 API 健康检查..."
"${compose[@]}" up -d --wait --force-recreate api celery-worker celery-beat nginx

echo "[deploy] 等待 API 就绪：http://127.0.0.1:8000/health"
api_ready=false
for attempt in $(seq 1 30); do
  if curl --noproxy '*' --ipv4 --fail --silent --show-error --max-time 5 \
      http://127.0.0.1:8000/health >/dev/null; then
    api_ready=true
    break
  fi
  echo "[deploy] API 尚未就绪 ($attempt/30)，等待 2s..."
  sleep 2
done
if [[ "$api_ready" != true ]]; then
  echo "[deploy] API 健康检查失败，最近日志：" >&2
  "${compose[@]}" logs --tail=100 api >&2 || true
  exit 1
fi

echo "[deploy] 等待 Nginx 网页入口：http://127.0.0.1:8094/"
web_ready=false
for attempt in $(seq 1 15); do
  if curl --noproxy '*' --ipv4 --fail --silent --show-error --max-time 5 \
      http://127.0.0.1:8094/ >/dev/null; then
    web_ready=true
    break
  fi
  echo "[deploy] Nginx 尚未就绪 ($attempt/15)，等待 2s..."
  sleep 2
done
if [[ "$web_ready" != true ]]; then
  echo "[deploy] Nginx 网页入口检查失败，最近日志：" >&2
  echo "[deploy] Nginx 容器状态与端口映射：" >&2
  "${compose[@]}" ps nginx >&2 || true
  "${compose[@]}" port nginx 80 >&2 || true
  nginx_container=$("${compose[@]}" ps -q nginx 2>/dev/null || true)
  if [[ -n "$nginx_container" ]]; then
    echo "[deploy] Nginx 实际健康检查结果：" >&2
    docker inspect --format '{{json .Config.Healthcheck.Test}}' "$nginx_container" >&2 || true
    docker inspect --format '{{range .State.Health.Log}}{{.Start}} exit={{.ExitCode}} {{.Output}}{{end}}' "$nginx_container" >&2 || true
  fi
  "${compose[@]}" logs --tail=100 nginx >&2 || true
  exit 1
fi

echo "[deploy] 校验 Celery Worker 关键任务注册..."
if ! "${compose[@]}" exec -T celery-worker python -c 'import celery_app; required = {"meta.sync_custom_audiences", "credentials.check_expiring"}; registered = set(celery_app.celery_app.tasks); missing = sorted(required - registered); assert not missing, f"missing celery tasks: {missing}"; print("celery task registration ok")'; then
  echo "[deploy] Celery Worker 关键任务未注册，拒绝完成部署。最近日志：" >&2
  "${compose[@]}" logs --tail=100 celery-worker >&2 || true
  exit 1
fi

echo "[deploy] API 和网页入口均已就绪。"

# 默认保留镜像和 BuildKit 缓存，避免下一次部署重新下载 Debian/Python 依赖。
# 确需清理时显式执行：PRUNE_DOCKER_CACHE=1 ./deploy.sh
if [[ "${PRUNE_DOCKER_CACHE:-0}" == "1" ]]; then
  docker image prune -f
  docker builder prune -f
else
  echo "[deploy] 保留 Docker 镜像/构建缓存；如需清理请设置 PRUNE_DOCKER_CACHE=1"
fi

docker system df
