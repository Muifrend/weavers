from __future__ import annotations

import json
import os
import random
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from .agents import DemographicAgent
from .adapters import CensusAdapter, PumsAdapter, first_resolved_state
from .pums_store import PumsStore
from .openai_agent import OpenAIConfigError, OpenAIRequestError, OpenAIResponsesClient, PERSONA_SET_SCHEMA
from .schemas import AgentResult, Evidence, to_dict
from .weave_support import traceable_op


SECTOR_LABELS = {
    "agriculture_mining_industry_share": "Agriculture, forestry, fishing, hunting, and mining",
    "manufacturing_industry_share": "Manufacturing",
    "retail_trade_industry_share": "Retail trade",
    "transportation_warehousing_utilities_industry_share": "Transportation, warehousing, and utilities",
    "finance_real_estate_industry_share": "Finance, insurance, real estate, rental, and leasing",
    "professional_scientific_management_admin_industry_share": "Professional, scientific, management, administrative, and waste management services",
    "education_health_social_assistance_industry_share": "Educational services, health care, and social assistance",
    "arts_accommodation_food_industry_share": "Arts, entertainment, recreation, accommodation, and food services",
    "public_administration_industry_share": "Public administration",
}

OCCUPATION_LABELS = {
    "management_business_science_arts_occupation_share": "Management, business, science, and arts",
    "service_occupation_share": "Service",
    "sales_office_occupation_share": "Sales and office",
    "natural_resources_construction_maintenance_occupation_share": "Natural resources, construction, and maintenance",
    "production_transportation_material_moving_occupation_share": "Production, transportation, and material moving",
}

RACE_LABELS = {
    "hispanic_or_latino_share": "Hispanic or Latino",
    "white_alone_or_combination_share": "White alone or in combination",
    "black_alone_or_combination_share": "Black or African American alone or in combination",
    "asian_alone_or_combination_share": "Asian alone or in combination",
}

EDUCATION_LABELS = {
    "high_school_graduate_share": "High school graduate",
    "some_college_or_associates_share": "Some college or associate's degree",
    "bachelors_degree_share": "Bachelor's degree",
    "graduate_or_professional_degree_share": "Graduate or professional degree",
}

AGE_LABELS = {
    "age_25_to_34_share": ("25-34", 31),
    "age_35_to_44_share": ("35-44", 39),
    "age_45_to_54_share": ("45-54", 49),
    "age_65_to_74_share": ("65-74", 68),
}

INCOME_LABELS = {
    "household_income_35k_49k_share": "$35k-$49k",
    "household_income_50k_74k_share": "$50k-$74k",
    "household_income_75k_99k_share": "$75k-$99k",
    "household_income_100k_149k_share": "$100k-$149k",
    "household_income_150k_199k_share": "$150k-$199k",
}


@dataclass
class PopulationPipeline:
    census: CensusAdapter = field(default_factory=CensusAdapter)
    pums: PumsAdapter = field(default_factory=PumsAdapter)
    store: PumsStore = field(default_factory=PumsStore)
    persona_set_agent: Any = field(default_factory=lambda: OpenAISampledPersonaAgent())
    require_local_pums_cache: bool = False

    @traceable_op(name="population_pipeline_initialize")
    def initialize(self, location: str, output_dir: str | None = None, persona_count: int | None = None) -> dict[str, Any]:
        target_personas = persona_count or self.persona_set_agent.target_personas
        geo_result = self.resolve_location(location)
        geo_context = geo_result.data["geography"]
        demographic_agent = DemographicAgent(census=self.census)
        demographic_result = demographic_agent.run(geo_context)

        population_context = build_population_context(demographic_result.data.get("features", {}))
        population_profile = {
            "location": location,
            "geo_context": geo_context,
            "demographic_priors": demographic_result.data.get("features", {}),
            "population_context": population_context,
            "raw_name": demographic_result.data.get("raw_name"),
            "status": demographic_result.status,
        }
        sampler_result = PumsPopulationSampler(
            pums=self.pums,
            store=self.store,
            require_local_cache=self.require_local_pums_cache,
        ).run(
            geo_context=geo_context,
            priors=demographic_result.data.get("features", {}),
            count=target_personas,
        )
        samples = sampler_result.data.get("samples", [])
        with ThreadPoolExecutor(max_workers=min(max(1, target_personas), 8)) as executor:
            persona_results = list(
                executor.map(
                    lambda item: self.persona_set_agent.run(
                        population_profile=population_profile,
                        sample=item[1],
                        sample_index=item[0],
                        total_samples=target_personas,
                    ),
                    enumerate(samples, start=1),
                )
            )
        personas = [
            result.data["persona"]
            for result in persona_results
            if result.status == "complete" and isinstance(result.data.get("persona"), dict)
        ]
        apply_sample_representation(personas)
        persona_set = normalize_persona_set(
            {
                "state": population_profile.get("raw_name") or location,
                "generation_notes": (
                    "Each persona was generated by a separate OpenAI sample-persona agent initialized with "
                    "one weighted ACS PUMS public microdata sample plus the state ACS profile."
                ),
                "personas": personas,
            },
            target_count=target_personas,
        )
        persona_result = AgentResult(
            agent="sampled_persona_agent_pool",
            status="complete" if len(persona_set.get("personas", [])) == target_personas and all(result.status == "complete" for result in persona_results) else "partial",
            data={"persona_set": persona_set},
            evidence=[
                Evidence(
                    source="OpenAI Responses API structured output from ACS PUMS samples",
                    source_type="model_generation_from_public_microdata_sample",
                    confidence="medium",
                    notes=f"Initialized {len(persona_results)} sample-persona agents for requested count {target_personas}.",
                )
            ],
            warnings=[
                warning
                for result in persona_results
                for warning in result.warnings
            ],
        )
        file_manifest = (
            write_persona_files(persona_result.data.get("persona_set", {}), output_dir)
            if output_dir and persona_result.status == "complete"
            else None
        )

        agent_context = {
            "initialized": demographic_result.status == "complete" and persona_result.status == "complete",
            "population_profile": population_profile,
            "persona_set": persona_result.data.get("persona_set"),
            "available_to_agents": [
                "supervisor_agent",
                "geo_agent",
                "demographic_agent",
                "pums_population_sampler",
                "openai_sample_persona_agents",
            ],
            "usage": "Use persona_set.personas as one persona per weighted ACS PUMS population sample.",
        }

        return {
            "status": (
                "complete"
                if demographic_result.status == "complete"
                and sampler_result.status == "complete"
                and persona_result.status == "complete"
                else "partial"
            ),
            "population_profile": population_profile,
            "persona_set": persona_result.data.get("persona_set"),
            "personas": persona_result.data.get("persona_set", {}).get("personas", []),
            "files": file_manifest,
            "agent_context": agent_context,
            "agent_results": [
                to_dict(geo_result),
                to_dict(demographic_result),
                to_dict(sampler_result),
                *[to_dict(result) for result in persona_results],
                to_dict(persona_result),
            ],
            "warnings": [*demographic_result.warnings, *sampler_result.warnings, *persona_result.warnings],
        }

    def resolve_location(self, location: str) -> AgentResult:
        geo = self.census.resolve_place(location)
        status = "complete" if geo.get("resolved_options") else "partial"
        return AgentResult(
            agent="population_geo_agent",
            status=status,
            data={"geography": geo},
            evidence=[
                Evidence(
                    source="U.S. Census Bureau geography / ACS lookup",
                    source_type="public_aggregate_api",
                    year=self.census.acs_year,
                    confidence="high" if status == "complete" else "medium",
                    notes="Resolves population location into Census geography.",
                )
            ],
        )


@dataclass
class PumsPopulationSampler:
    pums: PumsAdapter = field(default_factory=PumsAdapter)
    store: PumsStore = field(default_factory=PumsStore)
    require_local_cache: bool = False

    def run(self, geo_context: dict[str, Any], priors: dict[str, Any], count: int) -> AgentResult:
        variables = ["AGEP", "SEX", "HISP", "RAC1P", "SCHL", "ESR", "COW", "OCCP", "INDP", "PINCP", "PWGTP"]
        state_option = first_resolved_state(geo_context)

        if state_option and self.store.exists(state_option["state_fips"], self.pums.acs_year):
            return self._run_from_parquet(state_option, count, variables)
        if state_option and self.require_local_cache:
            path = self.store.parquet_path(state_option["state_fips"], self.pums.acs_year)
            warning = (
                f"ACS PUMS parquet cache is missing at {path}. "
                "Run `persona-pipeline download-pums <state>` or set PUMS_DATA_DIR to a directory with the cached file."
            )
            return AgentResult(
                agent="pums_population_sampler",
                status="partial",
                data={
                    "samples": [],
                    "sample_pool_size": 0,
                    "requested_samples": count,
                    "source": "missing_local_parquet",
                },
                evidence=[Evidence(
                    source="ACS PUMS local parquet cache",
                    source_type="public_anonymized_microdata_local",
                    year=self.pums.acs_year,
                    variables=variables,
                    confidence="low",
                    notes=warning,
                )],
                warnings=[warning],
            )
        return self._run_from_api(geo_context, count, variables)

    def _run_from_parquet(
        self,
        state_option: dict[str, Any],
        count: int,
        variables: list[str],
    ) -> AgentResult:
        state_fips = state_option["state_fips"]
        year = self.pums.acs_year
        raw_samples, pool_size = self.store.weighted_sample(state_fips, year, count, variables)
        # weighted_sample already drew exactly count records proportional to PWGTP —
        # each record IS the weighted draw, no secondary sampling step needed.
        samples = [
            {
                "sample_id": f"pums_sample_{index}",
                "raw_record": record,
                "decoded_record": decode_pums_record(record),
                "person_weight": parse_int(record.get("PWGTP")) or 1,
            }
            for index, record in enumerate(raw_samples, start=1)
        ]
        source_note = (
            f"Drew {len(samples)} PWGTP-weighted samples without replacement from "
            f"{pool_size:,} cached ACS PUMS person records (parquet)."
        )
        if len(samples) < count:
            warning = (
                f"ACS PUMS parquet has {pool_size:,} records; could only draw {len(samples)} "
                f"of {count} requested samples."
            )
            return AgentResult(
                agent="pums_population_sampler",
                status="partial",
                data={"samples": samples, "sample_pool_size": pool_size, "requested_samples": count, "source": "parquet"},
                evidence=[Evidence(
                    source="ACS PUMS local parquet cache",
                    source_type="public_anonymized_microdata_local",
                    year=year,
                    variables=variables,
                    confidence="low",
                    notes=source_note,
                )],
                warnings=[warning],
            )
        return AgentResult(
            agent="pums_population_sampler",
            status="complete",
            data={"samples": samples, "sample_pool_size": pool_size, "requested_samples": count, "source": "parquet"},
            evidence=[Evidence(
                source="ACS PUMS local parquet cache",
                source_type="public_anonymized_microdata_local",
                year=year,
                variables=variables,
                confidence="high",
                notes=source_note,
            )],
        )

    def _run_from_api(
        self,
        geo_context: dict[str, Any],
        count: int,
        variables: list[str],
    ) -> AgentResult:
        result = self.pums.fetch_person_records(geo_context, variables)
        records = result.get("records", [])
        decoded_records = [
            {
                "sample_id": f"pums_sample_{index}",
                "raw_record": record,
                "decoded_record": decode_pums_record(record),
                "person_weight": parse_int(record.get("PWGTP")) or 1,
            }
            for index, record in enumerate(records, start=1)
        ]
        samples = weighted_sample_without_replacement(decoded_records, count)

        if len(samples) < count:
            warning = (
                f"ACS PUMS returned {len(decoded_records)} usable records; requested {count} samples. "
                "Persona generation will not invent missing samples. "
                "Run `persona-pipeline download-pums <state>` to cache PUMS data locally and avoid this."
            )
            return AgentResult(
                agent="pums_population_sampler",
                status="partial",
                data={
                    "samples": samples,
                    "sample_pool_size": len(decoded_records),
                    "requested_samples": count,
                    "source_status": result.get("status"),
                    "source": "api",
                },
                evidence=[
                    Evidence(
                        source="U.S. Census Bureau ACS 5-year PUMS person microdata",
                        source_type="public_anonymized_microdata_api",
                        year=self.pums.acs_year,
                        url=result.get("url"),
                        variables=variables,
                        confidence="low",
                        notes="Could not retrieve enough weighted public microdata samples for the requested count.",
                    )
                ],
                warnings=[warning],
            )

        return AgentResult(
            agent="pums_population_sampler",
            status="complete",
            data={
                "samples": samples,
                "sample_pool_size": len(decoded_records),
                "requested_samples": count,
                "source_status": result.get("status"),
                "source": "api",
            },
            evidence=[
                Evidence(
                    source="U.S. Census Bureau ACS 5-year PUMS person microdata",
                    source_type="public_anonymized_microdata_api",
                    year=self.pums.acs_year,
                    url=result.get("url"),
                    variables=variables,
                    confidence="high",
                    notes="Drew weighted random samples from returned anonymized ACS PUMS person records using PWGTP.",
                )
            ],
        )


@dataclass
class OpenAISampledPersonaAgent:
    client: OpenAIResponsesClient = field(default_factory=OpenAIResponsesClient)
    target_personas: int = 10

    @traceable_op(name="openai_sample_persona_generate")
    def run(
        self,
        *,
        population_profile: dict[str, Any],
        sample: dict[str, Any],
        sample_index: int,
        total_samples: int,
    ) -> AgentResult:
        payload = {
            "task": "Generate one synthetic campaign persona from one ACS PUMS public microdata sample.",
            "requirements": {
                "synthetic_only": True,
                "one_persona_only": True,
                "sample_index": sample_index,
                "total_samples": total_samples,
                "use_pums_sample_for_cross_field_coherence": True,
                "use_acs_profile_for_state_context": True,
                "political_view_is_inferred_not_census": True,
                "avoid_real_people_or_voter_file_logic": True,
            },
            "population_profile": population_profile,
            "pums_sample": sample,
        }
        try:
            persona = self.client.create_json(
                system_prompt=sample_persona_system_prompt(),
                user_payload=payload,
                schema=SAMPLED_PERSONA_SCHEMA,
                schema_name="sampled_population_persona",
            )
        except OpenAIConfigError as error:
            return AgentResult(
                agent=f"openai_sample_persona_agent_{sample_index}",
                status="blocked",
                data={},
                evidence=[Evidence(source="OpenAI Responses API", source_type="model_generation", confidence="low", notes=str(error))],
                warnings=[str(error)],
            )
        except OpenAIRequestError as error:
            return AgentResult(
                agent=f"openai_sample_persona_agent_{sample_index}",
                status="partial",
                data={},
                evidence=[Evidence(source="OpenAI Responses API", source_type="model_generation", confidence="low", notes=str(error))],
                warnings=[str(error)],
            )

        persona["synthetic"] = True
        persona.setdefault("persona_id", slugify(f"{population_profile.get('location', 'state')}_{sample_index}_{persona.get('name', 'persona')}"))
        persona.setdefault("representation_pct", round(100 / total_samples, 2))
        persona.setdefault("representation_basis", "One weighted random ACS PUMS public microdata sample from the returned Census sample pool.")
        evidence_backing = persona.get("evidence_backing") if isinstance(persona.get("evidence_backing"), dict) else {}
        evidence_backing["pums_sample"] = {
            "sample_id": sample.get("sample_id"),
            "decoded_record": sample.get("decoded_record"),
            "person_weight": sample.get("person_weight"),
        }
        evidence_backing["acs_year"] = population_profile.get("demographic_priors", {}).get("acs_year")
        persona["evidence_backing"] = evidence_backing

        return AgentResult(
            agent=f"openai_sample_persona_agent_{sample_index}",
            status="complete",
            data={"persona": persona},
            evidence=[
                Evidence(
                    source="OpenAI Responses API structured output",
                    source_type="model_generation_from_public_microdata_sample",
                    confidence="medium",
                    notes="Generated one persona from one anonymized ACS PUMS sample plus aggregate ACS context.",
                )
            ],
        )


SAMPLED_PERSONA_SCHEMA = {
    "type": "object",
    "properties": deepcopy(PERSONA_SET_SCHEMA["properties"]["personas"]["items"]["properties"]),
    "required": PERSONA_SET_SCHEMA["properties"]["personas"]["items"]["required"],
}


def sample_persona_system_prompt() -> str:
    return """You are a bounded sampled-persona generation agent.

Generate exactly one synthetic persona JSON object from the provided ACS PUMS public microdata sample.

Rules:
- The PUMS sample is anonymized public Census microdata, not a real identifiable person.
- Use the decoded PUMS sample for age, sex, race/ethnicity, education, worker class, occupation group, industry, and income coherence.
- Use the aggregate ACS state profile only as broader context.
- Political view, media diet, issues, and narrative stake may be inferred, but must be labeled as inferred in evidence_backing.
- Do not use voter files, social profiles, data brokers, or individual profiling.
- Return exactly one JSON object matching the schema.
"""


def weighted_sample_without_replacement(records: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    rng = random.SystemRandom()
    pool = list(records)
    selected = []
    for _ in range(min(count, len(pool))):
        weights = [max(1, int(record.get("person_weight") or 1)) for record in pool]
        chosen = rng.choices(pool, weights=weights, k=1)[0]
        selected.append(chosen)
        pool.remove(chosen)
    return selected


def apply_sample_representation(personas: list[dict[str, Any]]) -> None:
    weights = []
    for persona in personas:
        evidence = persona.get("evidence_backing") if isinstance(persona.get("evidence_backing"), dict) else {}
        sample = evidence.get("pums_sample") if isinstance(evidence.get("pums_sample"), dict) else {}
        weights.append(max(1, int(sample.get("person_weight") or 1)))

    total = sum(weights)
    if total <= 0:
        return

    for persona, weight in zip(personas, weights, strict=False):
        persona["representation_pct"] = round((weight / total) * 100, 2)
        persona["representation_basis"] = "Normalized ACS PUMS PWGTP weight across the N sampled records."


@dataclass
class PumsCorrelationAgent:
    pums: PumsAdapter = field(default_factory=PumsAdapter)

    def run(self, geo_context: dict[str, Any], priors: dict[str, Any]) -> AgentResult:
        variables = ["AGEP", "SEX", "HISP", "RAC1P", "SCHL", "ESR", "COW", "OCCP", "INDP", "PINCP", "PWGTP"]
        query_plan = plan_pums_queries(priors)
        query_attempts = []
        final_result: dict[str, Any] = {"records": [], "status": "unavailable", "url": None}
        selected_filters: dict[str, str] = {}
        records: list[dict[str, str]] = []

        for attempt in query_plan:
            filters = attempt["filters"]
            result = self.pums.fetch_person_records(geo_context, variables, filters=filters)
            attempt_records = result.get("records", [])
            query_attempts.append(
                {
                    "strategy": attempt["strategy"],
                    "filters": filters,
                    "status": result.get("status"),
                    "matching_records": len(attempt_records),
                    "url": result.get("url"),
                }
            )
            if len(attempt_records) >= 20:
                final_result = result
                selected_filters = filters
                records = attempt_records
                break
            if attempt_records and not records:
                final_result = result
                selected_filters = filters
                records = attempt_records

        sample_pool = records[:20]
        selected = select_pums_record(sample_pool)

        if not selected:
            return AgentResult(
                agent="pums_correlation_agent",
                status="partial",
                data={
                    "pums_correlation_profile": {
                        "status": final_result.get("status"),
                        "query_plan": query_plan,
                        "query_attempts": query_attempts,
                        "filters": selected_filters,
                        "total_matching_records": len(records),
                        "sample_size": len(sample_pool),
                        "sample_pool_size": len(sample_pool),
                        "selected_record": None,
                    }
                },
                evidence=[
                    Evidence(
                        source="U.S. Census Bureau ACS 5-year PUMS person microdata",
                        source_type="public_anonymized_microdata_api",
                        year=self.pums.acs_year,
                        url=final_result.get("url"),
                        variables=variables,
                        confidence="low",
                        notes=pums_unavailable_note(final_result.get("status")),
                    )
                ],
                warnings=[pums_unavailable_note(final_result.get("status"))],
            )

        decoded = decode_pums_record(selected)
        return AgentResult(
            agent="pums_correlation_agent",
            status="complete",
            data={
                "pums_correlation_profile": {
                    "status": "complete",
                    "query_plan": query_plan,
                    "query_attempts": query_attempts,
                    "filters": selected_filters,
                    "total_matching_records": len(records),
                    "sample_size": len(sample_pool),
                    "sample_pool_size": len(sample_pool),
                    "selected_record": selected,
                    "decoded_record": decoded,
                    "correlation_note": "Fields in decoded_record come from one randomly sampled anonymized ACS PUMS person record from the first 20 matching API results.",
                }
            },
            evidence=[
                Evidence(
                    source="U.S. Census Bureau ACS 5-year PUMS person microdata",
                        source_type="public_anonymized_microdata_api",
                        year=self.pums.acs_year,
                        url=final_result.get("url"),
                        variables=variables,
                        confidence="high",
                        notes="Selected one anonymized PUMS person record to preserve cross-field coherence.",
                )
            ],
        )


def build_population_context(priors: dict[str, Any]) -> dict[str, Any]:
    return {
        "dominant_race_ethnicity": top_share(priors, RACE_LABELS),
        "sex_distribution": {
            "female_share": priors.get("female_share"),
            "male_share": priors.get("male_share"),
            "persona_default": "Female" if value_or_zero(priors.get("female_share")) >= value_or_zero(priors.get("male_share")) else "Male",
        },
        "age_distribution": {
            "median_age": priors.get("median_age"),
            "largest_working_age_band": top_age_band(priors),
        },
        "education_distribution": {
            "largest_attainment": top_share(priors, EDUCATION_LABELS),
            "some_college_or_associates_share": priors.get("some_college_or_associates_share"),
        },
        "employment_distribution": {
            "largest_sector": top_share(priors, SECTOR_LABELS),
            "largest_occupation_group": top_share(priors, OCCUPATION_LABELS),
            "worker_class": top_share(
                priors,
                {
                    "private_wage_salary_worker_share": "Private wage and salary worker",
                    "government_worker_share": "Government worker",
                    "self_employed_worker_share": "Self-employed worker",
                },
            ),
        },
        "income_distribution": {
            "median_household_income": priors.get("median_household_income"),
            "largest_household_income_band": top_share(priors, INCOME_LABELS),
        },
    }


def normalize_persona_set(persona_set: dict[str, Any], target_count: int | None = None) -> dict[str, Any]:
    personas = persona_set.get("personas", [])
    if not isinstance(personas, list):
        personas = []
    if target_count is not None and len(personas) > target_count:
        personas = personas[:target_count]
        persona_set["personas"] = personas
    total = sum(float(persona.get("representation_pct", 0) or 0) for persona in personas)
    if personas and total and round(total, 2) != 100:
        scale = 100 / total
        for persona in personas:
            persona["representation_pct"] = round(float(persona.get("representation_pct", 0) or 0) * scale, 2)
    rounded_total = round(sum(float(persona.get("representation_pct", 0) or 0) for persona in personas), 2)
    if personas and rounded_total != 100:
        personas[-1]["representation_pct"] = round(float(personas[-1].get("representation_pct", 0) or 0) + (100 - rounded_total), 2)
    for index, persona in enumerate(personas, start=1):
        persona.setdefault("persona_id", slugify(f"{persona_set.get('state', 'state')}_{index}_{persona.get('name', 'persona')}"))
        persona["synthetic"] = True
        persona.setdefault("safety_note", "Synthetic aggregate persona. Not a real person or individual profile.")
    persona_set["personas"] = personas
    persona_set["representation_total_pct"] = round(
        sum(float(persona.get("representation_pct", 0) or 0) for persona in personas),
        2,
    )
    return persona_set


def write_persona_files(persona_set: dict[str, Any], output_dir: str) -> dict[str, Any]:
    os.makedirs(output_dir, exist_ok=True)
    personas = persona_set.get("personas", []) if isinstance(persona_set, dict) else []
    files = []
    for persona in personas:
        persona_id = persona.get("persona_id") or slugify(persona.get("name", "persona"))
        path = os.path.abspath(os.path.join(output_dir, f"{persona_id}.json"))
        with open(path, "w", encoding="utf-8") as output:
            json.dump(persona, output, indent=2, sort_keys=True)
            output.write("\n")
        files.append(path)

    index_path = os.path.abspath(os.path.join(output_dir, "index.json"))
    with open(index_path, "w", encoding="utf-8") as output:
        json.dump(persona_set, output, indent=2, sort_keys=True)
        output.write("\n")

    return {"output_dir": os.path.abspath(output_dir), "index": index_path, "personas": files}


def top_share(priors: dict[str, Any], labels: dict[str, str]) -> dict[str, Any] | None:
    options = [
        {"field": field, "label": label, "share": priors.get(field)}
        for field, label in labels.items()
        if isinstance(priors.get(field), (int, float))
    ]
    if not options:
        return None
    return max(options, key=lambda item: item["share"])


def context_item(context: dict[str, Any] | None, key: str) -> dict[str, Any]:
    if not isinstance(context, dict):
        return {}
    value = context.get(key)
    return value if isinstance(value, dict) else {}


def top_age_band(priors: dict[str, Any]) -> dict[str, Any] | None:
    top = top_share(priors, {field: label for field, (label, _) in AGE_LABELS.items()})
    if not top:
        median_age = priors.get("median_age")
        return {"label": "median-age anchor", "age": round(median_age) if isinstance(median_age, (int, float)) else 39}
    _, age = AGE_LABELS[top["field"]]
    top["age"] = age
    return top


def value_or_zero(value: Any) -> float:
    return value if isinstance(value, (int, float)) else 0.0


def income_band_from_median(median: Any) -> str:
    if not isinstance(median, (int, float)):
        return "Not specified"
    if median >= 150000:
        return "$150k-$199k"
    if median >= 100000:
        return "$100k-$149k"
    if median >= 75000:
        return "$75k-$99k"
    if median >= 50000:
        return "$50k-$74k"
    if median >= 35000:
        return "$35k-$49k"
    return "Under $35k"


def infer_political_view(location: str, priors: dict[str, Any], sector: str) -> dict[str, str]:
    location_lower = location.lower()
    if "california" in location_lower:
        return {
            "view": "Center-left / Democratic-leaning",
            "basis": "Location-level political inference for California; not a Census field.",
        }
    if "texas" in location_lower or "florida" in location_lower:
        return {
            "view": "Mixed or center-right leaning",
            "basis": "Location-level political inference; not a Census field.",
        }
    if "Public administration" in sector or "Educational services" in sector:
        return {
            "view": "Center-left or institutionally pragmatic",
            "basis": "Low-confidence inference from sector context; not a Census field.",
        }
    return {
        "view": "Moderate / persuadable",
        "basis": "Default low-confidence inference because political ideology is not available in ACS.",
    }


def infer_household_context(priors: dict[str, Any], income_band: str) -> str:
    median = priors.get("median_household_income")
    if isinstance(median, (int, float)) and median >= 100000:
        return f"Lives in a household near a higher-cost, middle-to-upper income bracket ({income_band})."
    if isinstance(median, (int, float)) and median >= 50000:
        return f"Lives in a middle-income household around {income_band}, with cost-of-living sensitivity."
    return "Household details are synthetic and lightly grounded by aggregate income priors."


def infer_media_environment(location: str) -> list[str]:
    if "California" in location:
        return ["local TV/news apps", "Instagram", "YouTube clips", "Spanish-language or community media if relevant"]
    return ["local TV/news apps", "Facebook", "YouTube clips"]


def infer_institutional_trust(political_view: str, sector: str) -> dict[str, str]:
    if "Public administration" in sector or "Educational services" in sector:
        return {"government": "medium", "media": "medium", "experts": "medium-high"}
    if "Moderate" in political_view:
        return {"government": "low-medium", "media": "medium", "experts": "medium"}
    return {"government": "medium", "media": "medium", "experts": "medium"}


def infer_top_issues(sector: str, income_band: str, political_view: str) -> list[str]:
    issues = ["cost of living", "housing affordability"]
    if "Educational services" in sector or "health" in sector.lower():
        issues.append("healthcare access")
    if "Professional" in sector:
        issues.append("economic mobility")
    if "left" in political_view.lower():
        issues.append("climate and civil rights")
    if income_band in {"$50k-$74k", "$75k-$99k"}:
        issues.append("wages keeping up with prices")
    return issues


def build_persona_evidence(
    priors: dict[str, Any],
    context: dict[str, Any],
    political: dict[str, str],
    pums_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "correlation_backed_fields": {
            "source": "ACS PUMS anonymized person record",
            "status": (pums_profile or {}).get("status"),
            "query_attempts": (pums_profile or {}).get("query_attempts"),
            "sample_size": (pums_profile or {}).get("sample_size"),
            "sample_pool_size": (pums_profile or {}).get("sample_pool_size"),
            "total_matching_records": (pums_profile or {}).get("total_matching_records"),
            "fields": (pums_profile or {}).get("decoded_record"),
            "note": (pums_profile or {}).get("correlation_note"),
        },
        "census_backed_fields": {
            "age": context.get("age_distribution"),
            "sex": context.get("sex_distribution"),
            "race_ethnicity": context.get("dominant_race_ethnicity"),
            "education": context.get("education_distribution"),
            "household_income": context.get("income_distribution"),
            "employed_sector": context.get("employment_distribution", {}).get("largest_sector"),
            "occupation_group": context.get("employment_distribution", {}).get("largest_occupation_group"),
        },
        "inferred_fields": {
            "political_view": political,
            "media_environment": "Inferred from broad location/media assumptions; not ACS-backed.",
            "household_context": "Narrative synthesis from income priors, not an observed household.",
        },
        "acs_year": 2024,
        "raw_prior_count": len(priors),
    }


def choose_population_name(race: str, sex: str) -> str:
    lowered = race.lower()
    if "hispanic" in lowered and sex == "Female":
        return "Sofia"
    if "hispanic" in lowered:
        return "Daniel"
    if "asian" in lowered and sex == "Female":
        return "Mina"
    if "black" in lowered and sex == "Female":
        return "Tanya"
    return "Jordan"


def slugify(value: str) -> str:
    import re

    return re.sub(r"[^a-zA-Z0-9]+", "_", value).strip("_").lower()


def plan_pums_queries(priors: dict[str, Any], rng: random.Random | None = None) -> list[dict[str, Any]]:
    rng = rng or random.SystemRandom()
    age_options = sample_age_options(priors, rng)
    race_filters = dominant_race_filters(priors)
    education_filter = dominant_education_filter(priors)
    sex_filter = dominant_sex_filter(priors)
    base = {"ESR": "1"}
    if sex_filter:
        base.update(sex_filter)

    plans = []
    for index, age in enumerate(age_options[:3]):
        filters = {**base, "AGEP": str(age)}
        if index == 0:
            filters.update(race_filters)
            filters.update(education_filter)
            strategy = "employed_dominant_sex_random_age_race_education"
        elif index == 1:
            filters.update(race_filters)
            strategy = "employed_dominant_sex_random_age_race"
        else:
            filters.update(education_filter)
            strategy = "employed_dominant_sex_random_age_education"
        plans.append({"strategy": strategy, "filters": filters})

    broad_age = rng.choice(age_options)
    plans.append({"strategy": "employed_dominant_sex_random_age", "filters": {**base, "AGEP": str(broad_age)}})
    plans.append({"strategy": "employed_dominant_sex_no_age", "filters": base})
    return plans


def sample_age_options(priors: dict[str, Any], rng: random.Random) -> list[int]:
    bands = [
        (field, label, share)
        for field, (label, _) in AGE_LABELS.items()
        if isinstance((share := priors.get(field)), (int, float)) and share > 0
    ]
    if not bands:
        return [rng.randint(25, 64) for _ in range(4)]

    # Pick several bands with replacement using ACS shares, then sample an actual age inside each band.
    weights = [share for _, _, share in bands]
    chosen = rng.choices(bands, weights=weights, k=4)
    return [rng.randint(*age_range_for_label(label)) for _, label, _ in chosen]


def age_range_for_label(label: str) -> tuple[int, int]:
    return {
        "25-34": (25, 34),
        "35-44": (35, 44),
        "45-54": (45, 54),
        "65-74": (65, 74),
    }.get(label, (25, 64))


def dominant_race_filters(priors: dict[str, Any]) -> dict[str, str]:
    filters = {}
    race = top_share(priors, RACE_LABELS)
    if race and race.get("field") == "white_alone_or_combination_share":
        filters["RAC1P"] = "1"
        filters["HISP"] = "01"
    elif race and race.get("field") == "black_alone_or_combination_share":
        filters["RAC1P"] = "2"
        filters["HISP"] = "01"
    elif race and race.get("field") == "asian_alone_or_combination_share":
        filters["RAC1P"] = "6"
        filters["HISP"] = "01"
    elif race and race.get("field") == "hispanic_or_latino_share":
        filters["HISP"] = "02"
    return filters


def dominant_education_filter(priors: dict[str, Any]) -> dict[str, str]:
    filters = {}
    education = top_share(priors, EDUCATION_LABELS)
    if education and education.get("field") == "some_college_or_associates_share":
        filters["SCHL"] = "19"
    elif education and education.get("field") == "bachelors_degree_share":
        filters["SCHL"] = "21"
    elif education and education.get("field") == "graduate_or_professional_degree_share":
        filters["SCHL"] = "22"
    return filters


def dominant_sex_filter(priors: dict[str, Any]) -> dict[str, str]:
    female = priors.get("female_share")
    male = priors.get("male_share")
    if isinstance(female, (int, float)) and isinstance(male, (int, float)):
        return {"SEX": "2" if female >= male else "1"}
    return {"SEX": "2"}


def select_pums_record(records: list[dict[str, str]]) -> dict[str, str] | None:
    if not records:
        return None
    return random.SystemRandom().choice(records)


def decode_pums_record(record: dict[str, str]) -> dict[str, Any]:
    return {
        "age": parse_int(record.get("AGEP")),
        "sex": {"1": "Male", "2": "Female"}.get(record.get("SEX"), "Unknown"),
        "race_ethnicity": decode_race_ethnicity(record.get("RAC1P"), record.get("HISP")),
        "education": decode_schl(record.get("SCHL")),
        "employment_status": decode_esr(record.get("ESR")),
        "worker_class": decode_cow(record.get("COW")),
        "occupation": decode_occupation(record.get("OCCP")),
        "industry": decode_industry(record.get("INDP")),
        "personal_income": parse_int(record.get("PINCP")),
        "person_weight": parse_int(record.get("PWGTP")),
        "raw_codes": record,
    }


def decode_race_ethnicity(rac1p: str | None, hisp: str | None) -> str:
    if hisp and hisp != "01":
        return "Hispanic or Latino"
    return {
        "1": "White alone",
        "2": "Black or African American alone",
        "3": "American Indian alone",
        "4": "Alaska Native alone",
        "6": "Asian alone",
        "7": "Native Hawaiian or Pacific Islander alone",
        "8": "Some other race alone",
        "9": "Two or more races",
    }.get(rac1p or "", "Unknown")


def decode_schl(value: str | None) -> str:
    code = parse_int(value)
    if code is None:
        return "Unknown"
    if code <= 15:
        return "Less than high school"
    if code in {16, 17}:
        return "High school graduate"
    if code == 18:
        return "Some college, no degree"
    if code in {19, 20}:
        return "Associate's degree"
    if code == 21:
        return "Bachelor's degree"
    if code >= 22:
        return "Graduate or professional degree"
    return "Unknown"


def decode_esr(value: str | None) -> str:
    return {
        "1": "Civilian employed, at work",
        "2": "Civilian employed, with a job but not at work",
        "3": "Unemployed",
        "4": "Armed forces, at work",
        "5": "Armed forces, with a job but not at work",
        "6": "Not in labor force",
    }.get(value or "", "Unknown")


def decode_cow(value: str | None) -> str:
    return {
        "1": "Private for-profit wage and salary worker",
        "2": "Private not-for-profit wage and salary worker",
        "3": "Local government worker",
        "4": "State government worker",
        "5": "Federal government worker",
        "6": "Self-employed in own incorporated business",
        "7": "Self-employed in own not incorporated business",
        "8": "Unpaid family worker",
    }.get(value or "", "Unknown")


def decode_occupation(value: str | None) -> str:
    code = parse_int(value)
    if code is None:
        return "Unknown occupation"
    if code < 2000:
        return "Management, business, science, and arts"
    if code < 3600:
        return "Service"
    if code < 6000:
        return "Sales and office"
    if code < 7800:
        return "Natural resources, construction, and maintenance"
    return "Production, transportation, and material moving"


def decode_industry(value: str | None) -> str:
    code = parse_int(value)
    if code is None:
        return "Unknown industry"
    if code < 500:
        return "Agriculture, forestry, fishing, hunting, and mining"
    if code < 800:
        return "Construction"
    if code < 4000:
        return "Manufacturing"
    if code < 4700:
        return "Retail trade"
    if 7860 <= code < 8470:
        return "Educational services, health care, and social assistance"
    if 7270 <= code < 7860:
        return "Professional, scientific, management, administrative, and waste management services"
    if 6070 <= code < 6470:
        return "Finance, insurance, real estate, rental, and leasing"
    if 6470 <= code < 6790:
        return "Professional, scientific, management, administrative, and waste management services"
    if code >= 9370:
        return "Public administration"
    return "Other services"


def parse_int(value: str | None) -> int | None:
    try:
        return int(value) if value not in {None, ""} else None
    except ValueError:
        return None


def age_to_band(age: int | None) -> str:
    if age is None:
        return "Unknown"
    if age < 25:
        return "Under 25"
    if age < 35:
        return "25-34"
    if age < 45:
        return "35-44"
    if age < 55:
        return "45-54"
    if age < 65:
        return "55-64"
    return "65+"


def dollar_amount(value: int) -> str:
    return f"${value:,}"


def pums_unavailable_note(status: str | None) -> str:
    if status == "missing_api_key":
        return "PUMS correlation unavailable because CENSUS_API_KEY is not configured."
    if status == "key_rejected":
        return "PUMS correlation unavailable because the Census API rejected the configured key."
    if status == "unsupported_geography":
        return "PUMS correlation currently supports state-level population profiles."
    if status == "empty":
        return "PUMS query returned no matching anonymized person records."
    return "PUMS correlation unavailable; persona falls back to aggregate ACS profile priors."
