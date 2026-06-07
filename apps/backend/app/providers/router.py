from __future__ import annotations

import logging
from typing import Any

from app.config import Settings
from app.providers.anthropic_provider import AnthropicProvider
from app.providers.base import BaseProvider, ProviderError, ProviderResult
from app.providers.gemini_provider import GeminiProvider
from app.providers.openai_provider import OpenAIProvider
from app.providers.openrouter_provider import OpenRouterProvider
from app.schemas import Persona


logger = logging.getLogger(__name__)

PROVIDER_MODELS = {
    "openai": "gpt-4o-mini",
    "anthropic": "claude-haiku-4-5-20251001",
    "gemini": "gemini-2.5-flash",
    "openrouter": "openai/gpt-4o-mini",
}

# Temporary credit-saving mode: route demo persona traffic to OpenAI first.
FULL_DEMO_PROVIDER_PLAN = ["openai"] * 20
SMOKE_PROVIDER_PLAN = ["openai", "openai", "openai"]
FALLBACKS = {
    "openrouter": ["openai"],
    "gemini": ["openai"],
    "anthropic": ["openai"],
    "openai": ["anthropic", "gemini", "openrouter"],
}


class ProviderRouter:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.providers = self._build_providers(settings)

    def _build_providers(self, settings: Settings) -> dict[str, BaseProvider]:
        providers: dict[str, BaseProvider] = {}
        if settings.openai_api_key:
            providers["openai"] = OpenAIProvider(settings.openai_api_key)
        if settings.anthropic_api_key:
            providers["anthropic"] = AnthropicProvider(settings.anthropic_api_key)
        if settings.gemini_api_key:
            providers["gemini"] = GeminiProvider(settings.gemini_api_key)
        if settings.openrouter_api_key:
            providers["openrouter"] = OpenRouterProvider(settings.openrouter_api_key)
        return providers

    def configured_provider_names(self) -> list[str]:
        return list(self.providers.keys())

    def assign_personas(self, personas: list[Persona]) -> list[Persona]:
        total = len(personas)
        if total == 20:
            plan = FULL_DEMO_PROVIDER_PLAN
        elif total <= 3:
            plan = SMOKE_PROVIDER_PLAN[:total]
        else:
            plan = ["openai"] * total

        assigned: list[Persona] = []
        for index, persona in enumerate(personas):
            provider_name = plan[index % len(plan)]
            assigned.append(
                persona.model_copy(
                    update={
                        "assigned_provider": provider_name,
                        "assigned_model": PROVIDER_MODELS[provider_name],
                    }
                )
            )
        return assigned

    def _candidate_providers(self, preferred_provider: str | None) -> list[str]:
        ordered: list[str] = []
        if preferred_provider:
            ordered.append(preferred_provider)
            ordered.extend(FALLBACKS.get(preferred_provider, []))
        ordered.extend(["openai", "anthropic", "gemini", "openrouter"])

        deduped: list[str] = []
        for provider in ordered:
            if provider not in deduped and provider in self.providers:
                deduped.append(provider)
        return deduped

    async def generate_json(
        self,
        *,
        preferred_provider: str | None,
        prompt: str,
        schema_hint: str,
        model: str | None = None,
        max_tokens: int = 900,
        temperature: float = 0.4,
    ) -> ProviderResult:
        attempts: list[str] = []
        last_error: ProviderError | None = None
        for provider_name in self._candidate_providers(preferred_provider):
            provider = self.providers[provider_name]
            selected_model = model if provider_name == preferred_provider else PROVIDER_MODELS[provider_name]
            attempts.append(provider_name)
            try:
                payload, latency_ms, used_model = await provider.generate_json(
                    prompt,
                    schema_hint=schema_hint,
                    model=selected_model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
                return ProviderResult(
                    provider=provider_name,
                    model=used_model,
                    payload=payload,
                    latency_ms=latency_ms,
                    fallback_attempts=attempts,
                )
            except ProviderError as exc:
                last_error = exc
                logger.warning("Provider %s failed with %s: %s", provider_name, exc.error_code, exc.safe_message)

        if last_error:
            raise ProviderError("router", last_error.error_code, last_error.safe_message)
        raise ProviderError("router", "no_provider_configured", "No configured model provider was available.")

    async def check_provider(self, provider_name: str) -> tuple[str, int]:
        provider = self.providers.get(provider_name)
        if not provider:
            raise ProviderError(provider_name, "provider_not_configured", f"{provider_name} is not configured.")
        return await provider.check()
