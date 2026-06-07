from __future__ import annotations

import re
from dataclasses import dataclass

from .schemas import EvidencePacket


BLOCKED_PATTERNS = [
    r"\bvoter file\b",
    r"\breal voters?\b",
    r"\bfacebook profiles?\b",
    r"\blinkedin profiles?\b",
    r"\bdata broker\b",
    r"\bpeople search\b",
    r"\baddresses?\b",
    r"\bscrape\b.*\bprofiles?\b",
    r"\bnamed person\b",
    r"\blookalike\b.*\bperson\b",
]

SENSITIVE_INFERENCE_PATTERNS = [
    r"\binfer\b.*\b(pregnan|religion|health|family status)\b",
    r"\bpredict\b.*\b(pregnan|religion|health|family status)\b",
]


@dataclass
class SafetyVerifier:
    def review_request_text(self, text: str) -> dict[str, object]:
        lowered = text.lower()
        violations = []
        for pattern in BLOCKED_PATTERNS:
            if re.search(pattern, lowered):
                violations.append("blocked_private_or_real_person_targeting")
                break
        for pattern in SENSITIVE_INFERENCE_PATTERNS:
            if re.search(pattern, lowered):
                violations.append("blocked_sensitive_individual_inference")
                break
        return {"approved": not violations, "violations": violations}

    def review_packet(self, packet: EvidencePacket) -> dict[str, object]:
        request_review = self.review_request_text(packet.persona_request.raw_text)
        violations = list(request_review["violations"])
        warnings = list(packet.warnings)

        if not packet.safety_constraints.synthetic_only:
            violations.append("synthetic_only_constraint_missing")
        if not packet.evidence:
            warnings.append("No provenance attached.")
        if not packet.geo_context:
            warnings.append("No geography context attached.")

        return {
            "approved": not violations,
            "violations": violations,
            "warnings": warnings,
            "synthetic_only": packet.safety_constraints.synthetic_only,
        }

