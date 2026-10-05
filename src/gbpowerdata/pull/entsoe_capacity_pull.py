"""Pull GB cross-border interconnector capacity from the ENTSO-E Transparency Platform.

Day-ahead forecasted (net) transfer capacity for each GB border, both directions:
  GB<->FR (IFA/IFA2/ElecLink)   GB<->BE (Nemo)
  GB<->NL (BritNed)             GB<->IE (Moyle/EWIC/Greenlink, IE-SEM zone)

This is the *border-level* NTC (MW) the market can schedule day-ahead, i.e. the
capacity ceiling behind the N2EX/observed flows already collected. ENTSO-E
aggregates all cables on a border into one number — per-cable capacity is not
available on this product. Complements (does not duplicate) the N2EX flow volumes.

Document type A61 (forecasted transfer capacity) + contract_MarketAgreement.Type
A01 (day-ahead). Directional: in_Domain = importing zone, out_Domain = exporting
zone. Values are an hourly (PT60M) sparse curve (curveType A03) — a value is
emitted only when it changes, so a missing hour carries the previous value
forward within the same published day. Days ENTSO-E never published stay as gaps
(we do NOT carry capacity across days — that would fabricate an NTC).

Requires the same free ENTSO-E token as entsoe_pull.py (ENTSOE_TOKEN env or
data/reference/entsoe_token.txt).

Output (raw XML cached per border-direction per year, then one combined long CSV):
  data/raw/entsoe/capacity/by_year/<from>_<to>_<year>.xml
  data/raw/entsoe/capacity/gb_interconnector_capacity_<start>_<end>.csv
    columns: deliveryStart(UTC), fromZone, toZone, capacity_mw

Usage:
  python -m gbpowerdata.pull.entsoe_capacity_pull --start 2016 --end 2027
  python -m gbpowerdata.pull.entsoe_capacity_pull --borders FR NL --start 2023 --end 2024
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone
from xml.etree import ElementTree as ET

import pandas as pd
import requests

from gbpowerdata import config as cfg
from gbpowerdata.pull.entsoe_pull import API, _RESOLUTION, _strip_ns, get_token

OUT = cfg.raw_dir() / "entsoe" / "capacity"
SLEEP_S = 1.0

GB = "10YGB----------A"
# counterparty zone EICs; keys are the --borders values.
COUNTERPARTY = {
    "FR": "10YFR-RTE------C",
    "BE": "10YBE----------2",
    "NL": "10YNL----------L",
    "IE": "10Y1001A1001A59C",  # IE(SEM)
    "NO2": "10YNO-2--------T",  # North Sea Link
    "DK1": "10YDK-1--------W",  # Viking Link
}


def _fetch_year(token: str, in_eic: str, out_eic: str, year: int) -> str:
    """Raw A61 day-ahead capacity XML for one direction, one year (UTC)."""
    params = {
        "securityToken": token,
        "documentType": "A61",
        "contract_MarketAgreement.Type": "A01",
        "in_Domain": in_eic,
        "out_Domain": out_eic,
        "periodStart": f"{year}01010000",
        "periodEnd": f"{year + 1}01010000",
    }
    r = requests.get(API, params=params, timeout=180)
    r.raise_for_status()
    return r.text


def _parse_xml(xml: str, from_zone: str, to_zone: str) -> list[dict]:
    """Flatten one A61 document to rows [deliveryStart(UTC), from, to, capacity_mw].

    Each published day is its own Period (start + resolution + positional points);
    sparse positions carry forward WITHIN a Period only.
    """
    root = ET.fromstring(xml.encode("utf-8"))
    if _strip_ns(root.tag).startswith("Acknowledgement"):
        reason = " ".join(e.text or "" for e in root.iter()
                          if _strip_ns(e.tag) == "text")
        raise RuntimeError(f"ENTSO-E returned no data: {reason.strip()}")

    rows = []
    for period in root.iter():
        if _strip_ns(period.tag) != "Period":
            continue
        start, res, points = None, None, []
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
                pos = qty = None
                for p in child:
                    pn = _strip_ns(p.tag)
                    if pn == "position":
                        pos = int(p.text)
                    elif pn == "quantity":
                        qty = float(p.text)
                if pos is not None and qty is not None:
                    points.append((pos, qty))
        if start is None or res is None or not points:
            continue
        points.sort()
        last_pos = points[-1][0]
        cur, i = None, 0
        for pos in range(1, last_pos + 1):
            if i < len(points) and points[i][0] == pos:
                cur = points[i][1]
                i += 1
            rows.append({"deliveryStart": start + res * (pos - 1),
                         "fromZone": from_zone, "toZone": to_zone,
                         "capacity_mw": cur})
    return rows


def _directions(borders: list[str]) -> list[tuple[str, str, str, str]]:
    """(from_zone, to_zone, in_eic, out_eic) for both directions of each border."""
    out = []
    for b in borders:
        cp = COUNTERPARTY[b]
        out.append(("GB", b, cp, GB))   # GB -> counterparty (in=cp, out=GB)
        out.append((b, "GB", GB, cp))   # counterparty -> GB
    return out


def pull(borders: list[str], start_year: int, end_year: int) -> None:
    token = get_token()
    ydir = OUT / "by_year"
    ydir.mkdir(parents=True, exist_ok=True)
    now_year = datetime.now(timezone.utc).year

    for from_zone, to_zone, in_eic, out_eic in _directions(borders):
        tag = f"{from_zone.lower()}_{to_zone.lower()}"
        for year in range(start_year, end_year):
            cache = ydir / f"{tag}_{year}.xml"
            if cache.exists() and year < now_year:
                continue
            try:
                xml = _fetch_year(token, in_eic, out_eic, year)
            except requests.HTTPError as e:
                body = e.response.text[:150] if e.response is not None else ""
                print(f"  skip {tag} {year}: {e} {body}", flush=True)
                continue
            try:
                n = len(_parse_xml(xml, from_zone, to_zone))
                cache.write_text(xml, encoding="utf-8")
                print(f"  {tag} {year}: {n:,} hourly points -> {cache.name}", flush=True)
            except RuntimeError as e:
                print(f"  {tag} {year}: {e}", flush=True)
            time.sleep(SLEEP_S)

    # Rebuild combined long CSV from every cached direction+year in range.
    rows = []
    for from_zone, to_zone, _, _ in _directions(borders):
        tag = f"{from_zone.lower()}_{to_zone.lower()}"
        for year in range(start_year, end_year):
            cache = ydir / f"{tag}_{year}.xml"
            if cache.exists():
                try:
                    rows.extend(_parse_xml(cache.read_text(encoding="utf-8"),
                                           from_zone, to_zone))
                except RuntimeError:
                    pass
    df = pd.DataFrame(rows)
    if not df.empty:
        df["deliveryStart"] = pd.to_datetime(df["deliveryStart"], utc=True)
        df = (df.drop_duplicates(["deliveryStart", "fromZone", "toZone"])
                .sort_values(["fromZone", "toZone", "deliveryStart"])
                .reset_index(drop=True))
    path = OUT / f"gb_interconnector_capacity_{start_year}_{end_year}.csv"
    df.to_csv(path, index=False)
    print(f"Saved {len(df):,} capacity points -> {path}", flush=True)


def main(argv: list[str]) -> None:
    p = argparse.ArgumentParser(
        description="Pull GB cross-border day-ahead capacity from ENTSO-E (free).")
    p.add_argument("--borders", nargs="+", default=sorted(COUNTERPARTY),
                   choices=sorted(COUNTERPARTY),
                   help="GB borders to pull (default: all four)")
    p.add_argument("--start", type=int, default=2016, help="first year (inclusive)")
    p.add_argument("--end", type=int, default=2027, help="year AFTER the last (exclusive)")
    args = p.parse_args(argv[1:])
    print(f"GB capacity {'/'.join(args.borders)} {args.start} -> {args.end - 1}", flush=True)
    pull(args.borders, args.start, args.end)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
