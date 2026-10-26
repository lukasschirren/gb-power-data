"""The annual generation by fuel against itself and the half-hourly mix: the four countries add up to DUKES's UK
total, and the half-hourly table holds the share of GB's official output (supplied basis) measured on 26 Oct 2026 for
each fuel in 2016-2025: wind 0.90-1.04, coal 0.98-1.05, nuclear 1.02-1.03, gas 0.90-0.94 (the CHP of the other
generators is outside it), all fuels 0.88-0.90. The four countries match the UK within 0.4% from 2009."""
import pandas as pd
import pytest

from gbpowerdata.build import generation_by_fuel as G

from .conftest import need

pytestmark = pytest.mark.realdata


def test_the_countries_add_up_to_the_uk(processed):
    need([processed / "generation_by_fuel_annual.csv"])
    assert G.countries_vs_uk(pd.read_csv(processed / "generation_by_fuel_annual.csv")) < 0.01


@pytest.mark.parametrize("fuel, low, high", [("gas", 0.88, 0.97), ("wind", 0.88, 1.06), ("coal", 0.95, 1.07),
                                             ("nuclear", 0.95, 1.08), ("total", 0.85, 0.93)])
def test_the_half_hourly_table_holds_its_measured_share(processed, fuel, low, high):
    need([processed / "generation_reconciliation_annual.csv"])
    r = pd.read_csv(processed / "generation_reconciliation_annual.csv")
    r = r[(r["fuel"] == fuel) & r["half_hourly_share"].notna() & (r["half_hourly_coverage"] > 0.99)]
    if fuel == "coal":
        r = r[r["official_supplied_gwh"] > 1000]                 # the last years of coal are too small to compare
    assert len(r) and r["half_hourly_share"].between(low, high).all(), r.set_index("year")["half_hourly_share"].to_dict()
