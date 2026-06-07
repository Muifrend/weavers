from __future__ import annotations

import re

from .schemas import PersonaRequest


CITY_STATE_RE = re.compile(
    r"\b([A-Z][a-zA-Z .'-]+),?\s+(AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|IA|ID|IL|IN|KS|KY|LA|MA|MD|ME|MI|MN|MO|MS|MT|NC|ND|NE|NH|NJ|NM|NV|NY|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VA|VT|WA|WI|WV|WY)\b"
)


def parse_persona_request(text: str) -> PersonaRequest:
    lowered = text.lower()
    request = PersonaRequest(raw_text=text)

    location_match = CITY_STATE_RE.search(text)
    if location_match:
        request.location = f"{location_match.group(1).strip()}, {location_match.group(2)}"
    elif "milwaukee" in lowered:
        request.location = "Milwaukee, WI"

    issue_match = re.search(r"\bfocused on\s+([a-zA-Z -]+?)(?:\.|$)", lowered)
    if not issue_match:
        issue_match = re.search(r"\b(?:around|about)\s+([a-zA-Z -]+?)(?:\.|$)", lowered)
    if not issue_match:
        issue_match = re.search(r"\bon\s+([a-zA-Z -]+?)(?:\.|$)", lowered)
    if issue_match:
        request.issue = issue_match.group(1).strip()
    elif "abortion" in lowered:
        request.issue = "abortion"
    elif "reproductive" in lowered:
        request.issue = "reproductive rights"

    tag_map = {
        "suburban": "suburban",
        "working class": "working_class",
        "working-class": "working_class",
        "union": "union_household",
        "woman": "suburban_women",
        "women": "suburban_women",
        "latina": "latina",
        "latino": "latino",
        "electrician": "skilled_trades",
    }
    for needle, tag in tag_map.items():
        if needle in lowered and tag not in request.segment_tags:
            request.segment_tags.append(tag)

    if "latina" in lowered:
        request.race_ethnicity = "Latina"
        if "suburban_women" not in request.segment_tags:
            request.segment_tags.append("suburban_women")
    elif "latino" in lowered:
        request.race_ethnicity = "Latino"

    if "electrician" in lowered:
        request.occupation = "Union electrician" if "union" in lowered else "Electrician"
        request.industry = "Construction"
    elif "teacher" in lowered:
        request.occupation = "Teacher"
        request.industry = "Education"

    if "democrat" in lowered:
        request.party_affiliation = "Democrat"
    elif "republican" in lowered:
        request.party_affiliation = "Republican"
    elif "independent" in lowered:
        request.party_affiliation = "Independent"

    return request
