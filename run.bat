@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" goto setup
if not exist ".venv\Scripts\pythonw.exe" goto setup
if not exist ".setup-v8" goto setup
".venv\Scripts\python.exe" -c "import customtkinter, PIL, telegram, tkinterdnd2, yt_dlp" >nul 2>&1
if errorlevel 1 goto setup
goto launch

:setup
  echo AIwithSaeed Downloader is not set up yet. Running setup...
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
  if errorlevel 1 (
    pause
    exit /b 1
  )

:launch
start "" ".venv\Scripts\pythonw.exe" "%~dp0launcher.pyw"
endlocal
