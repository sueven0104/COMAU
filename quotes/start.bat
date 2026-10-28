@echo off
rem ============================================================
rem  AI 报价查询系统 - 一键启动
rem  双击运行：自动加载 .env 密钥 -> 清理旧实例 -> 校验 -> 启动服务 -> 打开浏览器
rem  停止服务：关闭本窗口（或按 Ctrl+C）
rem ============================================================
chcp 65001 >nul
title AI 报价查询系统
cd /d "%~dp0"
set "PORT=8000"

rem --- 1. 加载 .env（密钥文件，不入 git） ---
if not exist ".env" (
    echo [X] 未找到 .env 文件！请参照 .env.example 填写 API Key 后重试。
    pause
    exit /b 1
)
for /f "usebackq tokens=1,* delims==" %%a in (`findstr /r "^[A-Za-z_]" ".env"`) do set "%%a=%%b"

rem --- 2. 清理占用 %PORT% 的旧实例（上次未关闭的窗口等） ---
set "OLD_PID="
for /f "tokens=5" %%p in ('netstat -a -n -o -p tcp ^| findstr ":%PORT% " ^| findstr "LISTENING"') do set "OLD_PID=%%p"
if defined OLD_PID (
    echo [!] 端口 %PORT% 被旧实例占用（PID %OLD_PID%），自动结束它...
    taskkill /f /pid %OLD_PID% >nul 2>&1
    timeout /t 1 /nobreak >nul
)

rem --- 3. 校验数据库 ---
if not exist "data\quotes.db" (
    echo [X] 未找到 data\quotes.db！请先运行建库管道：
    echo     python -m app.ingestion.pipeline
    pause
    exit /b 1
)

rem --- 4. 校验 Python 依赖 ---
python -c "import fastapi, uvicorn, openai" >nul 2>&1
if errorlevel 1 (
    echo [X] 缺少依赖！请先执行：pip install -e .
    pause
    exit /b 1
)

echo [*] 启动服务中，浏览器将自动打开 http://127.0.0.1:%PORT% ...
rem --- 5. 3 秒后自动打开浏览器（等服务器就绪） ---
start "" cmd /c "timeout /t 3 /nobreak >nul & start http://127.0.0.1:%PORT%"

rem --- 6. 前台启动服务（窗口关闭即停止） ---
python -m uvicorn app.web.server:app --host 127.0.0.1 --port %PORT%
if errorlevel 1 (
    echo.
    echo [X] 服务启动失败，请检查上方错误信息。
)
echo.
echo [*] 服务已停止。
pause
