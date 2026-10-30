"""The Baseload Market Reference Price (BMRP) on the half-hourly spine.

WHY. Baseload CfDs (Drax unit 1, Lynemouth, Teesside REP, K3 CHP) do not settle against the generation-weighted
intermittent reference price that makes wind and solar CfDs "produce and forget". They settle against the BMRP: a
seasonal, volume-weighted average of forward-season trades reported by LEBA, fixed before the season starts and
independent of the plant's own output. The market terms therefore do not cancel in the generator's margin:

    revenue(h) = P_h q_h + (K - R) q_h,   so the plant generates while P_h > AC - (K - R)

and (K - R) is an output-contingent payment of known value per MWh, the same object as a Renewables Obligation
certificate. Hedging does not change the marginal condition. A merit-order model that prices these contracts needs R
by half-hour at the seasonal resolution: calendar 2023 alone spans three seasons at 405.26, 207.07 and 128.81
GBP/MWh, and the preceding year's mean day-ahead price is no substitute (it once put Drax's offer at +112/MWh and
priced 1.3 GW out of the stack).

SEASONS. Summer is 1 April to 30 September; Winter 1 October to 31 March of the following year, so "Winter 2023"
covers October 2023 to March 2024. A season's end is a date and the season runs to the end of that day.

COVERAGE. LCCC publishes from Summer 2019. Half-hours before 1 April 2019 carry NaN rather than an invented value;
a model falls back to an avoidable-cost offer there.

CHECK (out of sample, in the research repository's docstring): GB's metered biomass output against the seasonal
BMRP over 14 seasons 2019-2025 has a correlation of -0.63, output in the three highest-reference seasons
1,181-1,642 MW against 1,864-2,450 MW elsewhere, the direction and timing the contract implies.

SOURCE. LCCC, Market Reference Prices (https://www.lowcarboncontracts.uk/our-schemes/contracts-for-difference/
market-reference-prices/), BMRP set under condition 15 of the CfD Standard Terms; pulled to raw/lccc/
bmrp_seasonal.csv (season, season_start, season_end, bmrp_gbp_mwh, status, source) by `pull.lccc_pull`.
Ported on 30 Oct 2026 from the research repository's scripts/build_bmrp_reference.py (its table reproduced value
for value).

OUTPUT processed/bmrp_halfhourly.csv: startTime (UTC, half-hourly, START to END), season, bmrp_gbp_mwh.
READ BY the merit-order model (baseload CfD offers and settlement), `modelinputs`.
RUN    python -m gbpowerdata.build.bmrp
"""
from __future__ import annotations

import argparse
import sys

import pandas as pd

from gbpowerdata import config as cfg

SRC = "bmrp_seasonal.csv"
OUT = "bmrp_halfhourly.csv"
START, END = "2016-01-01", "2026-12-31"


def load_seasons() -> pd.DataFrame:
    """LCCC's published seasons, sorted by their start."""
    f = cfg.raw_dir() / "lccc" / SRC
    if not f.exists():
        raise FileNotFoundError(f"no seasonal BMRP file {f} (python -m gbpowerdata.pull.lccc_pull)")
    d = pd.read_csv(f)
    d["season_start"] = pd.to_datetime(d["season_start"], utc=True)
    d["season_end"] = pd.to_datetime(d["season_end"], utc=True)
    return d.sort_values("season_start").reset_index(drop=True)


def to_halfhourly(seasons: pd.DataFrame, start: str = START, end: str = END) -> pd.DataFrame:
    """Every half-hour of `start`..`end` (UTC) with its season's name and price; NaN where no season is published."""
    idx = pd.date_range(start, end, freq="30min", tz="UTC")
    out = pd.DataFrame({"startTime": idx})
    out["season"] = pd.NA
    out["bmrp_gbp_mwh"] = float("nan")
    for _, r in seasons.iterrows():
        m = (idx >= r["season_start"]) & (idx < r["season_end"] + pd.Timedelta(days=1))
        out.loc[m, "season"] = r["season"]
        out.loc[m, "bmrp_gbp_mwh"] = float(r["bmrp_gbp_mwh"])
    return out


def build() -> pd.DataFrame:
    """The half-hourly table, written to processed/, with the coverage and the spread within each year printed."""
    out = to_halfhourly(load_seasons())
    path = cfg.processed_dir() / OUT
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(path, index=False)
    cov = out["bmrp_gbp_mwh"].notna().mean()
    print(f"wrote {path} ({len(out):,} half-hours, {100 * cov:.1f}% covered)\n")

    y = out.dropna(subset=["bmrp_gbp_mwh"]).copy()
    y["year"] = y["startTime"].dt.year
    t = y.groupby("year")["bmrp_gbp_mwh"].agg(n_seasons=lambda x: x.nunique(), min="min", mean="mean",
                                               max="max").round(1)
    t["spread"] = (t["max"] - t["min"]).round(1)
    print("BMRP by calendar year:\n" + t.to_string())
    miss = out[out["bmrp_gbp_mwh"].isna()]
    if not miss.empty:
        print(f"\nno published BMRP from {miss.startTime.min().date()} to {miss.startTime.max().date()} "
              f"({len(miss):,} half-hours): LCCC publishes from Summer 2019")
    return out


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args(argv)
    build()
    return 0


if __name__ == "__main__":
    sys.exit(main())
