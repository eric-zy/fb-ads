@echo off
setlocal
set "PROJECT_DIR=%~dp0"
cd /d "%PROJECT_DIR%"

docker compose version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] docker compose is not available
    echo         Install Docker Desktop and ensure `docker compose` works in your terminal.
    pause
    exit /b 1
)

echo [INFO] Stopping local PostgreSQL and Redis ...
docker compose -f deploy\docker-compose.local-deps.yml down
if errorlevel 1 (
    echo [ERROR] Failed to stop local dependencies
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   Local dependencies stopped
echo ------------------------------------------------------------
echo   To remove data volumes too, run:
echo   docker compose -f deploy\docker-compose.local-deps.yml down -v
echo ============================================================
pause
endlocal
