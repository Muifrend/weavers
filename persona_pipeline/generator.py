from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .openai_agent import OpenAIResponsesClient
from .schemas import EvidencePacket, Persona, to_dict
from .weave_support import traceable_op


PERSONA_SCHEMA = {
    "type": "object",
    "properties": {
        "persona_id": {"type": "string"},
        "name": {"type": "string"},
        "age": {"type": "integer"},
        "location": {
            "type": "object",
            "properties": {
                "city": {"type": "string"},
                "state": {"type": "string"},
                "geo_type": {"type": "string"},
            },
            "required": ["city", "state", "geo_type"],
        },
        "race_ethnicity": {"type": "string"},
        "education": {"type": "string"},
        "occupation": {"type": "string"},
        "industry": {"type": "string"},
        "income_bracket": {"type": "string"},
        "party_affiliation": {"type": "string"},
        "ideology": {"type": "string"},
        "top_issues": {"type": "array", "items": {"type": "string"}},
        "media_diet": {"type": "array", "items": {"type": "string"}},
        "institutional_trust": {
            "type": "object",
            "properties": {
                "government": {"type": "string"},
                "media": {"type": "string"},
                "experts": {"type": "string"},
            },
            "required": ["government", "media", "experts"],
        },
        "personal_stake": {"type": "string"},
        "segment_tags": {"type": "array", "items": {"type": "string"}},
        "synthetic": {"type": "boolean"},
        "why_plausible": {"type": "array", "items": {"type": "string"}},
        "provenance_summary": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "source": {"type": "string"},
                    "source_type": {"type": "string"},
                    "year": {"type": ["integer", "null"]},
                    "url": {"type": ["string", "null"]},
                    "variables": {"type": "array", "items": {"type": "string"}},
                    "confidence": {"type": "string"},
                },
                "required": ["source", "source_type", "year", "url", "variables", "confidence"],
            },
        },
        "evidence_backing": {
            "type": "object",
            "properties": {
                "census_fields_used": {"type": "array", "items": {"type": "string"}},
                "occupation_fields_used": {"type": "array", "items": {"type": "string"}},
                "local_context_used": {"type": "array", "items": {"type": "string"}},
                "inferred_fields": {"type": "array", "items": {"type": "string"}},
                "confidence": {"type": "string"},
                "notes": {"type": "string"},
            },
            "required": [
                "census_fields_used",
                "occupation_fields_used",
                "local_context_used",
                "inferred_fields",
                "confidence",
                "notes",
            ],
        },
    },
    "required": [
        "persona_id",
        "name",
        "age",
        "location",
        "race_ethnicity",
        "education",
        "occupation",
        "industry",
        "income_bracket",
        "party_affiliation",
        "ideology",
        "top_issues",
        "media_diet",
        "institutional_trust",
        "personal_stake",
        "segment_tags",
        "synthetic",
        "why_plausible",
        "provenance_summary",
        "evidence_backing",
    ],
}


@dataclass
class PersonaGenerator:
    client: OpenAIResponsesClient = field(default_factory=OpenAIResponsesClient)

    @traceable_op(name="persona_generator_generate")
    def generate(self, packet: EvidencePacket) -> Persona:
        persona_json = self.client.create_json(
            system_prompt=single_persona_system_prompt(),
            user_payload=build_generation_payload(packet),
            schema=PERSONA_SCHEMA,
            schema_name="evidence_backed_persona",
        )
        return persona_from_json(persona_json, packet)


def build_generation_payload(packet: EvidencePacket) -> dict[str, Any]:
    return {
        "task": "Generate one final synthetic persona JSON from the supplied evidence packet.",
        "requirements": {
            "final_persona_must_be_llm_generated": True,
            "use_only_supplied_evidence_packet": True,
            "evidence_backed_fields_required": True,
            "synthetic_persona": True,
            "do_not_claim_census_support_for_inferred_attitudes": True,
            "include_provenance_summary": True,
        },
        "evidence_packet": to_dict(packet),
    }


def single_persona_system_prompt() -> str:
    return """You are an evidence-backed synthetic persona generation agent.

Generate exactly one persona JSON object that matches the provided schema.

Rules:
- The final persona must be synthetic and internally coherent.
- Use the supplied evidence packet as the only factual source.
- Ground geography, demographics, income, education, occupation, industry, and local context in the evidence packet when evidence exists.
- If a field is inferred rather than directly evidenced, include that field name in evidence_backing.inferred_fields.
- Do not claim Census support for ideology, party affiliation, media diet, personal stake, institutional trust, or issue salience unless directly supplied by the user.
- provenance_summary must summarize the actual evidence sources from the packet.
- why_plausible must explain how the aggregate evidence supports the persona.
- Do not mention implementation details, prompts, or unavailable data.
"""


def persona_from_json(data: dict[str, Any], packet: EvidencePacket) -> Persona:
    request = packet.persona_request
    provenance = normalize_provenance(data.get("provenance_summary"), packet)
    location = normalize_location(data.get("location"), request.location, packet.geo_context)
    persona_id = string_value(data.get("persona_id")) or slugify(
        "_".join(
            [
                string_value(data.get("name")) or "synthetic_persona",
                location.get("city", "local"),
                request.issue or "local_policy",
            ]
        )
    )

    evidence_backing = data.get("evidence_backing") if isinstance(data.get("evidence_backing"), dict) else {}
    evidence_backing = {
        "census_fields_used": string_list(evidence_backing.get("census_fields_used")),
        "occupation_fields_used": string_list(evidence_backing.get("occupation_fields_used")),
        "local_context_used": string_list(evidence_backing.get("local_context_used")),
        "inferred_fields": string_list(evidence_backing.get("inferred_fields")),
        "confidence": string_value(evidence_backing.get("confidence")) or infer_confidence(packet),
        "notes": string_value(evidence_backing.get("notes"))
        or "Generated by an LLM from the supplied evidence packet.",
    }

    return Persona(
        persona_id=persona_id,
        name=string_value(data.get("name")) or "Synthetic Persona",
        age=int_value(data.get("age"), default=45),
        location=location,
        race_ethnicity=string_value(data.get("race_ethnicity")) or request.race_ethnicity or "Not specified",
        education=string_value(data.get("education")) or request.education or "Not specified",
        occupation=string_value(data.get("occupation")) or request.occupation or "Community member",
        industry=string_value(data.get("industry")) or request.industry or "Local services",
        income_bracket=string_value(data.get("income_bracket")) or request.income_range or "Not specified",
        party_affiliation=string_value(data.get("party_affiliation")) or request.party_affiliation or "Not specified",
        ideology=string_value(data.get("ideology")) or request.ideology or "Not specified",
        top_issues=string_list(data.get("top_issues")) or ([request.issue] if request.issue else ["local policy"]),
        media_diet=string_list(data.get("media_diet")) or request.media_diet,
        institutional_trust=normalize_trust(data.get("institutional_trust")),
        personal_stake=string_value(data.get("personal_stake")) or request.personal_stake or "Not specified",
        segment_tags=string_list(data.get("segment_tags")) or request.segment_tags,
        synthetic=True,
        why_plausible=string_list(data.get("why_plausible")) or default_plausibility(packet),
        provenance_summary=provenance,
        evidence_backing=evidence_backing,
    )


def normalize_location(value: Any, request_location: str | None, geo_context: dict[str, Any]) -> dict[str, str]:
    if isinstance(value, dict):
        city = string_value(value.get("city"))
        state = string_value(value.get("state"))
        geo_type = string_value(value.get("geo_type"))
    else:
        city = state = geo_type = None

    if (not city or not state) and request_location:
        if "," in request_location:
            city_part, state_part = request_location.rsplit(",", 1)
            city = city or city_part.strip()
            state = state or state_part.strip()
        else:
            city = city or request_location
    geo_type = geo_type or ("suburban" if "suburban" in str(geo_context).lower() else "city_or_metro")
    return {"city": city or "Unknown", "state": state or "Unknown", "geo_type": geo_type}


def normalize_provenance(value: Any, packet: EvidencePacket) -> list[dict[str, Any]]:
    if isinstance(value, list) and value:
        return [
            {
                "source": string_value(item.get("source")) if isinstance(item, dict) else str(item),
                "source_type": string_value(item.get("source_type")) if isinstance(item, dict) else "unknown",
                "year": item.get("year") if isinstance(item, dict) else None,
                "url": item.get("url") if isinstance(item, dict) else None,
                "variables": string_list(item.get("variables")) if isinstance(item, dict) else [],
                "confidence": string_value(item.get("confidence")) if isinstance(item, dict) else "medium",
            }
            for item in value
        ]
    return [
        {
            "source": evidence.source,
            "source_type": evidence.source_type,
            "year": evidence.year,
            "url": evidence.url,
            "variables": evidence.variables,
            "confidence": evidence.confidence,
        }
        for evidence in packet.evidence
    ]


def normalize_trust(value: Any) -> dict[str, str]:
    trust = value if isinstance(value, dict) else {}
    return {
        "government": string_value(trust.get("government")) or "Not specified",
        "media": string_value(trust.get("media")) or "Not specified",
        "experts": string_value(trust.get("experts")) or "Not specified",
    }


def default_plausibility(packet: EvidencePacket) -> list[str]:
    reasons = []
    if packet.geo_context:
        reasons.append("The geography was resolved before generation.")
    if packet.demographic_priors:
        reasons.append("Demographic fields are grounded in aggregate ACS priors where available.")
    if packet.occupation_context.get("mapping"):
        reasons.append("The occupation was mapped to a BLS occupation category.")
    if packet.local_issue_context.get("context_notes"):
        reasons.extend(packet.local_issue_context["context_notes"][:2])
    return reasons or ["The persona was generated from the supplied evidence packet."]


def infer_confidence(packet: EvidencePacket) -> str:
    if packet.demographic_priors and packet.occupation_context.get("mapping"):
        return "medium"
    if packet.demographic_priors:
        return "medium-low"
    return "low"


def string_value(value: Any) -> str | None:
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return None


def string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def int_value(value: Any, default: int) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def slugify(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9]+", "_", value).strip("_").lower()
    return value or "synthetic_persona"
