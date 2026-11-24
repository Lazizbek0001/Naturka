@echo off
chcp 65001 >nul
title Naturka - zapusk
cd /d "%~dp0"

rem Python iz virtualnogo okruzheniya; esli ego net - sistemnyy
set "PY=C:\Users\User\.venvs\naturka\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

echo.
echo  Naturka: zapusk servera API (127.0.0.1:8011) i sayta (port 5500)
echo.

rem esli Naturka uzhe zapushchena - ostanovit' (porty 8011 i 5500)
for %%p in (8011 5500) do (
  for /f "tokens=5" %%i in ('netstat -ano ^| findstr /r /c:":%%p .*LISTENING"') do taskkill /pid %%i /t /f >nul 2>&1
)

start "Naturka API" /min cmd /k ""%PY%" main.py"
start "Naturka SITE" /min cmd /k "cd /d "%~dp0frontend" && "%PY%" serve.py 5500"

rem zhdem, poka sayt otvetit
set /a n=0
:wait
ping -n 2 127.0.0.1 >nul
set /a n+=1
powershell -NoProfile -Command "try { (Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 http://localhost:5500/api/docs) | Out-Null; exit 0 } catch { exit 1 }" >nul 2>&1
if errorlevel 1 if %n% lss 30 goto wait

for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do (
  for /f "tokens=*" %%b in ("%%a") do set "IP=%%b"
)

echo  Gotovo.
echo    Na etom kompyutere:  http://localhost:5500
if defined IP echo    Po seti:             http://%IP%:5500
echo.
echo  Servera rabotayut v svernutykh oknakh "Naturka API" i "Naturka SITE".
echo  Chtoby ostanovit' - zakroyte eti okna (ili zapustite stop.bat).
echo.
start "" http://localhost:5500
ping -n 9 127.0.0.1 >nul
