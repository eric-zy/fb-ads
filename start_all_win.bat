@echo off
REM ============================================================
REM  Windows 侧一键启动全部: API + Celery Worker + Celery Beat + 前端
REM  窗口分配:
REM    [窗口1] FB-Ads API    -> uvicorn :8000 (后台)
REM    [窗口2] FB-Ads Front  -> vite dev (端口 5173, 后台)
REM    [窗口3] FB-Ads Beat   -> celery beat 定时调度 (后台)
REM    [窗口4] FB-Ads Celery -> worker (pool=solo, 前台日志)
REM  前置: .\venv 已建好装好依赖; frontend\node_modules 已装 (脚本会自动装);
REM        Redis 由 WSL 提供 (localhost:6379)
REM
REM  注意: 定时调度已由 APScheduler 迁移为 Celery Beat，
REM        Beat(触发) 与 Worker(执行) 必须成对启动，否则任务只堆积不执行。
REM ============================================================

setlocal
set "PROJECT_DIR=%~dp0"
cd /d "%PROJECT_DIR%"

if not exist "%PROJECT_DIR%venv\Scripts\activate.bat" (
    echo [错误] 未找到 venv，请先执行: python -m venv venv ^&^& pip install -r requirements.txt
    pause
    exit /b 1
)

REM 窗口1: FastAPI (uvicorn) 后台
echo [INFO] 启动 FastAPI (uvicorn :8000) ...
start "FB-Ads API" cmd /k "cd /d "%PROJECT_DIR%" && call "%PROJECT_DIR%venv\Scripts\activate.bat" && python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload"

REM 窗口2: 前端 (vite) 后台
echo [INFO] 启动前端 (vite :5173) ...
start "FB-Ads Front" cmd /k "cd /d "%PROJECT_DIR%frontend%" && if not exist node_modules (call npm install) && npm run dev"

timeout /t 3 /nobreak >nul

REM 窗口3: Celery Beat 后台（定时调度）
echo [INFO] 启动 Celery Beat ...
start "FB-Ads Beat" cmd /k "cd /d "%PROJECT_DIR%" && call "%PROJECT_DIR%venv\Scripts\activate.bat" && celery -A celery_app beat --loglevel=info"

timeout /t 2 /nobreak >nul

REM 窗口4: Celery Worker 前台 (保留日志)
echo [INFO] 启动 Celery Worker (pool=solo) ...
echo [INFO] broker: redis://localhost:6379/0  (WSL Redis)
call "%PROJECT_DIR%venv\Scripts\activate.bat"
celery -A celery_app worker --loglevel=info --pool=solo

endlocal
pause
