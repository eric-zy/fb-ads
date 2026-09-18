$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$FrontendDir = Join-Path $ProjectRoot "frontend"

Write-Host "[frontend] checking Node.js and npm..." -ForegroundColor Cyan
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    throw "Node.js 未安装，请先安装 Node.js 20 LTS。"
}
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw "npm 未安装或不在 PATH 中。"
}

Push-Location $FrontendDir
try {
    Write-Host "[frontend] installing dependencies..." -ForegroundColor Cyan
    npm ci --allow-remote=all
    if ($LASTEXITCODE -ne 0) { throw "npm ci 执行失败。" }

    Write-Host "[frontend] building production assets..." -ForegroundColor Cyan
    npm run build
    if ($LASTEXITCODE -ne 0) { throw "npm run build 执行失败。" }
}
finally {
    Pop-Location
}

if (-not (Test-Path (Join-Path $FrontendDir "dist\index.html"))) {
    throw "编译完成但未找到 frontend/dist/index.html。"
}

Write-Host "[frontend] build completed:" -ForegroundColor Green
Write-Host "  Dist:    $(Join-Path $FrontendDir 'dist')"
Write-Host "[frontend] frontend/dist has been overwritten with the latest production build." -ForegroundColor Green
