@echo off
setlocal
cd /d "%~dp0.."
python -m pip install -U pyinstaller
python -m PyInstaller --clean --noconfirm packaging\pc-connect.spec
if errorlevel 1 exit /b 1
echo Build complete: dist\PC Connect.exe
