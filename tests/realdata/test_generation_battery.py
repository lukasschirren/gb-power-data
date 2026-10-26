"""The battery table (generation_battery_summary.csv, generation_battery_units.csv): the GSP groups add up to the
fleet, metered and response alike; the fleet's capacity in December (non-BM batteries included) against DESNZ's
grid-scale battery capacity at the year's end (data/reference/official_statistics.csv; UK, where the table is GB,
and with the supplier, virtual lead party and non-BM units at a lower bound), 0.95-1.04 of it in 2022-2025 on
26 Oct 2026, so the band is 0.9-1.1; the fleet's metered discharge below its metered charge from 2022 (0.82-0.90);
and the units that meter more out than in (docs/AUDIT.md A9-14)."""
import pandas as pd
import pytest

from gbpowerdata.checks import official as O

from .conftest import need

pytestmark = pytest.mark.realdata


@pytest.fixture(scope="module")
def summary(processed):
    need([processed / "generation_battery_summary.csv"])
    return pd.read_csv(processed / "generation_battery_summary.csv", dtype={"period": str})


@pytest.fixture(scope="module")
def units(processed):
    need([processed / "generation_battery_units.csv"])
    return pd.read_csv(processed / "generation_battery_units.csv")


def test_regions_add_up_to_the_fleet(summary):
    y = summary[summary["resolution"] == "year"]
    fleet = y[(y["group"] == "all") & (y["gsp_group"] == "all")].set_index(["period", "basis", "flow"])
    regions = y[y["gsp_group"] != "all"].groupby(["period", "basis", "flow"])[["energy_gwh", "mean_mw"]].sum(min_count=1)
    metered = regions.xs("metered", level="basis")["energy_gwh"].dropna()
    assert (metered - fleet.xs("metered", level="basis").loc[metered.index, "energy_gwh"]).abs().max() < 0.05
    resp = regions.xs("response", level="basis")["mean_mw"].dropna()
    assert (resp - fleet.xs("response", level="basis").loc[resp.index, "mean_mw"]).abs().max() < 0.5


def test_december_capacity_near_desnz_grid_scale(summary):
    dec = summary[(summary["resolution"] == "month") & summary["period"].str.endswith("-12")
                  & (summary["basis"] == "response") & (summary["group"] == "all")
                  & (summary["gsp_group"] == "all") & (summary["flow"] == "dcl")]
    ours = dec.set_index(dec["period"].str[:4].astype(int))["capacity_mw"]
    official = O.series("battery_capacity_grid_scale").dropna()
    years = [y for y in range(2022, 2026) if y in ours.index and y in official.index]
    if not years:
        pytest.skip("no year in both")
    ratio = ours.loc[years] / official.loc[years]
    assert ratio.between(0.9, 1.1).all(), ratio.round(3).to_dict()


def test_fleet_meters_less_out_than_in_from_2022(summary):
    y = summary[(summary["resolution"] == "year") & (summary["basis"] == "metered") & (summary["group"] == "all")
                & (summary["gsp_group"] == "all")].pivot(index="period", columns="flow", values="energy_gwh")
    y = y[(y.index >= "2022") & (y.index <= "2025")].dropna()
    if y.empty:
        pytest.skip("no metered year from 2022")
    assert (y["discharge"] < y["charge"]).all(), (y["discharge"] / y["charge"]).round(3).to_dict()


@pytest.mark.xfail(strict=True, reason="docs/AUDIT.md A9-14: units classed as batteries meter more out than in")
def test_no_battery_unit_meters_more_out_than_in(units):
    u = units[units["year"].between(2019, 2025)].dropna(subset=["discharge_metered_mwh", "charge_metered_mwh"])
    over = u[u["discharge_metered_mwh"] > u["charge_metered_mwh"]]
    assert over.empty, over[["year", "unit_id", "discharge_metered_mwh", "charge_metered_mwh"]].head(10).to_string()
