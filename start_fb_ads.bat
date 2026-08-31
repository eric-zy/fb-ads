@echo off
REM ============================================================
REM  FB Ads 后端一键启动脚本 (WSL)
REM  作用: 启动 WSL 实例 -> 触发 systemd 自启服务
REM        (redis / fb-api / fb-celery) -> 等待并校验就绪
REM  用法: 双击本文件, 或加入 Windows 任务计划程序(开机/登录触发)
REM ============================================================

set WSL_DISTRO=Ubuntu-24.04

echo [1/4] 启动 WSL 实例 (%WSL_DISTRO%) ...
wsl -d %WSL_DISTRO% -e true
if errorlevel 1 (
    echo [错误] WSL 启动失败, 请确认已安装 Ubuntu-24.04 且 Docker/BIOS 虚拟化正常
    pause
    exit /b 1
)

echo [2/4] 确保服务已 enable 并启动 ...
wsl -d %WSL_DISTRO% -e bash -c "sudo systemctl enable fb-api.service fb-celery.service redis-server.service 2>/dev/null; sudo systemctl start fb-api.service fb-celery.service redis-server.service 2>/dev/null; echo done"

echo [3/4] 等待后端就绪 (最多 30s) ...
set /a tries=0
:waitloop
wsl -d %WSL_DISTRO% -e bash -c "curl -s -o /dev/null -w '%%{http_code}' http://localhost:8000/health" > %temp%\fb_health.txt 2>nul
set /p HEALTH=<%%temp%%\fb_health.txt
if "%HEALTH%"=="200" goto ready
set /a tries+=1
if %tries% geq 30 (
    echo [警告] 30s 内后端未返回 200, 请查看日志: journalctl -u fb-api.service
    goto end
)
timeout /t 1 /nobreak >nul
goto waitloop

:ready
echo [4/4] 后端已就绪!
echo ----------------------------------------------------------
echo  API     : http://localhost:8000
echo  Health  : http://localhost:8000/health
echo  WSL日志 :
echo    journalctl -u fb-api.service -f
echo    journalctl -u fb-celery.service -f
echo ----------------------------------------------------------

:end
pause
