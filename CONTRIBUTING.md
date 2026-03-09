# Contributing

## Scope

Contributions are welcome for:

- bug fixes
- deployment improvements
- frontend and backend usability improvements
- model-provider integrations
- documentation

## Development

Use one of the documented workflows from `README.md`:

- native backend plus native frontend
- Docker Compose production-style stack
- Dockerized development stack

Before opening a pull request:

1. build the frontend with `npm run build` in `frontend/`
2. verify backend imports with `python -m compileall backend/app`
3. do not commit runtime data, local logs, or `.env.local`

## Pull Requests

- keep changes focused
- include a clear description of user-visible impact
- mention environment assumptions when changing deployment behavior
- update `README.md` and `.env.example` when configuration changes

## Issues

When reporting a bug, include:

- provider: `Ollama` or `vLLM`
- model id
- runtime settings if you changed `num_ctx`, `num_predict`, or `keep_alive`
- source file type: PNG, JPG, TIFF, or PDF
- backend error message or stack trace
