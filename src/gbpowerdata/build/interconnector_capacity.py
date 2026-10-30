"""GB interconnectors by the hour: the neighbours' day-ahead prices in GBP and each link's capacity, both directions.

WHY. A merit-order model represents each interconnector as two blocks: an import of up to the capacity
foreign-to-GB offered at P_foreign / (1 - loss), and an export of up to the capacity GB-to-foreign willing to pay
P_foreign x (1 - loss). The flow is then an output of the clearing; the realised flow is never an input, because it
is a function of the GB price being explained (feeding it in cut a 2023 fit's R2 from 0.62 to 0.37), and serves as
an out-of-sample check instead (NSL: 91.4% sign agreement). This table holds what those blocks need.

PRICES. ENTSO-E's day-ahead prices of the neighbouring zones (`pull.entsoe_pull`), hourly (a mixed 60/15-minute MTU
after 2025 is averaged to the hour), converted with the ECB's daily EUR/GBP reference rate (`pull.fx_pull`),
forward-filled across non-publication days, the market convention; an annual mean would misprice early 2016 by
about 11%, when sterling moved from 0.738 to 0.90 within the year. Before the daily series starts, and if it is
absent, the annual means in EUR_GBP_ANNUAL apply.

CAPACITY. Two series per link and direction, so a model can pick either:
  historical  import_cap_mw / export_cap_mw: the capacity published for the day-ahead market, better than the
              nameplate because it carries outages and limits (France: mean 2,432 MW against a 4,028 MW maximum;
              Viking: 827 MW in 2024 under Energinet's 800 MW cap for West Jutland's grid). ENTSO-E's hourly
              directional forecast transfer capacity (document A61, `pull.entsoe_capacity_pull`) for France, the
              Netherlands, Belgium, Ireland and, since December 2023, Denmark; Nord Pool's N2EX day-ahead capacity
              for Norway (NSL, `pull.nordpool_pull`), whose border ENTSO-E leaves empty. Hours the source left
              unpublished are filled with the median of the capacity published within FILL_DAYS either side of the
              gap (fill_unpublished) and flagged in cap_filled: the gaps are mostly blocks of weeks (France 1,609 h
              from 16 Oct 2020, Ireland 1,584 h from 27 Oct 2025, BritNed 840 h from 27 Nov 2023), zero would count
              them as the cable out of service, and one day carried across weeks would spread whatever that day held.
  full        import_cap_full_mw / export_cap_full_mw: every cable at its rating from its first day in service
              (`reference/ic_rated_capacity.csv`, one sourced row per cable), or the published capacity where that is
              higher, so the series carries no outage or limit and never sits below the historical one.
Before a link's first power both capacities are zero.

LOSSES are physical, by cable length (about 2% for the Channel and Irish Sea crossings, 5% for the long subsea HVDC
links), not fitted to flows.

Ported on 30 Oct 2026 from the research repository's scripts/build_ic_reference.py (its data/reference/
ic_hourly.parquet is reproduced value for value; the interim caches that script kept are dropped).

OUTPUT processed/ic_hourly.parquet, long format, one row per hour (2016-01-01 to END) and link: startTime, link,
zone, price_gbp_mwh, import_cap_mw, export_cap_mw, import_cap_full_mw, export_cap_full_mw, cap_filled, loss,
cap_source (entsoe_ntc | nordpool), import_bid_gbp_mwh, export_wtp_gbp_mwh. Hours without a price are dropped.
READ BY the merit-order model and `modelinputs`.
RUN    python -m gbpowerdata.build.interconnector_capacity
"""
from __future__ import annotations

import argparse
import sys

import numpy as np
import pandas as pd

from gbpowerdata import config as cfg

OUT = "ic_hourly.parquet"
RATED = "ic_rated_capacity.csv"
START, END = "2016-01-01", "2026-07-20"   # the hourly spine the table is built on
FILL_DAYS = 30                            # fill_unpublished: the window either side of a gap

# Annual-average fallback where the daily ECB file is absent or starts later. These match the ECB's annual means
# for 2016-2024; 2025-27 were estimates, 2-3% off the realised daily mean, one reason the daily series is preferred.
EUR_GBP_ANNUAL = {2015: 0.7260, 2016: 0.8195, 2017: 0.8767, 2018: 0.8847, 2019: 0.8778,
                  2020: 0.8897, 2021: 0.8596, 2022: 0.8528, 2023: 0.8698, 2024: 0.8466,
                  2025: 0.8568, 2026: 0.8658, 2027: 0.8658}

# link -> (price zone, capacity source, loss, first power). The capacity source is an ENTSO-E zone (A61) or
# "NORDPOOL" (N2EX day-ahead capacity). The first power must be the earliest in-service date of the link's cables
# in the rated table (checked in build).
LINKS = {
    "IFA_ElecLink_IFA2": ("fr", "FR", 0.02, "2016-01-01"),
    "BritNed": ("nl", "NL", 0.03, "2016-01-01"),
    "Nemo": ("be", "BE", 0.025, "2019-01-31"),
    "Ireland": ("ie", "IE", 0.02, "2016-01-01"),
    "NSL": ("no2", "NORDPOOL", 0.05, "2021-10-01"),
    "Viking": ("dk1", "DK1", 0.05, "2023-12-29"),
}


def load_fx(idx: pd.DatetimeIndex) -> pd.Series:
    """Daily ECB EUR->GBP on `idx`, forward-filled across non-publication days; the annual means where the daily
    file is absent or does not reach back far enough."""
    f = cfg.raw_dir() / "ecb_fx" / "eur_gbp_daily.csv"
    if not f.exists():
        print("  WARNING no daily FX file; falling back to annual averages")
        return pd.Series(idx.year, index=idx).map(EUR_GBP_ANNUAL).ffill().bfill()
    d = pd.read_csv(f)
    d["date"] = pd.to_datetime(d["date"], utc=True)
    s = (d.set_index("date")["eur_gbp"].astype(float).sort_index()
         .reindex(pd.date_range(d["date"].min(), max(d["date"].max(), idx.max()), freq="D", tz="UTC"))
         .ffill())
    r = pd.Series(s.reindex(idx.floor("D")).to_numpy(), index=idx)
    if r.isna().any():
        r = r.fillna(pd.Series(idx.year, index=idx).map(EUR_GBP_ANNUAL))
    return r


def load_price(zone: str) -> pd.Series:
    """The zone's hourly day-ahead price in GBP/MWh (rounded to 2), from ENTSO-E's pull."""
    folder = cfg.raw_dir() / "entsoe" / "dayahead_prices"
    f = folder / f"{zone}_dayahead_prices_2016_2027.csv"
    if not f.exists():
        raise FileNotFoundError(f"no day-ahead prices for {zone} in {folder} (python -m gbpowerdata.pull.entsoe_pull)")
    d = pd.read_csv(f)
    # The files mix "YYYY-MM-DD HH:MM:SS+00:00" with "T" separators; a strict format once truncated DK1 at Dec 2017.
    d["t"] = pd.to_datetime(d["deliveryStart"], utc=True, format="ISO8601")
    s = d.set_index("t")["price_eur_mwh"].resample("1h").mean().dropna()
    return (s * load_fx(s.index)).round(2)


def load_capacity() -> tuple[pd.DataFrame, pd.DataFrame]:
    """ENTSO-E's forecast transfer capacity into GB and out of GB, hourly, one column per neighbouring zone."""
    f = cfg.raw_dir() / "entsoe" / "capacity" / "gb_interconnector_capacity_2016_2027.csv"
    if not f.exists():
        raise FileNotFoundError(f"no ENTSO-E capacity file {f} (python -m gbpowerdata.pull.entsoe_capacity_pull)")
    c = pd.read_csv(f)
    c["t"] = pd.to_datetime(c["deliveryStart"], utc=True, format="%Y-%m-%d %H:%M:%S%z")
    imp = c[c.toZone == "GB"].pivot_table(index="t", columns="fromZone", values="capacity_mw", aggfunc="mean")
    exp = c[c.fromZone == "GB"].pivot_table(index="t", columns="toZone", values="capacity_mw", aggfunc="mean")
    return imp, exp


def load_nordpool_capacity() -> tuple[pd.Series, pd.Series]:
    """NSL's day-ahead capacity: Nord Pool's N2EX capacity product for area UK against NO2 (import into GB, export
    from it), hourly from September 2021. It carries the link's first months at about 700 MW and Norway's 2022
    export restrictions (mean 1,044 MW that year)."""
    folder = cfg.raw_dir() / "nordpool" / "capacity"
    files = sorted(folder.glob("n2ex_capacity_uk_nsl_*.csv"))
    if not files:
        raise FileNotFoundError(f"no Nord Pool NSL capacity under {folder} (python -m gbpowerdata.pull.nordpool_pull)")
    d = pd.concat([pd.read_csv(f) for f in files], ignore_index=True)
    d = d[d["counterpartyArea"] == "NO2"].copy()
    d["t"] = pd.to_datetime(d["deliveryStart"], utc=True, format="ISO8601")
    d = d.drop_duplicates("t", keep="last").set_index("t").sort_index()
    return d["import_capacity_mw"].astype(float), d["export_capacity_mw"].astype(float)


def fill_unpublished(s: pd.Series, days: int = FILL_DAYS) -> tuple[pd.Series, pd.Series]:
    """Hours the source left unpublished (NaN) filled with the median of the capacity published within `days`
    either side of each gap (the series' median where that window is empty); returns the filled series and the
    mask of filled hours."""
    pub = s.copy()
    miss = pub.isna()
    out = pub.copy()
    if miss.any():
        run = (miss != miss.shift()).cumsum()[miss]
        for _, hrs in run.groupby(run):
            a, b = hrs.index[0], hrs.index[-1]
            w = pub[(pub.index >= a - pd.Timedelta(days=days)) & (pub.index <= b + pd.Timedelta(days=days))].dropna()
            out.loc[hrs.index] = w.median() if len(w) else pub.median()
    return out, miss


def rated_capacity(link: str, idx: pd.DatetimeIndex, rated: pd.DataFrame) -> pd.Series:
    """The link's cables at their ratings from their first day in service (one sourced row per cable): France 2,000
    MW, 3,000 from IFA2 (22 Jan 2021), 4,000 from ElecLink (25 May 2022); Ireland 1,000, 1,504 from Greenlink
    (29 Jan 2025)."""
    r = rated[rated["link"] == link]
    if r.empty:
        raise KeyError(f"no rated capacity for {link} in {RATED}")
    s = pd.Series(0.0, index=idx)
    for _, row in r.iterrows():
        s[idx >= pd.Timestamp(row["in_service_from"], tz="UTC")] += float(row["rated_mw"])
    return s


def build(start: str = START, end: str = END) -> pd.DataFrame:
    """The table for every link on the hourly spine `start`..`end`, written to processed/."""
    imp_cap, exp_cap = load_capacity()
    np_imp, np_exp = load_nordpool_capacity()
    rated = pd.read_csv(cfg.reference_dir() / RATED)
    idx = pd.date_range(start, end, freq="1h", tz="UTC")

    out = []
    for link, (zone, capzone, loss, live) in LINKS.items():
        praw = load_price(zone)
        cov = praw.reindex(idx).notna().mean()
        print(f"  {link:<20} {zone.upper():<4} price coverage {100 * cov:5.1f}% "
              f"({praw.index.min().date()} to {praw.index.max().date()})")
        if cov < 0.5:
            print(f"    WARNING low coverage for {zone.upper()} - check the source file")
        p = praw.reindex(idx)
        live_ts = pd.Timestamp(live, tz="UTC")
        first = pd.Timestamp(rated.loc[rated["link"] == link, "in_service_from"].min(), tz="UTC")
        if first != live_ts:
            raise ValueError(f"{link}: first power {live_ts.date()} but {RATED} starts {first.date()}")

        if capzone == "NORDPOOL":
            ci, ce = np_imp.reindex(idx), np_exp.reindex(idx)
            src = "nordpool"
        else:
            if capzone not in imp_cap.columns:     # no silent nameplate fallback for a border in the pull
                raise KeyError(f"{link}: no ENTSO-E capacity for {capzone} in the capacity pull")
            ci = imp_cap[capzone].reindex(idx)
            ce = exp_cap[capzone].reindex(idx) if capzone in exp_cap.columns else ci
            src = "entsoe_ntc"
        ci, filled_i = fill_unpublished(ci)
        ce, filled_e = fill_unpublished(ce)

        off = idx < live_ts                      # before first power the link does not exist
        ci, ce = ci.where(~off, 0.0), ce.where(~off, 0.0)
        ci, ce = ci.fillna(0.0).clip(lower=0), ce.fillna(0.0).clip(lower=0)
        full = rated_capacity(link, idx, rated)

        out.append(pd.DataFrame({
            "startTime": idx, "link": link, "zone": zone.upper(),
            "price_gbp_mwh": p.to_numpy(),
            "import_cap_mw": ci.to_numpy(), "export_cap_mw": ce.to_numpy(),
            "import_cap_full_mw": np.maximum(full.to_numpy(), ci.to_numpy()),
            "export_cap_full_mw": np.maximum(full.to_numpy(), ce.to_numpy()),
            "cap_filled": ((filled_i | filled_e) & ~off).to_numpy(),
            "loss": loss, "cap_source": src,
        }))

    d = pd.concat(out, ignore_index=True).dropna(subset=["price_gbp_mwh"])
    d["import_bid_gbp_mwh"] = (d["price_gbp_mwh"] / (1 - d["loss"])).round(2)
    d["export_wtp_gbp_mwh"] = (d["price_gbp_mwh"] * (1 - d["loss"])).round(2)

    out_path = cfg.processed_dir() / OUT
    out_path.parent.mkdir(parents=True, exist_ok=True)
    d.to_parquet(out_path, index=False)
    print(f"wrote {out_path} ({len(d):,} rows)\n")

    s = (d[d.import_cap_mw > 0].groupby(["link", "zone", "cap_source"])
         .agg(hours=("startTime", "size"), price_mean=("price_gbp_mwh", "mean"),
              price_neg_pct=("price_gbp_mwh", lambda x: 100 * (x < 0).mean()),
              imp_cap_mean=("import_cap_mw", "mean"), imp_cap_max=("import_cap_mw", "max"),
              exp_cap_mean=("export_cap_mw", "mean"), imp_full_mean=("import_cap_full_mw", "mean"),
              filled_pct=("cap_filled", lambda x: 100 * x.mean())).round(1))
    print(s.to_string())
    tot = d[d.import_cap_mw > 0].groupby("startTime")["import_cap_mw"].sum()
    print(f"\ntotal GB import capacity: mean {tot.mean():.0f} MW, max {tot.max():.0f} MW "
          f"(2025 mean {tot[tot.index.year == 2025].mean():.0f} MW)")
    return d


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--end", default=END, help=f"last day of the hourly spine (default {END})")
    a = ap.parse_args(argv)
    build(end=a.end)
    return 0


if __name__ == "__main__":
    sys.exit(main())
