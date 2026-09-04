@echo off
setlocal
set "PROJECT_DIR=%~dp0"
cd /d "%PROJECT_DIR%"

echo ============================================================
echo   FB-Ads Full Docker Bootstrap
echo ============================================================

docker compose version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] docker compose is not available
    echo         Install Docker Desktop and ensure `docker compose` works in your terminal.
    pause
    exit /b 1
)

if not exist "%PROJECT_DIR%deploy\.env" (
    if exist "%PROJECT_DIR%deploy\.env.example" (
        echo [INFO] deploy\.env not found, copying from deploy\.env.example ...
        copy "%PROJECT_DIR%deploy\.env.example" "%PROJECT_DIR%deploy\.env" >nul
        echo [WARN] deploy\.env generated. Review SECRET_KEY / DB_PASSWORD / REDIS_PASSWORD / FB_* when convenient.
    ) else (
        echo [ERROR] deploy\.env not found and no deploy\.env.example template, cannot continue
        pause
        exit /b 1
    )
)

echo [INFO] Pulling base Docker images ...
docker compose -f deploy\docker-compose.yml --env-file deploy\.env pull db redis
if errorlevel 1 (
    echo [WARN] Initial base image pull failed, retrying once ...
    docker compose -f deploy\docker-compose.yml --env-file deploy\.env pull db redis
)

echo [INFO] Pulling build base images ...
docker pull python:3.12-slim
if errorlevel 1 (
    echo [WARN] Initial pull for python:3.12-slim failed, retrying once ...
    docker pull python:3.12-slim
)
if errorlevel 1 (
    echo [ERROR] Failed to pull python:3.12-slim
    pause
    exit /b 1
)

docker pull node:20-bookworm-slim
if errorlevel 1 (
    echo [WARN] Initial pull for node:20-bookworm-slim failed, retrying once ...
    docker pull node:20-bookworm-slim
)
if errorlevel 1 (
    echo [ERROR] Failed to pull node:20-bookworm-slim
    pause
    exit /b 1
)

docker pull nginx:alpine
if errorlevel 1 (
    echo [WARN] Initial pull for nginx:alpine failed, retrying once ...
    docker pull nginx:alpine
)
if errorlevel 1 (
    echo [ERROR] Failed to pull nginx:alpine
    pause
    exit /b 1
)

echo [INFO] Building application images ...
docker compose -f deploy\docker-compose.yml --env-file deploy\.env build
if errorlevel 1 (
    echo [WARN] Initial Docker build failed, retrying once ...
    docker compose -f deploy\docker-compose.yml --env-file deploy\.env build
)
if errorlevel 1 (
    echo [ERROR] Failed to build Docker images
    echo         Try pulling these manually, then re-run:
    echo         - docker pull python:3.12-slim
    echo         - docker pull node:20-bookworm-slim
    echo         - docker pull nginx:alpine
    pause
    exit /b 1
)

echo [INFO] Starting full Docker environment ...
docker compose -f deploy\docker-compose.yml --env-file deploy\.env up -d
if errorlevel 1 (
    echo [WARN] Initial compose up failed, retrying once ...
    docker compose -f deploy\docker-compose.yml --env-file deploy\.env up -d
)
if errorlevel 1 (
    echo [ERROR] Failed to start the full Docker environment
    pause
    exit /b 1
)

echo [INFO] Running database migrations inside api container ...
docker compose -f deploy\docker-compose.yml --env-file deploy\.env exec api alembic upgrade head
if errorlevel 1 (
    echo [ERROR] Failed to apply database migrations inside Docker
    pause
    exit /b 1
)

echo [INFO] Creating or resetting the default admin account inside Docker ...
docker compose -f deploy\docker-compose.yml --env-file deploy\.env exec api python cli.py create-admin
if errorlevel 1 (
    echo [ERROR] Failed to create the default admin account inside Docker
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   Full Docker environment is ready
echo ------------------------------------------------------------
echo   App URL        : http://localhost
echo   Admin email    : admin@fbads.com
echo   Admin password : admin123456
echo ------------------------------------------------------------
echo   Useful commands:
echo   - Stop: .\stop-docker.bat
echo   - Logs: docker compose -f deploy\docker-compose.yml --env-file deploy\.env logs -f api
echo ============================================================
pause
endlocal
