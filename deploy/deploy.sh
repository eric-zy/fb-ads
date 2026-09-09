#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

# API/Worker/Beat 共用 fbads-api:latest，只构建一次，避免三个服务并行生成重复镜像。
docker compose build api nginx
docker compose up -d --force-recreate api celery-worker celery-beat nginx

# 迁移必须在服务更新后执行；失败时保留现场，不清理镜像。
docker compose run --rm api alembic upgrade head

# 仅清理不再被容器使用的旧镜像和构建缓存，不触碰任何 Volume。
docker image prune -f
docker builder prune -f

docker system df
