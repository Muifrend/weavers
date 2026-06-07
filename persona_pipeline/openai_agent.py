from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .adapters import read_dotenv_value
from .weave_support import traceable_op


PERSONA_SET_SCHEMA = {
    "type": "object",
    "properties": {
        "state": {"type": "string"},
        "generation_notes": {"type": "string"},
        "representation_total_pct": {"type": "number"},
        "personas": {
            "type": "array",
            "minItems": 1,
            "maxItems": 100,
            "items": {
                "type": "object",
                "properties": {
                    "persona_id": {"type": "string"},
                    "name": {"type": "string"},
                    "age": {"type": "integer"},
                    "age_band": {"type": "string"},
                    "sex": {"type": "string"},
                    "race_ethnicity": {"type": "string"},
                    "education": {"type": "string"},
                    "household_income": {"type": "string"},
                    "employed_sector": {"type": "string"},
                    "occupation_group": {"type": "string"},
                    "worker_class": {"type": "string"},
                    "political_view": {"type": "string"},
                    "political_view_basis": {"type": "string"},
                    "media_environment": {"type": "array", "items": {"type": "string"}},
                    "top_issues": {"type": "array", "items": {"type": "string"}},
                    "institutional_trust": {
                        "type": "object",
                        "properties": {
                            "government": {"type": "string"},
                            "media": {"type": "string"},
                            "experts": {"type": "string"},
                        },
                        "required": ["government", "media", "experts"],
                    },
                    "representation_pct": {"type": "number"},
                    "representation_basis": {"type": "string"},
                    "evidence_backing": {
                        "type": "object",
                        "properties": {
                            "census_fields_used": {"type": "array", "items": {"type": "string"}},
                            "inferred_fields": {"type": "array", "items": {"type": "string"}},
                            "confidence": {"type": "string"},
                        },
                        "required": ["census_fields_used", "inferred_fields", "confidence"],
                    },
                    "synthetic": {"type": "boolean"},
                    "safety_note": {"type": "string"},
                },
                "required": [
                    "persona_id",
                    "name",
                    "age",
                    "age_band",
                    "sex",
                    "race_ethnicity",
                    "education",
                    "household_income",
                    "employed_sector",
                    "occupation_group",
                    "worker_class",
                    "political_view",
                    "political_view_basis",
                    "media_environment",
                    "top_issues",
                    "institutional_trust",
                    "representation_pct",
                    "representation_basis",
                    "evidence_backing",
                    "synthetic",
                    "safety_note",
                ],
            },
        },
    },
    "required": ["state", "generation_notes", "representation_total_pct", "personas"],
}


@dataclass
class OpenAIResponsesClient:
    api_key: str | None = field(default_factory=lambda: os.getenv("OPENAI_API_KEY") or read_dotenv_value("OPENAI_API_KEY"))
    model: str = field(default_factory=lambda: os.getenv("OPENAI_MODEL") or read_dotenv_value("OPENAI_MODEL") or "gpt-4.1")
    timeout: float = 60.0

    @traceable_op(name="openai_create_json")
    def create_json(
        self,
        system_prompt: str,
        user_payload: dict[str, Any],
        schema: dict[str, Any],
        schema_name: str = "representative_persona_set",
    ) -> dict[str, Any]:
        if not self.api_key:
            raise OpenAIConfigError("OPENAI_API_KEY is required for OpenAI persona generation.")

        body = {
            "model": self.model,
            "input": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload, sort_keys=True)},
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": schema_name,
                    "schema": schema,
                    "strict": False,
                }
            },
        }
        request = Request(
            "https://api.openai.com/v1/responses",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "User-Agent": "persona-pipeline/0.1",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                response_body = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            error_body = error.read().decode("utf-8", errors="replace")
            raise OpenAIRequestError(f"OpenAI API request failed with HTTP {error.code}: {error_body[:500]}") from error
        except (OSError, URLError, TimeoutError, json.JSONDecodeError) as error:
            raise OpenAIRequestError(f"OpenAI API request failed: {error}") from error

        text = extract_response_text(response_body)
        try:
            return json.loads(text)
        except json.JSONDecodeError as error:
            raise OpenAIRequestError("OpenAI response did not contain parseable JSON.") from error


class OpenAIConfigError(Exception):
    pass


class OpenAIRequestError(Exception):
    pass


def extract_response_text(response: dict[str, Any]) -> str:
    if isinstance(response.get("output_text"), str):
        return response["output_text"]
    parts = []
    for item in response.get("output", []):
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"} and isinstance(content.get("text"), str):
                parts.append(content["text"])
    return "".join(parts)
