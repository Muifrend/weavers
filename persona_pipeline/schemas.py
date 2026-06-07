from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal


AgentStatus = Literal["complete", "partial", "blocked", "rejected"]


@dataclass
class Evidence:
    source: str
    source_type: str
    year: int | None = None
    url: str | None = None
    variables: list[str] = field(default_factory=list)
    confidence: Literal["low", "medium", "high"] = "medium"
    notes: str | None = None


@dataclass
class AgentResult:
    agent: str
    status: AgentStatus
    data: dict[str, Any] = field(default_factory=dict)
    evidence: list[Evidence] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class PersonaRequest:
    raw_text: str
    location: str | None = None
    issue: str | None = None
    segment_tags: list[str] = field(default_factory=list)
    age: int | None = None
    race_ethnicity: str | None = None
    education: str | None = None
    income_range: str | None = None
    occupation: str | None = None
    industry: str | None = None
    party_affiliation: str | None = None
    ideology: str | None = None
    media_diet: list[str] = field(default_factory=list)
    personal_stake: str | None = None

    def missing_required_fields(self) -> list[str]:
        missing = []
        if not self.location:
            missing.append("location")
        if not self.issue:
            missing.append("issue")
        return missing


@dataclass
class SafetyConstraints:
    synthetic_only: bool = True
    no_real_person_profiles: bool = True
    no_individual_sensitive_inference: bool = True
    no_private_or_social_scraping: bool = True
    no_voter_file_profiles: bool = True


@dataclass
class EvidencePacket:
    persona_request: PersonaRequest
    geo_context: dict[str, Any] = field(default_factory=dict)
    demographic_priors: dict[str, Any] = field(default_factory=dict)
    economic_priors: dict[str, Any] = field(default_factory=dict)
    occupation_context: dict[str, Any] = field(default_factory=dict)
    media_priors: dict[str, Any] = field(default_factory=dict)
    local_issue_context: dict[str, Any] = field(default_factory=dict)
    manual_personal_stake: dict[str, Any] = field(default_factory=dict)
    safety_constraints: SafetyConstraints = field(default_factory=SafetyConstraints)
    evidence: list[Evidence] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


@dataclass
class Persona:
    persona_id: str
    name: str
    age: int
    location: dict[str, str]
    race_ethnicity: str
    education: str
    occupation: str
    industry: str
    income_bracket: str
    party_affiliation: str
    ideology: str
    top_issues: list[str]
    media_diet: list[str]
    institutional_trust: dict[str, str]
    personal_stake: str
    segment_tags: list[str]
    synthetic: bool
    why_plausible: list[str]
    provenance_summary: list[dict[str, Any]]
    evidence_backing: dict[str, Any]


def to_dict(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    if isinstance(value, list):
        return [to_dict(item) for item in value]
    if isinstance(value, dict):
        return {key: to_dict(item) for key, item in value.items()}
    return value
