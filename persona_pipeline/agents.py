from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .adapters import ApprovedSourceFetcher, BLSAdapter, CensusAdapter, extract_state
from .schemas import AgentResult, Evidence, PersonaRequest


ACS_PROFILE_VARIABLES = {
    "DP05_0001E": "total_population",
    "DP05_0002PE": "male_share",
    "DP05_0003PE": "female_share",
    "DP05_0010PE": "age_25_to_34_share",
    "DP05_0011PE": "age_35_to_44_share",
    "DP05_0012PE": "age_45_to_54_share",
    "DP05_0015PE": "age_65_to_74_share",
    "DP05_0018E": "median_age",
    "DP05_0083PE": "white_alone_or_combination_share",
    "DP05_0084PE": "black_alone_or_combination_share",
    "DP05_0086PE": "asian_alone_or_combination_share",
    "DP05_0090PE": "hispanic_or_latino_share",
    "DP02_0062PE": "high_school_graduate_share",
    "DP02_0063PE": "some_college_no_degree_share",
    "DP02_0064PE": "associates_degree_share",
    "DP02_0065PE": "bachelors_degree_share",
    "DP02_0066PE": "graduate_or_professional_degree_share",
    "DP03_0027PE": "management_business_science_arts_occupation_share",
    "DP03_0028PE": "service_occupation_share",
    "DP03_0029PE": "sales_office_occupation_share",
    "DP03_0030PE": "natural_resources_construction_maintenance_occupation_share",
    "DP03_0031PE": "production_transportation_material_moving_occupation_share",
    "DP03_0033PE": "agriculture_mining_industry_share",
    "DP03_0035PE": "manufacturing_industry_share",
    "DP03_0037PE": "retail_trade_industry_share",
    "DP03_0038PE": "transportation_warehousing_utilities_industry_share",
    "DP03_0040PE": "finance_real_estate_industry_share",
    "DP03_0041PE": "professional_scientific_management_admin_industry_share",
    "DP03_0042PE": "education_health_social_assistance_industry_share",
    "DP03_0043PE": "arts_accommodation_food_industry_share",
    "DP03_0045PE": "public_administration_industry_share",
    "DP03_0047PE": "private_wage_salary_worker_share",
    "DP03_0048PE": "government_worker_share",
    "DP03_0049PE": "self_employed_worker_share",
    "DP03_0056PE": "household_income_35k_49k_share",
    "DP03_0057PE": "household_income_50k_74k_share",
    "DP03_0058PE": "household_income_75k_99k_share",
    "DP03_0059PE": "household_income_100k_149k_share",
    "DP03_0060PE": "household_income_150k_199k_share",
    "DP03_0062E": "median_household_income",
}


@dataclass
class SupervisorAgent:
    def run(self, request: PersonaRequest) -> AgentResult:
        missing = request.missing_required_fields()
        if missing:
            return AgentResult(
                agent="supervisor_agent",
                status="blocked",
                data={
                    "clarifying_question": f"What {missing[0]} should this persona be grounded in?",
                    "missing": missing,
                },
            )

        return AgentResult(
            agent="supervisor_agent",
            status="complete",
            data={
                "plan": [
                    "resolve_geography",
                    "pull_acs_priors",
                    "pull_occupation_context",
                    "fetch_approved_local_context",
                    "normalize_evidence_packet",
                    "generate_llm_persona",
                ]
            },
        )


@dataclass
class GeoAgent:
    census: CensusAdapter = field(default_factory=CensusAdapter)

    def run(self, request: PersonaRequest) -> AgentResult:
        geo = self.census.resolve_place(request.location or "")
        status = "complete" if geo.get("resolved_options") else "partial"
        return AgentResult(
            agent="geo_agent",
            status=status,
            data={"geography": geo},
            evidence=[
                Evidence(
                    source="U.S. Census Bureau geography / ACS place lookup",
                    source_type="public_aggregate_api",
                    year=self.census.acs_year,
                    confidence="high" if status == "complete" else "medium",
                    notes="Resolves user location into Census geography where possible.",
                )
            ],
        )


@dataclass
class DemographicAgent:
    census: CensusAdapter = field(default_factory=CensusAdapter)

    def run(self, geo_context: dict[str, Any]) -> AgentResult:
        variables = list(ACS_PROFILE_VARIABLES)
        profile = self.census.fetch_profile(geo_context, variables)
        values = profile.get("values", {})
        features = {
            name: parse_number(values.get(variable))
            for variable, name in ACS_PROFILE_VARIABLES.items()
            if variable in values
        }
        some_college = features.get("some_college_no_degree_share")
        associates = features.get("associates_degree_share")
        if isinstance(some_college, (int, float)) and isinstance(associates, (int, float)):
            features["some_college_or_associates_share"] = round(some_college + associates, 1)

        if not features:
            return AgentResult(
                agent="demographic_agent",
                status="partial",
                data={"features": {}, "raw_status": profile.get("status")},
                evidence=[
                    Evidence(
                        source="U.S. Census Bureau ACS 5-year profile",
                        source_type="public_aggregate_api",
                        year=self.census.acs_year,
                        url=profile.get("url"),
                        variables=variables,
                        confidence="low",
                        notes=acs_unavailable_note(profile.get("status")),
                    )
                ],
                warnings=[acs_unavailable_note(profile.get("status"))],
            )

        return AgentResult(
            agent="demographic_agent",
            status="complete",
            data={"features": features, "raw_name": values.get("NAME")},
            evidence=[
                Evidence(
                    source="U.S. Census Bureau ACS 5-year profile",
                    source_type="public_aggregate_api",
                    year=self.census.acs_year,
                    url=profile.get("url"),
                    variables=variables,
                    confidence="high",
                )
            ],
        )


@dataclass
class OccupationAgent:
    bls: BLSAdapter = field(default_factory=BLSAdapter)

    def run(self, request: PersonaRequest) -> AgentResult:
        context = self.bls.lookup_occupation(request.occupation, extract_state(request.location))
        status = "complete" if context.get("mapping") else "partial"
        return AgentResult(
            agent="occupation_agent",
            status=status,
            data={"occupation_context": context},
            evidence=[
                Evidence(
                    source="U.S. Bureau of Labor Statistics OEWS occupation taxonomy",
                    source_type="public_aggregate_dataset",
                    year=None,
                    url="https://www.bls.gov/oes/",
                    confidence="medium" if status == "complete" else "low",
                )
            ],
            warnings=[] if status == "complete" else ["Occupation could not be mapped to a known SOC code."],
        )


@dataclass
class LocalContextAgent:
    fetcher: ApprovedSourceFetcher = field(default_factory=ApprovedSourceFetcher)

    def run(self, request: PersonaRequest, source_urls: list[str] | None = None) -> AgentResult:
        fetched = self.fetcher.fetch(source_urls or [])
        accepted = [item for item in fetched if item.get("status") == "complete"]
        rejected = [item for item in fetched if item.get("status") == "rejected"]

        issue_context = {
            "issue": request.issue,
            "location": request.location,
            "approved_sources": accepted,
            "context_notes": build_issue_notes(request),
        }
        evidence = [
            Evidence(
                source=item.get("title") or item["url"],
                source_type="approved_public_web",
                url=item["url"],
                confidence="medium",
            )
            for item in accepted
        ]
        if not evidence:
            evidence.append(
                Evidence(
                    source="No approved local URLs supplied",
                    source_type="internal_note",
                    confidence="low",
                    notes="Local context is limited to request text and aggregate priors.",
                )
            )

        warnings = []
        if rejected:
            warnings.append(f"{len(rejected)} source URL(s) rejected by whitelist.")

        return AgentResult(
            agent="local_context_agent",
            status="complete" if accepted else "partial",
            data={"local_issue_context": issue_context},
            evidence=evidence,
            warnings=warnings,
        )


def parse_number(value: str | None) -> float | int | None:
    if value is None:
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    if number.is_integer():
        return int(number)
    return number


def acs_unavailable_note(status: str | None) -> str:
    if status == "missing_api_key":
        return "ACS demographic priors unavailable because CENSUS_API_KEY is not configured."
    if status == "key_rejected":
        return "ACS demographic priors unavailable because the Census API rejected the configured key."
    return "ACS request unavailable; LLM generation must rely on user-provided fields and other evidence."


def build_issue_notes(request: PersonaRequest) -> list[str]:
    notes = []
    issue = (request.issue or "").lower()
    if "reproductive" in issue or "abortion" in issue:
        notes.append("Treat reproductive rights as a public issue context, not as an inferred private health fact.")
    if request.occupation and "union" in request.occupation.lower():
        notes.append("Union context may shape economic trust and messenger credibility.")
    if request.location:
        notes.append(f"Ground local texture in approved public sources for {request.location}.")
    return notes
