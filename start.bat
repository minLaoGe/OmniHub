@echo off
chcp 65001 >nul
title OmniHub - 大模型与多服务统一中枢

echo ==================================================================
echo   OmniHub 跨平台统一控制台 (Windows 启动器)
echo ==================================================================

cd /d "%~dp0"

where python >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [错误] 系统未检测到 python 命令，请确保已安装 Python 并添加到 PATH 环境变量。
    pause
    exit /b 1
)

python start.py %1
if %ERRORLEVEL% neq 0 (
    pause
)
