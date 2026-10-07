"""data/reference/thermal_parameters.csv, the sourced operating parameters of thermal plant, and the BM dynamic data
behind its GB rows (gbpowerdata.build.bm_dynamic).

The table: its columns in order; every parameter from the vocabulary in the unit that parameter is kept in (costs and
VOM in a currency, with a price year where the source gives one); every row with a value or a range, the value inside
its range, shares between 0 and 1; status transcribed, converted or derived; every source it cites listed in
thermal_parameter_sources.csv, and every listed source with a publisher, title, URL, access date and licence; at most
one GB default per technology, parameter, year and commissioning period; and the GB defaults taken from the BM
dynamic data equal to data/reference/bm_dynamic_by_tech.csv, so a rebuild of that summary cannot drift from the table
unnoticed.

The build: the run-up and run-down arithmetic over declared rate segments and elbows (Grid Code BC1.A.1.5; NESO
DVC&D rules V_RURE_5, V_RDRE_5), a 999 MW/min segment taken as a step, the record in force at the start of a
settlement period, and the start of settlement period 24 in winter and summer."""
import re

import numpy as np
import pandas as pd
import pytest

from gbpowerdata import config as cfg
from gbpowerdata.build import bm_dynamic as B

REFERENCE = cfg.reference_dir()
TABLE = REFERENCE / "thermal_parameters.csv"
SOURCES = REFERENCE / "thermal_parameter_sources.csv"
COLUMNS = ["technology", "class", "commissioned_from", "commissioned_to", "year", "parameter", "value", "low", "high",
           "unit", "basis", "region", "source", "locator", "status", "gb_default", "note"]
SOURCE_COLUMNS = ["source_id", "publisher", "title", "published", "kind", "url", "accessed", "licence"]
COST = r"(EUR|GBP|USD)(\d{4})?/MW"
UNITS = {  # parameter -> the unit it is kept in (a regular expression for costs)
    "efficiency_full_load": "fraction", "efficiency_annual_average": "fraction", "efficiency_min_load": "fraction",
    "min_stable_generation": "fraction", "ramp_up_rate": "fraction/min", "ramp_down_rate": "fraction/min",
    "start_up_ramp_limit": "fraction", "shut_down_ramp_limit": "fraction",
    "start_up_notice": "h", "start_up_notice_hot": "h", "start_up_notice_warm": "h", "start_up_notice_cold": "h",
    "sync_to_full_load_time_hot": "h", "sync_to_full_load_time_warm": "h", "sync_to_full_load_time_cold": "h",
    "run_up_to_min_stable_time": "h", "start_up_time_hot": "h", "start_up_time_warm": "h", "start_up_time_cold": "h",
    "hot_start_max_offline": "h", "warm_start_max_offline": "h", "min_up_time": "h", "min_down_time": "h",
    "start_up_cost": COST, "start_up_cost_hot": COST, "start_up_cost_warm": COST, "start_up_cost_cold": COST,
    "start_up_fuel": "MWh_th/MW", "start_up_fuel_hot": "MWh_th/MW", "start_up_fuel_warm": "MWh_th/MW",
    "start_up_fuel_cold": "MWh_th/MW", "shut_down_fuel": "MWh_th/MW",
    "forced_outage_rate": "fraction", "planned_outage": "days/yr", "availability": "fraction",
    "emission_factor": "tCO2/MWh_th", "ncv_gcv_ratio": "fraction", "vom": COST + "h",
}
# GB defaults taken from the BM dynamic data: parameter -> (summary metric, factor to the table's unit)
FROM_BM = {"ramp_up_rate": ("run_up_share_per_min", 1), "ramp_down_rate": ("run_down_share_per_min", 1),
           "start_up_notice": ("ndz_min", 1 / 60), "run_up_to_min_stable_time": ("time_zero_to_sel_min", 1 / 60),
           "min_up_time": ("mnzt_min", 1 / 60), "min_down_time": ("mzt_min", 1 / 60)}


@pytest.fixture(scope="module")
def table() -> pd.DataFrame:
    return pd.read_csv(TABLE, dtype={"year": str})


@pytest.fixture(scope="module")
def sources() -> pd.DataFrame:
    return pd.read_csv(SOURCES, dtype=str)


def test_the_columns(table, sources):
    assert list(table.columns) == COLUMNS
    assert list(sources.columns) == SOURCE_COLUMNS


def test_every_parameter_is_in_the_vocabulary_and_its_unit(table):
    unknown = sorted(set(table["parameter"]) - set(UNITS))
    assert not unknown, f"parameters outside the vocabulary: {unknown}"
    bad = table[[not re.fullmatch(UNITS[p], u) for p, u in zip(table["parameter"], table["unit"])]]
    assert bad.empty, bad[["technology", "parameter", "unit", "source"]].to_string()


def test_every_row_has_a_value_or_a_range_and_the_value_sits_in_it(table):
    # a one-sided range is a value as the source prints it: 'up to 59 %' (high only), '< 1 h' (high only)
    empty = table[table[["value", "low", "high"]].isna().all(axis=1)]
    assert empty.empty, empty[["technology", "class", "parameter", "source"]].to_string()
    lo_ok = table["low"].isna() | table["value"].isna() | (table["low"] <= table["value"] + 1e-9)
    hi_ok = table["high"].isna() | table["value"].isna() | (table["value"] <= table["high"] + 1e-9)
    range_ok = table["low"].isna() | table["high"].isna() | (table["low"] <= table["high"] + 1e-9)
    bad = table[~(lo_ok & hi_ok & range_ok)]
    assert bad.empty, bad[["technology", "class", "parameter", "value", "low", "high"]].to_string()


def test_shares_lie_between_zero_and_one(table):
    shares = table[table["unit"] == "fraction"]
    x = shares[["value", "low", "high"]]
    bad = shares[((x < 0) | (x > 1)).any(axis=1)]
    assert bad.empty, bad[["technology", "parameter", "value", "low", "high", "source"]].to_string()


def test_status_and_default_flags(table):
    assert set(table["status"]) <= {"transcribed", "converted", "derived"}
    assert set(table["gb_default"].fillna("")) <= {"yes", ""}


def test_every_cited_source_is_listed_and_every_source_is_complete(table, sources):
    assert sources["source_id"].is_unique
    cited = {s for v in table["source"] for s in v.split(";")}
    assert cited <= set(sources["source_id"]), f"cited but not listed: {sorted(cited - set(sources['source_id']))}"
    blank = sources[sources[["publisher", "title", "url", "accessed", "licence"]].isna().any(axis=1)]
    assert blank.empty, blank["source_id"].tolist()
    assert sources["url"].str.startswith("https://").all()


def test_one_gb_default_per_technology_parameter_year_and_vintage(table):
    d = table[table["gb_default"] == "yes"]
    key = d[["technology", "parameter", "year", "commissioned_from", "commissioned_to"]].astype(str).agg("|".join, axis=1)
    assert key.is_unique, sorted(set(key[key.duplicated()]))


def test_the_gb_defaults_from_the_bm_dynamic_data_match_its_summary(table):
    summary = pd.read_csv(REFERENCE / B.SUMMARY_FILE)
    summary = summary[summary["period"] == B.PERIOD_ALL].set_index(["tech", "metric"])
    d = table[(table["gb_default"] == "yes") & (table["source"] == "elexon-bm-dynamic")]
    expected = {(t, p) for t in ("ccgt", "ocgt", "coal", "biomass") for p in [*FROM_BM, "min_stable_generation"]}
    assert set(zip(d["technology"], d["parameter"])) == expected | {("nuclear", "min_stable_generation")}
    for _, r in d.iterrows():
        if r["parameter"] == "min_stable_generation":
            metric = "sel_share_capacity_running" if r["technology"] != "ocgt" else "sel_share_capacity"
            f = 1
        else:
            metric, f = FROM_BM[r["parameter"]]
        s = summary.loc[(r["technology"], metric)]
        # the table keeps six decimals
        assert np.allclose([r["value"], r["low"], r["high"]], [s["median"] * f, s["p10"] * f, s["p90"] * f],
                           rtol=0, atol=1e-6), (r["technology"], r["parameter"])


# --- gbpowerdata.build.bm_dynamic -------------------------------------------------------------------------------

def test_run_up_over_three_segments_with_elbows():
    rates = (2.0, 100.0, 1.0, 150.0, 5.0)          # 2 MW/min to 100 MW, 1 MW/min to 150 MW, 5 MW/min above
    assert B.run_minutes(0, 100, rates, up=True) == pytest.approx(50)
    assert B.run_minutes(50, 200, rates, up=True) == pytest.approx(25 + 50 + 10)
    assert np.isnan(B.run_minutes(100, 100, rates, up=True))


def test_run_down_applies_the_first_rate_at_the_top():
    rates = (10.0, 300.0, 5.0, 100.0, 1.0)         # 10 MW/min down to 300 MW, 5 MW/min to 100 MW, 1 MW/min below
    assert B.run_minutes(400, 300, rates, up=False) == pytest.approx(10)
    assert B.run_minutes(400, 0, rates, up=False) == pytest.approx(10 + 40 + 100)
    assert B.run_minutes(50, 0, (8.0, np.nan, np.nan, np.nan, np.nan), up=False) == pytest.approx(6.25)


def test_a_999_segment_is_a_step_and_takes_no_time():
    rates = (999.0, 10.0, 2.0, np.nan, np.nan)     # synchronisation block of 10 MW, then 2 MW/min
    assert B.run_minutes(0, 50, rates, up=True) == pytest.approx(20)
    assert B.run_minutes(0, 10, rates, up=True) == pytest.approx(0)


def test_the_record_in_force_is_the_latest_before_the_start_else_the_first_after():
    start = pd.Timestamp("2024-01-15T11:30Z")
    df = pd.DataFrame({"dataset": ["SEL"] * 4, "nationalGridBmUnit": ["A", "A", "A", "B"],
                       "time": ["2024-01-10T00:00Z", "2024-01-15T11:01Z", "2024-01-15T11:59Z", "2024-01-15T11:45Z"],
                       "value": [100, 120, 140, 50]})
    got = B._in_force(df, start).set_index("nationalGridBmUnit")["value"]
    assert got.to_dict() == {"A": 120, "B": 50}


def test_settlement_period_24_starts_at_local_11_30():
    assert B.sp_start_utc("2024-01-15", 24) == pd.Timestamp("2024-01-15T11:30Z")
    assert B.sp_start_utc("2024-07-15", 24) == pd.Timestamp("2024-07-15T10:30Z")
