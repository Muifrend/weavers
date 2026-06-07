from __future__ import annotations

import argparse
import json
import os
import sys

from .pipeline import PersonaPipeline
from .population import PopulationPipeline
from .pums_store import DEFAULT_DATA_DIR, PumsStore, download_state_pums
from .adapters import STATE_FIPS, STATE_NAMES
from .weave_support import init_weave


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create a bounded synthetic persona from aggregate evidence.")
    parser.add_argument("request", nargs="?", help="Natural-language persona request.")
    parser.add_argument(
        "--source-url",
        action="append",
        default=[],
        help="Approved public URL to include as local context. May be repeated.",
    )
    parser.add_argument(
        "--no-packet",
        action="store_true",
        help="Omit the evidence packet from output.",
    )
    parser.add_argument(
        "--census-api-key",
        default=None,
        help="Census Data API key. Defaults to the CENSUS_API_KEY environment variable.",
    )
    parser.add_argument(
        "--weave-project",
        default=None,
        help="W&B Weave project name. Defaults to WEAVE_PROJECT, WANDB_PROJECT, or the repo name when set.",
    )
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")
    return parser


def build_population_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Initialize a Census-grounded population profile for a location.")
    parser.add_argument("command", choices=["population"])
    parser.add_argument("location", help="Location to fetch, e.g. California, CA, or Milwaukee, WI.")
    parser.add_argument(
        "--census-api-key",
        default=None,
        help="Census Data API key. Defaults to CENSUS_API_KEY or .env.",
    )
    parser.add_argument(
        "--openai-api-key",
        default=None,
        help="OpenAI API key. Defaults to OPENAI_API_KEY or .env.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="OpenAI model for representative persona generation. Defaults to OPENAI_MODEL or gpt-4.1.",
    )
    parser.add_argument(
        "--output-dir",
        default="generated_personas",
        help="Directory where persona JSON files are written.",
    )
    parser.add_argument(
        "--persona-count",
        type=int,
        default=10,
        help="Number of representative personas to generate.",
    )
    parser.add_argument(
        "--weave-project",
        default=None,
        help="W&B Weave project name. Defaults to WEAVE_PROJECT, WANDB_PROJECT, or the repo name when set.",
    )
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")
    return parser


def build_download_pums_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Download and cache ACS PUMS person microdata for a state as a local parquet file. "
            "Run this once per state before using the population pipeline to avoid Census API timeouts."
        )
    )
    parser.add_argument("command", choices=["download-pums"])
    parser.add_argument("location", help="State name or abbreviation, e.g. California or CA.")
    parser.add_argument(
        "--census-api-key",
        default=None,
        help="Census Data API key. Defaults to CENSUS_API_KEY or .env.",
    )
    parser.add_argument(
        "--year",
        type=int,
        default=2024,
        help="ACS 5-year vintage year (default: 2024).",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help=f"Directory to store parquet files. Defaults to PUMS_DATA_DIR env var or {DEFAULT_DATA_DIR}.",
    )
    return parser


def _resolve_state_fips(location: str) -> str | None:
    normalized = location.strip().lower()
    if len(normalized) == 2 and normalized.upper() in STATE_FIPS:
        return STATE_FIPS[normalized.upper()]
    abbrev = STATE_NAMES.get(normalized)
    if abbrev:
        return STATE_FIPS[abbrev]
    return None


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "download-pums":
        args = build_download_pums_parser().parse_args(argv)
        from .adapters import read_dotenv_value
        api_key = args.census_api_key or os.getenv("CENSUS_API_KEY") or read_dotenv_value("CENSUS_API_KEY")
        if not api_key:
            print("Error: CENSUS_API_KEY is required. Pass --census-api-key or set the env var.", file=sys.stderr)
            return 1
        state_fips = _resolve_state_fips(args.location)
        if not state_fips:
            print(f"Error: could not resolve {args.location!r} to a U.S. state.", file=sys.stderr)
            return 1
        store = PumsStore(args.data_dir)
        if store.exists(state_fips, args.year):
            path = store.parquet_path(state_fips, args.year)
            print(f"Already cached: {path}")
            return 0
        print(f"Downloading ACS {args.year} PUMS for state FIPS {state_fips} — this may take several minutes...")
        try:
            path = download_state_pums(state_fips, args.year, api_key, args.data_dir)
        except Exception as exc:  # noqa: BLE001
            print(f"Download failed: {exc}", file=sys.stderr)
            return 1
        print(f"Saved: {path}")
        return 0

    if argv and argv[0] == "population":
        args = build_population_parser().parse_args(argv)
        init_weave(args.weave_project)
        pipeline = PopulationPipeline()
        if args.census_api_key:
            pipeline.census.api_key = args.census_api_key
        if args.openai_api_key:
            pipeline.persona_set_agent.client.api_key = args.openai_api_key
        if args.model:
            pipeline.persona_set_agent.client.model = args.model
        result = pipeline.initialize(args.location, output_dir=args.output_dir, persona_count=args.persona_count)
        json.dump(result, sys.stdout, indent=2 if args.pretty else None, sort_keys=args.pretty)
        sys.stdout.write("\n")
        return 0 if result["status"] in {"complete", "partial"} else 1

    args = build_parser().parse_args(argv)
    if not args.request:
        build_parser().error("request is required unless using the population command")

    init_weave(args.weave_project)
    pipeline = PersonaPipeline()
    if args.census_api_key:
        pipeline.geo_agent.census.api_key = args.census_api_key
        pipeline.demographic_agent.census.api_key = args.census_api_key
    result = pipeline.run(args.request, source_urls=args.source_url, include_packet=not args.no_packet)
    json.dump(result, sys.stdout, indent=2 if args.pretty else None, sort_keys=args.pretty)
    sys.stdout.write("\n")
    return 0 if result["status"] in {"complete", "needs_clarification"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
