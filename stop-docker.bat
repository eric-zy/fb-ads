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

echo [INFO] Stopping full Docker environment ...
docker compose -f deploy\docker-compose.yml --env-file deploy\.env down
if errorlevel 1 (
    echo [ERROR] Failed to stop the full Docker environment
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   Full Docker environment stopped
echo ------------------------------------------------------------
echo   To remove Docker volumes too, run:
echo   docker compose -f deploy\docker-compose.yml --env-file deploy\.env down -v
echo ============================================================
pause
endlocal
