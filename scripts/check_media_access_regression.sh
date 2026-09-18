#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   MEDIA_OWNER_TOKEN='owner-token' \
#   MEDIA_READER_TOKEN='reader-token' \
#   ./scripts/check_media_access_regression.sh \
#     https://saas.example.com ASSET_ID
#
# Optional:
#   MEDIA_FORBIDDEN_ACCOUNT_ID='account-not-assigned-to-reader' ...
#   MEDIA_OTHER_TENANT_TOKEN='token-from-another-tenant' ...
#
# Requirements: curl, jq.
# This script is read-only: it does not upload, create bindings, retry, update,
# delete, or refresh any asset.

BASE_URL="${1:?SaaS base URL is required}"
ASSET_ID="${2:?asset ID is required}"
OWNER_TOKEN="${MEDIA_OWNER_TOKEN:?set MEDIA_OWNER_TOKEN without committing it}"
READER_TOKEN="${MEDIA_READER_TOKEN:?set MEDIA_READER_TOKEN without committing it}"

owner_auth=(-H "Authorization: Bearer $OWNER_TOKEN")
reader_auth=(-H "Authorization: Bearer $READER_TOKEN")
asset_url="$BASE_URL/api/v1/media/$ASSET_ID"

echo "[1/5] owner can read the asset"
OWNER_ASSET=$(curl -fsS "${owner_auth[@]}" "$asset_url")
jq -e --arg asset_id "$ASSET_ID" '.id == $asset_id' <<< "$OWNER_ASSET" >/dev/null

echo "[2/5] another user in the same tenant can list and read it"
READER_ASSET=$(curl -fsS "${reader_auth[@]}" "$asset_url")
jq -e --arg asset_id "$ASSET_ID" '.id == $asset_id' <<< "$READER_ASSET" >/dev/null
curl -fsS "${reader_auth[@]}" "$BASE_URL/api/v1/media" \
  | jq -e --arg asset_id "$ASSET_ID" 'map(.id) | index($asset_id) != null' >/dev/null

echo "[3/5] another user can obtain a signed download URL"
DOWNLOAD_JSON=$(curl -fsS "${reader_auth[@]}" \
  "$BASE_URL/api/v1/media/$ASSET_ID/download-url?kind=original")
jq -e '.asset_id | strings' <<< "$DOWNLOAD_JSON" >/dev/null
jq -e '.url | strings | length > 0' <<< "$DOWNLOAD_JSON" >/dev/null

echo "[4/5] account bindings are visible only within the reader account scope"
BINDINGS_JSON=$(curl -fsS "${reader_auth[@]}" \
  "$BASE_URL/api/v1/media/$ASSET_ID/bindings")
jq -e 'arrays' <<< "$BINDINGS_JSON" >/dev/null
if [[ -n "${MEDIA_FORBIDDEN_ACCOUNT_ID:-}" ]]; then
  jq -e --arg account_id "$MEDIA_FORBIDDEN_ACCOUNT_ID" \
    'map(select(.ad_account_id == $account_id)) | length == 0' \
    <<< "$BINDINGS_JSON" >/dev/null
  echo "forbidden_binding_scope=passed"
else
  echo "forbidden_binding_scope=skipped (set MEDIA_FORBIDDEN_ACCOUNT_ID to enable)"
fi

echo "[5/5] optional cross-tenant isolation"
if [[ -n "${MEDIA_OTHER_TENANT_TOKEN:-}" ]]; then
  status=$(curl -sS -o /dev/null -w '%{http_code}' \
    -H "Authorization: Bearer $MEDIA_OTHER_TENANT_TOKEN" "$asset_url")
  if [[ "$status" != "404" ]]; then
    echo "expected cross-tenant asset lookup to return 404, got $status" >&2
    exit 1
  fi
  echo "cross_tenant=passed"
else
  echo "cross_tenant=skipped (set MEDIA_OTHER_TENANT_TOKEN to enable)"
fi

echo "media access regression passed"
