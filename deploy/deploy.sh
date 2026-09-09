#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

# API/Worker/Beat 共用 fbads-api:latest，只构建一次，避免三个服务并行生成重复镜像。
docker compose build api nginx

# 先确保数据库已启动，再用刚构建的镜像检查迁移状态。
# 兼容未提供 current --check-heads 的旧版 Alembic：当前版本输出包含
# "(head)" 时视为已是最新，否则执行升级。
docker compose up -d db redis
current_revision="$(docker compose run --rm api alembic current 2>/dev/null || true)"
if printf '%s\n' "$current_revision" | grep -q '(head)'; then
  echo "[deploy] 数据库已是最新版本，跳过迁移。"
else
  echo "[deploy] 检测到待执行迁移，开始升级数据库。"
  # 迁移失败立即退出，API/Worker 不切换到可能不匹配的版本。
  docker compose run --rm api alembic upgrade head
  echo "[deploy] 数据库迁移完成。"
fi

# 数据库结构确认后再切换 API/Worker/Beat，避免出现 ORM 已更新而表结构未更新的窗口。
docker compose up -d --force-recreate api celery-worker celery-beat nginx

# 仅清理不再被容器使用的旧镜像和构建缓存，不触碰任何 Volume。
docker image prune -f
docker builder prune -f

docker system df
