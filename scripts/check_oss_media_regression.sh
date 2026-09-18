#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   OSS_TEST_TOKEN='token' ./scripts/check_oss_media_regression.sh \
#     http://127.0.0.1:8094 ACCOUNT_UUID ./sample.png
#
# Requirements: curl, jq, md5sum, sha256sum.
# The script does not delete the uploaded asset.

BASE_URL="${1:?SaaS base URL is required}"
ACCOUNT_ID="${2:?internal account UUID is required}"
FILE_PATH="${3:?local media file is required}"
TOKEN="${OSS_TEST_TOKEN:?set OSS_TEST_TOKEN without committing it}"
MIME_TYPE="${MIME_TYPE:-image/png}"

if [[ ! -f "$FILE_PATH" ]]; then
  echo "file not found: $FILE_PATH" >&2
  exit 1
fi

if [[ "$MIME_TYPE" == video/* ]]; then
  ASSET_TYPE=video
else
  ASSET_TYPE=image
fi

SIZE=$(wc -c < "$FILE_PATH" | tr -d ' ')
MD5=$(md5sum "$FILE_PATH" | awk '{print $1}')
SHA256=$(sha256sum "$FILE_PATH" | awk '{print $1}')
AUTH=(-H "Authorization: Bearer $TOKEN")
JSON_HEADER=(-H 'Content-Type: application/json')

echo "[1/6] create upload session"
SESSION_JSON=$(curl -fsS "${AUTH[@]}" "${JSON_HEADER[@]}" \
  -X POST "$BASE_URL/api/v1/media/upload-sessions" \
  --data "$(jq -cn \
    --arg name "$(basename "$FILE_PATH")" \
    --arg asset_type "$ASSET_TYPE" \
    --arg mime_type "$MIME_TYPE" \
    --argjson size "$SIZE" \
    --arg md5 "$MD5" \
    --arg sha256 "$SHA256" \
    --arg account_id "$ACCOUNT_ID" \
    '{name:$name,asset_type:$asset_type,mime_type:$mime_type,size:$size,md5:$md5,sha256:$sha256,account_id:$account_id}')")"

DUPLICATE=$(jq -r '.duplicate // false' <<< "$SESSION_JSON")
ASSET_ID=$(jq -er '.asset_id' <<< "$SESSION_JSON")

if [[ "$DUPLICATE" == "true" ]]; then
  echo "[2/6] duplicate detected; no second OSS object will be uploaded"
else
  UPLOAD_URL=$(jq -er '.upload.url' <<< "$SESSION_JSON")
  echo "[2/6] direct PUT to OSS"
  curl -fsS -X PUT -H "Content-Type: $MIME_TYPE" --upload-file "$FILE_PATH" "$UPLOAD_URL" >/dev/null

  echo "[3/6] complete upload session"
  COMPLETE_JSON=$(curl -fsS "${AUTH[@]}" -X POST \
    "$BASE_URL/api/v1/media/upload-sessions/$(jq -er '.upload_session_id' <<< "$SESSION_JSON")/complete")
  jq -e --arg asset_id "$ASSET_ID" '.asset_id == $asset_id' <<< "$COMPLETE_JSON" >/dev/null
fi

echo "[4/6] wait for server-side processing and hash verification"
PROCESSING_STATUS=""
for attempt in $(seq 1 60); do
  ASSET_JSON=$(curl -fsS "${AUTH[@]}" "$BASE_URL/api/v1/media/$ASSET_ID")
  PROCESSING_STATUS=$(jq -r '.processing_status // .status // ""' <<< "$ASSET_JSON")
  if [[ "$PROCESSING_STATUS" == "READY" ]]; then
    break
  fi
  if [[ "$PROCESSING_STATUS" == "FAILED" ]]; then
    jq . <<< "$ASSET_JSON" >&2
    echo "media processing failed" >&2
    exit 1
  fi
  sleep 2
done
if [[ "$PROCESSING_STATUS" != "READY" ]]; then
  echo "media did not become READY within 120 seconds" >&2
  exit 1
fi

echo "[5/6] signed original URL and account binding"
DOWNLOAD_JSON=$(curl -fsS "${AUTH[@]}" "$BASE_URL/api/v1/media/$ASSET_ID/download-url?kind=original")
DOWNLOAD_URL=$(jq -er '.url' <<< "$DOWNLOAD_JSON")
curl -fsSI "$DOWNLOAD_URL" >/dev/null

BINDINGS_JSON=$(curl -fsS "${AUTH[@]}" "$BASE_URL/api/v1/media/$ASSET_ID/bindings")
jq -e --arg account_id "$ACCOUNT_ID" 'map(select(.ad_account_id == $account_id)) | length == 1' <<< "$BINDINGS_JSON" >/dev/null

echo "[6/6] regression passed"
echo "asset_id=$ASSET_ID"
echo "object_key=$(jq -r '.object_key // ""' <<< "$ASSET_JSON")"
echo "processing_status=$PROCESSING_STATUS"
echo "binding=present"
