# Raster2Cad

[![CI](https://github.com/Zeed80/Raster2Cad/actions/workflows/ci.yml/badge.svg)](https://github.com/Zeed80/Raster2Cad/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-v0.1.0-blue.svg)](https://github.com/Zeed80/Raster2Cad/tree/v0.1.0)

[RU](README.md) | **EN**

Raster2Cad is a multimodal CAD rebuild application for two workflows:

- exact-copy redraw from raster or PDF source into deterministic CAD output
- isometric reconstruction from engineering drawings

The stack is split into:

- `backend/`: FastAPI API, job queue, model orchestration, scene-graph pipeline, DXF/SVG/artifact generation
- `frontend/`: React + Vite UI for uploads, model selection, runtime tuning, previews, clarifications, and chat edits
- `data/`: persisted jobs, uploads, and artifacts

The application supports `Ollama` and `vLLM` model catalogs. For Ollama, the UI exposes model-specific auto-tuned runtime settings with manual override.

Additional documentation:

- [Russian](CONTRIBUTING.md) | [English](CONTRIBUTING.en.md)
- [Russian](SECURITY.md) | [English](SECURITY.en.md)
- [Russian](CHANGELOG.md) | [English](CHANGELOG.en.md)

## Features

- FastAPI backend with upload and job lifecycle endpoints
- persistent file-backed jobs and artifact storage
- unified model catalog across `Ollama` and `vLLM`
- image and PDF normalization plus preview generation
- scene-graph extraction and deterministic CAD compilation
- DXF export and SVG isometric output
- overlay and diff artifacts for QA
- clarification flow for low-confidence parses
- chat-based patching for scene-graph corrections
- model-specific Ollama runtime tuning in the UI

## Repository Layout

- `backend/`: FastAPI service and model pipeline
- `frontend/`: React + Vite UI
- `data/`: runtime data volume
- `deploy/nginx/`: native Nginx example config
- `deploy/ollama/`: native Ollama systemd override example
- `deploy/systemd/`: native backend service example
- `scripts/`: Windows helper launchers
- `docker-compose.yml`: production-style Docker deployment
- `docker-compose.dev.yml`: Dockerized development workflow
- `.github/workflows/ci.yml`: GitHub Actions CI

## Requirements

Practical requirements depend on the selected model. For large Ollama models such as `qwen3.5:35b`, use a dedicated GPU and keep context conservative.

Typical requirements:

- Python `3.11+`
- Node.js `20+`
- npm `10+`
- Docker Engine and Docker Compose plugin for container deployment
- optional: `ODA File Converter` for DWG export
- optional: native `Ollama` server or external `vLLM` endpoint

## Quick Start

### Recommended: Docker Compose plus native or external Ollama

This is the preferred deployment path for the app itself.

1. Copy the root environment example:

```bash
cp .env.example .env
```

2. Edit `.env` and set at least:

```env
OLLAMA_BASE_URL=http://host.docker.internal:11434
DEFAULT_PROVIDER=ollama
DEFAULT_PRIMARY_MODEL=qwen3.5:35b
```

If Ollama runs on another machine, replace `host.docker.internal` with its LAN IP or DNS name.

3. Start the stack:

```bash
docker compose up --build -d
```

4. Open:

- frontend: `http://127.0.0.1:8080`
- backend API: `http://127.0.0.1:8010`

The frontend proxies `/api` and `/artifacts` to the backend through Nginx.

### Dockerized development workflow

Use this when you want hot reload inside containers:

```bash
cp .env.example .env
docker compose -f docker-compose.dev.yml up --build
```

Development URLs:

- frontend: `http://127.0.0.1:5173`
- backend: `http://127.0.0.1:8010`

### Native local development

Backend:

```bash
cd backend
python -m venv .venv
. .venv/bin/activate
pip install -U pip
pip install -e .
cp .env.example .env
python -m uvicorn app.main:app --host 127.0.0.1 --port 8010
```

Frontend:

```bash
cd frontend
npm install
cp .env.example .env.local
npm run dev -- --host 127.0.0.1 --port 5173
```

On Windows you can also use:

- `scripts/start-backend.cmd`
- `scripts/start-frontend.cmd`
- `scripts/start-all.cmd`

## Deployment Variants

### 1. App in Docker, Ollama native on the same host

Set:

```env
OLLAMA_BASE_URL=http://host.docker.internal:11434
```

This is the best compromise if you want the app containerized but GPU inference outside Docker.

### 2. App in Docker, Ollama native on another server

Set:

```env
OLLAMA_BASE_URL=http://192.168.x.x:11434
```

Make sure the Ollama server is reachable from the Docker host and firewall rules allow access.

### 3. Full native deployment

Use:

- `deploy/systemd/raster2cad-backend.service.example`
- `deploy/nginx/raster2cad.conf.example`

Suggested layout:

- backend as a `systemd` service on `127.0.0.1:8010`
- frontend built once with `npm run build`
- Nginx serving `frontend/dist` and proxying `/api` and `/artifacts`

### 4. Backend native, frontend as a static build

This is useful if the backend is installed on a workstation or server and the frontend is served by any static web server:

```bash
cd frontend
npm install
npm run build
```

Then serve `frontend/dist` behind a reverse proxy that forwards:

- `/api` -> backend
- `/artifacts` -> backend

## Included Docker Files

- `docker-compose.yml`: production-style deployment
- `docker-compose.dev.yml`: development containers with bind mounts
- `backend/Dockerfile`: Python backend image
- `frontend/Dockerfile`: static frontend image
- `frontend/nginx.conf`: SPA plus API/artifact proxy

## Environment Variables

### Root `.env` for Docker Compose

See `.env.example`.

Most important keys:

- `OLLAMA_BASE_URL`: native or external Ollama endpoint
- `VLLM_BASE_URL`: optional vLLM-compatible endpoint
- `DEFAULT_PROVIDER`: default UI provider
- `DEFAULT_PRIMARY_MODEL`: default parser model
- `OLLAMA_NUM_CTX`: safe backend fallback context when no per-model hint is available
- `OLLAMA_NUM_PREDICT`: safe backend fallback output budget
- `ODA_CONVERTER_PATH`: optional path for DWG conversion

### Backend native `.env`

See `backend/.env.example`.

### Frontend native `.env.local`

See `frontend/.env.example`.

For local development the usual value is:

```env
VITE_API_BASE_URL=http://127.0.0.1:8010/api
```

For production behind Nginx, the frontend defaults to relative `/api`, so no extra variable is required.

## Ollama Guidance

The application exposes model-specific runtime hints in the UI for Ollama:

- `num_ctx`
- `num_predict`
- `keep_alive`
- `auto_tune` mode with manual override

Current auto-tune profile for `qwen3.5:35b`:

- `num_ctx=4096`
- `num_predict=1024`
- `keep_alive=15m`

For native Ollama on Linux, a good starting `systemd` override is included at:

- `deploy/ollama/override.conf.example`

Typical workflow:

```bash
sudo systemctl edit ollama
# paste deploy/ollama/override.conf.example contents
sudo systemctl daemon-reload
sudo systemctl restart ollama
ollama ps
```

## API

- `GET /api/models`
- `POST /api/jobs`
- `GET /api/jobs/{job_id}`
- `GET /api/jobs/{job_id}/artifacts`
- `POST /api/jobs/{job_id}/clarification`
- `POST /api/jobs/{job_id}/chat-edit`
- `PATCH /api/jobs/{job_id}/view`

## CI

GitHub Actions is configured in `.github/workflows/ci.yml`.

The workflow currently:

- installs the backend package
- compiles Python sources with `compileall`
- installs frontend dependencies with `npm ci`
- runs `npm run build`

## License

This project is licensed under the MIT License. See `LICENSE`.

## Publishing and Releases

Before a public release, verify:

1. `.gitignore`
2. that `data/`, logs, `.env.local`, and local artifacts are not staged
3. `LICENSE`, `CHANGELOG.md`, and deployment defaults

Basic push flow:

```bash
git add .
git commit -m "Initial open-source release"
git branch -M main
git remote add origin https://github.com/<owner>/raster2cad.git
git push -u origin main
```

## Troubleshooting

### Frontend starts but cannot reach the API

- for native dev, check `frontend/.env.local`
- for Docker production, confirm the frontend is served through Nginx and uses relative `/api`
- verify backend is reachable on `127.0.0.1:8010`

### Large Ollama model stalls

- reduce `num_ctx`
- reduce `num_predict`
- set `OLLAMA_NUM_PARALLEL=1`
- set `OLLAMA_MAX_LOADED_MODELS=1`
- verify with `ollama ps` that the model is not spilling too much into CPU

### DWG export does not work

DWG export requires `ODA File Converter` and a valid `ODA_CONVERTER_PATH`.

### Docker backend cannot reach native Ollama

- use `host.docker.internal` for same-host native Ollama
- or point `OLLAMA_BASE_URL` to the remote machine IP
- verify firewall and bind settings on the Ollama host

## Notes

- The backend does not let the model emit DXF directly. The model returns structured scene data, and CAD is built deterministically.
- `data/` is intended as a runtime volume, not as source content for the repository.
- Example files under `Example/` can remain as demo material for the public repository.
