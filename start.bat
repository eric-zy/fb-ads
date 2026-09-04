@echo off
REM ============================================================
REM  FB-Ads 一键启动（Windows）
REM  启动 4 个组件，各占独立窗口：
REM    [API]     uvicorn :8000  (FastAPI，含 --reload)
REM    [Beat]    Celery Beat    (定时调度触发器)
REM    [Worker]  Celery Worker (任务执行，--pool=solo Windows 必需)
REM    [Front]   vite dev :5173(Vue3 前端)
REM
REM  前置依赖（需另行确保可用，本脚本不负责拉起）：
REM    - venv 已装依赖（requirements.txt）
REM    - Redis 可达（默认 localhost:6379，Celery broker）
REM    - PostgreSQL 可达（默认 localhost:5432）
REM    - Node.js 已安装（前端构建）
REM
REM  说明：Beat(触发) 与 Worker(执行) 必须成对启动，
REM        否则定时任务只堆积不执行。
REM ============================================================

setlocal enabledelayedexpansion
set "PROJECT_DIR=%~dp0"
cd /d "%PROJECT_DIR%"
title FB-Ads 一键启动

echo ============================================================
echo   FB-Ads 一键启动
echo   组件: API / Worker / Beat / 前端
echo ============================================================

REM ---- 1. venv 自检 ----
if not exist "%PROJECT_DIR%venv\Scripts\activate.bat" (
    echo [错误] 未找到 venv
    echo        请先执行: python -m venv venv ^&^& venv\Scripts\activate ^&^& pip install -r requirements.txt
    pause
    exit /b 1
)

REM ---- 2. .env 自检（缺失则从模板生成并提示填写）----
if not exist "%PROJECT_DIR%.env" (
    if exist "%PROJECT_DIR%.env.example" (
        echo [INFO] 未找到 .env，从 .env.example 复制 ...
        copy "%PROJECT_DIR%.env.example" "%PROJECT_DIR%.env" >nul
        echo [警告] 已生成 .env，请填写 SECRET_KEY / DB_* / REDIS_* / FB_* 后重新运行本脚本
        pause
        exit /b 1
    ) else (
        echo [错误] 未找到 .env 且无 .env.example 模板，无法启动
        pause
        exit /b 1
    )
)

REM ---- 3. 前端依赖自检（缺失则自动 npm install）----
if not exist "%PROJECT_DIR%frontend\node_modules" (
    echo [INFO] 前端 node_modules 不存在，执行 npm install ...
    pushd "%PROJECT_DIR%frontend"
    call npm install
    if errorlevel 1 (
        echo [错误] npm install 失败，请检查 Node.js / 网络
        popd
        pause
        exit /b 1
    )
    popd
) else (
    echo [INFO] 前端 node_modules 已存在，跳过安装
)

REM ---- 4. 启动 API (uvicorn :8000) ----
echo [INFO] 启动 API (uvicorn :8000) ...
start "FB-Ads API" cmd /k "cd /d "%PROJECT_DIR%" && call "%PROJECT_DIR%venv\Scripts\activate.bat" && python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload"

REM ---- 5. 启动 Celery Beat (定时调度触发器) ----
echo [INFO] 启动 Celery Beat ...
start "FB-Ads Beat" cmd /k "cd /d "%PROJECT_DIR%" && call "%PROJECT_DIR%venv\Scripts\activate.bat" && celery -A celery_app beat --loglevel=info"

timeout /t 2 /nobreak >nul

REM ---- 6. 启动 Celery Worker (pool=solo，Windows 必需) ----
echo [INFO] 启动 Celery Worker (pool=solo) ...
start "FB-Ads Worker" cmd /k "cd /d "%PROJECT_DIR%" && call "%PROJECT_DIR%venv\Scripts\activate.bat" && celery -A celery_app worker --loglevel=info --pool=solo"

REM ---- 7. 启动前端 (vite :5173) ----
echo [INFO] 启动前端 (vite :5173) ...
start "FB-Ads Front" cmd /k "cd /d "%PROJECT_DIR%frontend" && npm run dev"

echo.
echo ============================================================
echo   全部组件已启动（各占独立窗口）
echo ----------------------------------------------------------
echo   API      : http://localhost:8000
echo   健康检查  : http://localhost:8000/health
echo   Swagger  : http://localhost:8000/docs
echo   前端     : http://localhost:5173
echo ----------------------------------------------------------
echo   关闭: 直接关闭对应窗口即可（4 个组件窗口需保持开启）
echo   依赖: Redis(6379) / PostgreSQL(5432) 请另行确保可用
echo ============================================================
echo 本汇总窗口可关闭。
endlocal
pause
