#!/usr/bin/env bash
# Read-only OAuth diagnostics. Never print env values, tokens or signatures.
set -Eeuo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="${CONNECTOR_ENV_FILE:-$PROJECT_DIR/deploy/fb-connector.env}"
PROJECT_NAME="${COMPOSE_PROJECT_NAME:-fb-connector}"
if [[ "$ENV_FILE" != /* ]]; then ENV_FILE="$PROJECT_DIR/$ENV_FILE"; fi
if [[ ! -f "$ENV_FILE" ]]; then echo "[oauth-check] missing env file: $ENV_FILE" >&2; exit 1; fi
ENV_FILE="$(cd "$(dirname "$ENV_FILE")" && pwd)/$(basename "$ENV_FILE")"
export CONNECTOR_ENV_FILE="$ENV_FILE"
compose=(docker compose --project-name "$PROJECT_NAME" --env-file "$ENV_FILE" -f "$PROJECT_DIR/deploy/docker-compose.connector-prod.yml")
echo "[oauth-check] selected env file: $ENV_FILE; expected project: $PROJECT_NAME"
docker ps --filter publish=8100 --format 'table {{.ID}}\t{{.Names}}\t{{.Image}}\t{{.Ports}}'
mapfile -t containers < <(docker ps -q --filter label=com.docker.compose.service=fb-connector)
if [[ "${#containers[@]}" == 0 ]]; then echo "[oauth-check] no Compose fb-connector service found; inspect the process/container serving port 8100" >&2; exit 1; fi
python_check='import os, sys, json, hmac, inspect
from config.settings import settings
from fb_connector.api import oauth
model = json.load(sys.stdin)
expected = model["services"]["fb-connector"].get("environment", {}).get("FB_CONNECTOR_SIGNING_KEY") or ""
actual = os.getenv("FB_CONNECTOR_SIGNING_KEY", "")
loaded = settings.FB_CONNECTOR_SIGNING_KEY
present = lambda value: bool(value and value.strip())
result = {
 "compose_key_present": present(expected),
 "container_env_key_present": present(actual),
 "runtime_setting_key_present": present(loaded),
 "compose_matches_container": present(expected) and hmac.compare_digest(expected.encode(), actual.encode()),
 "container_matches_runtime": present(actual) and hmac.compare_digest(actual.encode(), loaded.encode()),
 "authorization_precheck_installed": hasattr(oauth, "_require_receipt_signing_key"),
 "readiness_key_check_installed": hasattr(settings, "missing_connector_config"),
 "configured_meta_callback_uri": settings.FB_OAUTH_REDIRECT_URI,
 "callback_checks_signing_key": "FB_CONNECTOR_SIGNING_KEY" in inspect.getsource(oauth.callback) or "_require_receipt_signing_key" in inspect.getsource(oauth.callback)
}
print(json.dumps(result, ensure_ascii=False, indent=2))'
for container in "${containers[@]}"; do
  docker inspect --format '[oauth-check] container={{.Name}} image={{.Image}} project={{index .Config.Labels "com.docker.compose.project"}} config={{index .Config.Labels "com.docker.compose.project.config_files"}}' "$container"
  "${compose[@]}" config --format json | docker exec -i "$container" python -c "$python_check"
done
echo '[oauth-check] localhost readiness:'
curl --fail --silent --show-error --max-time 10 http://127.0.0.1:8100/internal/ready
echo
echo '[oauth-check] public readiness:'
curl --fail --silent --show-error --max-time 10 https://iornix.com/internal/ready
echo
echo '[oauth-check] no configuration or containers were changed'
