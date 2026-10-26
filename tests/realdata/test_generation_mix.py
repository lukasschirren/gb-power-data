"""The generation mix (generation_mix_summary.csv) against DUKES (data/reference/official_statistics.csv): wind (BM-
metered plus NESO's embedded estimate) and solar (NESO's estimate) are GB, DUKES the UK, so they sit a little below it;
pumped storage output and input are GB in both, and FUELHH nets pumping and generation within a half-hour. The bands
are set from the measurements of 26 Oct 2026 (wind 0.95-0.99 of DUKES, solar 0.90-0.97, pumped storage 0.91-0.96).
The summary's shares of generation add to one and its net imports are imports less exports."""
import pandas as pd
import pytest

from gbpowerdata.checks import official as O

from .conftest import need

pytestmark = pytest.mark.realdata


@pytest.fixture(scope="module")
def annual(processed):
    need([processed / "generation_mix_summary.csv"])
    s = pd.read_csv(processed / "generation_mix_summary.csv", dtype={"period": str})
    y = s[s["resolution"] == "year"]
    return y.pivot(index="period", columns="technology", values="energy_gwh").rename(index=int), y


@pytest.mark.parametrize("ours, stats, low", [
    (("wind_metered", "wind_embedded"), ("onshore_wind_generation", "offshore_wind_generation"), 0.93),
    (("solar_embedded",), ("solar_generation",), 0.88),
    (("pumped_storage_generation",), ("pumped_storage_output",), 0.88),
    (("pumped_storage_pumping",), ("pumped_storage_input",), 0.88)])
def test_energy_sits_just_below_dukes(annual, ours, stats, low):
    e, _ = annual
    official = sum(O.series(s) for s in stats).dropna()
    years = official.index.intersection(e.index)
    if years.empty:
        pytest.skip("no year in both")
    ratio = e.loc[years, list(ours)].sum(axis=1) / official.loc[years]
    assert ratio.between(low, 1.0).all(), ratio.round(3).to_dict()


def test_shares_add_up_and_net_imports_are_imports_less_exports(annual):
    e, y = annual
    parts = y[~y["technology"].isin(["wind_offshore_metered", "wind_onshore_metered"])]      # parts of wind_metered
    shares = parts.dropna(subset=["share_of_generation"]).groupby("period")["share_of_generation"].sum()
    assert (shares - 1).abs().max() < 1e-3
    assert ((e["imports"] - e["exports"] - e["net_imports"]).abs() < 0.01).all()
    whole = y[(y["technology"] == "generation") & (y["period"].astype(int) < pd.Timestamp.today().year)]
    assert (whole["coverage"] > 0.99).all()                     # every complete year


def test_the_wind_split_matches_dukes_offshore_and_onshore(annual):
    """Offshore: GB's offshore is the UK's (Northern Ireland has none): 1.00-1.02 of DUKES in 2020-2025. Onshore,
    metered plus NESO's embedded estimate, against the UK's (Northern Ireland's onshore in it): 0.88-0.95."""
    e, y = annual
    cov = y[y["technology"] == "wind_offshore_metered"].set_index("period")["coverage"].rename(index=int)
    years = cov.index[cov > 0.99].intersection(O.series("offshore_wind_generation").index)
    if years.empty:
        pytest.skip("no year with the split and DUKES")
    off = e.loc[years, "wind_offshore_metered"] / O.series("offshore_wind_generation").loc[years]
    on = (e.loc[years, "wind_onshore_metered"] + e.loc[years, "wind_embedded"]) / O.series("onshore_wind_generation").loc[years]
    assert off.between(0.97, 1.05).all(), off.round(3).to_dict()
    assert on.between(0.85, 1.0).all(), on.round(3).to_dict()
