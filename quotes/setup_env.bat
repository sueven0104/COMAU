@echo off
rem ============================================================
rem  AI 报价查询系统 - 环境准备（新机器上运行一次即可）
rem  作用：检查 Python -> 安装依赖 -> 校验密钥/数据库/源文件
rem  注意：本文件需保存为 ANSI(GBK) 编码 + CRLF 行尾，cmd 才能正确解析中文
rem ============================================================
chcp 936 >nul
cd /d "%~dp0"

rem 国内直连 pypi.org 经常超时（报 "from versions: none"），默认走清华镜像
rem 如需改用官方源，把这行改成：set "INDEX=https://pypi.org/simple"
set "INDEX=https://pypi.tuna.tsinghua.edu.cn/simple"

echo [1/4] 检查 Python ...
where python >nul 2>&1
if errorlevel 1 (
    echo [X] 未找到 python 命令。请先安装 Python 3.12+，安装时勾选 Add python.exe to PATH。
    pause
    exit /b 1
)
python -c "import sys;sys.exit(0 if sys.version_info>=(3,12) else 1)"
if errorlevel 1 (
    echo [X] Python 版本过低，需要 3.12 或更高版本。当前版本：
    python --version
    pause
    exit /b 1
)
echo     版本：
python --version
echo     路径：
python -c "import sys;print(sys.executable)"

echo [2/4] 安装依赖 ...
if exist "wheels\" (
    echo     检测到离线依赖目录 wheels，全程离线安装 ...
    python -m pip install --no-index --find-links wheels --upgrade setuptools wheel
    if errorlevel 1 goto :piperr
    python -m pip install --no-index --find-links wheels -r requirements.txt
    if errorlevel 1 goto :piperr
    python -m pip install --no-index --find-links wheels -e . --no-deps
) else (
    echo     使用镜像源 %INDEX%
    python -m pip install --upgrade pip setuptools wheel -i %INDEX% --timeout 30 --retries 3
    if errorlevel 1 goto :piperr
    python -m pip install -r requirements.txt -i %INDEX% --timeout 30 --retries 3
    if errorlevel 1 goto :piperr
    python -m pip install -e . --no-deps
)
if errorlevel 1 goto :piperr

echo [3/4] 校验依赖 ...
python -c "import fastapi, uvicorn, openai, openpyxl, pymupdf, extract_msg; print('    依赖校验通过')"
if errorlevel 1 (
    echo [X] 依赖导入失败，请查看上方报错。
    pause
    exit /b 1
)

echo [4/4] 校验运行文件 ...
if not exist ".env" (
    echo [!] 未找到 .env：请复制 .env.example 为 .env 并填入 QUOTES_API_KEY
) else (
    findstr /b /c:"QUOTES_API_KEY=" ".env" >nul 2>&1
    if errorlevel 1 (
        echo [!] .env 中没有 QUOTES_API_KEY，提问功能不可用
    ) else (
        echo     .env 已配置
    )
)
if exist "data\quotes.db" (
    echo     data\quotes.db 已存在
) else (
    echo [!] 未找到 data\quotes.db：需运行 python -m app.ingestion.pipeline 建库
)
if exist "..\raw_data\" (
    echo     ..\raw_data\ 已存在
) else (
    echo [!] 未找到 ..\raw_data\：建库前请把历史报价文件夹放到项目根目录 raw_data\
)

echo.
echo 环境准备完成。双击 start.bat 启动系统。
pause
exit /b 0

:piperr
echo [X] 依赖安装失败。
echo     1. 网络超时：把本文件的 INDEX 换成 https://mirrors.aliyun.com/pypi/simple/ 重试
echo     2. 目标机器无外网：先在联网机器上执行
echo        python -m pip download -r requirements.txt setuptools wheel -d wheels -i %INDEX%
echo        再把整个 wheels 文件夹拷到本目录，重新运行本脚本
echo     3. wheels 目录里的包只适配生成它时的系统与 Python 版本，版本不一致请重新下载
pause
exit /b 1