"""Tests on the built tables (data/processed/) and the raw pulls (data/raw/), wherever config.yaml or
GBPOWERDATA_CONFIG points: skipped, not failed, where the data are absent, so the synthetic suite runs anywhere.

Every test here is marked `realdata`; those reading licensed N2EX/EPEX outputs are also marked `licensed` (they read
local files only and assert on aggregates; nothing licensed is written). Run them with
    python -m pytest tests/realdata              (or -m "realdata and not licensed")
A known defect is an xfail(strict=True) naming its docs/AUDIT.md id: the day it is fixed the test passes, strict
turns that into a failure, and the marker must go.
"""
from __future__ import annotations

import re

import pandas as pd
import pytest

from gbpowerdata import config as cfg

YEARS = range(2018, 2026)


@pytest.fixture(scope="session")
def processed():
    return cfg.processed_dir()


@pytest.fixture(scope="session")
def raw():
    return cfg.raw_dir()


def years_with(processed, family: str) -> list[int]:
    """The panel years for which processed/{family}_{year}.csv exists."""
    rx = re.compile(rf"^{re.escape(family)}_(\d{{4}})\.csv$")
    return sorted(int(m.group(1)) for p in processed.glob(f"{family}_*.csv") if (m := rx.match(p.name))
                  and int(m.group(1)) in YEARS)


def need(paths) -> None:
    """Skip unless every path exists."""
    missing = [str(p) for p in paths if not p.exists()]
    if missing:
        pytest.skip(f"data absent: {missing[0]}" + (f" (+{len(missing) - 1})" if len(missing) > 1 else ""))


def read_series(processed, family: str, years) -> pd.DataFrame:
    frames = []
    for y in years:
        d = pd.read_csv(processed / f"{family}_{y}.csv")
        d["startTime"] = pd.to_datetime(d["startTime"], utc=True)
        frames.append(d)
    return pd.concat(frames, ignore_index=True).set_index("startTime").sort_index()
