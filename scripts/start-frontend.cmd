@echo off
setlocal

if "%VITE_API_BASE_URL%"=="" set "VITE_API_BASE_URL=http://127.0.0.1:8010/api"

cd /d "%~dp0..\frontend"
npm.cmd run dev -- --host 0.0.0.0 --port 5173
