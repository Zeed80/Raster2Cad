from __future__ import annotations

from fastapi import APIRouter

from app.schemas.models import ModelCheckPayload
from app.services.model_registry import ModelRegistry

router = APIRouter(prefix="/models", tags=["models"])


@router.get("")
async def list_models() -> dict[str, list[dict]]:
    registry = ModelRegistry()
    models = await registry.list_models()
    return {"models": [model.model_dump(mode="json") for model in models]}


@router.post("/check")
async def check_model(payload: ModelCheckPayload) -> dict:
    registry = ModelRegistry()
    result = await registry.check_model(payload.provider, payload.model_id, require_vision=payload.require_vision)
    return result.model_dump(mode="json")
