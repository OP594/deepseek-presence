@echo off
set "SCRIPTS=%~dp0"
set "ROOT=%~dp0.."
set "PYW=%ROOT%\deps\venv\Scripts\pythonw.exe"
if not exist "%PYW%" (
  echo Python venv not found: %PYW%
  echo Create it first: python -m venv deps\venv
  pause
  exit /b 1
)
start "" "%PYW%" "%SCRIPTS%gui.py"
