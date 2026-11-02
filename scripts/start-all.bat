@echo off
rem ROOT = parent of scripts\ ; runtime data lives at ROOT
set "SCRIPTS=%~dp0"
set "ROOT=%~dp0.."
set "DEPS=%ROOT%\deps"
set "PYW=%DEPS%\venv\Scripts\pythonw.exe"
set "PY=%DEPS%\venv\Scripts\python.exe"
set "LOGS=%ROOT%\logs"
if not exist "%LOGS%" mkdir "%LOGS%"
set PYTHONIOENCODING=utf-8

echo [%date% %time%] launcher start >> "%LOGS%\bot.log"

rem backup once at boot
"%PY%" "%SCRIPTS%backup.py" >> "%LOGS%\bot.log" 2>&1

rem resident workers, no window
start "" /b "%PYW%" "%SCRIPTS%backup_loop.py"
start "" /b "%PYW%" "%SCRIPTS%watchdog.py"
start "" /b "%PYW%" "%SCRIPTS%keepawake.py"
start "" /b "%PYW%" "%SCRIPTS%wakeguard.py"
start "" /b "%PYW%" "%SCRIPTS%qzone_comments.py"
start "" /b "%PYW%" "%SCRIPTS%webproxy.py"
start "" /b "%PYW%" "%SCRIPTS%diary.py"
start "" /b "%PYW%" "%SCRIPTS%keeper_loop.py"

rem her own time: qzone post, signature
start "" /b "%PYW%" "%SCRIPTS%qzone_daemon.py"

rem AstrBot
start "" /b /d "%DEPS%\astrbot-home" "%DEPS%\venv\Scripts\astrbot.exe" run -p 6185

rem replay messages missed while off
start "" /b "%SCRIPTS%catchup-delayed.bat"

exit /b 0
