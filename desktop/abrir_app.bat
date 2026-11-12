@echo off
rem Opens the desktop app in development mode.
set "PATH=%USERPROFILE%\.cargo\bin;%PATH%"
cd /d "%~dp0app"
if not exist node_modules (
  echo Installing interface dependencies, first run only...
  call npm install
)
npm run tauri dev
