from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from app.config import Settings
from app.memory.local_persona_store import LocalPersonaStore
from app.providers.base import ProviderError
from app.schemas import Persona, PersonaGenerationRequest, PersonaGenerationResponse, PersonaLocation
from persona_pipeline.population import PopulationPipeline
from persona_pipeline.pums_store import PumsStore


@dataclass
class PersonaCreationAgent:
    settings: Settings
    store: LocalPersonaStore

    async def generate_state_personas(self, request: PersonaGenerationRequest) -> PersonaGenerationResponse:
        if not self.settings.openai_api_key:
            raise ProviderError(
                "persona_pipeline",
                "missing_openai_api_key",
                "OPENAI_API_KEY is required for evidence-backed persona generation.",
            )
        if not self.settings.census_api_key:
            raise ProviderError(
                "persona_pipeline",
                "missing_census_api_key",
                "CENSUS_API_KEY is required for Census-backed persona generation.",
            )

        result = await asyncio.to_thread(self._run_population_pipeline, request)
        raw_personas = result.get("personas")
        warnings = list(result.get("warnings") if isinstance(result.get("warnings"), list) else [])
        if not isinstance(raw_personas, list) or not raw_personas:
            message = "Persona pipeline did not return any evidence-backed personas."
            if warnings:
                message = f"{message} {warnings[0]}"
            raise ProviderError(
                "persona_pipeline",
                "persona_pipeline_incomplete",
                message,
            )
        if len(raw_personas) != request.persona_count:
            warnings.append(
                f"Generated {len(raw_personas)} of {request.persona_count} requested personas; using the completed personas."
            )

        profile = result.get("population_profile") if isinstance(result.get("population_profile"), dict) else {}
        personas = [adapt_pipeline_persona(item, profile, index) for index, item in enumerate(raw_personas, start=1)]

        location_name = str(profile.get("raw_name") or request.location)

        saved_path = None
        set_id = None
        set_label = None
        if request.persist:
            set_label = request.set_label or f"{location_name} · {len(personas)}"
            metadata = self.store.save_persona_set(personas, label=set_label, location=location_name)
            set_id = metadata["set_id"]
            saved_path = str(self.store.sets_dir / f"{set_id}.json")

        return PersonaGenerationResponse(
            status="complete" if len(personas) == request.persona_count and result.get("status") == "complete" else "partial",
            location=location_name,
            personas=personas,
            representation_total_pct=round(sum(persona.representation_pct or 0 for persona in personas), 2),
            demographic_priors=profile.get("demographic_priors") if isinstance(profile.get("demographic_priors"), dict) else {},
            population_context=profile.get("population_context") if isinstance(profile.get("population_context"), dict) else {},
            saved_path=saved_path,
            set_id=set_id,
            set_label=set_label,
            warnings=warnings,
        )

    def _run_population_pipeline(self, request: PersonaGenerationRequest) -> dict[str, Any]:
        pipeline = PopulationPipeline()
        pipeline.census.api_key = self.settings.census_api_key
        pipeline.pums.api_key = self.settings.census_api_key
        pipeline.store = PumsStore(self.settings.pums_data_dir)
        pipeline.require_local_pums_cache = True
        pipeline.persona_set_agent.client.api_key = self.settings.openai_api_key
        return pipeline.initialize(request.location, persona_count=request.persona_count)


def adapt_pipeline_persona(item: Any, population_profile: dict[str, Any], index: int) -> Persona:
    if not isinstance(item, dict):
        raise ProviderError("persona_pipeline", "invalid_persona", "Persona pipeline returned a non-object persona.")

    geo_context = population_profile.get("geo_context") if isinstance(population_profile.get("geo_context"), dict) else {}
    location = pipeline_location(item, population_profile, geo_context)
    political_view = str(item.get("political_view") or "Inferred / not Census-backed")
    evidence_backing = item.get("evidence_backing") if isinstance(item.get("evidence_backing"), dict) else {}
    evidence_backing = {
        **evidence_backing,
        "source_pipeline": "persona_pipeline.population.PopulationPipeline",
        "generation_method": "OpenAI structured output from ACS aggregate evidence and weighted ACS PUMS samples",
        "population_profile_status": population_profile.get("status"),
        "raw_census_name": population_profile.get("raw_name"),
    }

    payload = {
        "persona_id": item.get("persona_id") or f"{slugify(location.city)}_p{index}",
        "name": item.get("name") or f"Persona {index}",
        "age": item.get("age"),
        "location": location,
        "race_ethnicity": item.get("race_ethnicity"),
        "education": item.get("education"),
        "occupation": item.get("occupation_group") or item.get("occupation"),
        "industry": item.get("employed_sector") or item.get("industry"),
        "income_bracket": item.get("household_income") or item.get("income_bracket"),
        "party_affiliation": political_view,
        "ideology": political_view,
        "top_issues": item.get("top_issues"),
        "media_diet": item.get("media_environment") or item.get("media_diet"),
        "institutional_trust": item.get("institutional_trust"),
        "personal_stake": item.get("household_context")
        or item.get("personal_stake")
        or "Synthetic campaign-reaction stake inferred from aggregate demographic and economic context.",
        "segment_tags": item.get("segment_tags") or build_segment_tags(item),
        "representation_pct": item.get("representation_pct"),
        "representation_basis": item.get("representation_basis"),
        "evidence_backing": evidence_backing,
    }
    return Persona.model_validate(payload)


def pipeline_location(item: dict[str, Any], population_profile: dict[str, Any], geo_context: dict[str, Any]) -> PersonaLocation:
    item_location = item.get("location")
    if isinstance(item_location, dict):
        city = str(item_location.get("city") or population_profile.get("location") or "Statewide")
        state = str(item_location.get("state") or state_from_geo_context(geo_context) or city)
        geo_type = str(item_location.get("geo_type") or "state")
        return PersonaLocation(city=city, state=state, geo_type=geo_type)

    city = str(population_profile.get("location") or item_location or "Statewide")
    return PersonaLocation(city=city, state=state_from_geo_context(geo_context) or city, geo_type="state")


def state_from_geo_context(geo_context: dict[str, Any]) -> str | None:
    options = geo_context.get("resolved_options")
    if isinstance(options, list) and options:
        first = options[0]
        if isinstance(first, dict) and first.get("state"):
            return str(first["state"])
    return None


def build_segment_tags(item: dict[str, Any]) -> list[str]:
    tags = []
    for key in ("race_ethnicity", "education", "employed_sector", "occupation_group", "political_view"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            tags.append(slugify(value)[:48])
    return tags[:5]


def slugify(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else "_" for char in value).strip("_")
