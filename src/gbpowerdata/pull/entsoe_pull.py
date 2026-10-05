"""Pull NO2 (south Norway) day-ahead prices from the ENTSO-E Transparency Platform.

Why this and not Nord Pool: the paid Nord Pool marketdata credentials are
entitled to the UK area only (every Nordic/EU area returns 403 "Missing access").
The N2EX flow record shows the only post-Brexit GB coupling is North Sea Link to
NO2, so the NO2 day-ahead price is the counterparty price for that interconnector.
ENTSO-E publishes it for free (EUR/MWh, hourly) back to ~2015.

Requires a free ENTSO-E API security token (per account). Getting one:
  1. register at https://transparency.entsoe.eu/
  2. email transparency@entsoe.eu from the registered address, subject
     "Restful API access", asking for API access; they enable it (usually <1 day)
  3. token appears under Account Settings -> "Web Api Security Token"
Provide it via:
  - env var  ENTSOE_TOKEN=<token>, or
  - file     data/reference/entsoe_token.txt   (gitignored)

Document type A44 = day-ahead prices; for prices in_Domain == out_Domain. NO2's
EIC area code is 10YNO-2--------T. The API caps a single request at one year, so
we loop per calendar year and cache the raw XML under
  data/raw/entsoe/dayahead_prices/by_year/<area>_<year>.xml
then parse all cached years into
  data/raw/entsoe/dayahead_prices/<area>_dayahead_prices_<start>_<end>.csv
Re-runs reuse the cache (a completed year is never re-fetched), matching the
flows/curves per-period-cache pattern in nordpool_pull.py.

Usage:
  python -m gbpowerdata.pull.entsoe_pull --start 2016 --end 2026
  python -m gbpowerdata.pull.entsoe_pull --start 2023 --end 2024 --area NO2
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from xml.etree import ElementTree as ET

import pandas as pd
import requests

from gbpowerdata import config as cfg

API = "https://web-api.tp.entsoe.eu/api"
OUT = cfg.raw_dir() / "entsoe" / "dayahead_prices"
SLEEP_S = 1.0

# ENTSO-E EIC area codes. NO2 is the North Sea Link counterparty; others are here
# so the same puller can grab another bidding zone without code changes.
AREAS = {
    "NO2": "10YNO-2--------T",
    "NO1": "10YNO-1--------2",
    "DK1": "10YDK-1--------W",
    "SE3": "10Y1001A1001A46L",
    # GB interconnector counterparty zones (FR: IFA/IFA2/ElecLink, BE: Nemo,
    # NL: BritNed, IE-SEM: Moyle/EWIC/Greenlink).
    "FR": "10YFR-RTE------C",
    "BE": "10YBE----------2",
    "NL": "10YNL----------L",
    "IE": "10Y1001A1001A59C",  # IE(SEM) single bidding zone (RoI + NI)
}


def get_token() -> str:
    tok = os.environ.get("ENTSOE_TOKEN")
    if tok:
        return tok.strip()
    f = cfg.reference_dir() / "entsoe_token.txt"
    if f.exists():
        return f.read_text(encoding="utf-8").strip()
    sys.exit("No ENTSO-E token. Set ENTSOE_TOKEN or create "
             "data/reference/entsoe_token.txt (see module docstring for how to "
             "obtain one).")


def _fetch_year(token: str, eic: str, year: int) -> str:
    """Raw A44 XML for one calendar year (UTC). Raises on HTTP error."""
    params = {
        "securityToken": token,
        "documentType": "A44",
        "in_Domain": eic,
        "out_Domain": eic,
        "periodStart": f"{year}01010000",
        "periodEnd": f"{year + 1}01010000",
    }
    r = requests.get(API, params=params, timeout=180)
    r.raise_for_status()
    return r.text


# A44 responses use the publicationdocument namespace; the version is embedded in
# the root tag, so strip namespaces rather than hardcode one.
def _strip_ns(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


_RESOLUTION = {"PT60M": timedelta(hours=1), "PT30M": timedelta(minutes=30),
               "PT15M": timedelta(minutes=15)}


def _parse_xml(xml: str) -> list[dict]:
    """Flatten one A44 document to rows [deliveryStart(UTC), price_eur_mwh].

    ENTSO-E gives positional points within each Period; curveType A03 omits
    repeated values, so a missing position carries the previous price forward
    until the next stated position (standard sparse-curve handling).
    """
    root = ET.fromstring(xml.encode("utf-8"))
    # An Acknowledgement document (no data / error) has no TimeSeries.
    if _strip_ns(root.tag).startswith("Acknowledgement"):
        reason = " ".join(e.text or "" for e in root.iter()
                          if _strip_ns(e.tag) == "text")
        raise RuntimeError(f"ENTSO-E returned no data: {reason.strip()}")

    rows = []
    for ts in root.iter():
        if _strip_ns(ts.tag) != "TimeSeries":
            continue
        for period in ts:
            if _strip_ns(period.tag) != "Period":
                continue
            start, res = None, None
            points = []
            for child in period:
                name = _strip_ns(child.tag)
                if name == "timeInterval":
                    for ti in child:
                        if _strip_ns(ti.tag) == "start":
                            start = datetime.strptime(ti.text, "%Y-%m-%dT%H:%MZ") \
                                .replace(tzinfo=timezone.utc)
                elif name == "resolution":
                    res = _RESOLUTION.get(child.text)
                elif name == "Point":
                    pos = price = None
                    for p in child:
                        pn = _strip_ns(p.tag)
                        if pn == "position":
                            pos = int(p.text)
                        elif pn in ("price.amount", "price_amount"):
                            price = float(p.text)
                    if pos is not None and price is not None:
                        points.append((pos, price))
            if start is None or res is None or not points:
                continue
            points.sort()
            last_pos = points[-1][0]
            filled, cur, i = [], None, 0
            for pos in range(1, last_pos + 1):
                if i < len(points) and points[i][0] == pos:
                    cur = points[i][1]
                    i += 1
                filled.append(cur)  # carry forward for sparse (A03) curves
            for idx, price in enumerate(filled):
                rows.append({"deliveryStart": start + res * idx,
                             "price_eur_mwh": price})
    return rows


def pull(area: str, start_year: int, end_year: int) -> None:
    eic = AREAS[area]
    token = get_token()
    ydir = OUT / "by_year"
    ydir.mkdir(parents=True, exist_ok=True)
    tag = area.lower()

    now_year = datetime.now(timezone.utc).year
    for year in range(start_year, end_year):
        cache = ydir / f"{tag}_{year}.xml"
        # Never cache the in-progress year: it is incomplete and must be refetched.
        if cache.exists() and year < now_year:
            continue
        try:
            xml = _fetch_year(token, eic, year)
        except requests.HTTPError as e:
            body = e.response.text[:200] if e.response is not None else ""
            print(f"  skip {year}: {e} {body}", flush=True)
            continue
        cache.write_text(xml, encoding="utf-8")
        try:
            n = len(_parse_xml(xml))
            print(f"  {area} {year}: {n:,} points -> {cache.name}", flush=True)
        except RuntimeError as e:
            print(f"  {area} {year}: {e}", flush=True)
            cache.unlink(missing_ok=True)  # don't cache an empty/error doc
        time.sleep(SLEEP_S)

    # Rebuild the combined CSV from every cached year in range.
    rows = []
    for year in range(start_year, end_year):
        cache = ydir / f"{tag}_{year}.xml"
        if cache.exists():
            try:
                rows.extend(_parse_xml(cache.read_text(encoding="utf-8")))
            except RuntimeError:
                pass
    df = pd.DataFrame(rows)
    if not df.empty:
        df["deliveryStart"] = pd.to_datetime(df["deliveryStart"], utc=True)
        df = (df.drop_duplicates("deliveryStart")
                .sort_values("deliveryStart")
                .reset_index(drop=True))
    path = OUT / f"{tag}_dayahead_prices_{start_year}_{end_year}.csv"
    df.to_csv(path, index=False)
    print(f"Saved {len(df):,} price points -> {path}", flush=True)


def main(argv: list[str]) -> None:
    p = argparse.ArgumentParser(
        description="Pull day-ahead prices from ENTSO-E (free; NO2 by default).")
    p.add_argument("--area", default="NO2", choices=sorted(AREAS))
    p.add_argument("--start", type=int, default=2016, help="first year (inclusive)")
    p.add_argument("--end", type=int, default=2026, help="year AFTER the last (exclusive)")
    args = p.parse_args(argv[1:])
    print(f"{args.area} day-ahead {args.start} -> {args.end - 1}", flush=True)
    pull(args.area, args.start, args.end)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
