@echo off
chcp 65001 >nul
title 远程控制服务端

echo ================================
echo   远程控制服务端启动脚本
echo ================================

:: 检查Python是否安装
python --version >nul 2>&1
if errorlevel 1 (
    echo 错误: 未找到Python，请先安装Python 3.7+
    pause
    exit /b 1
)

:: 检查依赖是否安装
python -c "import flask" >nul 2>&1
if errorlevel 1 (
    echo 依赖未安装，正在安装...
    python install_requirements.py
    if errorlevel 1 (
        echo 依赖安装失败，请手动安装
        pause
        exit /b 1
    )
)

echo 启动服务端...
python server.py

if errorlevel 1 (
    echo 服务端启动失败
    pause
)