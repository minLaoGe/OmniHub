@echo off
REM 启动 REA 逆向工程分析控制台 (Windows)
set PORT=8877
set URL=http://127.0.0.1:%PORT%

echo ========================================================
echo   正在启动 REA 逆向工程分析控制台 (v6.4.0)...
echo   访问地址: %URL%
echo ========================================================

python -m uvicorn rea_service.app:app --host 127.0.0.1 --port %PORT%
