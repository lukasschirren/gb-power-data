"""Parse the BLOCK orders of both GB hourly day-ahead auctions into one common schema.

Why this exists: the aggregated supply/demand curves both venues publish are built from
HOURLY orders only — every block order is excluded. So the curve alone never clears the
auction, and the "missing" volume is exactly what this module recovers. Blocks are also
the closest thing either venue publishes to a portfolio bid: one order, one limit price,
a multi-hour volume shape, an all-or-nothing (or min-acceptance-ratio) condition, and a
stable per-order id.

Sources, and how they differ:
  EPEX  data/raw/epex/great-britain/block_bids{,_hourly}/bbof_great-britain_YYYY.zip
        Semicolon CSV, one file per delivery day. Row type BB, columns taken from the
        file's own "# Data type(BB);..." comment (the spec PDF lists a slightly different
        order, so the file header is the ground truth). Volume sign carries the side:
        POSITIVE = purchase, NEGATIVE = sale. Accepted volume must be DERIVED as
        volume x AAR (and only when Execution == Y).
  N2EX  data/raw/nordpool/curves/{date}.json -> "blockOrders". Richer: an explicit
        side, per-interval acceptedVolume (no derivation needed), and a
        paradoxicallyRejected flag EPEX does not publish.

Block types. EPEX codes them C01 normal / C02 linked / C04 exclusive group / C88 loop;
N2EX instead exposes linkedOrderId and exclusiveGroupId. Both are mapped to a common
`family` column (normal / linked / exclusive / loop).

Outputs (per venue, per year):
  data/processed/{venue}_block_hours_{year}.csv  -- one row per delivery hour
      deliveryStart, buy_submitted_mw, sell_submitted_mw, buy_accepted_mw,
      sell_accepted_mw, n_blocks_active, n_blocks_accepted
  data/processed/{venue}_blocks_{year}.csv       -- one row per block order
      deliveryDate, block_id, side, family, limit_price, mar, aar, executed,
      n_hours, submitted_mwh, accepted_mwh, first_hour, last_hour

Usage:
  python -m gbpowerdata.build.parse_blocks epex 2020 2025
  python -m gbpowerdata.build.parse_blocks n2ex 2021 2025 --every 3
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
import zipfile
from collections import defaultdict

import numpy as np
import pandas as pd

from gbpowerdata import config as cfg
from gbpowerdata.build.parse_epex_curves import epex_day
from gbpowerdata.pull.epex_pull import RAW_BLOCK_DIRS

CET = "Europe/Berlin"
N2EX_CURVES = cfg.raw_dir() / "nordpool" / "curves"
BLOCK_ZIP_RE = re.compile(r"bbof_great-britain_(\d{4})\.zip$")
EPEX_FAMILY = {"C01": "normal", "C02": "linked", "C04": "exclusive", "C88": "loop"}
_VOL_RE = re.compile(r"(?i)^volume\s*h(\d+)\s*([ab]?)\s*$")


def _hour_ts(day: pd.Timestamp, hour: int, ab: str):
    """CET (day, hour 1..24, optional A/B DST twin) -> UTC hour start."""
    ts = (day + pd.Timedelta(hours=hour - 1)).tz_localize(
        CET, ambiguous=(ab != "b"), nonexistent="NaT")
    return pd.NaT if ts is pd.NaT else ts.tz_convert("UTC")


# --------------------------------------------------------------------------- #
# EPEX
# --------------------------------------------------------------------------- #
def _epex_header(text: str) -> tuple[list[str] | None, pd.Timestamp]:
    """BB column names and the delivery day.

    The BB rows carry no date of their own — it sits on the single ST status row
    (ST;<delivery date DD.MM.YYYY>;<currency>;<creation time>;<creation date>)."""
    cols, day = None, pd.NaT
    for line in text.splitlines():
        if line.startswith("# Data type(BB)"):
            cols = [c.strip() for c in line.lstrip("# ").split(";")]
        elif line.startswith("ST;"):
            day = epex_day(line.split(";")[1].strip().replace(".", "/"))
        if cols is not None and pd.notna(day):
            break
    return cols, day


def epex_blocks_day(raw: bytes) -> list[dict]:
    """One bbof daily file -> per-block records with an hour->(submitted, accepted) map."""
    text = raw.decode("utf-8", "replace")
    cols, day = _epex_header(text)
    if not cols or pd.isna(day):
        return []
    vol_cols = {i: _VOL_RE.match(c) for i, c in enumerate(cols)}
    vol_cols = {i: (int(m.group(1)), m.group(2).lower()) for i, m in vol_cols.items() if m}
    idx = {c: i for i, c in enumerate(cols)}

    out = []
    for line in text.splitlines():
        if not line.startswith("BB;"):
            continue
        f = line.split(";")
        if len(f) < len(cols):
            continue

        def num(key, default=np.nan):
            try:
                return float(f[idx[key]])
            except (KeyError, ValueError, IndexError):
                return default

        executed = f[idx["Execution"]].strip().upper() == "Y" if "Execution" in idx else False
        aar = num("AAR", 1.0)
        if not np.isfinite(aar):
            aar = 1.0
        hours = {}
        for i, (h, ab) in vol_cols.items():
            try:
                v = float(f[i])
            except (ValueError, IndexError):
                continue
            if v == 0.0:
                continue
            ts = _hour_ts(day, h, ab)
            if ts is pd.NaT:
                continue
            # EPEX publishes only the ratio, so accepted volume is derived, not given.
            hours[ts] = (v, v * aar if executed else 0.0)
        if not hours:
            continue
        out.append({"deliveryDate": day.date(), "block_id": f[idx["BlockID"]] if "BlockID" in idx
                    else f[1],
                    "family": EPEX_FAMILY.get(f[idx["Block Type"]].strip(), f[idx["Block Type"]].strip())
                    if "Block Type" in idx else "",
                    "limit_price": num("Limit Price"), "mar": num("MAR"), "aar": aar,
                    "executed": executed, "hours": hours})
    return out


def epex_year(year: int, modality: str, every: int) -> list[dict]:
    zpath = next((z for z in RAW_BLOCK_DIRS[modality].glob("*.zip")
                  if BLOCK_ZIP_RE.search(z.name)
                  and int(BLOCK_ZIP_RE.search(z.name).group(1)) == year), None)
    if zpath is None:
        print(f"  {year}: no EPEX {modality} block zip", flush=True)
        return []
    rows = []
    with zipfile.ZipFile(zpath) as zf:
        names = sorted(n for n in zf.namelist() if n.lower().endswith(".csv"))[::every]
        for inner in names:
            try:
                rows.extend(epex_blocks_day(zf.read(inner)))
            except Exception as e:
                print(f"    skip {inner}: {e}", flush=True)
    return rows


# --------------------------------------------------------------------------- #
# N2EX
# --------------------------------------------------------------------------- #
def n2ex_blocks_day(path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    day = pd.to_datetime(data.get("deliveryDateCET"), errors="coerce")
    out = []
    for b in data.get("blockOrders") or []:
        sign = -1.0 if str(b.get("side", "")).lower().startswith("s") else 1.0
        hours = {}
        for iv in b.get("intervals") or []:
            v = float(iv.get("volume") or 0.0)
            if v == 0.0:
                continue
            ts = pd.to_datetime(iv["deliveryStart"], utc=True)
            hours[ts] = (sign * v, sign * float(iv.get("acceptedVolume") or 0.0))
        if not hours:
            continue
        family = ("exclusive" if b.get("exclusiveGroupId") else
                  "linked" if b.get("linkedOrderId") else "normal")
        aar = float(b.get("actualAcceptanceRatio") or 0.0)
        out.append({"deliveryDate": day.date() if pd.notna(day) else None,
                    "block_id": str(b.get("id")), "family": family,
                    "limit_price": float(b.get("price")) if b.get("price") is not None else np.nan,
                    "mar": float(b.get("minimumAcceptanceRatio") or 0.0), "aar": aar,
                    "executed": aar > 0,
                    "paradoxically_rejected": bool(b.get("paradoxicallyRejected")),
                    "hours": hours})
    return out


def n2ex_year(year: int, every: int) -> list[dict]:
    files = sorted(N2EX_CURVES.glob(f"{year}-*.json"))[::every]
    rows = []
    for i, fp in enumerate(files):
        try:
            rows.extend(n2ex_blocks_day(fp))
        except Exception as e:
            print(f"    skip {fp.name}: {e}", flush=True)
        if (i + 1) % 60 == 0:
            print(f"    n2ex {i + 1}/{len(files)} days", flush=True)
    return rows


# --------------------------------------------------------------------------- #
def write(rows: list[dict], venue: str, year: int) -> None:
    if not rows:
        print(f"  {year}: no blocks", flush=True)
        return
    # Per-block summary (the "portfolio bid" view).
    recs = []
    for r in rows:
        sub = np.array([v[0] for v in r["hours"].values()], float)
        acc = np.array([v[1] for v in r["hours"].values()], float)
        ts = sorted(r["hours"])
        recs.append({k: r[k] for k in
                     ("deliveryDate", "block_id", "family", "limit_price", "mar", "aar",
                      "executed")} |
                    {"paradoxically_rejected": r.get("paradoxically_rejected"),
                     "side": "sell" if sub.sum() < 0 else "buy",
                     "n_hours": len(ts),
                     "submitted_mwh": float(np.abs(sub).sum()),
                     "accepted_mwh": float(np.abs(acc).sum()),
                     "first_hour": ts[0], "last_hour": ts[-1]})
    blocks = pd.DataFrame(recs).sort_values(["deliveryDate", "block_id"])
    bpath = cfg.processed_dir() / f"{venue}_blocks_{year}.csv"
    blocks.to_csv(bpath, index=False)

    # Per delivery hour. Positive volume = purchase, negative = sale, on both venues.
    agg = defaultdict(lambda: dict(buy_submitted_mw=0.0, sell_submitted_mw=0.0,
                                   buy_accepted_mw=0.0, sell_accepted_mw=0.0,
                                   n_blocks_active=0, n_blocks_accepted=0))
    for r in rows:
        for ts, (sub, acc) in r["hours"].items():
            a = agg[ts]
            side = "buy" if sub > 0 else "sell"
            a[f"{side}_submitted_mw"] += abs(sub)
            a[f"{side}_accepted_mw"] += abs(acc)
            a["n_blocks_active"] += 1
            a["n_blocks_accepted"] += int(abs(acc) > 0)
    hours = (pd.DataFrame.from_dict(agg, orient="index").rename_axis("deliveryStart")
             .sort_index().reset_index())
    hpath = cfg.processed_dir() / f"{venue}_block_hours_{year}.csv"
    hours.to_csv(hpath, index=False)
    print(f"  {year}: {len(blocks):,} blocks, {len(hours):,} hours | "
          f"accepted {100 * blocks['executed'].mean():.0f}% of orders, "
          f"mean {hours['sell_accepted_mw'].mean():.0f} MW sell + "
          f"{hours['buy_accepted_mw'].mean():.0f} MW buy per hour -> {bpath.name}", flush=True)


def main(argv: list[str]) -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("venue", choices=["epex", "n2ex"])
    p.add_argument("start", type=int)
    p.add_argument("end", type=int, nargs="?")
    p.add_argument("--every", type=int, default=1, help="sample every Nth day")
    p.add_argument("--modality", default="hourly", choices=list(RAW_BLOCK_DIRS),
                   help="EPEX only: which day-ahead auction's blocks")
    a = p.parse_args(argv[1:])
    years = list(range(a.start, (a.end or a.start) + 1))
    label = "epex" if a.venue == "epex" else "n2ex"
    print(f"Parsing {label} block orders for {years} (every {a.every} days)", flush=True)
    for y in years:
        rows = (epex_year(y, a.modality, a.every) if a.venue == "epex"
                else n2ex_year(y, a.every))
        write(rows, label, y)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
