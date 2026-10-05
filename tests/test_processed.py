"""Loaders (gbpowerdata.processed) on a synthetic year: merge_drivers keeps the coal price that
fuel_prices carries when there is no raw coal series (a data-pack install), and uses the monthly
raw series when there is one."""
import pandas as pd
import pytest

from gbpowerdata import config as cfg
from gbpowerdata import processed


@pytest.fixture
def tree(tmp_path, monkeypatch):
    proc, raw = tmp_path / "processed", tmp_path / "raw"
    proc.mkdir()
    raw.mkdir()
    monkeypatch.setattr(cfg, "processed_dir", lambda: proc)
    monkeypatch.setattr(cfg, "raw_dir", lambda: raw)
    t = pd.date_range("2023-01-01", periods=4, freq="30min", tz="UTC").astype(str)
    tables = {
        "demand": {"startTime": t, "national_demand_mw": 25000.0},
        "capacity_factors": {"startTime": t, "solar_cf": 0.0},
        "fuel_prices": {"startTime": t, "gas_price_pence_per_therm": 100.0, "coal_price_gbp_per_mwh_thermal": 22.5},
        "mid_target": {"startTime": t, "price_gbp_per_mwh": 80.0, "mid_source": "APXMIDP"},
        "agents": {"agent_id": ["a"]}, "regime_summary": {"support_regime": ["CfD"]},
        "cfd_fleet": {"CfD_ID": ["c"]}, "powerplants_tagged": {"id": [1]},
    }
    for name, cols in tables.items():
        pd.DataFrame(cols).to_csv(proc / f"{name}_2023.csv", index=False)
    return raw


def test_merge_drivers_keeps_the_processed_coal_price_without_raw_data(tree):
    m = processed.merge_drivers(2023)
    assert (m["coal_price_gbp_per_mwh_thermal"] == 22.5).all()     # not the flat 40 fallback


def test_merge_drivers_uses_the_monthly_raw_series_when_present(tree):
    pd.DataFrame({"month": ["2023-01"], "coal_gbp_per_mwh_thermal": [19.0]}).to_csv(
        tree / "coal_monthly.csv", index=False)
    assert (processed.merge_drivers(2023)["coal_price_gbp_per_mwh_thermal"] == 19.0).all()
