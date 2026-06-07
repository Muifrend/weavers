from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator

from app.agents.benchmark import BenchmarkAgent
from app.agents.persona import PersonaAgent, PersonaAgentResult
from app.agents.synthesis import SynthesisAgent
from app.config import Settings
from app.memory.local_persona_store import LocalPersonaStore
from app.memory.redis_agent_memory import RedisAgentMemory
from app.observability.weave_client import WeaveClient
from app.providers.base import ProviderError
from app.providers.router import ProviderRouter
from app.schemas import EventEnvelope, Persona, RunRequest
from app.streaming.ag_ui_events import EventBuilder, make_run_id, safe_error


logger = logging.getLogger(__name__)


class CampaignOrchestrator:
    def __init__(self, settings: Settings, *, initialize_weave: bool = True):
        self.settings = settings
        self.local_store = LocalPersonaStore()
        self.provider_router = ProviderRouter(settings)
        self.memory = RedisAgentMemory(settings)
        self.weave = WeaveClient(settings)
        if initialize_weave:
            self.weave.init()

    async def stream_run(self, request: RunRequest) -> AsyncIterator[EventEnvelope]:
        run_id = make_run_id(request.stimulus_id)
        builder = EventBuilder(run_id)
        started = time.perf_counter()

        yield builder.emit(
            "run.started",
            {
                "stimulus_id": request.stimulus_id,
                "event_name": event_name_for(request.stimulus_id),
                "memory_enabled": request.memory_enabled,
                "persona_count": request.persona_count,
            },
            weave_url=self.weave.weave_url(),
        )

        try:
            async for event in self._stream_run_after_start(request, run_id, builder, started):
                yield event
        except Exception as exc:  # noqa: BLE001 - terminal failure must be safe and contract-shaped.
            logger.exception("Run failed unexpectedly")
            yield builder.emit(
                "run.failed",
                {
                    "run_id": run_id,
                    "stimulus_id": request.stimulus_id,
                    "completed_personas": 0,
                    "failed_personas": request.persona_count,
                    "error_code": "run_exception",
                    "message": f"Run failed unexpectedly: {exc.__class__.__name__}.",
                },
                error=safe_error("run_exception", "The run failed unexpectedly."),
            )

    async def _stream_run_after_start(
        self,
        request: RunRequest,
        run_id: str,
        builder: EventBuilder,
        started: float,
    ) -> AsyncIterator[EventEnvelope]:
        if request.stimulus_id != "dobbs_2022":
            yield builder.emit(
                "run.failed",
                {
                    "run_id": run_id,
                    "stimulus_id": request.stimulus_id,
                    "completed_personas": 0,
                    "failed_personas": request.persona_count,
                    "error_code": "unsupported_stimulus",
                    "message": "Only dobbs_2022 is supported in the first pass.",
                },
                error=safe_error("unsupported_stimulus", "Only dobbs_2022 is supported."),
            )
            return

        try:
            selected_personas = self.local_store.select_personas(request.persona_count, request.persona_set_id)
        except (FileNotFoundError, ValueError) as exc:
            yield builder.emit(
                "run.failed",
                {
                    "run_id": run_id,
                    "stimulus_id": request.stimulus_id,
                    "completed_personas": 0,
                    "failed_personas": 0,
                    "error_code": "personas_not_generated",
                    "message": str(exc),
                },
                error=safe_error("personas_not_generated", str(exc)),
            )
            return

        personas = self.provider_router.assign_personas(
            selected_personas,
            providers=request.providers,
            model_overrides=request.provider_models,
        )

        agent = PersonaAgent(self.provider_router, self.memory, self.weave)
        semaphore = asyncio.Semaphore(max(1, self.settings.persona_concurrency_limit))
        completed: list[tuple[Persona, PersonaAgentResult]] = []
        failed: list[tuple[Persona, str, str]] = []

        tasks = [
            asyncio.create_task(
                run_persona_safely(
                    semaphore=semaphore,
                    agent=agent,
                    persona=persona,
                    run_id=run_id,
                    stimulus_id=request.stimulus_id,
                    stimulus_text=request.stimulus_text,
                    memory_enabled=request.memory_enabled,
                )
            )
            for persona in personas
        ]

        for task in asyncio.as_completed(tasks):
            persona, result, error_code, message = await task
            if result:
                completed.append((persona, result))
                payload = persona_reaction_payload(persona, result)
                if result.memory_warning:
                    payload["memory_warning"] = result.memory_warning
                yield builder.emit("persona_reaction.completed", payload)
            else:
                failed.append((persona, error_code, message))
                yield builder.emit(
                    "persona_reaction.failed",
                    {
                        "persona_id": persona.persona_id,
                        "persona_name": persona.name,
                        "provider": persona.assigned_provider or "fallback",
                        "model_used": persona.assigned_model or "unknown",
                        "error_code": error_code,
                        "message": message,
                    },
                    error=safe_error(error_code, message),
                )

        threshold = minimum_success_threshold(len(personas))
        if len(completed) < threshold:
            yield builder.emit(
                "run.failed",
                {
                    "run_id": run_id,
                    "stimulus_id": request.stimulus_id,
                    "completed_personas": len(completed),
                    "failed_personas": len(failed),
                    "error_code": "insufficient_persona_completions",
                    "message": (
                        f"Only {len(completed)} of {len(personas)} personas completed, "
                        f"below the minimum threshold of {threshold}."
                    ),
                },
                error=safe_error(
                    "insufficient_persona_completions",
                    "Too few personas completed for synthesis.",
                ),
            )
            return

        yield builder.emit(
            "synthesis.started",
            {"completed_personas": len(completed), "failed_personas": len(failed)},
        )

        synthesis_agent = SynthesisAgent(self.provider_router, self.weave)
        synthesis = await synthesis_agent.run(
            reactions=[(persona, result.reaction) for persona, result in completed]
        )

        for segment in synthesis.segments:
            yield builder.emit("synthesis.segment_completed", segment.model_dump())

        for red_flag in synthesis.red_flags:
            yield builder.emit("synthesis.red_flag_detected", red_flag.model_dump())

        yield builder.emit(
            "synthesis.completed",
            {
                "overall_sentiment": synthesis.overall_sentiment,
                "executive_summary": synthesis.executive_summary,
                "best_quotes": [quote.model_dump() for quote in synthesis.best_quotes],
            },
        )

        if not request.skip_benchmark:
            benchmark_id = benchmark_id_for(request.stimulus_id)
            yield builder.emit("benchmark.started", {"benchmark_id": benchmark_id})

            benchmark_agent = BenchmarkAgent(self.local_store, self.weave)
            benchmark = await benchmark_agent.run(benchmark_id=benchmark_id, synthesis=synthesis)
            yield builder.emit("benchmark.completed", benchmark.model_dump())

        total_latency_ms = int((time.perf_counter() - started) * 1000)
        yield builder.emit(
            "run.completed",
            {
                "run_id": run_id,
                "stimulus_id": request.stimulus_id,
                "completed_personas": len(completed),
                "failed_personas": len(failed),
                "memory_enabled": request.memory_enabled,
                "total_latency_ms": total_latency_ms,
                "weave_url": self.weave.weave_url(),
            },
            weave_url=self.weave.weave_url(),
        )


async def run_persona_safely(
    *,
    semaphore: asyncio.Semaphore,
    agent: PersonaAgent,
    persona: Persona,
    run_id: str,
    stimulus_id: str,
    stimulus_text: str,
    memory_enabled: bool,
) -> tuple[Persona, PersonaAgentResult | None, str, str]:
    async with semaphore:
        try:
            result = await agent.run(
                persona=persona,
                run_id=run_id,
                stimulus_id=stimulus_id,
                stimulus_text=stimulus_text,
                memory_enabled=memory_enabled,
            )
            return persona, result, "", ""
        except ProviderError as exc:
            logger.warning("Persona %s failed: %s", persona.persona_id, exc.error_code)
            return persona, None, exc.error_code, "Persona response failed and was omitted from synthesis."
        except Exception as exc:  # noqa: BLE001
            logger.warning("Persona %s failed: %s", persona.persona_id, exc.__class__.__name__)
            return persona, None, "persona_failed", "Persona response failed and was omitted from synthesis."


def persona_reaction_payload(persona: Persona, result: PersonaAgentResult) -> dict[str, object]:
    reaction = result.reaction
    return {
        "persona_id": persona.persona_id,
        "persona_name": persona.name,
        "age": persona.age,
        "location": persona.display_location(),
        "occupation": persona.occupation,
        "segment_tags": persona.segment_tags,
        "provider": reaction.provider,
        "model_used": reaction.model_used,
        "reaction_text": reaction.reaction_text,
        "voter_voice_quote": reaction.voter_voice_quote,
        "latency_ms": reaction.latency_ms,
    }


def minimum_success_threshold(persona_count: int) -> int:
    if persona_count >= 20:
        return 15
    return persona_count


def event_name_for(stimulus_id: str) -> str:
    if stimulus_id == "dobbs_2022":
        return "Dobbs v. Jackson, June 2022"
    return stimulus_id


def benchmark_id_for(stimulus_id: str) -> str:
    if stimulus_id == "dobbs_2022":
        return "dobbs_2022"
    return stimulus_id
