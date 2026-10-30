"""gbpowerdata.build.pecd_build: raw-shape detection and the calendar-safe reindex/gap-flag step.

"No silent gap filling; flag missing hours" is the actual behaviour under test here: an hour
absent from the raw source must come out as NaN in the wide CSV AND as a row in the gaps table,
never interpolated.
"""

from __future__ import annotations

import pandas as pd

from gbpowerdata.build import pecd_build


def test_to_long_detects_wide_raw_shape():
    raw = pd.DataFrame({
        "time": ["2023-01-01T00:00:00Z", "2023-01-01T01:00:00Z"],
        "UKC1": [0.10, 0.20],
        "UKD1": [0.30, 0.40],
    })
    long = pecd_build._to_long(raw)
    assert set(long["zone"]) == {"UKC1", "UKD1"}
    assert long.loc[(long["zone"] == "UKC1") & (long["time"] == pd.Timestamp("2023-01-01T01:00:00Z")),
                    "value"].iloc[0] == 0.20


def test_to_long_detects_long_raw_shape():
    raw = pd.DataFrame({
        "time": ["2023-01-01T00:00:00Z", "2023-01-01T00:00:00Z"],
        "zone": ["UKC1", "UKD1"],
        "value": [0.10, 0.30],
    })
    long = pecd_build._to_long(raw)
    assert sorted(long["zone"]) == ["UKC1", "UKD1"]


def test_load_raw_tech_keeps_only_uk_zones_of_every_file(tmp_path):
    # Two overlapping raw files (the pull's year blocks overlap) with European zones beside GB's:
    # only the UK zones survive, each hour once.
    (tmp_path / "solar_pv_2020-2021_0.csv").write_text(
        "# preamble\nDate,UKC1,FR10,DE11\n2021-01-01T00:00:00Z,0.1,0.5,0.6\n", encoding="utf-8")
    (tmp_path / "solar_pv_2014-2021_0.csv").write_text(
        "# preamble\nDate,UKC1,FR10\n2021-01-01T00:00:00Z,0.1,0.5\n2021-01-01T01:00:00Z,0.2,0.5\n",
        encoding="utf-8")

    long = pecd_build.load_raw_tech("solar_pv", tmp_path)

    assert set(long["zone"]) == {"UKC1"}
    assert long["value"].tolist() == [0.1, 0.2]


def test_reindex_and_flag_marks_missing_hour_not_fills_it():
    long = pd.DataFrame({
        "time": pd.to_datetime(["2023-01-01T00:00Z", "2023-01-01T01:00Z", "2023-01-01T03:00Z"]),
        "zone": ["UKC1"] * 3,   # 02:00 missing entirely
        "value": [0.10, 0.20, 0.40],
    })

    wide, gaps = pecd_build.reindex_and_flag(long, "onshore_wind")

    assert list(wide.columns) == ["UKC1_onshore_wind"]
    assert wide.index.name == "startTime"
    missing_ts = pd.Timestamp("2023-01-01T02:00", tz="UTC")
    assert pd.isna(wide.loc[missing_ts, "UKC1_onshore_wind"])
    assert len(gaps) == 1
    row = gaps.iloc[0]
    assert row["startTime"] == missing_ts
    assert row["column"] == "UKC1_onshore_wind"
    assert row["reason"] == "missing_from_source"


def test_reindex_and_flag_no_gaps_when_spine_is_complete():
    long = pd.DataFrame({
        "time": pd.to_datetime(["2023-01-01T00:00Z", "2023-01-01T01:00Z"]),
        "zone": ["UKC1", "UKC1"],
        "value": [0.10, 0.20],
    })

    wide, gaps = pecd_build.reindex_and_flag(long, "onshore_wind")

    assert gaps.empty
    assert wide["UKC1_onshore_wind"].tolist() == [0.10, 0.20]
