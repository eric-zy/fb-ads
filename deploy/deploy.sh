#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

# API/Worker/Beat 共用 fbads-api:latest，只构建一次，避免三个服务并行生成重复镜像。
docker compose build api nginx

docker compose up -d --wait db redis

# upgrade head 是幂等操作：已执行的版本会跳过，未执行的版本会按链路补齐。
# 这里不依赖 current 的文本输出判断是否需要迁移，避免连接异常、多个 head
# 或 Alembic 输出格式变化导致误判并漏执行迁移。
echo "[deploy] 迁移前数据库版本："
docker compose run --rm api alembic current || {
  echo "[deploy] 无法读取数据库当前版本，终止部署。" >&2
  exit 1
}

echo "[deploy] 执行数据库迁移：alembic upgrade head"
docker compose run --rm api alembic upgrade head

echo "[deploy] 校验数据库当前版本："
docker compose run --rm api alembic current
echo "[deploy] 数据库迁移完成。"

# 数据库结构确认后再切换 API/Worker/Beat，避免出现 ORM 已更新而表结构未更新的窗口。
docker compose up -d --force-recreate api celery-worker celery-beat nginx

# 仅清理不再被容器使用的旧镜像和构建缓存，不触碰任何 Volume。
docker image prune -f
docker builder prune -f

docker system df
