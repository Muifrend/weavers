from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from urllib.parse import urlencode


PUMS_VARIABLES = ["AGEP", "SEX", "HISP", "RAC1P", "SCHL", "ESR", "COW", "OCCP", "INDP", "PINCP", "PWGTP"]

DEFAULT_DATA_DIR = Path(os.getenv("PUMS_DATA_DIR") or Path.home() / ".cache" / "persona_pipeline" / "pums")


class PumsStore:
    """Manages locally cached ACS PUMS parquet files and PWGTP-weighted sampling."""

    def __init__(self, data_dir: str | Path | None = None) -> None:
        self.data_dir = Path(data_dir) if data_dir else DEFAULT_DATA_DIR

    def parquet_path(self, state_fips: str, year: int) -> Path:
        return self.data_dir / f"{state_fips}_{year}_pums.parquet"

    def exists(self, state_fips: str, year: int) -> bool:
        return self.parquet_path(state_fips, year).exists()

    def weighted_sample(
        self,
        state_fips: str,
        year: int,
        count: int,
        variables: list[str] | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """
        Draw exactly `count` records using PWGTP-weighted sampling without replacement.

        Higher-PWGTP records (representing more real residents) are proportionally
        more likely to be drawn. Returns (sampled_records, total_pool_size).
        Sampled records are returned as string-valued dicts to match the Census API
        record format expected by decode_pums_record.
        """
        import pandas as pd

        cols = [v for v in (variables or PUMS_VARIABLES) if v != "state"]
        df = pd.read_parquet(self.parquet_path(state_fips, year), columns=cols)
        pool_size = len(df)

        if "PWGTP" not in df.columns:
            df["PWGTP"] = 1
        # Clip to >=1 so every record has at least some probability of being drawn.
        weights = pd.to_numeric(df["PWGTP"], errors="coerce").fillna(1).clip(lower=1).astype(int)

        n = min(count, pool_size)
        sampled = df.sample(n=n, weights=weights, replace=False)
        # Convert to string-valued dicts so downstream decode_pums_record can parse them
        # consistently regardless of whether the source was the API or a local file.
        records = sampled.astype(str).replace({"nan": None, "<NA>": None}).to_dict(orient="records")
        return records, pool_size


def download_state_pums(
    state_fips: str,
    year: int,
    api_key: str,
    data_dir: str | Path | None = None,
    variables: list[str] | None = None,
) -> Path:
    """
    Download the full ACS PUMS person microdata for one state and save as parquet.

    This is a one-time operation (3-10 minutes for large states). Subsequent calls
    are instant — the function returns immediately if the file already exists.
    The saved file is used by PumsPopulationSampler via PumsStore.weighted_sample
    instead of hitting the Census API on every pipeline run.
    """
    import pandas as pd
    from .adapters import HTTPClient

    store = PumsStore(data_dir)
    path = store.parquet_path(state_fips, year)
    if path.exists():
        return path

    all_vars = variables or PUMS_VARIABLES
    # Use a long timeout — this is intentionally a slow, one-time download.
    http = HTTPClient(timeout=600.0)
    query = {"get": ",".join(all_vars), "for": f"state:{state_fips}", "key": api_key}
    url = f"https://api.census.gov/data/{year}/acs/acs5/pums?{urlencode(query)}"

    rows = http.get_json(url)
    if len(rows) < 2:
        raise RuntimeError(f"No PUMS records returned for state {state_fips!r} year {year}.")

    header, *records = rows
    df = pd.DataFrame(records, columns=header)

    # Census always appends a 'state' FIPS column — drop it; state_fips is in the filename.
    if "state" in df.columns:
        df = df.drop(columns=["state"])

    # Normalize PWGTP so PumsStore.weighted_sample can weight immediately on load.
    df["PWGTP"] = pd.to_numeric(df["PWGTP"], errors="coerce").fillna(1).clip(lower=1).astype(int)

    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False, compression="snappy")
    return path
