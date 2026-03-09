@echo off
setlocal
cd /d "%~dp0.."

if not exist logs mkdir logs

start "Raster2Cad Backend" cmd /c "scripts\start-backend.cmd > logs\backend.log 2>&1"
timeout /t 5 /nobreak > nul
start "Raster2Cad Frontend" cmd /c "scripts\start-frontend.cmd > logs\frontend.log 2>&1"

echo Backend log: logs\backend.log
echo Frontend log: logs\frontend.log
