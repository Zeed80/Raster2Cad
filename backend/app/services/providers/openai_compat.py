from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import httpx

from app.schemas.models import CapabilityProfile, EngineeringSceneGraph, ModelCheckResult, ModelDescriptor, ModelRuntimeOptions, ProviderType
from app.services.scene_graph_contract import copy_system_prompt, full_scene_graph_schema
from app.services.providers.base import BaseModelProvider
from app.services.scene_graph_normalizer import normalize_scene_graph_payload

TINY_PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAIAAAACACAIAAABMXPacAAACeElEQVR4nO3csWrqUByAcb3t4GZn"
    "H6EOJbpYMup7dPGJhEKhiHTpM1jqqg6CY3yALG66iOLyv0PA+do290P7/aYkEI7k45wg4qlGREWc"
    "P+DYMgDPADADwAwAMwDMADADwAwAMwDMADADwAwAMwDMALDbc2+oVqvlfJLrcdZPLM6AS5sBBX9H"
    "+6nlwRkAMwDMADADwAwAMwDMADADwAwAMwDMADADwAwAMwDMADADwAwAMwDMADADwAwAMwDMADAD"
    "wAwAMwDMADADwAwAMwDMADADwAwAMwDMADADwAxwpQFGo1G73X58fGy3229vb8XFu7u74iDP8yRJ"
    "1ut1SaNfkjjTv9w1Ho/TNN1sNhGx2WzSNP38/IyIer0eEfv9Pk3T+XweV+cLj7SUAN1udzabnU6n"
    "02mv1zsFeHp6en19jWtUOT9AKUvQarVKkuR02mq1siwrjgeDQa1W6/f7ZYx7if7HSzgiir+QH4/H"
    "5+dnl/7SA9zf3y+Xy9PpcrlsNpuVSuXm5maxWOx2u5eXlzLGvUhlLHMfHx9pmm6329NLeDKZnN4B"
    "eZ43Go0sy+LqfOGRlhIgIobDYZIknU6n1WqNRqPiYhEgIt7f3x8eHg6HQ8RvD1A9d9+TYjV3t5Sf"
    "ejh+E4YZAGYAmAFgBoAZAGYAmAFgBoAZAGYAmAFgBoAZAGYAmAFgBoAZAGYAmAFgBoAZAGYAmAFg"
    "BoAZAGYAmAFgBoAZAGYAmAFgBoAZAGYAmAFgBoAZAGYAmAFgBoAZAGYAmAFgBoAZAHb7nX1Z9H3O"
    "ANjZGzbpZzkDYAaAGQBmAJgBYAaAGQBmAJgBYAaAGQBmAJgBYAaosP4CpBzX7Kkv4AcAAAAASUVO"
    "RK5CYII="
)


class OpenAICompatibleProvider(BaseModelProvider):
    def __init__(self, *, provider: ProviderType, base_url: str, timeout_s: float) -> None:
        self.provider = provider
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s

    async def list_models(self) -> list[ModelDescriptor]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                response = await client.get(f"{self.base_url}/models")
                response.raise_for_status()
        except Exception:
            return []

        payload = response.json()
        models: list[ModelDescriptor] = []
        for item in payload.get("data", []):
            model_id = item.get("id", "")
            models.append(
                ModelDescriptor(
                    id=model_id,
                    display_name=model_id,
                    provider=self.provider,
                    capabilities=self._capabilities_for(model_id),
                    recommended=model_id.lower() == "qwen3.5:35b",
                    summary=model_id,
                    details=item,
                )
            )
        return models

    async def check_model(
        self,
        *,
        model_id: str,
        require_vision: bool,
        runtime_options: ModelRuntimeOptions | None = None,
    ) -> ModelCheckResult:
        result = ModelCheckResult(provider=self.provider, model_id=model_id)
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                models_response = await client.get(f"{self.base_url}/models")
                models_response.raise_for_status()
                result.reachable = True
                models_payload = models_response.json().get("data", [])
                descriptor = next((item for item in models_payload if str(item.get("id", "")).lower() == model_id.lower()), None)
                if descriptor is None:
                    result.error = f"Model {model_id} is not present in the provider catalog."
                    return result

                result.available = True
                capabilities = self._capabilities_for(model_id)
                result.vision_capable = capabilities.vision
                result.details = descriptor

                text_payload: dict[str, Any] = {
                    "model": model_id,
                    "messages": [{"role": "user", "content": "Reply with exactly ok."}],
                }
                text_response = await client.post(f"{self.base_url}/chat/completions", json=text_payload)
                if text_response.is_success:
                    result.can_text = True
                else:
                    result.error = self._response_error(text_response)
                    return result

                if require_vision:
                    if not result.vision_capable:
                        result.error = f"Model {model_id} is not marked as vision-capable."
                        return result
                    vision_payload: dict[str, Any] = {
                        "model": model_id,
                        "messages": [
                            {
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": "Look at the image and reply with exactly ok."},
                                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{TINY_PNG_BASE64}"}},
                                ],
                            }
                        ],
                    }
                    vision_response = await client.post(f"{self.base_url}/chat/completions", json=vision_payload)
                    if vision_response.is_success:
                        result.can_vision = True
                    else:
                        result.error = self._response_error(vision_response)
                        return result

                result.ok = result.can_text and (result.can_vision if require_vision else True)
                return result
        except Exception as exc:
            result.error = str(exc)
            return result

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
        encoded = base64.b64encode(source_path.read_bytes()).decode("utf-8")
        effective_system_prompt = system_prompt or copy_system_prompt()
        if response_schema:
            effective_system_prompt = (
                f"{effective_system_prompt} "
                f"Conform to this JSON schema exactly: {json.dumps(response_schema, ensure_ascii=False)}"
            )
        payload: dict[str, Any] = {
            "model": model_id,
            "messages": [
                {
                    "role": "system",
                    "content": effective_system_prompt,
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded}"}},
                    ],
                },
            ],
            "response_format": {"type": "json_object"},
            "temperature": temperature,
        }
        if runtime_options and runtime_options.num_predict:
            payload["max_tokens"] = runtime_options.num_predict
        response_text = await self._chat(payload)
        if not response_text:
            return None
        try:
            return normalize_scene_graph_payload(self._extract_json(response_text))
        except Exception:
            return None

    async def critique_drawing(
        self,
        *,
        model_id: str,
        prompt: str,
        runtime_options: ModelRuntimeOptions | None = None,
    ) -> list[str]:
        payload = {
            "model": model_id,
            "messages": [
                {"role": "system", "content": "Return concise critique findings as short plain-text lines."},
                {"role": "user", "content": prompt},
            ],
        }
        if runtime_options and runtime_options.num_predict:
            payload["max_tokens"] = min(runtime_options.num_predict, 512)
        response_text = await self._chat(payload)
        if not response_text:
            return []
        return [line.strip("- ").strip() for line in response_text.splitlines() if line.strip()]

    async def patch_scene_graph(
        self,
        *,
        model_id: str,
        scene_graph: EngineeringSceneGraph,
        instruction: str,
        runtime_options: ModelRuntimeOptions | None = None,
    ) -> EngineeringSceneGraph | None:
        payload: dict[str, Any] = {
            "model": model_id,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        f"{copy_system_prompt()} "
                        "You update engineering scene graphs after user CAD editing instructions. "
                        "Preserve unchanged entities and never drop objects unless deletion is explicitly requested. "
                        f"Conform to this JSON schema exactly: {json.dumps(full_scene_graph_schema(), ensure_ascii=False)} "
                        "Return JSON only."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Current counts: objects={len(scene_graph.objects)}, texts={len(scene_graph.texts)}, dimensions={len(scene_graph.dimensions)}.\n"
                        "Return the full updated scene graph with the same top-level keys as the input JSON.\n\n"
                        "Current scene graph JSON:\n"
                        f"{scene_graph.model_dump_json(indent=2)}\n\n"
                        f"User instruction:\n{instruction}"
                    ),
                },
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.0,
        }
        if runtime_options and runtime_options.num_predict:
            payload["max_tokens"] = runtime_options.num_predict
        response_text = await self._chat(payload)
        if not response_text:
            return None
        try:
            patched = normalize_scene_graph_payload(self._extract_json(response_text))
        except Exception:
            return None
        patched.notes.append(f"Patched by model {model_id} from chat instruction.")
        return patched

    async def _chat(self, payload: dict[str, Any]) -> str | None:
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                response = await client.post(f"{self.base_url}/chat/completions", json=payload)
                response.raise_for_status()
        except Exception:
            return None

        data = response.json()
        message = data.get("choices", [{}])[0].get("message", {})
        content = message.get("content", "")
        if isinstance(content, list):
            return "".join(part.get("text", "") for part in content if isinstance(part, dict))
        return str(content)

    def _capabilities_for(self, model_id: str) -> CapabilityProfile:
        lowered = model_id.lower()
        vision = any(token in lowered for token in ("vl", "vision", "omni", "qwen3.5"))
        role_fit = ["critic", "patcher"]
        if vision:
            role_fit = ["parser", "critic", "patcher", "iso-generator"]
        return CapabilityProfile(
            vision=vision,
            reasoning=True,
            tool_calling=True,
            structured_json=True,
            provider=self.provider,
            role_fit=role_fit,
        )

    def _extract_json(self, response_text: str) -> dict[str, Any]:
        text = response_text.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if "\n" in text:
                text = text.split("\n", 1)[1]
            if text.endswith("```"):
                text = text[:-3]
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                return json.loads(text[start : end + 1])
            raise

    def _response_error(self, response: httpx.Response) -> str:
        try:
            payload = response.json()
            if isinstance(payload, dict):
                error = payload.get("error")
                if isinstance(error, dict) and error.get("message"):
                    return str(error["message"])
                if error:
                    return str(error)
        except Exception:
            pass
        return response.text.strip() or f"HTTP {response.status_code}"
