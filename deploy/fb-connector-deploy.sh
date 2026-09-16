#!/usr/bin/env bash
set -Eeuo pipefail

# 海外 Connector 一键部署脚本。
# 只清理明确的部署临时目录、悬空镜像和构建缓存；绝不删除 Docker Volume、数据库文件或 Redis 数据。
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
COMPOSE_FILE="$SCRIPT_DIR/docker-compose.connector-prod.yml"
ENV_FILE="${CONNECTOR_ENV_FILE:-$SCRIPT_DIR/fb-connector.env}"
PROJECT_NAME="${COMPOSE_PROJECT_NAME:-fb-connector}"

cd "$PROJECT_DIR"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "[connector] missing env file: $ENV_FILE" >&2
  echo "[connector] copy deploy/fb-connector.env.example and fill real secrets first" >&2
  exit 1
fi

if grep -Eq 'REPLACE_WITH_|change-me|your_app|example\.com' "$ENV_FILE"; then
  echo "[connector] placeholder value detected in $ENV_FILE" >&2
  exit 1
fi

for command in docker git; do
  command -v "$command" >/dev/null || { echo "[connector] command not found: $command" >&2; exit 1; }
done

compose=(docker compose --project-name "$PROJECT_NAME" --env-file "$ENV_FILE" -f "$COMPOSE_FILE")

echo "[connector] validating compose configuration..."
"${compose[@]}" config --quiet

echo "[connector] stopping legacy deployments only..."
docker compose -f "$SCRIPT_DIR/docker-compose.yml" down --remove-orphans 2>/dev/null || true
docker compose -f "$SCRIPT_DIR/docker-compose.connector.yml" down --remove-orphans 2>/dev/null || true

echo "[connector] cleaning safe deployment fragments..."
find /tmp -maxdepth 1 -type d -name 'fb-ads-connector-deploy-*' -mtime +1 -exec rm -rf -- {} + 2>/dev/null || true
docker image prune -f
docker builder prune -f

echo "[connector] building image..."
"${compose[@]}" build --pull fb-connector

echo "[connector] starting database and redis..."
"${compose[@]}" up -d --wait db redis

echo "[connector] running independent connector migrations..."
"${compose[@]}" run --rm fb-connector alembic -c fb_connector/alembic.ini upgrade head

echo "[connector] starting connector API, worker and beat..."
"${compose[@]}" up -d --force-recreate fb-connector fb-connector-worker fb-connector-beat

echo "[connector] checking service status..."
"${compose[@]}" ps
echo "[connector] health check..."
curl --fail --silent --show-error http://127.0.0.1:8100/internal/health
echo
echo "[connector] deployment complete; volumes were preserved."
