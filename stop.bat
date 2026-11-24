@echo off
title Naturka - ostanovka
rem ostanavlivaem tol'ko to, chto slushayet porty Naturka: 8011 (API) i 5500 (sayt)
for %%p in (8011 5500) do (
  for /f "tokens=5" %%i in ('netstat -ano ^| findstr /r /c:":%%p .*LISTENING"') do taskkill /pid %%i /t /f >nul 2>&1
)
echo Naturka ostanovlena.
ping -n 4 127.0.0.1 >nul
