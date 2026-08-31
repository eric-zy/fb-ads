@echo off
REM ============================================================
REM  Windows 侧前端启动脚本 (Vue3 + Vite)
REM  - 首次自动 npm install (若 node_modules 不存在)
REM  - 启动 vite dev server (默认端口 5173)
REM  前置: 已安装 Node.js (npm)
REM ============================================================

setlocal
set "FRONTEND_DIR=%~dp0frontend"
cd /d "%FRONTEND_DIR%" || (echo [错误] 未找到 frontend 目录 & pause & exit /b 1)

if not exist "%FRONTEND_DIR%\node_modules" (
    echo [INFO] 未检测到 node_modules，正在执行 npm install ...
    npm install
    if errorlevel 1 (
        echo [错误] npm install 失败，请检查 Node.js / 网络
        pause
        exit /b 1
    )
) else (
    echo [INFO] node_modules 已存在，跳过 npm install
)

echo [INFO] 启动前端 dev server (vite) ...
npm run dev

endlocal
pause
