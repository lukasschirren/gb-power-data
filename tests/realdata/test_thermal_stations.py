"""The thermal station map (reference/thermal_station_bmu.csv) against the built tables: every BM unit it names is in
a year's register, every powerplantmatching plant it replaces is in a located roster, and stage 3's agents carry the
stations dated by the register (Didcot B in 2025, Drax coal only units 5-6)."""
import pandas as pd
import pytest

from .conftest import need, years_with

pytestmark = pytest.mark.realdata


def test_map_names_real_units_and_plants(processed):
    from gbpowerdata import config as cfg
    m = pd.read_csv(cfg.reference_dir() / "thermal_station_bmu.csv", dtype={"bmu_ids": str})
    reg_years, ppm_years = years_with(processed, "bm_unit_register"), years_with(processed, "powerplants_located")
    if not reg_years or not ppm_years:
        need([processed / "bm_unit_register_2025.csv", processed / "powerplants_located_2025.csv"])
    units = set()
    for y in reg_years:
        units |= set(pd.read_csv(processed / f"bm_unit_register_{y}.csv", usecols=["unit_id"])["unit_id"])
    for _, s in m.iterrows():
        ids = [u for u in str(s["bmu_ids"]).split(";") if u and u != "nan"]
        assert set(ids) <= units, (s["station"], set(ids) - units)
    ppm = pd.concat([pd.read_csv(processed / f"powerplants_located_{y}.csv", keep_default_na=False, na_values=[""],
                                 usecols=["Name", "Fueltype"]) for y in ppm_years])
    assert set(zip(m["ppm_name"], m["ppm_fueltype"])) <= set(zip(ppm["Name"], ppm["Fueltype"]))


def test_agents_carry_the_register_dated_stations(processed):
    need([processed / "agents_2021.csv", processed / "agents_2025.csv"])
    a25 = pd.read_csv(processed / "agents_2025.csv")
    assert "Didcot B" in set(a25["name"]) and "Baglan Bay" not in set(a25["name"])
    a21 = pd.read_csv(processed / "agents_2021.csv")
    coal = a21[a21["tech"] == "Hard Coal"].set_index("name")["capacity_mw"]
    assert coal.get("Drax units 5-6 (coal)", 0.0) <= 1290.0 + 1e-6
