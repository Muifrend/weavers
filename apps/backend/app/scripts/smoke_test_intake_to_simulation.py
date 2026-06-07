from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from app.agents.persona_creation import PersonaCreationAgent
from app.config import get_settings
from app.memory.local_persona_store import LocalPersonaStore
from app.orchestrator import CampaignOrchestrator
from app.schemas import PersonaGenerationRequest, RunRequest


DOBBS_TEXT = (
    "The Supreme Court has overturned Roe v. Wade in the Dobbs v. Jackson decision, "
    "ending the constitutional right to abortion and returning the matter to states."
)


async def main() -> int:
    settings = get_settings()
    location = os.getenv("PERSONA_INTAKE_SMOKE_LOCATION") or "California"
    count = int(os.getenv("PERSONA_INTAKE_SMOKE_COUNT") or "3")

    orchestrator = CampaignOrchestrator(settings)
    orchestrator.local_store = LocalPersonaStore(
        personas_path=Path("/tmp/weavers-persona-intake-smoke/personas.json"),
        benchmark_path=orchestrator.local_store.benchmark_path,
    )

    agent = PersonaCreationAgent(settings=settings, store=orchestrator.local_store)
    try:
        generation = await agent.generate_state_personas(
            PersonaGenerationRequest(location=location, persona_count=count, persist=True)
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[fail] Persona intake failed: {exc.__class__.__name__}: {exc}")
        return 1

    if len(generation.personas) != count:
        print(f"[fail] Generated {len(generation.personas)} personas; expected {count}")
        return 1
    if not all(persona.evidence_backing for persona in generation.personas):
        print("[fail] Generated personas are missing evidence_backing")
        return 1

    print(f"[ok] Generated {count} evidence-backed personas for {generation.location}")
    print(f"[ok] Saved temporary persona store: {generation.saved_path}")

    request = RunRequest(
        stimulus_id="dobbs_2022",
        stimulus_text=DOBBS_TEXT,
        memory_enabled=False,
        persona_count=count,
    )
    event_types: list[str] = []
    async for event in orchestrator.stream_run(request):
        event_types.append(event.event_type)

    if "run.failed" in event_types or "run.completed" not in event_types:
        print("[fail] Sentiment simulation did not complete")
        print("Events:", ", ".join(event_types))
        return 1

    print("[ok] Ran sentiment analysis against generated personas")
    print("[ok] Intake-to-simulation smoke test passed")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

