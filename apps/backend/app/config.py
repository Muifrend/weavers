from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = Path(__file__).resolve().parents[1]
ROOT_ENV_FILE = REPO_ROOT / ".env"
BACKEND_ENV_FILE = BACKEND_ROOT / ".env"


class ConfigurationError(RuntimeError):
    """Raised when required runtime configuration is missing."""


def _parse_bool(value: str | bool | None, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _parse_int(value: str | int | None, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except ValueError:
        return default


def _parse_path(value: str | None, default: Path) -> Path:
    if not value:
        return default
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return (REPO_ROOT / path).resolve()


def _read_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def _load_env() -> dict[str, str]:
    # Repo-root .env is the verified local file. Backend .env can override it.
    values: dict[str, str] = {}
    values.update(_read_env_file(ROOT_ENV_FILE))
    values.update(_read_env_file(BACKEND_ENV_FILE))
    values.update({key: value for key, value in os.environ.items() if value is not None})
    return values


@dataclass(frozen=True)
class Settings:
    openai_api_key: str | None
    census_api_key: str | None
    anthropic_api_key: str | None
    gemini_api_key: str | None
    openrouter_api_key: str | None
    redis_agent_memory_endpoint: str | None
    redis_agent_memory_api_key: str | None
    redis_agent_memory_store_id: str | None
    weave_api_key: str | None
    weave_project_name: str
    backend_env: str
    demo_mode: bool
    persona_count: int
    persona_concurrency_limit: int
    pums_data_dir: Path
    copilot_runtime_url: str

    @classmethod
    def load(cls) -> "Settings":
        env = _load_env()
        return cls(
            openai_api_key=env.get("OPENAI_API_KEY") or None,
            census_api_key=env.get("CENSUS_API_KEY") or None,
            anthropic_api_key=env.get("ANTHROPIC_API_KEY") or None,
            gemini_api_key=env.get("GEMINI_API_KEY") or None,
            openrouter_api_key=env.get("OPENROUTER_API_KEY") or None,
            redis_agent_memory_endpoint=env.get("REDIS_AGENT_MEMORY_ENDPOINT") or None,
            redis_agent_memory_api_key=env.get("REDIS_AGENT_MEMORY_API_KEY") or None,
            redis_agent_memory_store_id=env.get("REDIS_AGENT_MEMORY_STORE_ID") or None,
            weave_api_key=env.get("WEAVE_API_KEY") or None,
            weave_project_name=env.get("WEAVE_PROJECT_NAME") or "campaign-persona-agent",
            backend_env=env.get("BACKEND_ENV") or "local",
            demo_mode=_parse_bool(env.get("DEMO_MODE"), default=True),
            persona_count=_parse_int(env.get("PERSONA_COUNT"), default=20),
            persona_concurrency_limit=_parse_int(env.get("PERSONA_CONCURRENCY_LIMIT"), default=25),
            pums_data_dir=_parse_path(env.get("PUMS_DATA_DIR"), REPO_ROOT / "data" / "pums"),
            copilot_runtime_url=(env.get("COPILOT_RUNTIME_URL") or "http://localhost:3001").rstrip("/"),
        )

    def missing_required(self) -> list[str]:
        required = {
            "OPENAI_API_KEY": self.openai_api_key,
            "CENSUS_API_KEY": self.census_api_key,
            "ANTHROPIC_API_KEY": self.anthropic_api_key,
            "GEMINI_API_KEY": self.gemini_api_key,
            "OPENROUTER_API_KEY": self.openrouter_api_key,
            "REDIS_AGENT_MEMORY_ENDPOINT": self.redis_agent_memory_endpoint,
            "REDIS_AGENT_MEMORY_API_KEY": self.redis_agent_memory_api_key,
            "REDIS_AGENT_MEMORY_STORE_ID": self.redis_agent_memory_store_id,
            "WEAVE_API_KEY": self.weave_api_key,
            "WEAVE_PROJECT_NAME": self.weave_project_name,
        }
        return [name for name, value in required.items() if not value]

    def provider_configured(self, provider: str) -> bool:
        return {
            "openai": bool(self.openai_api_key),
            "anthropic": bool(self.anthropic_api_key),
            "gemini": bool(self.gemini_api_key),
            "openrouter": bool(self.openrouter_api_key),
        }.get(provider, False)

    def configured_providers(self) -> list[str]:
        return [
            provider
            for provider in ("openai", "anthropic", "gemini", "openrouter")
            if self.provider_configured(provider)
        ]

    def redis_configured(self) -> bool:
        return bool(
            self.redis_agent_memory_endpoint
            and self.redis_agent_memory_api_key
            and self.redis_agent_memory_store_id
        )

    def weave_configured(self) -> bool:
        return bool(self.weave_api_key and self.weave_project_name)

    def require_providers(self) -> None:
        if not self.configured_providers():
            raise ConfigurationError("No model providers are configured.")

    def safe_startup_summary(self) -> str:
        provider_lines = [
            f"- OpenAI: {'configured' if self.openai_api_key else 'missing'}",
            f"- Census: {'configured' if self.census_api_key else 'missing'}",
            f"- Anthropic: {'configured' if self.anthropic_api_key else 'missing'}",
            f"- Gemini: {'configured' if self.gemini_api_key else 'missing'}",
            f"- OpenRouter: {'configured' if self.openrouter_api_key else 'missing'}",
        ]
        missing = self.missing_required()
        missing_block = ""
        if missing:
            missing_block = "\n\nMissing required variables:\n" + "\n".join(f"- {name}" for name in missing)

        return (
            "Campaign Persona Agent backend starting...\n\n"
            "Environment:\n"
            f"- BACKEND_ENV: {self.backend_env}\n"
            f"- DEMO_MODE: {str(self.demo_mode).lower()}\n"
            f"- PERSONA_COUNT: {self.persona_count}\n"
            f"- PERSONA_CONCURRENCY_LIMIT: {self.persona_concurrency_limit}\n"
            f"- PUMS_DATA_DIR: {self.pums_data_dir}\n\n"
            "Providers:\n"
            + "\n".join(provider_lines)
            + "\n\nMemory:\n"
            f"- Redis Agent Memory: {'configured' if self.redis_configured() else 'missing'}\n\n"
            "Observability:\n"
            f"- Weave project: {self.weave_project_name if self.weave_project_name else 'missing'}"
            + missing_block
        )


def get_settings() -> Settings:
    return Settings.load()
