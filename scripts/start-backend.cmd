@echo off
setlocal

if "%OLLAMA_BASE_URL%"=="" set "OLLAMA_BASE_URL=http://127.0.0.1:11434"
if "%DEFAULT_PROVIDER%"=="" set "DEFAULT_PROVIDER=ollama"
if "%DEFAULT_PRIMARY_MODEL%"=="" set "DEFAULT_PRIMARY_MODEL=qwen3.5:35b"
if "%ENABLE_LIVE_MODEL_CALLS%"=="" set "ENABLE_LIVE_MODEL_CALLS=true"
if "%ALLOW_FIXTURE_FALLBACK%"=="" set "ALLOW_FIXTURE_FALLBACK=false"
if "%PROVIDER_TIMEOUT_S%"=="" set "PROVIDER_TIMEOUT_S=240"
if "%OLLAMA_NUM_CTX%"=="" set "OLLAMA_NUM_CTX=4096"
if "%OLLAMA_NUM_PREDICT%"=="" set "OLLAMA_NUM_PREDICT=1024"
if "%API_PORT%"=="" set "API_PORT=8010"

cd /d "%~dp0..\backend"

if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port %API_PORT%
) else (
  py -3.11 -m uvicorn app.main:app --host 0.0.0.0 --port %API_PORT%
)
