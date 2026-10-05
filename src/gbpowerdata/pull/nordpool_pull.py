"""Pull GB / N2EX day-ahead data from the Nord Pool market data API (PAID).

This is the only paid source. Two products:
  prices  — N2EX day-ahead cleared price (the auction the ABM models; an
            independent validation target alongside Elexon MID).
  curves  — N2EX aggregated supply & demand bid curves: the empirical stack the
            ABM tries to reproduce bottom-up (Stage 2 calibration / Stage 4
            validation). Curves exist ONLY on the hourly N2EX_DayAhead market and
            are large (~tens of thousands of points/day) — raw JSON is kept
            per-day in raw/nordpool/curves/ so re-parsing never re-hits the API.
  flows   — N2EX day-ahead cross-border flows for the UK area (hourly MW, per
            connection). Only covers borders cleared inside the N2EX auction:
            EU-coupled borders up to 2020-12-31, then nothing until 2021-09-28,
            then North Sea Link (NO2) only. See pull_flows() docstring.
  capacity— N2EX day-ahead ATC capacity for the UK area (hourly MW per
            connection, + loss factor & ramping). Same borders/Brexit split as
            flows; this is the NSL(NO2) capacity ceiling. Viking(DK1)/BritNed(NL)/
            Nemo(BE)/IE clear elsewhere -> see entsoe_capacity_pull.py.

Raw layout under data/raw/nordpool/ (gitignored):
  n2ex_prices_<market>_<start>_<end>.csv     one file per pulled range
  curves/<YYYY-MM-DD>.json                   per-day bid curves (~5.8 MB/day)
  flows/by_day/<YYYY-MM-DD>.json             per-day flow cache (Final days only)
  flows/n2ex_flows_uk_eu_coupled_*.csv       era 1: UK in EU market coupling
  flows/n2ex_flows_uk_nsl_*.csv              era 2: North Sea Link (NO2) only
  capacity/by_day/<YYYY-MM-DD>.json          per-day ATC capacity cache
  capacity/n2ex_capacity_uk_eu_coupled_*.csv era 1 capacity / era 2 = ..._nsl_*.csv
  _n2ex_<product>_pull.log                   pull logs
The by_day/ caches make re-runs free on this paid API; the era CSVs are derived
and can always be rebuilt from them by re-running the same command.

Credentials (do NOT hardcode in a publication repo):
  - env NORDPOOL_USER / NORDPOOL_PASS, or
  - data/reference/nordpool_credentials.txt  (line 1 user, line 2 password; gitignored)

Markets:
  N2EX_DayAhead        hourly  (prices + curves)
  GbHalfHour_DayAhead  half-hourly (prices only; matches the 30-min model spine)

Usage:
  python -m gbpowerdata.pull.nordpool_pull prices --start 2023-01-01 --end 2024-01-01
  python -m gbpowerdata.pull.nordpool_pull prices --market GbHalfHour_DayAhead --start 2023-01-01 --end 2024-01-01
  python -m gbpowerdata.pull.nordpool_pull curves --start 2023-01-01 --end 2024-01-01
  python -m gbpowerdata.pull.nordpool_pull flows    --start 2023-01-01 --end 2024-01-01
  python -m gbpowerdata.pull.nordpool_pull capacity --start 2023-01-01 --end 2024-01-01
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import time
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests

from gbpowerdata import config as cfg

TOKEN_URL = "https://sts.nordpoolgroup.com/connect/token"
API = "https://data-api.nordpoolgroup.com"
CLIENT_B64 = base64.b64encode(b"client_marketdata_api:client_marketdata_api").decode()
OUT = cfg.raw_dir() / "nordpool"
SLEEP_S = 0.25


def credentials() -> tuple[str, str]:
    import os
    u, p = os.environ.get("NORDPOOL_USER"), os.environ.get("NORDPOOL_PASS")
    if u and p:
        return u, p
    f = cfg.reference_dir() / "nordpool_credentials.txt"
    if f.exists():
        lines = [ln.strip() for ln in f.read_text(encoding="utf-8").splitlines() if ln.strip()]
        if len(lines) >= 2:
            return lines[0], lines[1]
    sys.exit("No Nord Pool credentials. Set NORDPOOL_USER/NORDPOOL_PASS or create "
             "data/reference/nordpool_credentials.txt")


def get_token(user: str, pwd: str) -> str:
    r = requests.post(TOKEN_URL,
                      data={"grant_type": "password", "scope": "marketdata_api",
                            "username": user, "password": pwd},
                      headers={"Authorization": f"Basic {CLIENT_B64}",
                               "Content-Type": "application/x-www-form-urlencoded"},
                      timeout=60)
    r.raise_for_status()
    return r.json()["access_token"]


def _parse_date(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def _get(url: str, token: str, params: dict):
    r = requests.get(url, params=params, headers={"Authorization": f"Bearer {token}"}, timeout=120)
    r.raise_for_status()
    return r.json()


def pull_prices(start: datetime, end: datetime, market: str, currency: str = "GBP") -> None:
    user, pwd = credentials()
    token = get_token(user, pwd)
    rows, d = [], start
    while d < end:
        ds = d.strftime("%Y-%m-%d")
        try:
            data = _get(f"{API}/api/v2/Auction/Prices/ByAreas", token,
                        {"market": market, "areas": "UK", "currency": currency, "date": ds})
            for area in data:
                for p in area.get("prices", []):
                    rows.append({"deliveryStart": p["deliveryStart"], "deliveryEnd": p["deliveryEnd"],
                                 "price": p["price"], "currency": area.get("currency"),
                                 "unit": area.get("unit")})
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 401:
                token = get_token(user, pwd)
                continue
            print(f"  skip {ds}: {e}", flush=True)
        if d.day == 1:
            print(f"  prices {ds} ... {len(rows):,} points", flush=True)
        d += timedelta(days=1)
        time.sleep(SLEEP_S)

    df = pd.DataFrame(rows)
    if not df.empty:
        df["deliveryStart"] = pd.to_datetime(df["deliveryStart"], utc=True)
        df = df.drop_duplicates("deliveryStart").sort_values("deliveryStart").reset_index(drop=True)
    OUT.mkdir(parents=True, exist_ok=True)
    tag = "n2ex" if market == "N2EX_DayAhead" else "gbhh"
    path = OUT / f"n2ex_prices_{tag}_{start:%Y%m%d}_{end:%Y%m%d}.csv"
    df.to_csv(path, index=False)
    print(f"Saved {len(df):,} price points -> {path}", flush=True)


def pull_curves(start: datetime, end: datetime) -> None:
    """Save raw bid-curve JSON per day (append-only); large."""
    user, pwd = credentials()
    token = get_token(user, pwd)
    cdir = OUT / "curves"
    cdir.mkdir(parents=True, exist_ok=True)
    d = start
    while d < end:
        ds = d.strftime("%Y-%m-%d")
        out = cdir / f"{ds}.json"
        if out.exists():
            d += timedelta(days=1)
            continue
        try:
            data = _get(f"{API}/api/v2/Auction/N2EX_DayAhead/PriceCurves/UK", token, {"date": ds})
            out.write_text(json.dumps(data), encoding="utf-8")
            npos = len(data.get("orderPositions", []))
            print(f"  curves {ds}: {npos} periods -> {out.name}", flush=True)
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 401:
                token = get_token(user, pwd)
                continue
            print(f"  skip {ds}: {e}", flush=True)
        d += timedelta(days=1)
        time.sleep(SLEEP_S)
    print(f"Curves saved under {cdir}", flush=True)


# Brexit split the N2EX flow record in two. UK left EU market coupling after
# 2020-12-31; North Sea Link (NO2) first cleared 2021-09-29. Nothing in between.
BREXIT_LAST_DAY = datetime(2020, 12, 31, tzinfo=timezone.utc)
NSL_FIRST_DAY = datetime(2021, 9, 29, tzinfo=timezone.utc)


def _flow_rows(data: list) -> list[dict]:
    """Flatten one day's Flows response to long rows (one per period x connection)."""
    rows = []
    for area in data:
        if area.get("status") != "Final":
            continue
        for f in area.get("flows") or []:
            for c in f.get("byConnections") or []:
                rows.append({"deliveryStart": f["deliveryStart"],
                             "deliveryEnd": f["deliveryEnd"],
                             "counterpartyArea": c.get("area"),
                             "connection": c.get("connection"),
                             "import_mw": c.get("import"),
                             "export_mw": c.get("export"),
                             "net_mw": c.get("netPosition"),
                             "unit": area.get("unit")})
    return rows


def _write_flow_csv(rows: list[dict], path) -> None:
    df = pd.DataFrame(rows)
    if not df.empty:
        df["deliveryStart"] = pd.to_datetime(df["deliveryStart"], utc=True)
        df = (df.drop_duplicates(["deliveryStart", "counterpartyArea", "connection"])
                .sort_values(["deliveryStart", "counterpartyArea", "connection"])
                .reset_index(drop=True))
    df.to_csv(path, index=False)
    conns = sorted(df["connection"].fillna(df["counterpartyArea"]).unique()) if not df.empty else []
    print(f"  -> {path.name}: {len(df):,} rows, connections={conns}", flush=True)


def pull_flows(start: datetime, end: datetime) -> None:
    """Pull N2EX day-ahead cross-border flows for the UK area (hourly, MW).

    Scope warning — this is NOT all GB interconnectors. It is only the borders
    cleared inside the N2EX day-ahead auction itself:
      to   2020-12-31  UK was in EU market coupling: BE, FR (IFA/IFA2/ElecLink), GB2
      2021-01-01..09-28  nothing (Brexit decoupling; status="Missing")
      from 2021-09-29  NO2 only, i.e. North Sea Link
    Everything else (BritNed, Nemo, Viking, Greenlink, Moyle, EWIC, and post-Brexit
    IFA/IFA2/ElecLink) clears in separate auctions and must come from ENTSO-E/Elexon.

    Flows are from the UK point of view: import is after cable losses, export before.
    Only the hourly N2EX_DayAhead market is supported (GbHalfHour_DayAhead is rejected).

    Raw per-day JSON is cached under flows/by_day/ (same pattern as curves) so a
    re-run of a paid 10-year pull costs nothing. Only Final days are cached;
    Missing/Preliminary days stay uncached so they are retried on the next run.
    Two CSVs are emitted, split at Brexit, since the two eras are not one series.
    """
    user, pwd = credentials()
    token = get_token(user, pwd)
    fdir = OUT / "flows"
    ddir = fdir / "by_day"
    ddir.mkdir(parents=True, exist_ok=True)

    d, fetched, cached = start, 0, 0
    while d < end:
        ds = d.strftime("%Y-%m-%d")
        day_file = ddir / f"{ds}.json"
        if day_file.exists():
            cached += 1
            d += timedelta(days=1)
            continue
        try:
            data = _get(f"{API}/api/v2/Auction/Flows/ByAreas", token,
                        {"market": "N2EX_DayAhead", "areas": "UK", "date": ds})
            # Cache only settled days; a Missing day may become Final later.
            if any(a.get("status") == "Final" for a in data):
                day_file.write_text(json.dumps(data), encoding="utf-8")
                fetched += 1
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 401:
                token = get_token(user, pwd)
                continue
            print(f"  skip {ds}: {e}", flush=True)
        if d.day == 1:
            print(f"  flows {ds} ... {fetched:,} fetched / {cached:,} cached", flush=True)
        d += timedelta(days=1)
        time.sleep(SLEEP_S)
    print(f"Fetched {fetched:,} new days, {cached:,} already cached.", flush=True)

    # Rebuild both era CSVs from the cache covering the requested window.
    pre, post, d = [], [], start
    while d < end:
        day_file = ddir / f"{d:%Y-%m-%d}.json"
        if day_file.exists():
            rows = _flow_rows(json.loads(day_file.read_text(encoding="utf-8")))
            (pre if d <= BREXIT_LAST_DAY else post).extend(rows)
        d += timedelta(days=1)

    if pre:
        _write_flow_csv(pre, fdir / f"n2ex_flows_uk_eu_coupled_{start:%Y%m%d}_20201231.csv")
    if post:
        _write_flow_csv(post, fdir / f"n2ex_flows_uk_nsl_{NSL_FIRST_DAY:%Y%m%d}_{end:%Y%m%d}.csv")
    if not pre and not post:
        print("  no Final flow data in range.", flush=True)


def _capacity_rows(data: list) -> list[dict]:
    """Flatten one day's Capacities response to long rows (one per period x connection).

    import/export capacities are published as two separate per-connection lists;
    merge them on (area, connection) so each row carries both directions plus the
    cable's loss factor and ramping restriction.
    """
    rows = []
    for area in data:
        if area.get("status") != "Available":
            continue
        for cp in area.get("capacities") or []:
            merged: dict = {}
            for direction, key in (("import", "importsByConnection"),
                                   ("export", "exportsByConnection")):
                for c in cp.get(key) or []:
                    k = (c.get("area"), c.get("connection"))
                    m = merged.setdefault(k, {"counterpartyArea": c.get("area"),
                                              "connection": c.get("connection")})
                    m[f"{direction}_capacity_mw"] = c.get("capacity")
                    # lossFactor / ramping are per-connection, same on both sides.
                    m.setdefault("lossFactor", c.get("lossFactor"))
                    m.setdefault("rampingRestriction_mw", c.get("rampingRestriction"))
            for m in merged.values():
                rows.append({"deliveryStart": cp["deliveryStart"],
                             "deliveryEnd": cp["deliveryEnd"],
                             **m, "unit": area.get("unit")})
    return rows


def pull_capacity(start: datetime, end: datetime) -> None:
    """Pull N2EX day-ahead cross-border ATC capacity for the UK area (hourly, MW).

    Same scope and Brexit split as pull_flows (only borders inside the N2EX
    auction): EU-coupled connections up to 2020-12-31, then North Sea Link (NO2)
    only from 2021-09-29. This is the interconnector *capacity* ceiling behind the
    flows — import/export MW per connection, plus loss factor and ramping limit.
    Other GB interconnectors (Viking/DK1, BritNed/NL, Nemo/BE, IE) clear elsewhere;
    their capacity comes from ENTSO-E (see entsoe_capacity_pull.py).
    """
    user, pwd = credentials()
    token = get_token(user, pwd)
    cdir = OUT / "capacity"
    ddir = cdir / "by_day"
    ddir.mkdir(parents=True, exist_ok=True)

    d, fetched, cached = start, 0, 0
    while d < end:
        ds = d.strftime("%Y-%m-%d")
        day_file = ddir / f"{ds}.json"
        if day_file.exists():
            cached += 1
            d += timedelta(days=1)
            continue
        try:
            data = _get(f"{API}/api/v2/Auction/Capacities/ByAreas", token,
                        {"market": "N2EX_DayAhead", "areas": "UK", "date": ds})
            if any(a.get("status") == "Available" for a in data):
                day_file.write_text(json.dumps(data), encoding="utf-8")
                fetched += 1
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 401:
                token = get_token(user, pwd)
                continue
            print(f"  skip {ds}: {e}", flush=True)
        if d.day == 1:
            print(f"  capacity {ds} ... {fetched:,} fetched / {cached:,} cached", flush=True)
        d += timedelta(days=1)
        time.sleep(SLEEP_S)
    print(f"Fetched {fetched:,} new days, {cached:,} already cached.", flush=True)

    pre, post, d = [], [], start
    while d < end:
        day_file = ddir / f"{d:%Y-%m-%d}.json"
        if day_file.exists():
            rows = _capacity_rows(json.loads(day_file.read_text(encoding="utf-8")))
            (pre if d <= BREXIT_LAST_DAY else post).extend(rows)
        d += timedelta(days=1)

    if pre:
        _write_flow_csv(pre, cdir / f"n2ex_capacity_uk_eu_coupled_{start:%Y%m%d}_20201231.csv")
    if post:
        _write_flow_csv(post, cdir / f"n2ex_capacity_uk_nsl_{NSL_FIRST_DAY:%Y%m%d}_{end:%Y%m%d}.csv")
    if not pre and not post:
        print("  no Available capacity data in range.", flush=True)


def main(argv: list[str]) -> None:
    p = argparse.ArgumentParser(description="Pull N2EX day-ahead data from Nord Pool (paid).")
    p.add_argument("product", choices=["prices", "curves", "flows", "capacity"])
    p.add_argument("--market", default="N2EX_DayAhead",
                   choices=["N2EX_DayAhead", "GbHalfHour_DayAhead"])
    p.add_argument("--start", type=_parse_date, default=_parse_date("2023-01-01"))
    p.add_argument("--end", type=_parse_date, default=_parse_date("2024-01-01"))
    args = p.parse_args(argv[1:])

    print(f"{args.product} {args.start.date()} -> {args.end.date()} "
          f"({args.market if args.product == 'prices' else 'N2EX_DayAhead'})", flush=True)
    if args.product == "prices":
        pull_prices(args.start, args.end, args.market)
    elif args.product == "flows":
        pull_flows(args.start, args.end)
    elif args.product == "capacity":
        pull_capacity(args.start, args.end)
    else:
        pull_curves(args.start, args.end)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
