from __future__ import annotations

import asyncio
import sys

from app.config import get_settings
from app.memory.redis_agent_memory import RedisAgentMemory
from app.observability.weave_client import WeaveClient
from app.providers.base import ProviderError
from app.providers.router import ProviderRouter


async def main() -> int:
    settings = get_settings()
    router = ProviderRouter(settings)
    failures = 0
    display_names = {
        "openai": "OpenAI",
        "anthropic": "Anthropic",
        "gemini": "Gemini",
        "openrouter": "OpenRouter",
    }

    for provider_name in ["openai", "anthropic", "gemini", "openrouter"]:
        try:
            model, _latency_ms = await router.check_provider(provider_name)
            print(f"[ok] {display_names[provider_name]} generated with {model}")
        except ProviderError as exc:
            failures += 1
            print(f"[fail] {display_names[provider_name]}: {exc.error_code}")

    if settings.census_api_key:
        print("[ok] Census API key configured")
    else:
        failures += 1
        print("[fail] Census API key missing")

    print(f"[ok] PUMS data directory configured: {settings.pums_data_dir}")

    redis = RedisAgentMemory(settings)
    try:
        await redis.check_connection()
        print("[ok] Redis Agent Memory connected")
    except Exception as exc:  # noqa: BLE001
        failures += 1
        print(f"[fail] Redis Agent Memory: {exc.__class__.__name__}")

    weave = WeaveClient(settings)
    weave.init()
    if weave.initialized:
        print(f"[ok] Weave configured: {settings.weave_project_name}")
    else:
        failures += 1
        print("[fail] Weave initialization failed")

    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
