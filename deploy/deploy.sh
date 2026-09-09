#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

# 统一构建一次，API/Worker/Beat 共用同一镜像，避免重复产生镜像层。
docker compose build api celery-worker celery-beat nginx
docker compose up -d --force-recreate api celery-worker celery-beat nginx

# 迁移必须在服务更新后执行；失败时保留现场，不清理镜像。
docker compose run --rm api alembic upgrade head

# 仅清理不再被容器使用的旧镜像和构建缓存，不触碰任何 Volume。
docker image prune -f
docker builder prune -f

docker system df
