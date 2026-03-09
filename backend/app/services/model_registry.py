from __future__ import annotations

from app.core.config import get_settings
from app.schemas.models import CapabilityProfile, ModelCheckResult, ModelDescriptor, ModelRuntimeOptions, ProviderType
from app.services.providers.base import BaseModelProvider
from app.services.providers.ollama_native import OllamaNativeProvider
from app.services.providers.openai_compat import OpenAICompatibleProvider
from app.services.runtime_profile import recommend_runtime_hints


class ModelRegistry:
    def __init__(self) -> None:
        settings = get_settings()
        self.providers = {
            ProviderType.VLLM: OpenAICompatibleProvider(
                provider=ProviderType.VLLM,
                base_url=settings.vllm_base_url,
                timeout_s=settings.provider_timeout_s,
            ),
            ProviderType.OLLAMA: OllamaNativeProvider(
                base_url=settings.ollama_base_url,
                timeout_s=settings.provider_timeout_s,
                num_ctx=settings.ollama_num_ctx,
                num_predict=settings.ollama_num_predict,
            ),
        }

    async def list_models(self) -> list[ModelDescriptor]:
        models: list[ModelDescriptor] = []
        for provider in self.providers.values():
            models.extend(await provider.list_models())

        if models:
            return models

        default = get_settings().default_primary_model
        return [
            ModelDescriptor(
                id=default,
                display_name=default,
                provider=ProviderType.OLLAMA,
                recommended=True,
                capabilities=CapabilityProfile(
                    vision=True,
                    reasoning=True,
                    tool_calling=False,
                    structured_json=True,
                    provider=ProviderType.OLLAMA,
                    role_fit=["parser", "critic", "patcher", "iso-generator"],
                ),
                runtime_hints=recommend_runtime_hints(provider=ProviderType.OLLAMA, model_id=default, details={}),
            )
        ]

    async def find_model(self, provider: ProviderType, model_id: str) -> ModelDescriptor | None:
        for item in await self.providers[provider].list_models():
            if item.id == model_id:
                return item
        return None

    async def check_model(
        self,
        provider: ProviderType,
        model_id: str,
        *,
        require_vision: bool,
        runtime_options: ModelRuntimeOptions | None = None,
    ) -> ModelCheckResult:
        return await self.providers[provider].check_model(
            model_id=model_id,
            require_vision=require_vision,
            runtime_options=runtime_options,
        )

    def get_provider(self, provider: ProviderType) -> BaseModelProvider:
        return self.providers[provider]
