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

echo "[connector] preserving existing web/frontend deployment..."
# Do not run docker-compose.yml down here: that stack owns the public Nginx/Caddy
# entrypoint and its /, /privacy-policy and /terms pages.
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

echo "[connector] starting connector API, general worker, media worker and beat..."
"${compose[@]}" up -d --force-recreate \
  fb-connector fb-connector-worker fb-connector-media-worker fb-connector-beat

echo "[connector] checking service status..."
"${compose[@]}" ps
echo "[connector] health check..."
health_ok=false
for attempt in $(seq 1 30); do
  if curl --fail --silent --show-error --max-time 5 http://127.0.0.1:8100/internal/health; then
    health_ok=true
    echo
    break
  fi
  echo "[connector] health check not ready ($attempt/30), waiting 2s..."
  sleep 2
done
if [[ "$health_ok" != true ]]; then
  echo "[connector] health check failed; recent API logs:" >&2
  "${compose[@]}" logs --tail=100 fb-connector >&2 || true
  exit 1
fi
echo "[connector] deployment complete; volumes were preserved."
