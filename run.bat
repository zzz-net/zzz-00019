@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 正在启动 本地设备借用归还验收管理系统...
echo.
python app.py
if errorlevel 1 (
    echo.
    echo 启动失败，请检查是否已安装 Python 3.8+
    pause
)
