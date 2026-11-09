@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Тестовый матч без Dota 2. Сначала запустите start.bat.
where py >nul 2>nul && (py -3 tools\simulate_gsi.py %*) || (python tools\simulate_gsi.py %*)
pause
