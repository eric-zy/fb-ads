@echo off
setlocal
set "PROJECT_DIR=%~dp0"
cd /d "%PROJECT_DIR%"

if not exist "%PROJECT_DIR%.env" (
    if exist "%PROJECT_DIR%.env.example" (
        echo [INFO] .env not found, copying from .env.example ...
        copy "%PROJECT_DIR%.env.example" "%PROJECT_DIR%.env" >nul
        echo [WARN] .env generated. Review DB_PASSWORD / DB_PORT / REDIS_PORT before starting Docker deps.
    ) else (
        echo [ERROR] .env not found and no .env.example template, cannot continue
        pause
        exit /b 1
    )
)

docker compose version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] docker compose is not available
    echo         Install Docker Desktop and ensure `docker compose` works in your terminal.
    pause
    exit /b 1
)

echo [INFO] Starting local PostgreSQL and Redis with Docker Compose ...
echo [INFO] Pulling Docker images ...
docker compose -f deploy\docker-compose.local-deps.yml pull
if errorlevel 1 (
    echo [WARN] Initial image pull failed, retrying once ...
    docker compose -f deploy\docker-compose.local-deps.yml pull
)

docker compose -f deploy\docker-compose.local-deps.yml up -d
if errorlevel 1 (
    echo [WARN] Initial compose up failed, retrying once ...
    docker compose -f deploy\docker-compose.local-deps.yml up -d
)
if errorlevel 1 (
    echo [ERROR] Failed to start local dependencies
    echo         Common causes:
    echo         1. Docker Desktop is not fully running
    echo         2. Image pull was interrupted by network instability
    echo         3. Local Docker cache is in a bad state
    echo.
    echo         Try:
    echo         - Re-run: .\start-local-deps.bat
    echo         - Or pull manually: docker pull postgres:16-alpine
    echo         - If it still fails: docker image rm postgres:16-alpine && docker pull postgres:16-alpine
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   Local dependencies started
echo ------------------------------------------------------------
echo   PostgreSQL : localhost:5432
echo   Redis      : localhost:6379
echo ------------------------------------------------------------
echo   Next steps:
echo   1. Run: .\venv\Scripts\python.exe -m alembic upgrade head
echo   2. Run: .\start.bat
echo   3. Stop deps later: .\stop-local-deps.bat
echo ============================================================
pause
endlocal
