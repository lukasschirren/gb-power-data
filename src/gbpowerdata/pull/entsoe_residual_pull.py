"""Pull the neighbours' load and wind and solar generation from ENTSO-E -> raw/entsoe/foreign_residual/.

WHY. A market model that lets the price GB achieves abroad move with the flow (exporting into a zone lowers that
zone's residual demand and so its price; importing raises it) needs each neighbour's residual demand (load minus
wind minus solar) beside its day-ahead price, so the zone's inverse-supply slope can be estimated from the
neighbour's own data (`build.foreign_supply`). Nothing of GB's own price enters, so the estimate is not circular
for GB, which is small against each neighbour.

WHAT IT PULLS, per zone, hourly: A65 total load, and A75 generation for wind onshore (B19), wind offshore (B18) and
solar (B16); residual_demand = load - wind - solar. Zones are GB's interconnector neighbours, by EIC: FR
10YFR-RTE------C, NL 10YNL----------L, BE 10YBE----------2, IE 10Y1001A1001A59C (the all-island SEM, whose load
equals IE + NI at correlation 1.0000), NO2 10YNO-2--------T, DK1 10YDK-1--------W.

HOW THE RESPONSES BEHAVE (probed live in July 2026; an earlier version got all six wrong and produced corrupt
residuals):
  1. curveType is A03 on every series: a variable-sized block curve, a Point emitted only when the value changes
     and carried forward to the next stated position. Omitted positions are not missing data: FR solar 2025 states
     18,782 of 28,560 positions in one Period. Zero-filling them deleted 35-45% of French solar.
  2. The carry-forward runs to the Period's timeInterval end, not to the last stated position.
  3. The resolution varies by zone and by Period within one document (IE-SEM PT30M, FR/NL/BE PT15M during 2025,
     the rest PT60M), and a Period can start off the hour, so hourly means are duration-weighted and an hour is
     emitted only when its slots sum to 60 minutes.
  4. "No data" is HTTP 200 with an Acknowledgement_MarketDocument whose text reads "No matching data found"; HTTP
     400 is a malformed request (a window over one year) and 401 a bad token, never "no data".
  5. One calendar year per request is the maximum and enough.
  6. An A75 response routinely carries two TimeSeries for one psrType on identical intervals, production
     (inBiddingZone_Domain) and consumption by the same class (outBiddingZone_Domain), both businessType A01, in an
     order that is not stable. Series are selected by bidding-zone role: in for generation, out for load.
Series ENTSO-E does not publish (NO2 solar and offshore wind, IE solar) are recorded as 0 MW for a technology and
as an error for load, since every zone always has load.

Raw XML is cached per zone, product and year under by_year/ (a no-data answer as an empty .nodata marker), so a
killed run resumes and a re-run costs no requests; the in-progress calendar year is never cached.
Ported on 30 Oct 2026 from the research repository's scripts/pull_foreign_residual_demand.py.

Token: ENTSOE_TOKEN or data/reference/entsoe_token.txt (`pull.entsoe_pull.get_token`).
OUTPUT raw/entsoe/foreign_residual/{zone}_residual_hourly.csv (deliveryStart, load_mw, wind_on_mw, wind_off_mw,
solar_mw, vre_mw, residual_mw) and _coverage_report.csv.
RUN    python -m gbpowerdata.pull.entsoe_residual_pull [--years 2019 2025] [--zones fr nl] [--refresh] [--max-gap-h 3]
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

import numpy as np
import pandas as pd
import requests

from gbpowerdata import config as cfg
from gbpowerdata.pull.entsoe_pull import API, _strip_ns, get_token

SLEEP_S = 0.5


def out_dir() -> Path:
    return cfg.raw_dir() / "entsoe" / "foreign_residual"


def cache_dir() -> Path:
    return out_dir() / "by_year"


def _one(tag: str, eic: str) -> dict:
    return {"load": {tag: eic}, "gen": {tag: eic}}


# zone -> {"load": {part: eic}, "gen": {part: eic}}; "part" is only a cache-file tag
ZONES = {
    "fr": _one("fr", "10YFR-RTE------C"),
    "nl": _one("nl", "10YNL----------L"),
    "be": _one("be", "10YBE----------2"),
    "no2": _one("no2", "10YNO-2--------T"),
    "dk1": _one("dk1", "10YDK-1--------W"),
    "ie": _one("sem", "10Y1001A1001A59C"),   # all-island for both load and generation
}

# product key -> (documentType, psrType or None); the order sets the CSV column order
PRODUCTS = {"load": ("A65", None), "wind_on": ("A75", "B19"),
            "wind_off": ("A75", "B18"), "solar": ("A75", "B16")}
VRE = [k for k in PRODUCTS if k != "load"]

# every resolution ENTSO-E may return; an unknown one is a hard error, never a silent 60-minute fallback
RESOLUTION = {"PT60M": timedelta(hours=1), "PT30M": timedelta(minutes=30),
              "PT15M": timedelta(minutes=15), "PT10M": timedelta(minutes=10),
              "PT5M": timedelta(minutes=5), "PT1M": timedelta(minutes=1)}

# loose sanity bands for mean load (MW), warn-only: a silently broken pull lands far outside
LOAD_BAND = {"fr": (35_000, 75_000), "nl": (8_000, 20_000), "be": (6_000, 14_000),
             "ie": (3_000, 7_000), "no2": (2_000, 9_000), "dk1": (1_500, 4_500)}


class NoData(Exception):
    """ENTSO-E answered 200 with 'No matching data found': the series does not exist."""


# --------------------------------------------------------------------------- fetch
def _fetch(token: str, params: dict) -> str:
    """One request, retrying only what is worth retrying; raises on a real failure."""
    q = dict(params, securityToken=token)
    last = ""
    for attempt in range(5):
        try:
            r = requests.get(API, params=q, timeout=180)
        except requests.RequestException as e:          # transient network blip
            last = f"{type(e).__name__}: {e}"
            time.sleep(3 * (attempt + 1))
            continue
        if r.status_code == 200:
            return r.text
        last = f"HTTP {r.status_code}: {r.text[:200]}"
        if r.status_code == 429 or r.status_code >= 500:  # rate limit or server side
            time.sleep(8 * (attempt + 1))
            continue
        raise RuntimeError(last)                        # 400/401/403 are our fault
    raise RuntimeError(f"gave up after 5 attempts - {last}")


def _check_ack(xml: str) -> None:
    """Raise NoData for a genuine empty result, RuntimeError for an error acknowledgement."""
    root = ET.fromstring(xml.encode("utf-8"))
    if not _strip_ns(root.tag).startswith("Acknowledgement"):
        return
    text = " ".join(e.text or "" for e in root.iter() if _strip_ns(e.tag) == "text").strip()
    if "No matching data found" in text:
        raise NoData(text)
    raise RuntimeError(f"acknowledgement: {text[:200]}")


# --------------------------------------------------------------------------- parse
def _parse(xml: str, generation: bool) -> pd.DataFrame:
    """Flatten one GL_MarketDocument to sub-hourly samples: a frame indexed by UTC timestamp with columns value and
    step_min (the slot's duration), the A03 carry-forward applied within each Period out to its timeInterval end,
    TimeSeries selected by bidding-zone role (docstring, point 6)."""
    root = ET.fromstring(xml.encode("utf-8"))
    ts_stamp: list = []
    ts_value: list = []
    ts_step: list = []

    keep_periods: list = []
    for ts in root.iter():
        if _strip_ns(ts.tag) != "TimeSeries":
            continue
        has_in = any(_strip_ns(c.tag).startswith("inBiddingZone") for c in ts)
        has_out = any(_strip_ns(c.tag).startswith("outBiddingZone") for c in ts)
        wanted = (has_in and not has_out) if generation else has_out
        if not wanted:
            continue
        keep_periods += [p for p in ts.iter() if _strip_ns(p.tag) == "Period"]

    for period in keep_periods:
        start = end = res = None
        points: list[tuple[int, float]] = []
        for child in period:
            name = _strip_ns(child.tag)
            if name == "timeInterval":
                for ti in child:
                    if _strip_ns(ti.tag) == "start":
                        start = datetime.strptime(ti.text, "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc)
                    elif _strip_ns(ti.tag) == "end":
                        end = datetime.strptime(ti.text, "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc)
            elif name == "resolution":
                if child.text not in RESOLUTION:
                    raise RuntimeError(f"unhandled resolution {child.text!r}")
                res = RESOLUTION[child.text]
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
        # the slots the Period covers; some Periods stop stating positions before the end
        slots = int((end - start) / res) if end is not None else points[-1][0]
        slots = max(slots, points[-1][0])
        step_min = res.total_seconds() / 60.0
        cur, i = None, 0
        for pos in range(1, slots + 1):
            if i < len(points) and points[i][0] == pos:
                cur = points[i][1]
                i += 1
            if cur is None:                             # no value stated yet: a genuine gap
                continue
            ts_stamp.append(start + res * (pos - 1))
            ts_value.append(cur)
            ts_step.append(step_min)

    df = pd.DataFrame({"value": ts_value, "step_min": ts_step},
                      index=pd.DatetimeIndex(ts_stamp, tz="UTC", name="deliveryStart"))
    if df.empty:
        return df
    return df[~df.index.duplicated(keep="last")].sort_index()   # a revision repeats a slot: keep the last


def _to_hourly(df: pd.DataFrame) -> pd.Series:
    """Duration-weighted hourly mean; an hour is emitted only if fully covered (60 minutes)."""
    if df.empty:
        return pd.Series(dtype=float)
    hour = df.index.floor("h")
    num = (df["value"] * df["step_min"]).groupby(hour).sum()
    den = df["step_min"].groupby(hour).sum()
    out = num / den
    out[den < 59.999] = pd.NA                           # a partial hour is not a valid mean
    return out.astype(float)


# --------------------------------------------------------------------------- pull
def _params(doc: str, psr: str | None, eic: str, year: int) -> dict:
    p = {"documentType": doc, "processType": "A16",
         "periodStart": f"{year}01010000", "periodEnd": f"{year + 1}01010000"}
    if doc == "A65":
        p["outBiddingZone_Domain"] = eic
    else:
        p["in_Domain"] = eic
        p["psrType"] = psr
    return p


def _year_xml(token: str, zone: str, product: str, part: str, eic: str, year: int, refresh: bool) -> str | None:
    """Cached raw XML for one zone, product, EIC and year; None means 'no matching data' (cached as a marker)."""
    doc, psr = PRODUCTS[product]
    stem = cache_dir() / f"{zone}_{product}_{part}_{year}"
    xml_p, none_p = stem.with_suffix(".xml"), stem.with_suffix(".nodata")
    live_year = year >= datetime.now(timezone.utc).year   # in progress: never trust the cache
    if not refresh and not live_year:
        if xml_p.exists():
            return xml_p.read_text(encoding="utf-8")
        if none_p.exists():
            return None

    xml = _fetch(token, _params(doc, psr, eic, year))
    try:
        _check_ack(xml)
    except NoData:
        none_p.write_text("", encoding="utf-8")
        xml_p.unlink(missing_ok=True)
        time.sleep(SLEEP_S)
        return None
    xml_p.write_text(xml, encoding="utf-8")
    none_p.unlink(missing_ok=True)
    time.sleep(SLEEP_S)
    return xml


def _fill_short_gaps(s: pd.Series, max_gap: int) -> tuple[pd.Series, int]:
    """Time-interpolate interior NaN runs no longer than `max_gap` hours, all or nothing per run (interpolate's
    limit would fill the first hours of a long outage and leave a phantom ramp); leave the rest."""
    na = s.isna().to_numpy()
    if max_gap <= 0 or not na.any():
        return s, 0
    run_id = (na != np.r_[False, na[:-1]]).cumsum()
    inside = s.interpolate(method="time", limit_area="inside")
    out, filled = s.copy(), 0
    for g in pd.unique(run_id[na]):
        idx = np.flatnonzero((run_id == g) & na)
        if len(idx) <= max_gap:
            out.iloc[idx] = inside.iloc[idx]
            filled += int(inside.iloc[idx].notna().sum())
    return out, filled


def _product_series(token: str, zone: str, product: str, grid: pd.DatetimeIndex,
                    y0: int, y1: int, refresh: bool) -> tuple[pd.Series, list[int]]:
    """One product for one zone on the hourly grid, summed over its constituent EICs; a year with no data is a
    genuine zero for a technology and a hole for load."""
    parts = ZONES[zone]["load" if product == "load" else "gen"]
    per_part, absent_years = [], []
    for part, eic in parts.items():
        chunks, part_absent = [], []
        for year in range(y0, y1 + 1):
            xml = _year_xml(token, zone, product, part, eic, year, refresh)
            if xml is None:
                part_absent.append(year)
                continue
            chunks.append(_to_hourly(_parse(xml, generation=product != "load")))
        s = pd.concat(chunks) if chunks else pd.Series(dtype=float)
        if not s.empty:
            s = s[~s.index.duplicated(keep="last")].sort_index()
        s = s.reindex(grid)
        if product != "load":
            for year in part_absent:                    # nothing generated or nothing to report
                s[grid.year == year] = s[grid.year == year].fillna(0.0)
        per_part.append(s)
        absent_years += [y for y in part_absent if y not in absent_years]

    stacked = pd.concat(per_part, axis=1)
    return stacked.sum(axis=1, min_count=len(per_part)), sorted(absent_years)


def pull_zone(token: str, zone: str, y0: int, y1: int, refresh: bool,
              max_gap: int) -> tuple[pd.DataFrame, dict, dict, dict]:
    """One zone's hourly table for the years `y0`..`y1`, with the notes the coverage report prints."""
    grid = pd.date_range(f"{y0}-01-01", f"{y1 + 1}-01-01", freq="h", tz="UTC", inclusive="left",
                         name="deliveryStart")
    cols: dict[str, pd.Series] = {}
    notes: dict[str, list[int]] = {}
    prestart: dict[str, int] = {}
    interp: dict[str, int] = {}

    for product in PRODUCTS:
        s, absent = _product_series(token, zone, product, grid, y0, y1, refresh)
        if product != "load" and s.notna().any():
            # a technology appears when it is commissioned (FR offshore wind first reports 2023-07-25): hours before
            # its first observation generated zero and must not poison the residual; interior gaps stay NaN
            first = s.first_valid_index()
            lead = grid < first
            prestart[product] = int((lead & s.isna()).sum())
            s[lead] = s[lead].fillna(0.0)
        elif product == "load" and absent:
            print(f"    !! {zone} load has no data for {absent} - left as NaN", flush=True)
        s, n = _fill_short_gaps(s, max_gap)
        interp[product] = n
        cols[f"{product}_mw"] = s
        notes[product] = absent

    df = pd.DataFrame(cols, index=grid)
    df["vre_mw"] = df[[f"{v}_mw" for v in VRE]].sum(axis=1, min_count=len(VRE))
    df["residual_mw"] = df["load_mw"] - df["vre_mw"]
    return df, notes, prestart, interp


# --------------------------------------------------------------------------- report
def qc(zone: str, df: pd.DataFrame, notes: dict, prestart: dict, interp: dict) -> dict:
    """One row of the coverage report, with warnings where the pull looks broken."""
    n = len(df)
    load = df["load_mw"]
    row = {"zone": zone, "hours": n,
           "load_nan": int(load.isna().sum()),
           "vre_nan": int(df["vre_mw"].isna().sum()),
           "residual_nan": int(df["residual_mw"].isna().sum()),
           "load_mean_mw": round(load.mean(), 1),
           "wind_on_mean_mw": round(df["wind_on_mw"].mean(), 1),
           "wind_off_mean_mw": round(df["wind_off_mw"].mean(), 1),
           "solar_mean_mw": round(df["solar_mw"].mean(), 1),
           "vre_share_of_load": round(df["vre_mw"].mean() / load.mean(), 3),
           "residual_mean_mw": round(df["residual_mw"].mean(), 1),
           "residual_min_mw": round(df["residual_mw"].min(), 1),
           "residual_max_mw": round(df["residual_mw"].max(), 1),
           "absent_products": ";".join(f"{k}({len(v)}y)" for k, v in notes.items() if v),
           "prestart_zeroed_h": ";".join(f"{k}={v}" for k, v in prestart.items() if v),
           "interpolated_h": ";".join(f"{k}={v}" for k, v in interp.items() if v)}

    warn = []
    lo, hi = LOAD_BAND.get(zone, (0, 1e9))
    if not (lo <= load.mean() <= hi):
        warn.append(f"mean load {load.mean():,.0f} MW outside plausible {lo:,}-{hi:,}")
    if row["residual_nan"] / max(n, 1) > 0.02:
        warn.append(f"{row['residual_nan'] / n:.1%} of hours have no residual")
    for v in VRE:
        col = df[f"{v}_mw"]
        if (col.fillna(0) == 0).all() and not notes.get(v):
            warn.append(f"{v} is identically zero yet ENTSO-E returned data")
    if (df["residual_mw"] > load).any():
        warn.append("residual exceeds load somewhere (negative VRE?)")
    row["warnings"] = " | ".join(warn)
    return row


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--years", nargs=2, type=int, default=[2019, 2025], metavar=("FIRST", "LAST"),
                    help="inclusive calendar-year range")
    ap.add_argument("--zones", nargs="+", default=sorted(ZONES), choices=sorted(ZONES))
    ap.add_argument("--refresh", action="store_true", help="ignore the cached XML and refetch")
    ap.add_argument("--max-gap-h", type=int, default=3, metavar="H",
                    help="time-interpolate interior gaps up to H hours (0 disables)")
    args = ap.parse_args(argv)
    y0, y1 = args.years
    out, cache = out_dir(), cache_dir()
    out.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    token = get_token()

    rows = []
    for zone in args.zones:
        print(f"=== {zone.upper()} {y0}-{y1} ===", flush=True)
        df, notes, prestart, interp = pull_zone(token, zone, y0, y1, args.refresh, args.max_gap_h)
        path = out / f"{zone}_residual_hourly.csv"
        df.round(3).to_csv(path)
        row = qc(zone, df, notes, prestart, interp)
        rows.append(row)
        print(f"    wrote {path.name}  {row['hours']:,} h | load {row['load_mean_mw']:,.0f} MW "
              f"| vre {row['vre_share_of_load']:.0%} of load "
              f"| residual {row['residual_mean_mw']:,.0f} MW "
              f"[{row['residual_min_mw']:,.0f}, {row['residual_max_mw']:,.0f}]", flush=True)
        for key, label in (("absent_products", "not published"), ("prestart_zeroed_h", "pre-commissioning hours set to 0"),
                           ("interpolated_h", f"short gaps interpolated (<={args.max_gap_h}h)"), ("warnings", "WARN")):
            if row[key]:
                print(f"    {label}: {row[key]}", flush=True)

    rep = pd.DataFrame(rows)
    rep.to_csv(out / "_coverage_report.csv", index=False)
    print(f"\ncoverage report -> {out / '_coverage_report.csv'}", flush=True)
    print(rep[["zone", "hours", "residual_nan", "load_mean_mw", "vre_share_of_load", "residual_mean_mw"]]
          .to_string(index=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
