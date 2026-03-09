# Raster2Cad

[![CI](https://github.com/Zeed80/Raster2Cad/actions/workflows/ci.yml/badge.svg)](https://github.com/Zeed80/Raster2Cad/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-v0.1.0-blue.svg)](https://github.com/Zeed80/Raster2Cad/tree/v0.1.0)

**RU** | [EN](README.en.md)

Raster2Cad - это мультимодальное приложение для восстановления CAD по двум сценариям:

- точная перерисовка растрового изображения или PDF в детерминированный CAD-результат
- построение изометрии по инженерному чертежу

Стек проекта разделен на:

- `backend/`: FastAPI API, очередь задач, оркестрацию моделей, scene-graph pipeline, генерацию DXF/SVG и артефактов
- `frontend/`: React + Vite UI для загрузки файлов, выбора модели, настройки runtime, превью, уточнений и chat-edit
- `data/`: сохраненные jobs, uploads и artifacts

Проект поддерживает каталоги моделей `Ollama` и `vLLM`. Для `Ollama` в UI доступны автоподбор runtime-параметров по модели и ручной override.

Дополнительная документация:

- [Русский](CONTRIBUTING.md) | [English](CONTRIBUTING.en.md)
- [Русский](SECURITY.md) | [English](SECURITY.en.md)
- [Русский](CHANGELOG.md) | [English](CHANGELOG.en.md)

## Возможности

- FastAPI backend с endpoint-ами загрузки и жизненного цикла jobs
- постоянное файловое хранение jobs и артефактов
- единый каталог моделей для `Ollama` и `vLLM`
- нормализация изображений и PDF с генерацией превью
- извлечение scene graph и детерминированная CAD-компиляция
- экспорт DXF и SVG-изометрии
- overlay и diff-артефакты для QA
- flow уточнений для low-confidence результатов
- chat-based patching для исправления scene graph
- model-specific Ollama runtime tuning в UI

## Структура репозитория

- `backend/`: FastAPI сервис и pipeline моделей
- `frontend/`: React + Vite UI
- `data/`: runtime data volume
- `deploy/nginx/`: пример native-конфига Nginx
- `deploy/ollama/`: пример systemd override для native Ollama
- `deploy/systemd/`: пример systemd unit для backend
- `scripts/`: Windows-скрипты для локального запуска
- `docker-compose.yml`: production-style Docker deployment
- `docker-compose.dev.yml`: Dockerized development workflow
- `.github/workflows/ci.yml`: GitHub Actions CI

## Требования

Практические требования зависят от выбранной модели. Для крупных Ollama-моделей вроде `qwen3.5:35b` рекомендуется отдельный GPU и консервативный размер контекста.

Типичный набор:

- Python `3.11+`
- Node.js `20+`
- npm `10+`
- Docker Engine и Docker Compose plugin для контейнерного развертывания
- опционально: `ODA File Converter` для экспорта DWG
- опционально: native `Ollama` server или внешний `vLLM` endpoint

## Быстрый старт

### Рекомендуемый вариант: Docker Compose + native или внешний Ollama

Это основной предпочтительный способ развертывания приложения.

1. Скопируйте корневой пример окружения:

```bash
cp .env.example .env
```

2. Отредактируйте `.env` и задайте как минимум:

```env
OLLAMA_BASE_URL=http://host.docker.internal:11434
DEFAULT_PROVIDER=ollama
DEFAULT_PRIMARY_MODEL=qwen3.5:35b
```

Если Ollama работает на другой машине, замените `host.docker.internal` на LAN IP или DNS-имя.

3. Поднимите стек:

```bash
docker compose up --build -d
```

4. Откройте:

- frontend: `http://127.0.0.1:8080`
- backend API: `http://127.0.0.1:8010`

Frontend проксирует `/api` и `/artifacts` в backend через Nginx.

### Dockerized development workflow

Используйте этот вариант, если нужен hot reload внутри контейнеров:

```bash
cp .env.example .env
docker compose -f docker-compose.dev.yml up --build
```

URL для разработки:

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

На Windows можно использовать:

- `scripts/start-backend.cmd`
- `scripts/start-frontend.cmd`
- `scripts/start-all.cmd`

## Варианты развертывания

### 1. Приложение в Docker, Ollama native на том же хосте

Укажите:

```env
OLLAMA_BASE_URL=http://host.docker.internal:11434
```

Это лучший компромисс, если приложение хочется держать в контейнерах, а GPU inference оставить вне Docker.

### 2. Приложение в Docker, Ollama native на другом сервере

Укажите:

```env
OLLAMA_BASE_URL=http://192.168.x.x:11434
```

Убедитесь, что Ollama reachable с Docker-хоста и firewall пропускает трафик.

### 3. Полностью native deployment

Используйте:

- `deploy/systemd/raster2cad-backend.service.example`
- `deploy/nginx/raster2cad.conf.example`

Рекомендуемая схема:

- backend как `systemd` service на `127.0.0.1:8010`
- frontend собирается один раз через `npm run build`
- Nginx раздает `frontend/dist` и проксирует `/api` и `/artifacts`

### 4. Backend native, frontend как статический билд

Этот вариант подходит, если backend установлен на workstation или сервере, а frontend обслуживается любым static web server:

```bash
cd frontend
npm install
npm run build
```

Далее раздавайте `frontend/dist` за reverse proxy, который перенаправляет:

- `/api` -> backend
- `/artifacts` -> backend

## Включенные Docker-файлы

- `docker-compose.yml`: production-style deployment
- `docker-compose.dev.yml`: development containers с bind mounts
- `backend/Dockerfile`: Python-образ backend
- `frontend/Dockerfile`: образ статического frontend
- `frontend/nginx.conf`: SPA + API/artifact proxy

## Переменные окружения

### Корневой `.env` для Docker Compose

См. `.env.example`.

Наиболее важные ключи:

- `OLLAMA_BASE_URL`: адрес native или внешнего Ollama
- `VLLM_BASE_URL`: опциональный vLLM-compatible endpoint
- `DEFAULT_PROVIDER`: provider по умолчанию в UI
- `DEFAULT_PRIMARY_MODEL`: parser model по умолчанию
- `OLLAMA_NUM_CTX`: безопасный fallback-контекст backend, если для модели нет отдельных hints
- `OLLAMA_NUM_PREDICT`: безопасный fallback-лимит генерации backend
- `ODA_CONVERTER_PATH`: опциональный путь к DWG converter

### Backend native `.env`

См. `backend/.env.example`.

### Frontend native `.env.local`

См. `frontend/.env.example`.

Для локальной разработки обычно используется:

```env
VITE_API_BASE_URL=http://127.0.0.1:8010/api
```

Для production за Nginx frontend по умолчанию использует относительный `/api`, поэтому отдельная переменная не обязательна.

## Настройка Ollama

Для `Ollama` приложение показывает model-specific runtime hints прямо в UI:

- `num_ctx`
- `num_predict`
- `keep_alive`
- режим `auto_tune` с ручным override

Текущий auto-tune профиль для `qwen3.5:35b`:

- `num_ctx=4096`
- `num_predict=1024`
- `keep_alive=15m`

Для native Ollama на Linux базовый `systemd` override есть в:

- `deploy/ollama/override.conf.example`

Типовой workflow:

```bash
sudo systemctl edit ollama
# вставьте содержимое deploy/ollama/override.conf.example
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

GitHub Actions настроен в `.github/workflows/ci.yml`.

Сейчас workflow:

- устанавливает backend package
- компилирует Python source через `compileall`
- устанавливает frontend dependencies через `npm ci`
- запускает `npm run build`

## Лицензия

Проект распространяется по MIT License. См. `LICENSE`.

## Публикация и релизы

Перед публичным релизом проверьте:

1. `.gitignore`
2. что `data/`, логи, `.env.local` и локальные артефакты не попадают в commit
3. `LICENSE`, `CHANGELOG.md` и deployment defaults

Базовый push flow:

```bash
git add .
git commit -m "Initial open-source release"
git branch -M main
git remote add origin https://github.com/<owner>/raster2cad.git
git push -u origin main
```

## Устранение проблем

### Frontend запускается, но не видит API

- для native dev проверьте `frontend/.env.local`
- для Docker production убедитесь, что frontend раздается через Nginx и использует относительный `/api`
- проверьте доступность backend на `127.0.0.1:8010`

### Большая Ollama-модель подвисает

- уменьшите `num_ctx`
- уменьшите `num_predict`
- установите `OLLAMA_NUM_PARALLEL=1`
- установите `OLLAMA_MAX_LOADED_MODELS=1`
- проверьте через `ollama ps`, что модель не уходит слишком сильно в CPU

### DWG export не работает

Для DWG нужен `ODA File Converter` и корректный `ODA_CONVERTER_PATH`.

### Docker backend не может достучаться до native Ollama

- используйте `host.docker.internal` для Ollama на том же хосте
- либо укажите удаленный IP в `OLLAMA_BASE_URL`
- проверьте firewall и bind-настройки на Ollama-хосте

## Примечания

- Backend не позволяет модели генерировать DXF напрямую. Модель возвращает структурированные scene data, а CAD строится детерминированно.
- `data/` предназначен как runtime volume, а не как исходный контент репозитория.
- Примеры в `Example/` можно оставить как demo-материалы публичного репозитория.
