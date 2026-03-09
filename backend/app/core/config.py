from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATA_DIR = REPO_ROOT / "data"


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "Raster2Cad API")
    api_prefix: str = os.getenv("API_PREFIX", "/api")
    data_dir: Path = Path(os.getenv("DATA_DIR", str(DEFAULT_DATA_DIR)))
    jobs_dir: Path = Path(os.getenv("JOBS_DIR", str(DEFAULT_DATA_DIR / "jobs")))
    uploads_dir: Path = Path(os.getenv("UPLOADS_DIR", str(DEFAULT_DATA_DIR / "uploads")))
    artifacts_dir: Path = Path(os.getenv("ARTIFACTS_DIR", str(DEFAULT_DATA_DIR / "artifacts")))
    vllm_base_url: str = os.getenv("VLLM_BASE_URL", "http://127.0.0.1:8000/v1")
    ollama_base_url: str = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    provider_timeout_s: float = float(os.getenv("PROVIDER_TIMEOUT_S", "240"))
    ollama_num_ctx: int = int(os.getenv("OLLAMA_NUM_CTX", "4096"))
    ollama_num_predict: int = int(os.getenv("OLLAMA_NUM_PREDICT", "1024"))
    low_confidence_threshold: float = float(os.getenv("LOW_CONFIDENCE_THRESHOLD", "0.66"))
    critic_iterations: int = int(os.getenv("CRITIC_ITERATIONS", "2"))
    enable_live_model_calls: bool = os.getenv("ENABLE_LIVE_MODEL_CALLS", "true").lower() == "true"
    allow_fixture_fallback: bool = os.getenv("ALLOW_FIXTURE_FALLBACK", "false").lower() == "true"
    default_primary_model: str = os.getenv("DEFAULT_PRIMARY_MODEL", "qwen3.5:35b")
    default_provider: str = os.getenv("DEFAULT_PROVIDER", "ollama")
    oda_converter_path: str | None = os.getenv("ODA_CONVERTER_PATH")



@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.jobs_dir.mkdir(parents=True, exist_ok=True)
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    settings.artifacts_dir.mkdir(parents=True, exist_ok=True)
    return settings
