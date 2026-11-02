@echo off
rem wait for SnowLuma to inject QQ and open the OneBot port
ping -n 70 127.0.0.1 >nul
"%~dp0..\deps\venv\Scripts\python.exe" "%~dp0catchup.py" >> "%~dp0logs\catchup-run.log" 2>&1
