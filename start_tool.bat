@echo off
chcp 65001 > nul
echo ========================================
echo  Transtation 中文字符串提取工具
echo ========================================
echo.

echo 正在检查 Python 环境...
python --version > nul 2>&1
if %errorlevel% neq 0 (
    echo 错误：未找到 Python，请先安装 Python 3.7+
    pause
    exit /b 1
)

echo 正在检查依赖包...
pip show Flask > nul 2>&1
if %errorlevel% neq 0 (
    echo 正在安装依赖包...
    pip install -r requirements.txt
    if %errorlevel% neq 0 (
        echo 错误：依赖包安装失败
        pause
        exit /b 1
    )
)

echo 正在启动工具...
echo 请在浏览器中访问: http://localhost:5000
echo 按 Ctrl+C 停止服务
echo.
python chinese_string_extractor.py

pause