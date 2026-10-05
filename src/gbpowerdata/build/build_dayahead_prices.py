"""Build per-venue and combined GB day-ahead price series on the 30-min model spine.

GB runs three day-ahead auctions relevant here:
  * N2EX (Nord Pool)      — hourly, gate closure ~09:20 GMT
  * EPEX hourly           — hourly, gate closure ~09:20 GMT  (the LIKE-FOR-LIKE
                            counterpart to N2EX: same product & timing; the two
                            were an identical coupled price until GB left SDAC end-2020)
  * EPEX half-hourly (hh) — 30-min, gate closure 15:30 GMT  (a LATER, separate
                            auction for post-hourly balancing — NOT N2EX-comparable)

So the combined GB day-ahead file pairs N2EX with EPEX **hourly**; EPEX **hh** is kept
as its own series (still useful — it is natively on the 30-min settlement spine).

Outputs (data/processed/, one file per year, mirroring mid_target_{year}.csv):
  separate, per venue:
    dayahead_price_n2ex_{year}.csv         startTime, price_gbp_per_mwh, native_granularity
    dayahead_price_epex_hourly_{year}.csv  "
    dayahead_price_epex_hh_{year}.csv      "
  combined (wide, the two like-for-like morning auctions):
    dayahead_price_gb_{year}.csv           startTime, n2ex_gbp_per_mwh,
                                           epex_hourly_gbp_per_mwh, spread_epex_minus_n2ex

Conventions & modelling choices:
  * Spine = UTC calendar-year half-hourly (same index as mid_target: 17 520 rows,
    17 568 in a leap year). Full spine written; uncovered half-hours stay NaN.
  * N2EX and EPEX-hourly are natively HOURLY -> upsampled to half-hourly by repeating
    each hourly price across both half-hours (the rule stage2_build_timeseries already
    uses). native_granularity records this so the imputation is never implicit.
  * EPEX-hh is natively half-hourly.
  * All venues are GBP/MWh, so the combined file needs no FX.
  * Coverage: N2EX 2016-2025, EPEX (both) 2020-2025. Pre-2020 combined rows carry
    N2EX with an empty EPEX column (no EPEX file written for those years).

Usage:
  python -m gbpowerdata.build.build_dayahead_prices 2023          # one year
  python -m gbpowerdata.build.build_dayahead_prices 2016 2025     # inclusive range
  python -m gbpowerdata.build.build_dayahead_prices               # all covered years
"""

from __future__ import annotations

import sys

import pandas as pd

from gbpowerdata import config as cfg

RAW = cfg.raw_dir()
HALF_HOUR = pd.Timedelta(minutes=30)
# A venue counts as "present" in a year if it has more than one delivery day of data.
# This excludes only the ~2 half-hours a neighbouring year's file bleeds across the
# UTC/CET boundary, WITHOUT discarding a genuinely partial year (mid-year launch/retire).
MIN_YEAR_ROWS = 48


def _present(s: pd.Series) -> bool:
    return s.notna().sum() > MIN_YEAR_ROWS

# (raw glob, price column, upsample-hourly?, native_granularity label)
VENUES = {
    "n2ex":        ("nordpool/n2ex_prices_n2ex_*.csv",                    "price",         True,  "hourly"),
    "epex_hourly": ("epex/great-britain/epex_gb_dayahead_hourly_prices_*.csv", "price_gbp_mwh", True,  "hourly"),
    "epex_hh":     ("epex/great-britain/epex_gb_dayahead_hh_prices_*.csv",     "price_gbp_mwh", False, "half-hourly"),
}


def _year_spine(year: int) -> pd.DatetimeIndex:
    """UTC half-hourly index for the calendar year (matches mid_target_{year})."""
    return pd.date_range(f"{year}-01-01", f"{year + 1}-01-01", freq="30min",
                         tz="UTC", inclusive="left", name="startTime")


def _load_venue(glob: str, col: str, upsample: bool) -> pd.Series:
    """Load a raw price series as a half-hourly UTC series (GBP/MWh).

    Hourly venues are upsampled by placing each value on its :00 AND :30 half-hour
    explicitly (no ffill, so genuine gaps cannot bleed across hours)."""
    # Oldest-written first so that if several span-named files overlap (e.g. a re-pull
    # with a wider --end), keep="last" lets the most recently written file's value win
    # on shared timestamps (correct for EPEX/N2EX restatements) rather than the older one.
    files = sorted(RAW.glob(glob), key=lambda p: p.stat().st_mtime)
    if not files:
        return pd.Series(dtype=float)
    df = pd.concat([pd.read_csv(f, usecols=["deliveryStart", col]) for f in files],
                   ignore_index=True)
    df["startTime"] = pd.to_datetime(df["deliveryStart"], utc=True)
    s = (df.dropna(subset=[col]).drop_duplicates("startTime", keep="last")
           .set_index("startTime")[col].sort_index())
    if upsample:
        s = pd.concat([s, s.set_axis(s.index + HALF_HOUR)])
        s = s[~s.index.duplicated()].sort_index()
    return s


# Traded-capacity (cleared-volume) sources for the volume-weighted blend of the two like-for-like
# morning auctions. N2EX cleared volume from the processed bid panel; EPEX hourly cleared volume
# from the SFTP pull (auction_spot_volumes_* -> epex_gb_dayahead_hourly_volumes_*.csv). Both are
# hourly and upsampled to half-hourly the same way as the prices.
VOLUME_SOURCES = {
    "n2ex": (cfg.processed_dir(), "n2ex_bid_panel_*.csv", "cleared_volume_mw"),
    "epex": (RAW / "epex" / "great-britain", "epex_gb_dayahead_hourly_volumes_*.csv", "volume_mwh"),
}


def _load_volume(key: str) -> pd.Series:
    """Cleared volume (MWh/h) for a venue as a half-hourly UTC series; empty if absent."""
    base, glob, vcol = VOLUME_SOURCES[key]
    files = sorted(base.glob(glob), key=lambda p: p.stat().st_mtime)
    if not files:
        return pd.Series(dtype=float)
    df = pd.concat([pd.read_csv(f, usecols=["deliveryStart", vcol]) for f in files],
                   ignore_index=True)
    df["startTime"] = pd.to_datetime(df["deliveryStart"], utc=True)
    s = (df.dropna(subset=[vcol]).drop_duplicates("startTime", keep="last")
           .set_index("startTime")[vcol].astype(float).sort_index())
    s = pd.concat([s, s.set_axis(s.index + HALF_HOUR)])       # hourly -> half-hourly
    return s[~s.index.duplicated()].sort_index()


def _blend(n_p: pd.Series, e_p: pd.Series, v_n: pd.Series, v_e: pd.Series) -> pd.Series:
    """Traded-capacity-weighted composite of the N2EX and EPEX-hourly day-ahead prices:
        P = (P_n2ex*V_n2ex + P_epex*V_epex) / (V_n2ex + V_epex)
    weighting each venue's price by its cleared volume that half-hour. A venue contributes only
    where BOTH its price and volume exist; where volumes are absent but a price exists (e.g. pre-
    2018 N2EX, before the bid panel) the simple mean of the present prices is used as a fallback,
    so the blend is defined on the whole spine. Pre-2020 (no EPEX) the blend is just N2EX."""
    w_n = v_n.where(n_p.notna())
    w_e = v_e.where(e_p.notna())
    num = (n_p * w_n).fillna(0.0) + (e_p * w_e).fillna(0.0)
    den = w_n.fillna(0.0) + w_e.fillna(0.0)
    blend = (num / den).where(den > 0)
    return blend.fillna(pd.concat([n_p, e_p], axis=1).mean(axis=1))


def _covered_years(*series: pd.Series) -> list[int]:
    """Years where at least one venue genuinely operated (>=50% of the year).

    Excludes the boundary-only year a CET-delivered series bleeds into (N2EX's raw
    span starts 2015-12-31 23:00 UTC, i.e. 2 half-hours in the 2015 UTC spine)."""
    candidates: set[int] = set()
    for s in series:
        if not s.empty:
            candidates.update(range(s.index.min().year, s.index.max().year + 1))
    return [y for y in sorted(candidates)
            if any((not s.empty) and _present(s.reindex(_year_spine(y))) for s in series)]


def build(year: int, venues: dict[str, pd.Series],
          volumes: dict[str, pd.Series] | None = None) -> None:
    spine = _year_spine(year)
    onspine = {k: s.reindex(spine) for k, s in venues.items()}
    vol = {k: s.reindex(spine) for k, s in (volumes or {}).items()}
    proc = cfg.processed_dir()

    # Separate per-venue files whenever the venue has real data that year (see
    # _present: >1 delivery day, so the 2 boundary half-hours are excluded but a
    # genuinely partial year is kept).
    for name, s in onspine.items():
        gran = VENUES[name][3]
        if _present(s):
            pd.DataFrame({"startTime": spine, "price_gbp_per_mwh": s.values,
                          "native_granularity": gran}).to_csv(
                proc / f"dayahead_price_{name}_{year}.csv", index=False)

    # Combined wide file: the two like-for-like morning auctions (N2EX + EPEX hourly), their cleared
    # volumes, and the traded-capacity-weighted BLEND (the composite GB day-ahead price).
    n, e = onspine["n2ex"], onspine["epex_hourly"]
    v_n = vol.get("n2ex", pd.Series(index=spine, dtype=float))
    v_e = vol.get("epex", pd.Series(index=spine, dtype=float))
    blend = _blend(n, e, v_n, v_e)
    comb = pd.DataFrame({"startTime": spine,
                         "n2ex_gbp_per_mwh": n.values,
                         "epex_hourly_gbp_per_mwh": e.values,
                         "n2ex_volume_mwh": v_n.values,
                         "epex_volume_mwh": v_e.values,
                         "blend_gbp_per_mwh": blend.values})
    comb["spread_epex_minus_n2ex"] = comb["epex_hourly_gbp_per_mwh"] - comb["n2ex_gbp_per_mwh"]
    comb.to_csv(proc / f"dayahead_price_gb_{year}.csv", index=False)

    # Per-venue blend file (venue key "blend"), so the model can target it like any other venue.
    if _present(blend):
        pd.DataFrame({"startTime": spine, "price_gbp_per_mwh": blend.values,
                      "native_granularity": "hourly"}).to_csv(
            proc / f"dayahead_price_blend_{year}.csv", index=False)

    n_cov, e_cov = n.notna().mean() * 100, e.notna().mean() * 100
    spread = comb["spread_epex_minus_n2ex"].dropna()
    msg = f"  {year}: {len(spine):,} HH | N2EX {n_cov:5.1f}% GBP{n.mean():7.2f}"
    if _present(e):
        corr = comb["n2ex_gbp_per_mwh"].corr(comb["epex_hourly_gbp_per_mwh"])
        hh_cov = onspine["epex_hh"].notna().mean() * 100
        msg += (f" | EPEXhourly {e_cov:5.1f}% GBP{e.mean():7.2f} | EPEXhh {hh_cov:5.1f}% "
                f"| spread n={len(spread):,} mean GBP{spread.mean():+.2f} "
                f"MAD GBP{spread.abs().mean():.2f} corr {corr:.4f}")
    else:
        msg += " | EPEX none"
    print(msg, flush=True)


def main(argv: list[str]) -> None:
    venues = {k: _load_venue(glob, col, up) for k, (glob, col, up, _) in VENUES.items()}
    volumes = {k: _load_volume(k) for k in VOLUME_SOURCES}
    if len(argv) == 2:
        years = [int(argv[1])]
    elif len(argv) >= 3:
        years = list(range(int(argv[1]), int(argv[2]) + 1))
    else:
        years = _covered_years(*venues.values())
    print(f"Building GB day-ahead price series for {years}", flush=True)
    for y in years:
        build(y, venues, volumes)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
