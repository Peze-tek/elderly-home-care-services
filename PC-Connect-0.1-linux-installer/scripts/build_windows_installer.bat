@echo off
setlocal
cd /d "%~dp0.."
call scripts\build_windows.bat
if errorlevel 1 exit /b 1
where iscc >nul 2>nul
if errorlevel 1 (
  echo Inno Setup is not installed or iscc is not on PATH.
  exit /b 1
)
iscc packaging\PC-Connect.iss
