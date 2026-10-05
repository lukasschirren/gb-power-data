"""Daily EUR->GBP FX (ECB reference rate) + a reusable converter for EUR series.

Why: the ENTSO-E day-ahead prices (NO2/NO1/DK1/SE3/FR/BE/NL/IE) are in EUR/MWh,
while the N2EX/GB prices are GBP/MWh. To compare them — or to compute the
interconnector price spread that drives GB import/export — they must be on one
currency. Best-practice conversion for day-ahead electricity:

  * Source: the ECB euro foreign-exchange **reference rate** (the daily ~14:15 CET
    fixing), series D.GBP.EUR.SP00.A from the ECB Data Portal. This is the
    canonical, citable rate the whole European market settles against; going to
    the ECB directly avoids the flaky third-party wrappers (frankfurter.app was
    returning 520s). OBS_VALUE is GBP per 1 EUR, so price_gbp = price_eur * rate.
  * Granularity: **daily**, not monthly. A monthly mean smears out exactly the
    day-to-day FX moves that sit inside the spread signal.
  * Non-trading days: the ECB publishes only on TARGET business days, but power is
    delivered 365 days/year. We **forward-fill** the last published rate onto
    weekends/holidays — that is the rate a trader would actually have had locked
    in for the next-day auction.
  * Date alignment: by default we map the rate onto the **CET delivery date**
    (bidding zones run on CET day boundaries). The day-ahead auction actually
    clears on D-1, so `align="trade"` (shift one day) is offered for robustness
    checks; the difference is tiny (EUR/GBP rarely moves >0.5%/day) versus the
    electricity spread, so delivery-date is the sane default.

Free, no key. Raw daily table cached to data/raw/ecb_fx/eur_gbp_daily.csv.

Usage (CLI just refreshes the cached table):
  python -m gbpowerdata.pull.fx_pull --start 2016 --end 2027

As a library:
  from gbpowerdata.pull.fx_pull import to_gbp
  df = to_gbp(df, eur_col="price_eur_mwh", out_col="price_gbp_mwh")
"""

from __future__ import annotations

import argparse
import io
import sys
from datetime import datetime, timezone

import pandas as pd
import requests

from gbpowerdata import config as cfg

ECB_URL = "https://data-api.ecb.europa.eu/service/data/EXR/D.GBP.EUR.SP00.A"
UA = {"User-Agent": "Mozilla/5.0"}
OUT = cfg.raw_dir() / "ecb_fx"
FX_CSV = OUT / "eur_gbp_daily.csv"
MARKET_TZ = "Europe/Brussels"  # CET/CEST — the day-ahead delivery-date boundary


def pull_fx(start_year: int, end_year: int) -> pd.DataFrame:
    """Fetch daily ECB EUR->GBP (GBP per EUR) and cache to FX_CSV. Returns it."""
    r = requests.get(ECB_URL, headers=UA, timeout=90,
                     params={"startPeriod": f"{start_year}-01-01",
                             "endPeriod": f"{end_year - 1}-12-31",
                             "format": "csvdata"})
    r.raise_for_status()
    raw = pd.read_csv(io.StringIO(r.text))
    df = (raw.rename(columns={"TIME_PERIOD": "date", "OBS_VALUE": "eur_gbp"})
             [["date", "eur_gbp"]]
             .assign(date=lambda d: pd.to_datetime(d["date"]))
             .dropna()
             .sort_values("date")
             .reset_index(drop=True))
    OUT.mkdir(parents=True, exist_ok=True)
    df.to_csv(FX_CSV, index=False)
    print(f"Saved {len(df):,} daily ECB EUR->GBP rates "
          f"({df['date'].min().date()} -> {df['date'].max().date()}) -> {FX_CSV}",
          flush=True)
    return df


def load_daily_fx() -> pd.Series:
    """GBP-per-EUR indexed by every calendar day, forward-filled over non-trading days.

    Pulls once if the cache is missing. The series is reindexed to a continuous
    daily calendar and forward-filled, so any delivery date has a rate.
    """
    if not FX_CSV.exists():
        pull_fx(2016, datetime.now(timezone.utc).year + 1)
    df = pd.read_csv(FX_CSV, parse_dates=["date"])
    s = df.set_index("date")["eur_gbp"].sort_index()
    # Extend a few days past the last publication: the ECB fixing lags ~1 day, so
    # the most recent delivery dates run past it and should carry the last rate
    # forward (as a trader would) rather than go NaN.
    full = pd.date_range(s.index.min() - pd.Timedelta(days=5),
                         s.index.max() + pd.Timedelta(days=10), freq="D")
    # ffill covers weekends/holidays + that trailing edge; bfill only reaches the
    # ≤3 leading calendar days before the year's first ECB publication (e.g. 1-3
    # Jan) with the nearest rate — otherwise those delivery hours would be NaN.
    return s.reindex(full).ffill().bfill()


def to_gbp(df: pd.DataFrame, eur_col: str, out_col: str = "price_gbp_mwh",
           ts_col: str = "deliveryStart", align: str = "delivery",
           keep_rate: bool = False) -> pd.DataFrame:
    """Add a GBP column to a EUR-priced frame using the daily ECB reference rate.

    ts_col is a timezone-aware (UTC) delivery-start timestamp. The rate is matched
    on the CET delivery date; align="trade" uses the prior day (auction date).
    Rows whose date falls outside the FX coverage get NaN (never silently zero).
    """
    if align not in ("delivery", "trade"):
        raise ValueError("align must be 'delivery' or 'trade'")
    fx = load_daily_fx()

    ts = pd.to_datetime(df[ts_col], utc=True).dt.tz_convert(MARKET_TZ)
    key = ts.dt.normalize().dt.tz_localize(None)
    if align == "trade":
        key = key - pd.Timedelta(days=1)

    rate = key.map(fx)  # fx is indexed by naive daily Timestamps
    out = df.copy()
    out[out_col] = (out[eur_col] * rate).astype(float)
    if keep_rate:
        out["eur_gbp"] = rate.values
    return out


def main(argv: list[str]) -> None:
    p = argparse.ArgumentParser(description="Refresh the cached daily ECB EUR->GBP table.")
    p.add_argument("--start", type=int, default=2016, help="first year (inclusive)")
    p.add_argument("--end", type=int, default=datetime.now(timezone.utc).year + 1,
                   help="year AFTER the last (exclusive)")
    args = p.parse_args(argv[1:])
    pull_fx(args.start, args.end)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
