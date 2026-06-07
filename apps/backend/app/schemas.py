from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


ProviderName = Literal["openai", "anthropic", "gemini", "openrouter", "fallback"]
SentimentDirection = Literal[
    "strongly_negative",
    "negative",
    "mixed",
    "neutral",
    "positive",
    "strongly_positive",
]
MovementSignal = Literal[
    "low_salience",
    "persuasion_risk",
    "persuasion_opportunity",
    "high_activation",
    "base_reinforcement",
    "unclear",
]
Severity = Literal["low", "medium", "high"]


class RunRequest(BaseModel):
    stimulus_id: str
    stimulus_text: str
    memory_enabled: bool
    persona_count: int = Field(default=20, ge=1, le=100)


class PersonaLocation(BaseModel):
    city: str
    state: str
    geo_type: str


class InstitutionalTrust(BaseModel):
    government: str
    media: str
    experts: str


class Persona(BaseModel):
    persona_id: str
    name: str
    age: int
    location: PersonaLocation
    race_ethnicity: str
    education: str
    occupation: str
    industry: str
    income_bracket: str
    party_affiliation: str
    ideology: str
    top_issues: list[str]
    media_diet: list[str]
    institutional_trust: InstitutionalTrust
    personal_stake: str
    segment_tags: list[str]
    assigned_provider: str | None = None
    assigned_model: str | None = None
    representation_pct: float | None = None
    representation_basis: str | None = None
    evidence_backing: dict[str, Any] | None = None

    def display_location(self) -> str:
        return f"{self.location.geo_type.title()} {self.location.city}, {self.location.state}"


class PersonaReaction(BaseModel):
    persona_id: str
    persona_name: str
    provider: ProviderName
    model_used: str
    reaction_text: str
    voter_voice_quote: str
    latency_ms: int


class SynthesisSegment(BaseModel):
    segment_id: str
    segment_name: str
    sentiment_direction: SentimentDirection
    movement_signal: MovementSignal
    persona_count: int
    summary: str


class RedFlag(BaseModel):
    segment: str
    flag_description: str
    affected_personas: list[str]
    severity: Severity


class BestQuote(BaseModel):
    persona_id: str
    quote: str


class SynthesisOutput(BaseModel):
    overall_sentiment: str
    segments: list[SynthesisSegment]
    red_flags: list[RedFlag]
    best_quotes: list[BestQuote]
    executive_summary: str


class BenchmarkDatum(BaseModel):
    segment: str
    actual: str
    source_label: str


class SimulatedDistributionDatum(BaseModel):
    segment: str
    simulated: str


class BenchmarkOutput(BaseModel):
    event_name: str
    calibration_score: int = Field(ge=0, le=100)
    score_label: str
    simulated_distribution: list[SimulatedDistributionDatum]
    actual_polling_data: list[BenchmarkDatum]
    interpretation: str


class EventEnvelope(BaseModel):
    event_type: str
    run_id: str
    sequence: int
    timestamp: str
    payload: dict[str, Any]
    trace_id: str | None = None
    weave_url: str | None = None
    error: dict[str, Any] | None = None


class PersonaGenerationRequest(BaseModel):
    location: str
    persona_count: int = Field(default=10, ge=1, le=100)
    persist: bool = True


class PersonaGenerationResponse(BaseModel):
    status: str
    location: str
    personas: list[Persona]
    representation_total_pct: float
    demographic_priors: dict[str, Any]
    population_context: dict[str, Any]
    saved_path: str | None = None
    warnings: list[str] = Field(default_factory=list)
