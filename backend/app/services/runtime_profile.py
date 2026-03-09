from __future__ import annotations

import re
from typing import Any, Mapping

from app.schemas.models import ModelRuntimeHints, ModelRuntimeOptions, ProviderType


def recommend_runtime_hints(
    *,
    provider: ProviderType,
    model_id: str,
    details: Mapping[str, Any] | None = None,
) -> ModelRuntimeHints | None:
    if provider != ProviderType.OLLAMA:
        return None

    lowered = model_id.lower()
    size_b = _extract_parameter_size_billions(model_id=model_id, details=details)
    vision = _is_vision_model(model_id=model_id, details=details)

    if size_b is None and "35b" in lowered:
        size_b = 35.0
    elif size_b is None and any(token in lowered for token in ("70b", "72b")):
        size_b = 70.0
    elif size_b is None and any(token in lowered for token in ("30b", "32b", "34b")):
        size_b = 32.0
    elif size_b is None and any(token in lowered for token in ("24b", "27b")):
        size_b = 24.0
    elif size_b is None and any(token in lowered for token in ("14b", "12b")):
        size_b = 14.0
    elif size_b is None and any(token in lowered for token in ("8b", "9b", "7b")):
        size_b = 8.0
    elif size_b is None and any(token in lowered for token in ("4b", "3b", "2b", "1b")):
        size_b = 4.0

    if size_b is not None and size_b >= 60:
        return ModelRuntimeHints(
            num_ctx=2048,
            num_predict=512,
            keep_alive="10m",
            rationale="70B-class models on a single GPU are memory-bound; keep context conservative.",
        )
    if size_b is not None and size_b >= 30:
        return ModelRuntimeHints(
            num_ctx=4096,
            num_predict=1024,
            keep_alive="15m",
            rationale="30B-35B models fit more reliably with a 4k context and shorter generations.",
        )
    if size_b is not None and size_b >= 20:
        return ModelRuntimeHints(
            num_ctx=6144,
            num_predict=1024,
            keep_alive="15m",
            rationale="20B+ models benefit from a moderate context to avoid CPU offload and long stalls.",
        )
    if size_b is not None and size_b >= 10:
        return ModelRuntimeHints(
            num_ctx=8192,
            num_predict=1536,
            keep_alive="15m",
            rationale="Mid-size models can usually sustain an 8k context without excessive VRAM pressure.",
        )
    if size_b is not None and size_b >= 5:
        return ModelRuntimeHints(
            num_ctx=12288 if not vision else 8192,
            num_predict=2048,
            keep_alive="10m",
            rationale="Smaller 7B-9B models can use a larger context, but vision variants still need headroom.",
        )
    return ModelRuntimeHints(
        num_ctx=8192 if vision else 16384,
        num_predict=2048,
        keep_alive="10m",
        rationale="Default conservative profile for small Ollama models.",
    )


def resolve_runtime_options(
    *,
    provider: ProviderType,
    model_id: str,
    details: Mapping[str, Any] | None,
    requested: ModelRuntimeOptions,
    default_num_ctx: int,
    default_num_predict: int,
) -> ModelRuntimeOptions:
    hints = recommend_runtime_hints(provider=provider, model_id=model_id, details=details)
    base_num_ctx = hints.num_ctx if hints else default_num_ctx
    base_num_predict = hints.num_predict if hints else default_num_predict
    base_keep_alive = hints.keep_alive if hints else None

    return ModelRuntimeOptions(
        auto_tune=requested.auto_tune,
        num_ctx=max(1024, requested.num_ctx or base_num_ctx),
        num_predict=max(64, requested.num_predict or base_num_predict),
        keep_alive=(requested.keep_alive or base_keep_alive),
    )


def _extract_parameter_size_billions(*, model_id: str, details: Mapping[str, Any] | None) -> float | None:
    candidates = []
    if details:
        candidates.append(details.get("parameter_size"))
    candidates.append(model_id)

    for raw in candidates:
        value = _parse_billions(raw)
        if value is not None:
            return value
    return None


def _parse_billions(raw: Any) -> float | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    match = re.search(r"(\d+(?:\.\d+)?)\s*([bBmM])", text)
    if not match:
        return None
    value = float(match.group(1))
    unit = match.group(2).lower()
    if unit == "m":
        return value / 1000.0
    return value


def _is_vision_model(*, model_id: str, details: Mapping[str, Any] | None) -> bool:
    lowered = model_id.lower()
    families = []
    family = ""
    if details:
        families = [str(item).lower() for item in details.get("families", []) if isinstance(item, str)]
        family = str(details.get("family", "")).lower()
    return (
        "vision" in lowered
        or "vl" in lowered
        or "omni" in lowered
        or "qwen3.5" in lowered
        or "qwen35vl" in families
        or "qwen3vl" in families
        or family in {"qwen35vl", "qwen3vl"}
    )
