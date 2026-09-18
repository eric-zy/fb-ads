param(
    [string]$SaasBase = "http://49.232.238.163:8094",
    [string]$ConnectorBase = "https://iornix.com"
)

$ErrorActionPreference = "Stop"

function Invoke-StatusOnly([string]$Method, [string]$Url, [hashtable]$Headers = @{}) {
    $args = @("-sS", "-D", "-", "-o", "NUL", "--max-redirs", "0", "-X", $Method)
    foreach ($key in $Headers.Keys) { $args += @("-H", "$key`: $($Headers[$key])") }
    $raw = (& curl.exe @args $Url 2>&1) -join "`n"
    if ($LASTEXITCODE -ne 0 -and $raw -notmatch "HTTP/\d\.\d") { throw $raw }
    $statusMatch = [regex]::Match($raw, "HTTP/\d\.\d\s+(\d+)")
    if (-not $statusMatch.Success) { throw "No HTTP status in response: $raw" }
    $locationMatch = [regex]::Match($raw, "(?im)^location:\s*(.+)$")
    return @{ Status = [int]$statusMatch.Groups[1].Value; Location = if ($locationMatch.Success) { $locationMatch.Groups[1].Value.Trim() } else { "" } }
}

Write-Host "[1/5] SaaS callback is public and rejects invalid state safely"
$callback = Invoke-StatusOnly GET "$SaasBase/api/v1/meta-auth/callback?state=invalid&code=test"
if ($callback.Status -ne 302 -or -not $callback.Location.StartsWith("$SaasBase/dashboard/accounts?")) {
    throw "Unexpected SaaS callback result: $($callback.Status) $($callback.Location)"
}

Write-Host "[2/5] Connector callback is public for browser redirect"
try {
    $connectorCallback = Invoke-StatusOnly GET "$ConnectorBase/internal/meta/oauth/callback?state=invalid&code=test"
    if ($connectorCallback.Status -ne 302) { throw "Expected 302, got $($connectorCallback.Status)" }
} catch {
    throw "Connector callback could not be reached over HTTPS: $($_.Exception.Message)"
}

Write-Host "[3/5] Connector internal API rejects missing service signature"
$protected = Invoke-StatusOnly GET "$ConnectorBase/internal/meta/version"
if ($protected.Status -ne 401) { throw "Expected 401 without signature, got $($protected.Status)" }

Write-Host "[4/5] OAuth redirect allowlist is enforced in source"
$source = Get-Content -Raw "$PSScriptRoot\..\api\meta_auth.py"
foreach ($origin in @("https://iornix.com", "http://49.232.238.163:8094")) {
    if ($source -notmatch [regex]::Escape($origin)) { throw "Missing SaaS redirect allowlist entry: $origin" }
}

Write-Host "[5/5] Manual gate"
Write-Host "MANUAL_REQUIRED: login Meta, select an ad account, verify opaque credential binding, then verify account/page sync and task status."
Write-Host "OAUTH_CONNECTOR_REGRESSION_PARTIAL_PASSED"
