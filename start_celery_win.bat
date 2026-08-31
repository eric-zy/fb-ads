@echo off
REM ============================================================
REM  Windows 侧 Celery Worker 启动脚本
REM  说明: Windows 下 celery 5.x 的 prefork 多进程池会因 billiard
REM        的进程间同步对象报 [WinError 5 拒绝访问]，故使用
REM        --pool=solo (单进程内串行执行，稳定不崩溃)。
REM  前置: 依赖已装在 .\venv ; Redis 由 WSL 提供 (localhost:6379)
REM  用法: 双击本文件，或手动在 venv 激活后执行
REM        celery -A celery_app worker --loglevel=info --pool=solo
REM ============================================================

setlocal
set "PROJECT_DIR=%~dp0"
cd /d "%PROJECT_DIR%"

REM 激活虚拟环境
if exist "%PROJECT_DIR%venv\Scripts\activate.bat" (
    call "%PROJECT_DIR%venv\Scripts\activate.bat"
) else (
    echo [错误] 未找到 venv，请先执行: python -m venv venv ^&^& pip install -r requirements.txt
    pause
    exit /b 1
)

echo [INFO] 启动 Celery Worker (pool=solo) ...
echo [INFO] broker: redis://localhost:6379/0  (由 WSL Redis 提供)
celery -A celery_app worker --loglevel=info --pool=solo

endlocal
pause
