from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from app.schemas.models import EngineeringSceneGraph, ModelCheckResult, ModelDescriptor, ModelRuntimeOptions


class BaseModelProvider(ABC):
    @abstractmethod
    async def list_models(self) -> list[ModelDescriptor]:
        raise NotImplementedError

    @abstractmethod
    async def check_model(
        self,
        *,
        model_id: str,
        require_vision: bool,
        runtime_options: ModelRuntimeOptions | None = None,
    ) -> ModelCheckResult:
        raise NotImplementedError

    @abstractmethod
    async def parse_drawing(
        self,
        *,
        model_id: str,
        source_path: Path,
        prompt: str,
        system_prompt: str | None = None,
        response_schema: dict[str, Any] | None = None,
        temperature: float = 0.0,
        runtime_options: ModelRuntimeOptions | None = None,
    ) -> EngineeringSceneGraph | None:
        raise NotImplementedError

    @abstractmethod
    async def critique_drawing(
        self,
        *,
        model_id: str,
        prompt: str,
        runtime_options: ModelRuntimeOptions | None = None,
    ) -> list[str]:
        raise NotImplementedError

    @abstractmethod
    async def patch_scene_graph(
        self,
        *,
        model_id: str,
        scene_graph: EngineeringSceneGraph,
        instruction: str,
        runtime_options: ModelRuntimeOptions | None = None,
    ) -> EngineeringSceneGraph | None:
        raise NotImplementedError
