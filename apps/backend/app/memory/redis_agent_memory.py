from __future__ import annotations

import logging
import re
from hashlib import sha1
from datetime import UTC, datetime
from typing import Any

import httpx

from app.config import Settings
from app.schemas import Persona, PersonaReaction


logger = logging.getLogger(__name__)


class RedisAgentMemory:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.base_url = (settings.redis_agent_memory_endpoint or "").rstrip("/")
        self.store_id = settings.redis_agent_memory_store_id or ""
        self.api_key = settings.redis_agent_memory_api_key or ""

    def configured(self) -> bool:
        return bool(self.base_url and self.store_id and self.api_key)

    def _headers(self) -> dict[str, str]:
        return {
            "accept": "application/json",
            "authorization": f"Bearer {self.api_key}",
            "content-type": "application/json",
            "user-agent": "CampaignPersonaAgent/0.1 (+https://localhost)",
        }

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        timeout: float = 30,
    ) -> dict[str, Any]:
        if not self.configured():
            raise RuntimeError("Redis Agent Memory is not configured.")

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.request(method, self._url(path), headers=self._headers(), json=json_body)

        if response.status_code >= 400:
            raise RuntimeError(_redis_error_message(response))
        try:
            data = response.json()
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {"items": data}

    async def check_connection(self) -> None:
        await self._request("GET", f"/v1/stores/{self.store_id}/session-memory")

    async def seed_personas(self, personas: list[Persona]) -> None:
        if not self.configured():
            logger.warning("Redis Agent Memory is not configured; skipping persona seed.")
            return

        memories = []
        for persona in personas:
            memories.append(
                {
                    "id": redis_safe_id("profile", persona.persona_id),
                    "text": profile_text(persona),
                    "memoryType": "semantic",
                    "ownerId": owner_id(persona.persona_id),
                    "namespace": "profile",
                    "topics": ["persona_profile", *persona.segment_tags[:3]],
                }
            )

        try:
            await self._request(
                "POST",
                f"/v1/stores/{self.store_id}/long-term-memory",
                json_body={"memories": memories},
            )
        except Exception as exc:  # noqa: BLE001 - warning-only fallback path for demo resilience.
            logger.warning("Redis persona seed failed: %s", _safe_exception(exc))

    async def get_persona_with_history(
        self,
        persona: Persona,
        *,
        memory_enabled: bool,
    ) -> tuple[str, list[str], str | None]:
        if not memory_enabled:
            return profile_text(persona), [], None

        if not self.configured():
            return profile_text(persona), [], "Redis Agent Memory is not configured; using local persona profile."

        warning: str | None = None
        retrieved_profile = profile_text(persona)
        prior_reactions: list[str] = []

        try:
            profile_hits = await self.search_long_term_memory(
                text=f"profile for {persona.name} {persona.persona_id}",
                owner=owner_id(persona.persona_id),
                namespace="profile",
                limit=1,
            )
            if profile_hits:
                retrieved_profile = profile_hits[0]
        except Exception as exc:  # noqa: BLE001
            warning = f"Redis profile read failed; using local fallback. {_safe_exception(exc)}"
            logger.warning(warning)

        try:
            prior_reactions = await self.search_long_term_memory(
                text="prior political stimulus reactions",
                owner=owner_id(persona.persona_id),
                namespace="reactions",
                limit=5,
            )
        except Exception as exc:  # noqa: BLE001
            warning = f"Redis reaction history read failed; continuing without history. {_safe_exception(exc)}"
            logger.warning(warning)

        return retrieved_profile, prior_reactions, warning

    async def search_long_term_memory(
        self,
        *,
        text: str,
        owner: str,
        namespace: str,
        limit: int,
    ) -> list[str]:
        body = {
            "text": text,
            "limit": limit,
            "filter": {
                "ownerId": {"eq": owner},
                "namespace": {"eq": namespace},
            },
            "filterOp": "all",
        }
        data = await self._request(
            "POST",
            f"/v1/stores/{self.store_id}/long-term-memory/search",
            json_body=body,
        )
        return _extract_memory_texts(data)[:limit]

    async def save_persona_reaction(
        self,
        *,
        persona: Persona,
        run_id: str,
        stimulus_id: str,
        reaction: PersonaReaction,
    ) -> str | None:
        if not self.configured():
            return "Redis Agent Memory is not configured; reaction history was not saved."

        text = (
            f"{persona.name} reacted to {stimulus_id}: {reaction.reaction_text} "
            f"Voter voice quote: {reaction.voter_voice_quote}"
        )
        created_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")

        event_body = {
            "sessionId": session_id(run_id),
            "actorId": owner_id(persona.persona_id),
            "role": "ASSISTANT",
            "content": [{"text": text}],
            "createdAt": created_at,
            "metadata": {
                "stimulus_id": stimulus_id,
                "persona_id": persona.persona_id,
                "namespace": "reactions",
                "model_used": reaction.model_used,
                "provider": reaction.provider,
            },
        }
        memory_body = {
            "memories": [
                {
                    "id": redis_safe_id("reaction", run_id, persona.persona_id),
                    "text": text,
                    "memoryType": "episodic",
                    "sessionId": session_id(run_id),
                    "ownerId": owner_id(persona.persona_id),
                    "namespace": "reactions",
                    "topics": ["political_reaction", stimulus_id, *persona.segment_tags[:3]],
                }
            ]
        }

        try:
            await self._request(
                "POST",
                f"/v1/stores/{self.store_id}/session-memory/events",
                json_body=event_body,
            )
            await self._request(
                "POST",
                f"/v1/stores/{self.store_id}/long-term-memory",
                json_body=memory_body,
            )
        except Exception as exc:  # noqa: BLE001
            warning = f"Redis reaction write failed; continuing demo. {_safe_exception(exc)}: {exc}"
            logger.warning(warning)
            return warning

        return None


def owner_id(persona_id: str) -> str:
    return redis_safe_id("persona", persona_id)


def session_id(run_id: str) -> str:
    return redis_safe_id(run_id)


def redis_safe_id(*parts: str, max_length: int = 64) -> str:
    raw = "-".join(str(part) for part in parts if str(part))
    safe = re.sub(r"[^A-Za-z0-9-]+", "-", raw).strip("-")
    safe = re.sub(r"-{2,}", "-", safe)
    if not safe:
        return "memory-id"
    if len(safe) <= max_length:
        return safe
    digest = sha1(safe.encode("utf-8")).hexdigest()[:10]
    return f"{safe[: max_length - 11].rstrip('-')}-{digest}"


def profile_text(persona: Persona) -> str:
    return (
        f"{persona.name} is a {persona.age}-year-old {persona.race_ethnicity} voter from "
        f"{persona.location.geo_type} {persona.location.city}, {persona.location.state}. "
        f"They work as a {persona.occupation} in {persona.industry}, have {persona.education}, "
        f"identify as {persona.party_affiliation} / {persona.ideology}, and care about "
        f"{', '.join(persona.top_issues)}. Media diet: {', '.join(persona.media_diet)}. "
        f"Institutional trust: government {persona.institutional_trust.government}, "
        f"media {persona.institutional_trust.media}, experts {persona.institutional_trust.experts}. "
        f"Personal stake: {persona.personal_stake}. Segments: {', '.join(persona.segment_tags)}."
    )


def _extract_memory_texts(data: dict[str, Any]) -> list[str]:
    candidates: list[Any] = []
    for key in ("memories", "results", "items", "data"):
        value = data.get(key)
        if isinstance(value, list):
            candidates.extend(value)

    if not candidates and isinstance(data, dict):
        candidates = [data]

    texts: list[str] = []
    for item in candidates:
        if isinstance(item, str):
            texts.append(item)
        elif isinstance(item, dict):
            for key in ("text", "content", "memory", "value"):
                value = item.get(key)
                if isinstance(value, str):
                    texts.append(value)
                    break
                if isinstance(value, dict):
                    nested_text = value.get("text")
                    if isinstance(nested_text, str):
                        texts.append(nested_text)
                        break
    return texts


def _safe_exception(exc: Exception) -> str:
    return exc.__class__.__name__


def _redis_error_message(response: httpx.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return f"Redis Agent Memory request failed with HTTP {response.status_code}."

    detail = data.get("detail") if isinstance(data, dict) else None
    if isinstance(detail, str) and detail:
        return f"Redis Agent Memory request failed with HTTP {response.status_code}: {detail}"
    return f"Redis Agent Memory request failed with HTTP {response.status_code}."
