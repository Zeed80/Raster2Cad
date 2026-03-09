FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    libgl1 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./pyproject.toml
COPY app ./app

RUN pip install --upgrade pip && pip install .

RUN useradd --create-home --shell /bin/bash appuser \
    && mkdir -p /app/data/jobs /app/data/uploads /app/data/artifacts \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8010

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8010"]
