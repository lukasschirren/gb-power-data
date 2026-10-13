"""The investment inputs on the pulled files: one row per source, technology, year and parameter, and anchors read off
the source sheets on 10 Oct 2026 (DESNZ Electricity generation costs 2025, Annex A, sheet "Technical and Cost
Assumptions", column D: large-scale solar PV commissioning in 2030; the Danish Energy Agency's datasheet 0011, sheet
"180 Lithium Ion Battery", column E: 2030)."""
import pytest

from .conftest import need

pytestmark = pytest.mark.realdata


@pytest.fixture(scope="module")
def table(processed):
    need([processed / "investment_inputs.csv"])
    from gbpowerdata import processed as P
    return P.read_investment_inputs(reference=False)


def test_one_row_per_source_technology_year_and_parameter(table):
    key = ["source", "source_technology", "variant", "year", "parameter"]
    assert not table.duplicated(key).any(), table.loc[table.duplicated(key, keep=False), key].head(10).to_dict("records")


def row(table, source, tech, year, par):
    r = table[(table["source"] == source) & (table["source_technology"] == tech) & (table["year"] == year)
              & (table["parameter"] == par)]
    assert len(r) == 1, (source, tech, year, par, len(r))
    return r.iloc[0]


def test_the_generation_costs_2025_anchor(table):
    if "desnz-egc-2025" not in set(table["source"]):
        pytest.skip("the 2025 edition is not pulled")
    t, src = "Large Scale Solar PV", "desnz-egc-2025"
    cap = row(table, src, t, 2030, "capex_construction")
    assert (cap["value"], cap["low"], cap["high"], cap["unit"]) == (500, 400, 500, "GBP/kW")      # rows 19-21
    hr = row(table, src, t, 2030, "hurdle_rate")
    assert (hr["value"], hr["low"], hr["high"]) == pytest.approx((0.076, 0.065, 0.089))         # rows 38-40
    assert row(table, src, t, 2030, "fixed_om")["value"] == pytest.approx(5.9)                   # 5,900 GBP/MW/yr
    assert row(table, src, t, 2030, "capex_infrastructure")["value"] == pytest.approx(6100 / 52)  # GBP'000 / 52 MW
    assert row(table, src, t, 2030, "lifetime")["value"] == 38


def test_the_atb_anchor(table):
    if "nrel-atb-2021" not in set(table["source"]):
        pytest.skip("the 2021 ATB is not pulled")
    r = table[(table["source"] == "nrel-atb-2021") & (table["variant"] == "4Hr Battery Storage") & (table["year"] == 2019)
              & (table["parameter"] == "capex_total")].iloc[0]
    assert r["value"] == pytest.approx(1434.2856) and r["price_base_year"] == 2019     # ATBe.csv, Moderate, 2019$


def test_the_danish_energy_agency_anchor(table):
    if "dea-storage" not in set(table["source"]):
        pytest.skip("the datasheet is not pulled")
    t, src = "Lithium-ion battery (Utility-scale)", "dea-storage"
    assert row(table, src, t, 2030, "capex_specific")["value"] == pytest.approx(279.0)          # 0.279 MEUR/MWh
    assert row(table, src, t, 2030, "round_trip_efficiency")["value"] == pytest.approx(0.91)
    assert row(table, src, t, 2030, "lifetime")["value"] == 20
