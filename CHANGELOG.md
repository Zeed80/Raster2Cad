# Changelog

**RU** | [EN](CHANGELOG.en.md)

Все заметные изменения в проекте фиксируются в этом файле.

## [0.1.0] - 2026-03-09

### Добавлено

- начальная публичная структура репозитория для backend, frontend, deployment и CI
- Docker и Docker Compose сценарии развертывания
- native deployment examples для `systemd`, `nginx` и `ollama`
- единый каталог моделей для `Ollama` и `vLLM`
- Ollama runtime auto-tuning с ручным override в UI
- постоянные workflow для jobs, artifacts, clarification и chat-edit

### Изменено

- более безопасные Ollama defaults для крупных моделей
- документация переписана под публичный GitHub-репозиторий
