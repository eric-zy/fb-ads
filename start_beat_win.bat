@echo off
REM ============================================================
REM  Windows 侧 Celery Beat 定时调度启动脚本
REM
REM  说明: 定时任务已由 APScheduler 迁移到 Celery Beat
REM        （调度规则见 celery_app.conf.beat_schedule）。
REM        Beat 负责按 cron 触发任务，Worker 负责执行，二者需同时运行。
REM
REM  当前计划任务:
REM    fetch-insights   SCHEDULE_FETCH_INSIGHTS_CRON   每 2 小时
REM    risk-check       SCHEDULE_RISK_CHECK_CRON       每小时
REM    daily-reports    SCHEDULE_REPORT_DAILY_CRON     每天 8 点
REM    weekly-reports   SCHEDULE_REPORT_WEEKLY_CRON    每周一 9 点
REM
REM  等价命令: python cli.py start-beat
REM  前置: .\venv 已装好依赖; Redis 可用 (localhost:6379)
REM ============================================================

setlocal
set "PROJECT_DIR=%~dp0"
cd /d "%PROJECT_DIR%"

if exist "%PROJECT_DIR%venv\Scripts\activate.bat" (
    call "%PROJECT_DIR%venv\Scripts\activate.bat"
) else (
    echo [错误] 未找到 venv，请先执行: python -m venv venv ^&^& pip install -r requirements.txt
    pause
    exit /b 1
)

echo [INFO] 启动 Celery Beat ...
echo [INFO] 调度配置来自 .env 中的 SCHEDULE_*_CRON
celery -A celery_app beat --loglevel=info

endlocal
pause
