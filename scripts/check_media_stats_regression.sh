#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   MEDIA_STATS_TOKEN='token' ./scripts/check_media_stats_regression.sh \
#     http://127.0.0.1:8094
#
# Optional:
#   MEDIA_STATS_ACCOUNT_ID='internal-account-uuid' ...
#
# Requirements: curl, jq, date.
# This script is read-only and does not create, update, or delete media.

BASE_URL="${1:?SaaS base URL is required}"
TOKEN="${MEDIA_STATS_TOKEN:?set MEDIA_STATS_TOKEN without committing it}"
AUTH=(-H "Authorization: Bearer $TOKEN")
TODAY="$(date -u +%F)"
START_DATE="$(date -u -d '29 days ago' +%F)"

echo "[1/4] overview summary"
OVERVIEW_JSON=$(curl -fsS "${AUTH[@]}" "$BASE_URL/api/v1/media/stats/overview")
jq -e '
  (.asset_count | numbers) and
  (.ready_asset_count | numbers) and
  (.binding_count | numbers) and
  (.ready_binding_count | numbers) and
  (.usage_count | numbers) and
  (.successful_usage_count | numbers) and
  (.failed_usage_count | numbers) and
  (.success_rate | numbers) and
  (.top_assets | arrays)
' <<< "$OVERVIEW_JSON" >/dev/null

echo "[2/4] date-range overview"
RANGE_JSON=$(curl -fsS "${AUTH[@]}" \
  "$BASE_URL/api/v1/media/stats/overview?start_date=$START_DATE&end_date=$TODAY")
jq -e --arg start "$START_DATE" --arg end "$TODAY" '
  .range_start == $start and .range_end == $end and (.usage_count | numbers)
' <<< "$RANGE_JSON" >/dev/null

echo "[3/4] first asset detail statistics"
ASSET_ID=$(curl -fsS "${AUTH[@]}" "$BASE_URL/api/v1/media" | jq -r '.[0].id // empty')
if [[ -z "$ASSET_ID" ]]; then
  echo "no media found; overview checks passed, detail checks skipped"
else
  STATS_JSON=$(curl -fsS "${AUTH[@]}" "$BASE_URL/api/v1/media/$ASSET_ID/stats")
  jq -e '
    (.asset_id | strings) and
    (.usage_count | numbers) and
    (.successful_usage_count | numbers) and
    (.failed_usage_count | numbers) and
    (.by_account | arrays) and
    (.daily | arrays)
  ' <<< "$STATS_JSON" >/dev/null
fi

echo "[4/4] optional account-scoped overview"
if [[ -n "${MEDIA_STATS_ACCOUNT_ID:-}" ]]; then
  ACCOUNT_JSON=$(curl -fsS "${AUTH[@]}" \
    "$BASE_URL/api/v1/media/stats/overview?account_id=$(printf '%s' "$MEDIA_STATS_ACCOUNT_ID" | jq -sRr @uri)")
  jq -e '(.asset_count | numbers) and (.usage_count | numbers) and (.top_assets | arrays)' <<< "$ACCOUNT_JSON" >/dev/null
  echo "account_scope=passed"
else
  echo "account_scope=skipped (set MEDIA_STATS_ACCOUNT_ID to enable)"
fi

echo "media stats regression passed"
