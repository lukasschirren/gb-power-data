"""Thermal plant dated by the BM register in stage 3 (docs/AUDIT.md A7-8, 26 Oct 2026), on synthetic data and the
reference tables: a unit's share of the year runs from its first to its last day with output; thermal availability is
NESO's de-rating, 3/4 of the delivery year ending in the year and 1/4 of the one starting in it; the station map is
well formed. tests/realdata/test_thermal_stations.py checks it against the built register and roster."""
from pathlib import Path

import pandas as pd
import pytest

from gbpowerdata.build import stage3_build_agents as S3

REF = Path(__file__).resolve().parents[1] / "data" / "reference"


def test_active_share_counts_days_with_output_in_the_year():
    reg = pd.DataFrame(dict(unit_id=["all", "closes", "opens", "off", "gone"], active=[True, True, True, False, True],
                            active_from=[None, None, "2023-10-01", None, None],
                            active_to=[None, "2023-03-31", None, None, "2022-09-30"]))
    s = S3.active_share(reg, 2023)
    assert s["all"] == pytest.approx(1.0)
    assert s["closes"] == pytest.approx(90 / 365)                 # 1 Jan to 31 Mar inclusive
    assert s["opens"] == pytest.approx(92 / 365)                  # 1 Oct to 31 Dec
    assert s["off"] == 0.0 and s["gone"] == 0.0


def test_availability_weights_the_two_delivery_years():
    av = S3.thermal_availability(2025)
    t = pd.read_csv(REF / "thermal_parameters.csv", dtype={"year": str})
    t = t[(t["parameter"] == "availability") & (t["gb_default"] == "yes") & (t["technology"] == "ccgt")]
    dy = dict(zip(t["year"].str[:4].astype(int), t["value"]))
    assert av["CCGT"] == pytest.approx(0.75 * dy[2024] + 0.25 * dy[2025])
    assert set(av) == {"CCGT", "OCGT", "Hard Coal", "Oil"}


def test_station_rating_weights_oem_units_by_capacity():
    eic = pd.Series({"u1": "E1", "u2": "E2", "u3": "E3", "u4": None})
    cap = pd.Series({"u1": 400.0, "u2": 200.0, "u3": 300.0, "u4": 100.0})
    oem = pd.Series({"E1": 0.55, "E2": 0.52})                   # E3 has no OEM rating, u4 no EIC
    assert S3.station_rating(["u1", "u2", "u3", "u4"], eic, cap, oem) == pytest.approx((0.55 * 400 + 0.52 * 200) / 600)
    assert S3.station_rating(["u3", "u4"], eic, cap, oem) != S3.station_rating(["u3", "u4"], eic, cap, oem)  # NaN


def test_unit_efficiency_table_is_well_formed():
    d = pd.read_csv(REF / "thermal_unit_efficiency.csv")
    assert list(d.columns) == ["eic_g", "eic_p", "name_g", "name_p", "capacity_g", "type_g", "year_commissioned", "eff",
                               "best_source"]
    assert d["eic_g"].is_unique and d["eic_g"].str.startswith("48W").all()      # GB EICs
    assert set(d["type_g"]) <= {"Fossil Gas", "Fossil Hard coal", "Fossil Oil"}
    oem = d[d["best_source"].eq("OEM_derived")]
    assert len(oem[oem["type_g"] == "Fossil Gas"]) >= 60 and oem["eff"].between(0.25, 0.65).all()


def test_station_map_is_well_formed():
    m = pd.read_csv(REF / "thermal_station_bmu.csv", dtype={"bmu_ids": str})
    assert not m.duplicated("station").any()
    assert set(m["tech"]) <= {"CCGT", "OCGT", "Hard Coal", "Oil"}
    assert set(m["fuel"]) <= {"Natural Gas", "Hard Coal", "Oil"}
    assert m["commissioned"].between(1950, 2030).all()
    ids = [u for s in m["bmu_ids"].dropna() for u in s.split(";")]
    assert len(ids) == len(set(ids)), "a BM unit belongs to one station"
    assert m["ppm_name"].notna().all() and m["ppm_fueltype"].notna().all()
