"""Pull the CASH-OUT prices: Elexon's system sell and buy price and the net imbalance volume of
every settlement period, as published on BMRS.

Why: the repo held the day-ahead auctions, the intraday auctions, the continuous trades and the
market index, but not the price that settles whatever a party did not trade: the imbalance
(cash-out) price. It is the outside option of every intraday trade (a seller who does not trade
is paid it, a buyer who does not trade pays it), so an intraday price has no anchor without it,
and the net imbalance volume says in which direction the system was out of balance.

Source: Elexon Insights  /balancing/settlement/system-prices/{settlementDate}   (free, no key)
  One request per settlement date returns one row per settlement period (48, or 46 and 50 on the
  clock-change days), each with its UTC `startTime`:
    systemSellPrice, systemBuyPrice   GBP/MWh. One price since BSC modification P305 (5 November
                                      2015): the two are equal in every period of the pull, which
                                      gbpowerdata.build.build_system_prices checks instead of assuming.
    netImbalanceVolume                MWh in the period. Positive = the system was short (NESO
                                      bought more energy than it sold), negative = long.
    reserveScarcityPrice              GBP/MWh, VoLL x LoLP (P305); null when it does not bind.
    priceDerivationCode               Elexon's code for how the price was derived, kept as published.
    totalAccepted{Offer,Bid}Volume    MWh of accepted Balancing Mechanism offers and bids, the
    totalAdjustment{Sell,Buy}Volume   balancing-services adjustment volumes, and their
    totalSystemTagged...              system-tagged parts (removed from the energy price stack).
    sellPriceAdjustment, buyPriceAdjustment, replacementPrice, replacementPriceReferenceVolume,
    bsadDefaulted, createdDateTime
  The rows are those of the calculation BMRS publishes shortly after each period (createdDateTime
  is ~20 minutes after the period ends), not a later settlement run. History from 2016-01-01
  (checked 2 October 2026).

Raw CSVs are per year of settlement date and resumable: an existing file is skipped, except the
current year's, which stops at today and is pulled again in full on every run. A settlement date
is a UK local day, and 1 January and 31 December are in GMT, so a year of settlement dates is
exactly the calendar year in UTC. Days whose request failed after the retries are listed at the
end of the year and tried once more; any still missing are printed and left out (the build step
reports the coverage).

Output: data/raw/system_prices/system_prices_{year}.csv

Usage:
  python -m gbpowerdata.pull.system_price_pull                      # 2016-2025
  python -m gbpowerdata.pull.system_price_pull --start 2023 --end 2023
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import requests

from gbpowerdata import config as cfg

BASE_URL = "https://data.elexon.co.uk/bmrs/api/v1"
OUT = cfg.raw_dir() / "system_prices"


def _get(url: str, params: dict, tries: int = 6, timeout: int = 90) -> dict:
    for k in range(tries):
        try:
            r = requests.get(url, params=params, timeout=timeout)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(2 ** k)
                continue
            r.raise_for_status()
        except requests.RequestException:
            time.sleep(2 ** k)
    raise RuntimeError(f"failed after {tries} tries: {url} {params}")


def _day_rows(d: date) -> list[dict]:
    return _get(f"{BASE_URL}/balancing/settlement/system-prices/{d:%Y-%m-%d}", {"format": "json"}).get("data", [])


def settlement_dates(year: int, today: date) -> list[date]:
    """The settlement dates of `year`, up to and including `today`."""
    last = min(date(year, 12, 31), today)
    n = (last - date(year, 1, 1)).days + 1
    return [date(year, 1, 1) + timedelta(days=i) for i in range(max(n, 0))]


def pull(start: int, end: int, sleep_s: float = 0.1) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).date()
    for year in range(start, end + 1):
        out = OUT / f"system_prices_{year}.csv"
        if out.exists() and year < today.year:                  # the current year is never complete
            print(f"[system prices {year}] exists, skip", flush=True)
            continue
        rows: list[dict] = []
        failed: list[date] = []
        t0 = time.time()
        for n_days, d in enumerate(settlement_dates(year, today), 1):
            try:
                rows.extend(_day_rows(d))
            except RuntimeError:
                failed.append(d)
            if n_days % 60 == 0:
                print(f"  [system prices {year}] {n_days} days, {len(rows)} rows, {time.time() - t0:.0f}s", flush=True)
            time.sleep(sleep_s)
        missing = []
        for d in failed:                                         # one more pass over the failed days
            try:
                rows.extend(_day_rows(d))
            except RuntimeError as e:
                missing.append(d)
                print(f"  ! system prices {d}: {e}", flush=True)
        df = pd.DataFrame(rows)
        if df.empty:                                             # nothing published: write nothing to cache
            print(f"[system prices {year}] no rows", flush=True)
            continue
        df = df.drop_duplicates(subset=["settlementDate", "settlementPeriod", "createdDateTime"])
        df = df.sort_values(["settlementDate", "settlementPeriod", "createdDateTime"])
        tmp = out.with_suffix(".part.csv")
        df.to_csv(tmp, index=False)
        tmp.replace(out)
        print(f"[system prices {year}] {len(df)} rows, {df['settlementDate'].nunique()} days"
              f"{f', {len(missing)} days missing' if missing else ''} -> {out.name} ({time.time() - t0:.0f}s)", flush=True)


def main(argv: list[str]) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--start", type=int, default=2016)
    p.add_argument("--end", type=int, default=2025)
    a = p.parse_args(argv)
    pull(a.start, a.end)


if __name__ == "__main__":
    main(sys.argv[1:])
