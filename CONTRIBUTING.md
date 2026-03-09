# Contributing

**RU** | [EN](CONTRIBUTING.en.md)

## Область изменений

Приветствуются pull request-ы по следующим направлениям:

- исправления багов
- улучшения развертывания
- улучшения usability во frontend и backend
- интеграции с model provider-ами
- документация

## Разработка

Используйте один из workflow, описанных в `README.md` или `README.en.md`:

- native backend + native frontend
- production-style стек на Docker Compose
- Dockerized development stack

Перед открытием pull request:

1. соберите frontend через `npm run build` в `frontend/`
2. проверьте backend-импорты через `python -m compileall backend/app`
3. не коммитьте runtime data, локальные логи и `.env.local`

## Pull Request

- держите изменения сфокусированными
- описывайте user-visible impact
- указывайте environment assumptions, если меняете deployment behavior
- обновляйте `README.md`, `README.en.md` и `.env.example`, если меняется конфигурация

## Issues

При создании bug report по возможности укажите:

- provider: `Ollama` или `vLLM`
- model id
- runtime settings, если вы меняли `num_ctx`, `num_predict` или `keep_alive`
- тип исходного файла: PNG, JPG, TIFF или PDF
- backend error message или stack trace
