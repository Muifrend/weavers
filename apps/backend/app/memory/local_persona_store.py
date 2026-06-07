from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.config import REPO_ROOT
from app.schemas import Persona


class LocalPersonaStore:
    def __init__(
        self,
        personas_path: Path | None = None,
        benchmark_path: Path | None = None,
    ):
        self.personas_path = personas_path or REPO_ROOT / "data" / "personas" / "personas.json"
        self.benchmark_path = benchmark_path or REPO_ROOT / "data" / "benchmarks" / "dobbs_2022.json"

    def load_personas(self) -> list[Persona]:
        if not self.personas_path.exists():
            raise FileNotFoundError(
                f"No generated persona store exists at {self.personas_path}. Generate evidence-backed state personas first."
            )
        raw = json.loads(self.personas_path.read_text(encoding="utf-8"))
        return [Persona.model_validate(item) for item in raw["personas"]]

    def save_personas(self, personas: list[Persona]) -> None:
        self.personas_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"personas": [persona.model_dump(exclude_none=True) for persona in personas]}
        self.personas_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def select_personas(self, count: int) -> list[Persona]:
        personas = self.load_personas()
        if len(personas) < count:
            raise ValueError(
                f"Requested {count} personas, but only {len(personas)} generated evidence-backed personas are available."
            )
        selected = personas[:count]
        missing_evidence = [persona.persona_id for persona in selected if not persona.evidence_backing]
        if missing_evidence:
            raise ValueError("Selected personas are missing evidence_backing and cannot be used for simulation.")
        return selected

    def get_persona(self, persona_id: str) -> Persona | None:
        try:
            personas = self.load_personas()
        except FileNotFoundError:
            return None
        for persona in personas:
            if persona.persona_id == persona_id:
                return persona
        return None

    def load_benchmark(self, benchmark_id: str = "dobbs_2022") -> dict[str, Any]:
        raw = json.loads(self.benchmark_path.read_text(encoding="utf-8"))
        if raw.get("benchmark_id") != benchmark_id:
            raise ValueError(f"Unsupported benchmark_id: {benchmark_id}")
        return raw
