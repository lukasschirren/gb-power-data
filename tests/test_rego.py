"""REGOs (gbpowerdata.build.rego): the vintage of a month (compliance periods April to March, CP1 from April 2002), the
price summaries (a range at its midpoint for the median, its low and high for the extremes, forecasts left out), the
vintage table with the fuel mix disclosure figures and no EU GoOs counted from 2023/24; and the reference tables:
their columns, every price with a cited and complete source, a value inside its range, a known basis and a vintage
that matches its generation period, every statistic with a URL, licence and status. No data/processed and no network
needed."""
import numpy as np
import pandas as pd
import pytest

from gbpowerdata import config as cfg
from gbpowerdata.build import rego as R

REF = cfg.reference_dir()


def test_the_vintage_of_a_month_runs_april_to_march_from_cp1_in_2002():
    assert R.vintage_of("2002-04") == 1 and R.vintage_of("2003-03-31") == 1
    assert R.vintage_of("2023-04-01") == 22 and R.vintage_of("2024-03") == 22 and R.vintage_of("2024-04") == 23
    assert R.vintage_period(22) == ("2023-04", "2024-03")
    assert R.disclosure_label(22) == "2023/24" and R.disclosure_label(8) == "2009/10"


def _prices(rows):
    p = pd.DataFrame(rows, columns=["observed_from", "generation_from", "value", "low", "high", "basis", "source"])
    p["observed_to"] = p["observed_from"]
    p["vintage_basis"] = np.where(p["generation_from"].notna(), "stated", "none")
    p["cp"] = p["generation_from"].map(lambda m: R.vintage_of(m) if isinstance(m, str) else np.nan)
    return p


def test_a_range_counts_at_its_midpoint_and_forecasts_and_bounds_are_left_out():
    p = _prices([("2023-10-02", "2023-04", 20.0, np.nan, np.nan, "traded", "a"),
                 ("2023-10-20", "2023-04", np.nan, 12.0, 14.0, "traded", "b"),
                 ("2023-11-05", "2023-04", 25.0, np.nan, np.nan, "auction_high", "c"),
                 ("2023-11-06", "2023-04", 99.0, np.nan, np.nan, "forecast", "d"),
                 ("2023-11-07", "2023-04", np.nan, np.nan, 10.0, "traded", "e")])     # "below GBP 10": a bound
    v = R.summarise(p, ["cp"]).iloc[0]
    assert v["n_obs"] == 3 and v["price_median"] == 20.0                  # 20, 13 (midpoint), 25
    assert v["price_min"] == 12.0 and v["price_max"] == 25.0
    assert (v["first_observed"], v["last_observed"]) == ("2023-10", "2023-11") and v["sources"] == "a;b;c"
    m = R.summarise(p.assign(month=p["observed_from"].str[:7]), ["cp", "month"])
    assert m["month"].tolist() == ["2023-10", "2023-11"] and m["n_obs"].tolist() == [2, 1]


def test_only_observations_within_one_month_reach_the_monthly_table():
    p = pd.DataFrame({"observed_from": ["2023-10-02", "2023-10", "2023-09", "2020", np.nan],
                      "observed_to": ["2023-10-02", "2023-10", "2024-01", "2020", "2018-03"]})
    assert R.within_a_month(p).tolist() == [True, True, False, False, False]


def test_vintages_carry_the_disclosure_figures_and_no_eu_goos_from_2023_24():
    p = _prices([("2023-10-02", "2023-04", 20.0, np.nan, np.nan, "traded", "a")])
    stats = pd.DataFrame({"stat": ["fmd_residual_renewables_pct", "fmd_residual_renewables_pct", "eu_goo_recognised"],
                          "period_from": ["2022-04-01", "2023-04-01", "2022-04-01"], "value": [12.2, 0.2, 35818490]})
    v = R.vintages(p, stats).set_index("vintage")
    assert v.index.tolist() == ["CP21", "CP22"]
    assert v.loc["CP22", "fmd_residual_renewables_pct"] == 0.2 and v.loc["CP22", "eu_goo_recognised"] == 0
    assert v.loc["CP21", "eu_goo_recognised"] == 35818490 and v.loc["CP21", "n_obs"] == 0
    assert v.loc["CP22", "disclosure_period"] == "2023/24" and v.loc["CP22", "generation_to"] == "2024-03"


# --- the reference tables ---------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def prices():
    return pd.read_csv(REF / R.PRICE_FILE, dtype={"observed_from": str, "observed_to": str, "generation_from": str,
                                                    "generation_to": str})


@pytest.fixture(scope="module")
def sources():
    return pd.read_csv(REF / R.SOURCE_FILE, dtype=str)


def test_the_price_table_columns_units_and_bases(prices):
    assert list(prices.columns) == R.PRICE_COLUMNS
    assert (prices["unit"] == "GBP/MWh").all() and prices["basis"].isin(R.BASES).all()
    assert prices["status"].isin(["transcribed", "converted", "derived"]).all()
    assert prices["locator"].notna().all() and prices["vintage_basis"].isin(R.VINTAGE_BASES).all()
    has = prices[["value", "low", "high"]].notna().any(axis=1)              # a level, a range or a bound
    assert has.all(), prices.loc[~has, ["observed_from", "source"]]
    inside = prices["value"].isna() | prices["low"].isna() | prices["value"].between(prices["low"], prices["high"])
    ordered = prices["low"].isna() | prices["high"].isna() | (prices["low"] <= prices["high"])
    assert inside.all() and ordered.all() and (prices[["value", "low", "high"]].stack() >= 0).all()


def test_every_observation_is_dated_and_its_vintage_matches_its_generation_period(prices):
    assert prices["observed_to"].notna().all()
    for c in ("observed_from", "observed_to"):
        assert pd.to_datetime(prices[c].dropna(), format="mixed").notna().all()
    assert (prices["generation_from"].isna() == (prices["vintage_basis"] == "none")).all()
    for _, r in prices.dropna(subset=["generation_from"]).iterrows():
        cp = R.vintage_of(r["generation_from"])
        first, last = R.vintage_period(cp)
        # a whole vintage, or the months of one an auction lot covered ("CP22 (Apr 23 to Sept 23)")
        assert first <= r["generation_from"] <= r["generation_to"] <= last, r.to_dict()
        label = str(r["vintage"]).upper().replace(" ", "")
        if r["vintage_basis"] == "stated" and label[:2] == "CP" and label[2:4].isdigit():
            assert int(label[2:4]) == cp, r.to_dict()


def test_every_cited_source_is_listed_and_complete(prices, sources):
    assert list(sources.columns) == R.SOURCE_COLUMNS
    assert set(prices["source"]) <= set(sources["source_id"])
    assert not sources[["publisher", "title", "url", "accessed", "licence"]].isna().any().any()
    assert sources["url"].str.startswith("https://").all() and sources["source_id"].is_unique


def test_every_statistic_has_its_url_licence_and_status():
    s = pd.read_csv(REF / R.STATISTICS_FILE, dtype={"period_from": str, "period_to": str})
    assert list(s.columns) == R.STATISTICS_COLUMNS
    assert s["url"].str.startswith("https://").all() and s["licence"].notna().all()
    assert s["status"].isin(["verified", "derived"]).all()
    assert not s.duplicated(["stat", "period"]).any()
    shares = s[s["stat"].str.endswith("_pct")]
    for (stat, period), g in shares.assign(mix=shares["stat"].str.split("_").str[1]).groupby(["mix", "period"]):
        assert abs(g["value"].sum() - 100) <= 0.3, (stat, period, g["value"].sum())   # published to one decimal
