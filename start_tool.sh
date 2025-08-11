#!/bin/bash

echo "========================================"
echo " CMP/Android 中文字符串提取工具"
echo "========================================"
echo

# 检查Python环境
echo "正在检查 Python 环境..."
if ! command -v python &> /dev/null; then
    echo "错误：未找到 Python3，请先安装 Python 3.7+"
    exit 1
fi

python --version

# 检查pip
if ! command -v pip3 &> /dev/null; then
    echo "错误：未找到 pip3"
    exit 1
fi

# 检查依赖包
echo "正在检查依赖包..."
if ! pip3 show Flask > /dev/null 2>&1; then
    echo "正在安装依赖包..."
    pip3 install -r requirements.txt
    if [ $? -ne 0 ]; then
        echo "错误：依赖包安装失败"
        exit 1
    fi
fi

echo "正在启动工具..."
echo "请在浏览器中访问: http://localhost:5000"
echo "按 Ctrl+C 停止服务"
echo

python chinese_string_extractor.py