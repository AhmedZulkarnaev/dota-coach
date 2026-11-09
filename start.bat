@echo off
chcp 65001 >nul
cd /d "%~dp0"

where pyw >nul 2>nul
if %errorlevel%==0 (
    start "" pyw -3 main.py
    exit /b
)
where pythonw >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw main.py
    exit /b
)
where py >nul 2>nul
if %errorlevel%==0 (
    py -3 main.py
    exit /b
)

echo Python не найден.
echo Установите Python 3.11+ с https://www.python.org/downloads/
echo При установке поставьте галочку "Add python.exe to PATH".
pause
