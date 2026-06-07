from __future__ import annotations

import csv
import io
import json
import os
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen


STATE_FIPS = {
    "AL": "01",
    "AK": "02",
    "AZ": "04",
    "AR": "05",
    "CA": "06",
    "CO": "08",
    "CT": "09",
    "DE": "10",
    "FL": "12",
    "GA": "13",
    "HI": "15",
    "ID": "16",
    "IL": "17",
    "IN": "18",
    "IA": "19",
    "KS": "20",
    "KY": "21",
    "LA": "22",
    "ME": "23",
    "MD": "24",
    "MA": "25",
    "MI": "26",
    "MN": "27",
    "MS": "28",
    "MO": "29",
    "MT": "30",
    "NE": "31",
    "NV": "32",
    "NH": "33",
    "NJ": "34",
    "NM": "35",
    "NY": "36",
    "NC": "37",
    "ND": "38",
    "OH": "39",
    "OK": "40",
    "OR": "41",
    "PA": "42",
    "RI": "44",
    "SC": "45",
    "SD": "46",
    "TN": "47",
    "TX": "48",
    "UT": "49",
    "VT": "50",
    "VA": "51",
    "WA": "53",
    "WV": "54",
    "WI": "55",
    "WY": "56",
}


STATE_NAMES = {
    "alabama": "AL",
    "alaska": "AK",
    "arizona": "AZ",
    "arkansas": "AR",
    "california": "CA",
    "colorado": "CO",
    "connecticut": "CT",
    "delaware": "DE",
    "florida": "FL",
    "georgia": "GA",
    "hawaii": "HI",
    "idaho": "ID",
    "illinois": "IL",
    "indiana": "IN",
    "iowa": "IA",
    "kansas": "KS",
    "kentucky": "KY",
    "louisiana": "LA",
    "maine": "ME",
    "maryland": "MD",
    "massachusetts": "MA",
    "michigan": "MI",
    "minnesota": "MN",
    "mississippi": "MS",
    "missouri": "MO",
    "montana": "MT",
    "nebraska": "NE",
    "nevada": "NV",
    "new hampshire": "NH",
    "new jersey": "NJ",
    "new mexico": "NM",
    "new york": "NY",
    "north carolina": "NC",
    "north dakota": "ND",
    "ohio": "OH",
    "oklahoma": "OK",
    "oregon": "OR",
    "pennsylvania": "PA",
    "rhode island": "RI",
    "south carolina": "SC",
    "south dakota": "SD",
    "tennessee": "TN",
    "texas": "TX",
    "utah": "UT",
    "vermont": "VT",
    "virginia": "VA",
    "washington": "WA",
    "west virginia": "WV",
    "wisconsin": "WI",
    "wyoming": "WY",
}


STATE_LABELS = {abbreviation: name.title() for name, abbreviation in STATE_NAMES.items()}


KNOWN_PLACES = {
    ("milwaukee", "WI"): {
        "type": "place",
        "name": "Milwaukee city, Wisconsin",
        "state_fips": "55",
        "place_fips": "53000",
    }
}


OCCUPATION_CODES = {
    "electrician": {"soc": "47-2111", "title": "Electricians", "industry": "Construction"},
    "union electrician": {"soc": "47-2111", "title": "Electricians", "industry": "Construction"},
    "teacher": {"soc": "25-0000", "title": "Educational Instruction and Library Occupations", "industry": "Education"},
}


@dataclass
class HTTPClient:
    timeout: float = 6.0

    def get_json(self, url: str) -> Any:
        request = Request(url, headers={"User-Agent": "persona-pipeline/0.1"})
        try:
            with urlopen(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8")
        except HTTPError as error:
            body = error.read().decode("utf-8", errors="replace")
            if "Missing Key" in body or "Invalid Key" in body:
                raise CensusKeyError from error
            raise
        if "Missing Key" in body or "Invalid Key" in body:
            raise CensusKeyError
        return json.loads(body)

    def get_text(self, url: str) -> str:
        request = Request(url, headers={"User-Agent": "persona-pipeline/0.1"})
        with urlopen(request, timeout=self.timeout) as response:
            return response.read().decode("utf-8", errors="replace")


@dataclass
class CensusAdapter:
    acs_year: int = 2024
    api_key: str | None = field(default_factory=lambda: os.getenv("CENSUS_API_KEY") or read_dotenv_value("CENSUS_API_KEY"))
    http: HTTPClient = field(default_factory=HTTPClient)

    def resolve_place(self, location: str) -> dict[str, Any]:
        state = parse_state(location)
        if state and is_state_only(location):
            return {
                "input": location,
                "resolved_options": [
                    {
                        "type": "state",
                        "name": f"{STATE_LABELS.get(state, state)}",
                        "state": state,
                        "state_fips": STATE_FIPS[state],
                    }
                ],
                "recommended_scope": "state",
                "state_fips": STATE_FIPS[state],
            }

        city, state = parse_city_state(location)
        state_fips = STATE_FIPS.get(state)
        if not city or not state_fips:
            return {"input": location, "resolved_options": [], "recommended_scope": "needs_clarification"}

        known = KNOWN_PLACES.get((city.lower(), state))
        if known:
            return {
                "input": location,
                "resolved_options": [known],
                "recommended_scope": "place_with_suburban_context",
            }
        if not self.api_key:
            return {
                "input": location,
                "resolved_options": [],
                "recommended_scope": "state_fallback",
                "state_fips": state_fips,
                "status": "missing_api_key",
            }

        url = (
            f"https://api.census.gov/data/{self.acs_year}/acs/acs5/profile?"
            + urlencode({"get": "NAME", "for": "place:*", "in": f"state:{state_fips}", "key": self.api_key})
        )
        try:
            rows = self.http.get_json(url)
        except CensusKeyError:
            return {
                "input": location,
                "resolved_options": [],
                "recommended_scope": "state_fallback",
                "state_fips": state_fips,
                "status": "key_rejected",
            }
        except (OSError, URLError, TimeoutError, json.JSONDecodeError):
            return {
                "input": location,
                "resolved_options": [],
                "recommended_scope": "state_fallback",
                "state_fips": state_fips,
            }

        header, *records = rows
        name_idx = header.index("NAME")
        place_idx = header.index("place")
        normalized_city = city.lower().replace(" city", "")
        matches = [
            {
                "type": "place",
                "name": record[name_idx],
                "state_fips": state_fips,
                "place_fips": record[place_idx],
            }
            for record in records
            if record[name_idx].lower().startswith(normalized_city)
        ]
        return {
            "input": location,
            "resolved_options": matches[:5],
            "recommended_scope": "place_with_suburban_context" if matches else "state_fallback",
            "state_fips": state_fips,
        }

    def fetch_profile(self, geo_context: dict[str, Any], variables: list[str]) -> dict[str, Any]:
        option = first_resolved_place(geo_context)
        if not self.api_key:
            return {"values": {}, "url": None, "status": "missing_api_key"}
        if option:
            query = {
                "get": ",".join(["NAME", *variables]),
                "for": f"place:{option['place_fips']}",
                "in": f"state:{option['state_fips']}",
                "key": self.api_key,
            }
        elif state_option := first_resolved_state(geo_context):
            query = {
                "get": ",".join(["NAME", *variables]),
                "for": f"state:{state_option['state_fips']}",
                "key": self.api_key,
            }
        else:
            state_fips = geo_context.get("state_fips")
            if not state_fips:
                return {"values": {}, "url": None, "status": "unavailable"}
            query = {"get": ",".join(["NAME", *variables]), "for": f"state:{state_fips}", "key": self.api_key}

        url = f"https://api.census.gov/data/{self.acs_year}/acs/acs5/profile?{urlencode(query)}"
        try:
            rows = self.http.get_json(url)
        except CensusKeyError:
            return {"values": {}, "url": redact_query_secret(url), "status": "key_rejected"}
        except (OSError, URLError, TimeoutError, json.JSONDecodeError):
            return {"values": {}, "url": redact_query_secret(url), "status": "unavailable"}
        if len(rows) < 2:
            return {"values": {}, "url": redact_query_secret(url), "status": "unavailable"}

        header, record = rows[0], rows[1]
        values = dict(zip(header, record, strict=False))
        return {"values": values, "url": redact_query_secret(url), "status": "complete"}


@dataclass
class PumsAdapter:
    acs_year: int = 2024
    api_key: str | None = field(default_factory=lambda: os.getenv("CENSUS_API_KEY") or read_dotenv_value("CENSUS_API_KEY"))
    http: HTTPClient = field(default_factory=lambda: HTTPClient(timeout=12.0))

    def fetch_person_records(
        self,
        geo_context: dict[str, Any],
        variables: list[str],
        filters: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        state_option = first_resolved_state(geo_context)
        if not self.api_key:
            return {"records": [], "url": None, "status": "missing_api_key"}
        if not state_option:
            return {"records": [], "url": None, "status": "unsupported_geography"}

        query = {
            "get": ",".join(variables),
            "for": f"state:{state_option['state_fips']}",
            "key": self.api_key,
        }
        query.update(filters or {})
        url = f"https://api.census.gov/data/{self.acs_year}/acs/acs5/pums?{urlencode(query)}"

        try:
            rows = self.http.get_json(url)
        except CensusKeyError:
            return {"records": [], "url": redact_query_secret(url), "status": "key_rejected"}
        except (OSError, URLError, TimeoutError, json.JSONDecodeError):
            return {"records": [], "url": redact_query_secret(url), "status": "unavailable"}

        if len(rows) < 2:
            return {"records": [], "url": redact_query_secret(url), "status": "empty"}

        header, *records = rows
        parsed = [dict(zip(header, record, strict=False)) for record in records]
        return {"records": parsed, "url": redact_query_secret(url), "status": "complete"}


@dataclass
class BLSAdapter:
    http: HTTPClient = field(default_factory=HTTPClient)

    def lookup_occupation(self, occupation: str | None, state: str | None) -> dict[str, Any]:
        key = (occupation or "").lower().strip()
        mapped = OCCUPATION_CODES.get(key) or next(
            (value for needle, value in OCCUPATION_CODES.items() if needle in key),
            None,
        )
        if not mapped:
            return {"status": "partial", "occupation": occupation, "mapping": None}

        state_name = state or "United States"
        return {
            "status": "complete",
            "occupation": occupation,
            "mapping": mapped,
            "geography": state_name,
            "wage_context": {
                "basis": "BLS OEWS occupation mapping; live wage pull not configured in MVP",
                "soc": mapped["soc"],
                "title": mapped["title"],
            },
        }


@dataclass
class ApprovedSourceFetcher:
    allowed_domains: set[str] = field(
        default_factory=lambda: {
            "census.gov",
            "api.census.gov",
            "bls.gov",
            "www.bls.gov",
            "milwaukee.gov",
            "county.milwaukee.gov",
            "dhs.wisconsin.gov",
            "wisconsin.gov",
            "aflcio.org",
            "ibew.org",
            "www.ibew.org",
            "plannedparenthood.org",
            "www.plannedparenthood.org",
        }
    )
    http: HTTPClient = field(default_factory=HTTPClient)

    def fetch(self, urls: list[str], limit: int = 5) -> list[dict[str, Any]]:
        results = []
        for url in urls[:limit]:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            if domain.startswith("www.") and domain[4:] in self.allowed_domains:
                domain = domain[4:]
            if parsed.netloc.lower() not in self.allowed_domains and domain not in self.allowed_domains:
                results.append({"url": url, "status": "rejected", "reason": "domain_not_whitelisted"})
                continue
            try:
                text = self.http.get_text(url)
            except (OSError, URLError, TimeoutError):
                results.append({"url": url, "status": "unavailable", "reason": "fetch_failed"})
                continue
            results.append(
                {
                    "url": url,
                    "status": "complete",
                    "title": extract_title(text),
                    "summary": summarize_text(text),
                }
            )
        return results


def parse_city_state(location: str) -> tuple[str | None, str | None]:
    match = re.search(r"([A-Za-z .'-]+),?\s+([A-Z]{2})\b", location)
    if not match:
        return None, None
    return match.group(1).strip(), match.group(2).upper()


def parse_state(location: str) -> str | None:
    normalized = re.sub(r"\s+", " ", location.strip().lower())
    if len(normalized) == 2 and normalized.upper() in STATE_FIPS:
        return normalized.upper()
    return STATE_NAMES.get(normalized)


def is_state_only(location: str) -> bool:
    return parse_state(location) is not None


class CensusKeyError(Exception):
    pass


def redact_query_secret(url: str, secret_names: tuple[str, ...] = ("key",)) -> str:
    parsed = urlparse(url)
    query = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        query.append((key, "REDACTED" if key in secret_names else value))
    return urlunparse(parsed._replace(query=urlencode(query)))


def first_resolved_place(geo_context: dict[str, Any]) -> dict[str, Any] | None:
    for option in geo_context.get("resolved_options", []):
        if option.get("type") == "place":
            return option
    return None


def first_resolved_state(geo_context: dict[str, Any]) -> dict[str, Any] | None:
    for option in geo_context.get("resolved_options", []):
        if option.get("type") == "state":
            return option
    return None


def extract_state(location: str | None) -> str | None:
    if not location:
        return None
    _, state = parse_city_state(location)
    return state


def extract_title(html: str) -> str | None:
    match = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    return re.sub(r"\s+", " ", match.group(1)).strip()


def summarize_text(text: str, max_chars: int = 500) -> str:
    text = re.sub(r"<script.*?</script>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars]


def read_source_urls_csv(csv_text: str) -> list[str]:
    rows = csv.reader(io.StringIO(csv_text))
    return [row[0] for row in rows if row]


def read_dotenv_value(name: str, path: str = ".env") -> str | None:
    try:
        with open(path, encoding="utf-8") as env_file:
            for line in env_file:
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or "=" not in stripped:
                    continue
                key, value = stripped.split("=", 1)
                if key.strip() == name:
                    return value.strip().strip('"').strip("'")
    except OSError:
        return None
    return None
