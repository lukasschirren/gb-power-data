"""The model's half-hourly drivers on real data: capacity factors in [0, 1], demand against metered generation and
interconnector flows, prices without spurious zeros, and the definitions the tables state (docs/AUDIT.md A2, A5,
A6). Thresholds are set from the measurements of 10 Oct 2026."""
import numpy as np
import pandas as pd
import pytest

from gbpowerdata.checks import balance as B
from gbpowerdata.checks import official as O

from .conftest import need, read_series, years_with

pytestmark = pytest.mark.realdata


@pytest.fixture(scope="module")
def demand(processed):
    years = years_with(processed, "demand")
    if not years:
        pytest.skip("no demand_*.csv")
    return read_series(processed, "demand", years)


def test_capacity_factors_lie_in_0_1(processed):
    years = years_with(processed, "capacity_factors")
    if not years:
        pytest.skip("no capacity_factors_*.csv")
    cf = read_series(processed, "capacity_factors", years)
    assert ((cf >= 0) & (cf <= 1)).all().all()


def test_national_demand_is_never_the_embedded_generation_alone(demand):
    # where ITSDO is missing, national demand is empty (it was read as zero before Oct 2026: 0.7-11 GW)
    missing = demand["transmission_demand_mw"].isna()
    assert demand.loc[missing, "national_demand_mw"].isna().all()
    assert (demand["national_demand_mw"].dropna() > 10000).all()


def test_transmission_demand_balances_metered_generation_and_imports(raw, demand):
    need(sorted(raw.glob("fuelhh_*.csv"))[:1] or [raw / "fuelhh_*.csv"])
    r = B.transmission_residual(demand["transmission_demand_mw"], B.fuelhh(raw))
    r = r[r.index.isin(demand.index)]
    by_year = r.groupby(r.index.year)
    assert (by_year.median().abs() <= 400).all(), by_year.median().round(0).to_dict()   # -334 MW in 2025 at worst
    assert r.abs().quantile(0.95) <= 1000, r.abs().quantile(0.95)                     # 471 MW over 2018-2025


def test_national_demand_includes_exports_and_pumping(raw, demand):
    """A definition, not a defect: ITSDO carries exports and pumping (README, data caveats)."""
    need(sorted(raw.glob("fuelhh_*.csv"))[:1] or [raw / "fuelhh_*.csv"])
    c = B.components(B.fuelhh(raw)).reindex(demand.index)
    j = pd.DataFrame({"tsd": demand["transmission_demand_mw"], "exp": c["exports"], "pump": c["pumping"]}).dropna()
    hi = j[j["exp"] + j["pump"] > 3000]
    lo = j[j["exp"] + j["pump"] < 500]
    assert hi["tsd"].mean() > lo["tsd"].mean() - 5000           # exports and pumping lift transmission demand


def test_demand_tracks_dukes_total_demand_from_year_to_year(processed, demand):
    """ESPENI-like demand would hold a stable share of DUKES's UK total demand; national_demand_mw, which carries
    exports, jumps in 2022, a year of exports (A5)."""
    dukes = O.series("total_demand")
    ann = (demand["national_demand_mw"].groupby(demand.index.year).sum() / 2 / 1000).reindex(dukes.index).dropna()
    ratio = ann / dukes.reindex(ann.index)
    assert ratio.between(0.80, 0.95).all(), ratio.round(3).to_dict()


@pytest.mark.xfail(strict=True, reason="AUDIT A5-1: national_demand_mw includes interconnector exports and pumping")
def test_national_demand_share_of_dukes_is_stable(demand):
    dukes = O.series("total_demand")
    ann = (demand["national_demand_mw"].groupby(demand.index.year).sum() / 2 / 1000).reindex(dukes.index).dropna()
    ratio = ann / dukes.reindex(ann.index)
    assert ratio.max() - ratio.min() <= 0.03, ratio.round(3).to_dict()                 # 0.846-0.910 measured


def test_mid_target_has_no_zero_prices_marked_observed(processed):
    years = years_with(processed, "mid_target")
    if not years:
        pytest.skip("no mid_target_*.csv")
    m = read_series(processed, "mid_target", years)
    zero_observed = (m["price_gbp_per_mwh"] == 0) & (m["mid_source"] == "APXMIDP")
    assert zero_observed.sum() <= 10, int(zero_observed.sum())    # a traded price can be 0; 191 untraded ones were


@pytest.mark.xfail(strict=True, reason="AUDIT A6-1: CF denominators are peak-normalised; CF x capacity overstates wind")
def test_wind_energy_from_capacity_factors_and_agents_matches_dukes(processed):
    years = [y for y in years_with(processed, "capacity_factors") if (processed / f"agents_{y}.csv").exists()]
    if not years:
        pytest.skip("no capacity_factors and agents")
    dukes = O.series("onshore_wind_generation") + O.series("offshore_wind_generation")
    for y in years:
        cf = pd.read_csv(processed / f"capacity_factors_{y}.csv")
        a = pd.read_csv(processed / f"agents_{y}.csv")
        w = a[a["tech"] == "Wind"]
        off = w["is_offshore"].astype(str).str.lower() == "true"
        twh = (cf["wind_offshore_cf"].sum() * w.loc[off, "capacity_mw"].sum()
               + cf["wind_onshore_cf"].sum() * w.loc[~off, "capacity_mw"].sum()) / 2 / 1e6
        # GB wind is about 2-3% below the UK's (Northern Ireland onshore); allow 5% either way
        assert abs(twh / (dukes[y] / 1000) - 1) <= 0.05, (y, round(twh, 1), round(dukes[y] / 1000, 1))
