@echo off
setlocal
set "PROJECT_DIR=%~dp0"
cd /d "%PROJECT_DIR%"

echo ============================================================
echo   FB-Ads Local Bootstrap
echo ============================================================

if not exist "%PROJECT_DIR%venv\Scripts\python.exe" (
    echo [ERROR] venv not found
    echo         Run first: python -m venv venv
    pause
    exit /b 1
)

if not exist "%PROJECT_DIR%.env" (
    if exist "%PROJECT_DIR%.env.example" (
        echo [INFO] .env not found, copying from .env.example ...
        copy "%PROJECT_DIR%.env.example" "%PROJECT_DIR%.env" >nul
        echo [WARN] .env generated. Review SECRET_KEY / DB_* / REDIS_* / FB_* after bootstrap.
    ) else (
        echo [ERROR] .env not found and no .env.example template, cannot continue
        pause
        exit /b 1
    )
)

echo [INFO] Installing / updating backend dependencies ...
call "%PROJECT_DIR%venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Failed to install backend dependencies
    pause
    exit /b 1
)

if not exist "%PROJECT_DIR%frontend\node_modules" (
    echo [INFO] Installing frontend dependencies ...
    pushd "%PROJECT_DIR%frontend"
    call npm install
    if errorlevel 1 (
        echo [ERROR] Failed to install frontend dependencies
        popd
        pause
        exit /b 1
    )
    popd
) else (
    echo [INFO] Frontend dependencies already installed
)

call "%PROJECT_DIR%start-local-deps.bat"
if errorlevel 1 (
    echo [ERROR] Failed to start local dependencies
    pause
    exit /b 1
)

echo [INFO] Running database migrations ...
call "%PROJECT_DIR%venv\Scripts\python.exe" -m alembic upgrade head
if errorlevel 1 (
    echo [ERROR] Failed to apply database migrations
    pause
    exit /b 1
)

echo [INFO] Creating or resetting the default admin account ...
call "%PROJECT_DIR%venv\Scripts\python.exe" cli.py create-admin
if errorlevel 1 (
    echo [ERROR] Failed to create the default admin account
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   Local bootstrap completed
echo ------------------------------------------------------------
echo   Admin email    : admin@fbads.com
echo   Admin password : admin123456
echo ------------------------------------------------------------
echo   Starting application windows next...
echo ============================================================

call "%PROJECT_DIR%start.bat"
if errorlevel 1 (
    echo [ERROR] Failed to start application windows
    pause
    exit /b 1
)

endlocal
