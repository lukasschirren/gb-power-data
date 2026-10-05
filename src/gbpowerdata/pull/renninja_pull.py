"""Pull weather-derived (reanalysis) capacity factors from renewables.ninja.

This is the `cf_source: reanalysis` path — wind/solar CF that is INDEPENDENT of
dispatch, needed for any counterfactual (no-CfD world, different mix, locational
comparison) where the observed FUELHH-implied CF would wrongly bake in history.

Requires a free renewables.ninja API token (per account):
  - set env var  RENNINJA_TOKEN=<token>, or
  - put it in    data/reference/renewables_ninja_token.txt   (gitignored)

Reads representative GB sites from data/reference/ninja_sites.csv; one MERRA-2
hourly CF series per site per year -> data/raw/ninja/{site}_{year}.csv. The API
caps at ~50 requests/hour, so we sleep between calls; keep the site list small or
pull a few years at a time. Aggregating sites -> national CF happens in Stage 2.

Usage:
  python -m gbpowerdata.pull.renninja_pull                         # all sites, 2016-01-01..2026-01-01
  python -m gbpowerdata.pull.renninja_pull --start 2023-01-01 --end 2024-01-01
  python -m gbpowerdata.pull.renninja_pull --sites hornsea_offshore whitelee_onshore
"""

from __future__ import annotations

import argparse
import io
import os
import sys
import time
from datetime import datetime, timezone

import pandas as pd
import requests

from gbpowerdata import config as cfg

API = "https://www.renewables.ninja/api"
OUT_DIR = cfg.raw_dir() / "ninja"
SLEEP_S = 75.0          # sustained limit is 50/hour (1 per 72s); 75s keeps headroom
DATASET = "merra2"


def get_token() -> str:
    tok = os.environ.get("RENNINJA_TOKEN")
    if tok:
        return tok.strip()
    f = cfg.reference_dir() / "renewables_ninja_token.txt"
    if f.exists():
        return f.read_text(encoding="utf-8").strip()
    sys.exit("No renewables.ninja token. Set RENNINJA_TOKEN or create "
             "data/reference/renewables_ninja_token.txt")


def _session(token: str) -> requests.Session:
    s = requests.Session()
    s.headers.update({"Authorization": f"Token {token}"})
    return s


def fetch_site_year(s: requests.Session, site: pd.Series,
                    date_from: str, date_to: str) -> pd.DataFrame:
    """One site, [date_from, date_to). Returns DataFrame[time(UTC), cf]."""
    kind = site["kind"]
    if kind.startswith("wind"):
        url = f"{API}/data/wind"
        params = {
            "lat": site["lat"], "lon": site["lon"],
            "date_from": date_from, "date_to": date_to,
            "dataset": DATASET, "capacity": 1.0,
            "height": site["hub_height_m"], "turbine": site["turbine"],
            "format": "csv", "raw": "false",
        }
    elif kind == "solar":
        url = f"{API}/data/pv"
        params = {
            "lat": site["lat"], "lon": site["lon"],
            "date_from": date_from, "date_to": date_to,
            "dataset": DATASET, "capacity": 1.0, "system_loss": 0.1,
            "tracking": 0, "tilt": site["tilt"], "azim": site["azim"],
            "format": "csv", "raw": "false",
        }
    else:
        raise ValueError(f"unknown kind {kind!r} for site {site['site']}")

    for attempt in range(6):
        try:
            r = s.get(url, params=params, timeout=120)
        except requests.exceptions.RequestException as e:
            # Transient network drop (RemoteDisconnected, timeout, reset) — back
            # off and retry rather than killing a multi-hour pull.
            wait = 30 * (attempt + 1)
            print(f"    network error ({type(e).__name__}); retry in {wait}s", flush=True)
            time.sleep(wait)
            continue
        if r.status_code == 429:  # rate limited — respect Retry-After and back off
            wait = int(r.headers.get("Retry-After", 60)) + 2
            print(f"    429 rate-limited; sleeping {wait}s", flush=True)
            time.sleep(wait)
            continue
        r.raise_for_status()
        break
    else:
        raise RuntimeError("renewables.ninja: still failing after retries")

    # CSV payload: '#'-prefixed metadata lines, then a `time,electricity` table.
    # capacity=1 + raw=false => electricity is the capacity factor (0-1).
    df = pd.read_csv(io.StringIO(r.text), comment="#")
    df = df.rename(columns={"electricity": "cf"})
    df["time"] = pd.to_datetime(df["time"], utc=True)
    return df[["time", "cf"]]


def main(argv: list[str]) -> None:
    p = argparse.ArgumentParser(description="Pull reanalysis CF from renewables.ninja.")
    p.add_argument("--start", default="2016-01-01", help="UTC start YYYY-MM-DD (inclusive).")
    p.add_argument("--end", default="2026-01-01", help="UTC end YYYY-MM-DD (exclusive).")
    p.add_argument("--sites", nargs="*", help="subset of site names (default: all).")
    p.add_argument("--sites-file", default="ninja_sites.csv",
                   help="site list under data/reference/ (e.g. ninja_sites_by_zone.csv).")
    args = p.parse_args(argv[1:])

    token = get_token()
    s = _session(token)
    sites = pd.read_csv(cfg.reference_dir() / args.sites_file)
    if args.sites:
        sites = sites[sites["site"].isin(args.sites)]
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    start_year = datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=timezone.utc).year
    end_year = datetime.strptime(args.end, "%Y-%m-%d").replace(tzinfo=timezone.utc).year  # exclusive
    years = list(range(start_year, end_year))
    print(f"{len(sites)} sites x {len(years)} years = {len(sites) * len(years)} requests "
          f"(~{SLEEP_S}s apart). out={OUT_DIR}", flush=True)

    for _, site in sites.iterrows():
        for yr in years:
            out = OUT_DIR / f"{site['site']}_{yr}.csv"
            if out.exists():
                print(f"  skip {out.name} (exists)", flush=True)
                continue
            df = fetch_site_year(s, site, f"{yr}-01-01", f"{yr}-12-31")
            df.to_csv(out, index=False)
            print(f"  {site['site']} {yr}: {len(df):,} h, mean CF {df['cf'].mean():.3f} -> {out.name}",
                  flush=True)
            time.sleep(SLEEP_S)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
