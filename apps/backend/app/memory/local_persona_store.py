from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from app.config import REPO_ROOT
from app.schemas import Persona

LEGACY_SET_ID = "legacy-default"


class LocalPersonaStore:
    def __init__(
        self,
        personas_path: Path | None = None,
        benchmark_path: Path | None = None,
        sets_dir: Path | None = None,
    ):
        self.personas_path = personas_path or REPO_ROOT / "data" / "personas" / "personas.json"
        self.benchmark_path = benchmark_path or REPO_ROOT / "data" / "benchmarks" / "dobbs_2022.json"
        self.sets_dir = sets_dir or REPO_ROOT / "data" / "personas" / "sets"

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

    # ------------------------------------------------------------------
    # Named persona sets
    # ------------------------------------------------------------------
    def save_persona_set(self, personas: list[Persona], label: str, location: str) -> dict[str, Any]:
        """Persist a generated population as a named, selectable set and return its metadata."""
        self.sets_dir.mkdir(parents=True, exist_ok=True)
        set_id = f"{slugify(label)}-{int(time.time())}"
        representation_total_pct = round(sum(persona.representation_pct or 0 for persona in personas), 2)
        record = {
            "set_id": set_id,
            "label": label,
            "location": location,
            "persona_count": len(personas),
            "created_at": time.time(),
            "representation_total_pct": representation_total_pct,
            "personas": [persona.model_dump(exclude_none=True) for persona in personas],
        }
        (self.sets_dir / f"{set_id}.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
        # Keep the default store pointed at the latest set for back-compat.
        self.save_personas(personas)
        return {key: value for key, value in record.items() if key != "personas"}

    def list_persona_sets(self) -> list[dict[str, Any]]:
        """Return metadata for every saved set, newest first.

        If no sets exist yet but a legacy ``personas.json`` is present, surface it as a single
        ``legacy-default`` set so the sentiment tab is never empty.
        """
        summaries: list[dict[str, Any]] = []
        if self.sets_dir.exists():
            for path in self.sets_dir.glob("*.json"):
                try:
                    raw = json.loads(path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    continue
                summaries.append(
                    {
                        "set_id": raw.get("set_id", path.stem),
                        "label": raw.get("label", path.stem),
                        "location": raw.get("location", "Unknown"),
                        "persona_count": raw.get("persona_count", len(raw.get("personas", []))),
                        "created_at": raw.get("created_at", path.stat().st_mtime),
                        "representation_total_pct": raw.get("representation_total_pct", 0.0),
                    }
                )

        if not summaries and self.personas_path.exists():
            try:
                legacy = self.load_personas()
            except (FileNotFoundError, KeyError, json.JSONDecodeError):
                legacy = []
            if legacy:
                summaries.append(
                    {
                        "set_id": LEGACY_SET_ID,
                        "label": "Existing population",
                        "location": legacy[0].location.state if legacy else "Unknown",
                        "persona_count": len(legacy),
                        "created_at": self.personas_path.stat().st_mtime,
                        "representation_total_pct": round(
                            sum(persona.representation_pct or 0 for persona in legacy), 2
                        ),
                    }
                )

        summaries.sort(key=lambda item: item.get("created_at", 0), reverse=True)
        return summaries

    def load_set(self, set_id: str) -> list[Persona]:
        if set_id == LEGACY_SET_ID:
            return self.load_personas()
        path = self.sets_dir / f"{set_id}.json"
        if not path.exists():
            raise FileNotFoundError(f"No persona set exists with id {set_id}.")
        raw = json.loads(path.read_text(encoding="utf-8"))
        return [Persona.model_validate(item) for item in raw["personas"]]

    def select_personas(self, count: int, set_id: str | None = None) -> list[Persona]:
        personas = self.load_set(set_id) if set_id else self.load_personas()
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


def slugify(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else "-" for char in value).strip("-") or "set"
