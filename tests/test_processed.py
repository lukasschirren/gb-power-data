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


@pytest.fixture
def model_inputs(tmp_path, monkeypatch):
    """The model-input tables of October 2026, two rows each, on a synthetic processed tree."""
    proc = tmp_path / "processed"
    (proc / "pecd").mkdir(parents=True)
    monkeypatch.setattr(cfg, "processed_dir", lambda: proc)
    t = pd.date_range("2023-01-01", periods=2, freq="h", tz="UTC")
    pd.DataFrame({"startTime": t.astype(str), "wind_offshore_cf": [0.5, 0.6]}).to_csv(proc / "vre_cf_corrected.csv", index=False)
    pd.DataFrame({"startTime": t, "link": "Nemo", "price_gbp_mwh": [50.0, 60.0]}).to_parquet(proc / "ic_hourly.parquet", index=False)
    pd.DataFrame({"startTime": t.astype(str), "season": ["Winter 2022"] * 2, "bmrp_gbp_mwh": [405.26] * 2}).to_csv(proc / "bmrp_halfhourly.csv", index=False)
    pd.DataFrame({"zone": ["fr"], "link": ["IFA_ElecLink_IFA2"], "slope_gbp_per_mw": [0.00364], "r2": [0.079], "n": [28615], "usable": [True]}).to_csv(proc / "foreign_supply_slope.csv", index=False)
    pd.DataFrame({"accreditation_number": ["R00001SCSC"], "station_name": ["Hill"], "technology": ["Onshore wind"], "tech": ["Onshore"],
                  "dnc_mw": [1.5], "commissioning_date": ["2010-03-12"], "accreditation_date": ["2010-04-01"], "country": ["Scotland"],
                  "station_postcode": ["AB1 2CD"], "register_file": ["x.csv"]}).to_csv(proc / "ro_stations.csv", index=False)
    nat = pd.DataFrame({"wind_offshore_cf": [0.4, 0.5], "wind_onshore_cf": [0.2, 0.3], "solar_cf": [0.0, 0.1]}, index=t.rename("startTime"))
    nat.to_parquet(proc / "pecd" / "national_cf_historical.parquet")
    pd.DataFrame({"_A_onshore_wind": [0.2, 0.3]}, index=t.rename("startTime")).to_parquet(proc / "pecd" / "gsp_cf_era5.parquet")
    pd.DataFrame({"hour": [1, 2], "label": ["01JAN01", "01JAN02"], "mc_fr00": [40.0, 0.0]}).to_csv(proc / "tyndp_nt2030_cy2009_hourly.csv", index=False)
    return proc


def test_model_input_loaders_read_each_table_with_utc_time_axes(model_inputs):
    assert str(processed.read_vre_split().index.tz) == "UTC" and processed.read_vre_split().shape == (2, 1)
    ic = processed.read_interconnector()
    assert str(ic.index.tz) == "UTC" and list(ic["price_gbp_mwh"]) == [50.0, 60.0]
    assert processed.read_bmrp().loc["2023-01-01 01:00+00:00", "bmrp_gbp_mwh"] == 405.26
    assert processed.read_foreign_supply().loc[0, "zone"] == "fr"
    ro = processed.read_ro_stations()
    assert ro.loc[0, "accreditation_date"].year == 2010 and ro.loc[0, "station_postcode"] == "AB1 2CD"
    assert list(processed.read_weather_years().columns) == ["wind_offshore_cf", "wind_onshore_cf", "solar_cf"]
    assert str(processed.read_weather_years("gsp").index.tz) == "UTC"
    with pytest.raises(ValueError):
        processed.read_weather_years("ro")
    assert len(processed.read_tyndp_hourly()) == 2
