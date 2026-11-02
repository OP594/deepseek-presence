@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0.."
echo ============================================
echo  deepseek-presence 一键安装
echo ============================================
echo.
where python >nul 2>nul
if errorlevel 1 (
  echo 没找到 python，请先装 Python 3.11+ 并勾选 Add to PATH
  pause
  exit /b 1
)
python -X utf8 scripts\bootstrap.py %*
echo.
pause
