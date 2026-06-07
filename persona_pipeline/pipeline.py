from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from .agents import DemographicAgent, GeoAgent, LocalContextAgent, OccupationAgent, SupervisorAgent
from .generator import PersonaGenerator
from .openai_agent import OpenAIConfigError, OpenAIRequestError
from .parser import parse_persona_request
from .schemas import AgentResult, Evidence, EvidencePacket, Persona, PersonaRequest, to_dict
from .weave_support import traceable_op


class PersonaGraphState(TypedDict, total=False):
    request_input: PersonaRequest | str
    source_urls: list[str] | None
    include_packet: bool
    parsed_request: PersonaRequest
    supervisor_result: AgentResult
    geo_result: AgentResult
    demographic_result: AgentResult
    occupation_result: AgentResult
    local_result: AgentResult
    generation_result: AgentResult
    geo_context: dict[str, Any]
    evidence_packet: EvidencePacket
    persona: Persona
    status: str
    reason: str
    response: dict[str, Any]


@dataclass
class PersonaPipeline:
    supervisor: SupervisorAgent = field(default_factory=SupervisorAgent)
    geo_agent: GeoAgent = field(default_factory=GeoAgent)
    demographic_agent: DemographicAgent = field(default_factory=DemographicAgent)
    occupation_agent: OccupationAgent = field(default_factory=OccupationAgent)
    local_context_agent: LocalContextAgent = field(default_factory=LocalContextAgent)
    generator: PersonaGenerator = field(default_factory=PersonaGenerator)
    _graph: Any = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._graph = self._build_graph()

    @traceable_op(name="persona_pipeline_run")
    def run(
        self,
        request: PersonaRequest | str,
        source_urls: list[str] | None = None,
        include_packet: bool = True,
    ) -> dict[str, Any]:
        state = self._graph.invoke(
            {
                "request_input": request,
                "source_urls": source_urls,
                "include_packet": include_packet,
            }
        )
        return state["response"]

    def _build_graph(self) -> Any:
        graph = StateGraph(PersonaGraphState)
        graph.add_node("parse_request", self._parse_request)
        graph.add_node("supervise", self._supervise)
        graph.add_node("resolve_geography", self._resolve_geography)
        graph.add_node("pull_demographics", self._pull_demographics)
        graph.add_node("pull_occupation", self._pull_occupation)
        graph.add_node("fetch_local_context", self._fetch_local_context)
        graph.add_node("build_evidence_packet", self._build_evidence_packet)
        graph.add_node("generate_persona", self._generate_persona)
        graph.add_node("finalize", self._finalize)

        graph.add_edge(START, "parse_request")
        graph.add_edge("parse_request", "supervise")
        graph.add_conditional_edges(
            "supervise",
            route_after_supervisor,
            {
                "needs_clarification": "finalize",
                "continue": "resolve_geography",
            },
        )
        graph.add_edge("resolve_geography", "pull_demographics")
        graph.add_edge("pull_demographics", "pull_occupation")
        graph.add_edge("pull_occupation", "fetch_local_context")
        graph.add_edge("fetch_local_context", "build_evidence_packet")
        graph.add_edge("build_evidence_packet", "generate_persona")
        graph.add_edge("generate_persona", "finalize")
        graph.add_edge("finalize", END)
        return graph.compile()

    def _parse_request(self, state: PersonaGraphState) -> PersonaGraphState:
        request_input = state["request_input"]
        parsed_request = parse_persona_request(request_input) if isinstance(request_input, str) else request_input
        return {"parsed_request": parsed_request}

    def _supervise(self, state: PersonaGraphState) -> PersonaGraphState:
        supervisor_result = self.supervisor.run(state["parsed_request"])
        if supervisor_result.status == "blocked":
            return {"supervisor_result": supervisor_result, "status": "needs_clarification"}
        return {"supervisor_result": supervisor_result}

    def _resolve_geography(self, state: PersonaGraphState) -> PersonaGraphState:
        geo_result = self.geo_agent.run(state["parsed_request"])
        return {"geo_result": geo_result, "geo_context": geo_result.data.get("geography", {})}

    def _pull_demographics(self, state: PersonaGraphState) -> PersonaGraphState:
        return {"demographic_result": self.demographic_agent.run(state.get("geo_context", {}))}

    def _pull_occupation(self, state: PersonaGraphState) -> PersonaGraphState:
        return {"occupation_result": self.occupation_agent.run(state["parsed_request"])}

    def _fetch_local_context(self, state: PersonaGraphState) -> PersonaGraphState:
        return {
            "local_result": self.local_context_agent.run(
                state["parsed_request"],
                source_urls=state.get("source_urls") or [],
            )
        }

    def _build_evidence_packet(self, state: PersonaGraphState) -> PersonaGraphState:
        demographic_features = state["demographic_result"].data.get("features", {})
        packet = EvidencePacket(
            persona_request=state["parsed_request"],
            geo_context=state.get("geo_context", {}),
            demographic_priors=demographic_features,
            economic_priors={"median_household_income": demographic_features.get("median_household_income")},
            occupation_context=state["occupation_result"].data.get("occupation_context", {}),
            media_priors={"default_media_diet": ["local TV", "Facebook", "local news clips"]},
            local_issue_context=state["local_result"].data.get("local_issue_context", {}),
            manual_personal_stake={
                "value": state["parsed_request"].personal_stake,
                "provided": state["parsed_request"].personal_stake is not None,
            },
            evidence=[
                *state["geo_result"].evidence,
                *state["demographic_result"].evidence,
                *state["occupation_result"].evidence,
                *state["local_result"].evidence,
            ],
            warnings=[
                *state["geo_result"].warnings,
                *state["demographic_result"].warnings,
                *state["occupation_result"].warnings,
                *state["local_result"].warnings,
            ],
        )
        return {"evidence_packet": packet}

    def _generate_persona(self, state: PersonaGraphState) -> PersonaGraphState:
        try:
            persona = self.generator.generate(state["evidence_packet"])
        except OpenAIConfigError as error:
            return {
                "status": "blocked",
                "reason": "llm_generation_unavailable",
                "generation_result": generation_blocked_result(str(error)),
            }
        except OpenAIRequestError as error:
            return {
                "status": "partial",
                "reason": "llm_generation_failed",
                "generation_result": generation_failed_result(str(error)),
            }

        return {
            "status": "complete",
            "persona": persona,
            "generation_result": AgentResult(
                agent="openai_single_persona_agent",
                status="complete",
                data={"llm_generated": True},
                evidence=[
                    Evidence(
                        source="OpenAI Responses API structured output",
                        source_type="model_generation_from_evidence_packet",
                        confidence="medium",
                        notes="Generated the final persona JSON from the assembled evidence packet.",
                    )
                ],
            ),
        }

    def _finalize(self, state: PersonaGraphState) -> PersonaGraphState:
        include_packet = state.get("include_packet", True)
        status = state.get("status") or "complete"
        agent_results = collect_agent_results(state)

        if status == "needs_clarification":
            response = {
                "status": "needs_clarification",
                "supervisor": to_dict(state["supervisor_result"]),
                "agent_results": [to_dict(result) for result in agent_results],
            }
            return {"response": response}

        if "persona" not in state:
            response = {
                "status": status,
                "reason": state.get("reason", "persona_generation_incomplete"),
                "agent_results": [to_dict(result) for result in agent_results],
            }
            if include_packet and "evidence_packet" in state:
                response["evidence_packet"] = to_dict(state["evidence_packet"])
            return {"response": response}

        response = {
            "status": "complete",
            "persona": to_dict(state["persona"]),
            "agent_results": [to_dict(result) for result in agent_results],
        }
        if include_packet:
            response["evidence_packet"] = to_dict(state["evidence_packet"])
        return {"response": response}


def route_after_supervisor(state: PersonaGraphState) -> str:
    if state.get("supervisor_result") and state["supervisor_result"].status == "blocked":
        return "needs_clarification"
    return "continue"


def collect_agent_results(state: PersonaGraphState) -> list[AgentResult]:
    keys = [
        "supervisor_result",
        "geo_result",
        "demographic_result",
        "occupation_result",
        "local_result",
        "generation_result",
    ]
    return [state[key] for key in keys if key in state]


def generation_blocked_result(message: str) -> AgentResult:
    return AgentResult(
        agent="openai_single_persona_agent",
        status="blocked",
        data={"llm_generated": False},
        evidence=[Evidence(source="OpenAI Responses API", source_type="model_generation", confidence="low", notes=message)],
        warnings=[message],
    )


def generation_failed_result(message: str) -> AgentResult:
    return AgentResult(
        agent="openai_single_persona_agent",
        status="partial",
        data={"llm_generated": False},
        evidence=[Evidence(source="OpenAI Responses API", source_type="model_generation", confidence="low", notes=message)],
        warnings=[message],
    )
