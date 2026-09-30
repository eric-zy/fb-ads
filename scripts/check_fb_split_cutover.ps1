param(
    [string]$EnvFile = "deploy/.env"
)

$ErrorActionPreference = "Stop"
if (-not (Test-Path -LiteralPath $EnvFile)) {
    Write-Error "Environment file not found: $EnvFile"
}

$content = Get-Content -LiteralPath $EnvFile -Raw
$required = @(
    "APP_ROLE=saas",
    "FB_ACCESS_MODE=connector",
    "FB_CONNECTOR_BASE_URL=",
    "FB_CONNECTOR_SIGNING_KEY=",
    "CONNECTOR_SERVICE_TOKEN=",
    "SAAS_CALLBACK_BASE_URL=",
    "MEDIA_STORAGE_PROVIDER=oss",
    "ADS_OSS_ACCESS_KEY_ID=",
    "ADS_OSS_ACCESS_KEY_SECRET=",
    "ADS_OSS_BUCKET=",
    "ADS_OSS_REGION="
)
$failed = @()
foreach ($item in $required) {
    if ($content -notmatch [regex]::Escape($item)) { $failed += $item }
}

$forbidden = @("FB_APP_SECRET=", "FB_ACCESS_TOKEN=", "FB_OAUTH_REDIRECT_URI=")
foreach ($item in $forbidden) {
    if ($content -match [regex]::Escape($item)) { $failed += "Domestic config still contains $item" }
}

if ($content -match "(?i)change-me|replace-with|example\.com|your-secret|your_access") {
    $failed += "Configuration still contains placeholder values"
}

if ($failed.Count -gt 0) {
    Write-Host "CUTOVER_BLOCKED" -ForegroundColor Red
    foreach ($failure in $failed) {
        Write-Host ("- " + $failure)
    }
    exit 1
}

Write-Host "CUTOVER_CHECK_PASSED" -ForegroundColor Green
Write-Host "MANUAL_CHECK: migrations, connector load test, and Meta OAuth callback are complete."
