"""Reduce the EPEX GB day-ahead aggregated curves to per-period anonymous-bid features —
the EPEX analogue of parse_n2ex_curves. Curve-intrinsic only (no fleet/price anchoring),
so the features line up directly with n2ex_curve_features for the multi-venue offer-curve
comparison.

GB runs TWO day-ahead auctions and EACH publishes its own curves, in its own sFTP subtree
(see epex_pull). `--modality` picks one, and the output filename names it, because the two
are different order books and only one is the N2EX counterpart:
  hourly  — 60-min, gate ~09:20, curves 2008-2025. The like-for-like N2EX counterpart.
  hh      — 30-min, gate 15:30, curves 2017-2025. A separate, later auction.

Input: the yearly aggregated-curve zips under data/raw/epex/great-britain/
aggregated_curves{,_hourly}/ (CSV inner files 2020+, legacy .xls before that). Each daily
file lists the aggregated supply ("Sell") and demand ("Purchase") step curves — (price,
cumulative volume) points per delivery period, stamped in CET.

Output: data/processed/epex_{modality}_curve_features_{year}.csv, one row per delivery
period (UTC):
  deliveryStart, supply_floor_mw, supply_at_0_mw, supply_max_mw, demand_max_mw,
  supply_le_m100_mw, supply_le_m50_mw, supply_le_0_mw, supply_le_20_mw,
  supply_p_at_q25, supply_p_at_q50, supply_p_at_q75, supply_p_at_q90

⚠️ HOURLY-AUCTION DEMAND-SIDE COVERAGE (measured by sampling the raw archives 2026-07-29).
The supply curve is present throughout; the DEMAND curve is not:
    2011-2016  100% of hours carry a real demand curve (>=2 points)
    2017         0%  — absent all year. demand_max_mw comes out identically 0 and no
                       crossing can be computed; supply_max also jumps to ~23 GW against
                       ~5 GW either side. Treat the 2017 hourly curve year as UNUSABLE.
    2018        70%  — partial; the remainder carry a single token purchase point.
    2019-2025  100%
    2008-2010  sparse in every sense (only 690 / 4,960 / 136 hours trade at all).
Anything needing both sides — clearing, elasticity, the merit-order effect — should use
2011-2016 + 2019-2025 and skip 2017-2018.

The EPEX curve is COMPLETE — unlike Nord Pool's. Its own supply==demand crossing
reproduces the published clearing price to MAE GBP 0.34 (corr 1.0000, 93% of hours within
GBP 1, 2022-24), and its demand at that price matches the published cleared volume to 0.7%.
So blocks are already inside it and the auction can be re-cleared from this file alone.
The Nord Pool aggregate curve excludes its blocks and misses its own price by GBP 53.
(Tested by the research code's order-book analysis, gbabm.analysis.compare_blocks, which is not
part of this package.) (epex_pull `blocks` pulls the separate
per-order block file, which is an ORDER-LEVEL view, not a missing piece of the curve.)

Usage:
  python -m gbpowerdata.build.parse_epex_curves --modality hourly 2023      # one year
  python -m gbpowerdata.build.parse_epex_curves --modality hourly 2020 2025 # inclusive range
  python -m gbpowerdata.build.parse_epex_curves --modality hh               # all cached years
"""

from __future__ import annotations

import argparse
import io
import re
import sys
import zipfile

import numpy as np
import pandas as pd

from gbpowerdata import config as cfg
from gbpowerdata.pull.epex_pull import CURVE_RE, RAW_CURVE_DIRS

CET = "Europe/Berlin"
LONDON = "Europe/London"            # pre-2020 hourly files label the hour in GB local time
THRESHOLDS = [-100, -50, 0, 20]     # supply MW offered at/below these £/MWh
QUANTILES = [25, 50, 75, 90]        # supply price at these % of total supply volume
_HOUR_RE = re.compile(r"(\d+)\s*([ab]?)")


def step_curve(price, volume, side: str) -> tuple[np.ndarray, np.ndarray]:
    """Sort to a clean step curve with ONE volume per price.

    Both venues draw the vertical risers of the step function as repeated points at the
    same price -- EPEX lists several rows at the -500 floor -- so taking the first point
    would report only part of the floor block. Collapse each price to the fully-executed
    quantity: the largest cumulative offer for supply, the smallest remaining bid for
    demand. Public so that curve analyses read the curves the same way.
    """
    p, v = np.asarray(price, float), np.asarray(volume, float)
    ok = np.isfinite(p) & np.isfinite(v)
    p, v = p[ok], v[ok]
    if len(p) == 0:
        return p, v
    o = np.argsort(p, kind="mergesort")
    p, v = p[o], v[o]
    edge = np.r_[np.flatnonzero(np.diff(p)) + 1, len(p)]      # end index of each price group
    start = np.r_[0, edge[:-1]]
    agg = np.maximum if side == "supply" else np.minimum
    return p[edge - 1], np.array([agg.reduce(v[a:b]) for a, b in zip(start, edge)])


def epex_day(date) -> pd.Timestamp:
    """EPEX writes the delivery day as DD/MM/YYYY. Plain pd.Timestamp() reads that
    month-first and silently swaps day and month on every day-of-month <= 12."""
    if isinstance(date, str):
        return pd.to_datetime(date.strip(), format="%d/%m/%Y", errors="coerce")
    return pd.to_datetime(date, errors="coerce")


def _ts_cet(date, hour, half_hour):
    """CET (date, hour 1..24 with 3A/3B DST twins, half_hour 1|2) -> UTC period start."""
    hm = _HOUR_RE.match(str(hour).strip().lower())
    day = epex_day(date)
    if not hm or pd.isna(day):
        return pd.NaT
    naive = day + pd.Timedelta(hours=int(hm.group(1)) - 1, minutes=(int(half_hour) - 1) * 30)
    ts = naive.tz_localize(CET, ambiguous=(hm.group(2) != "b"), nonexistent="NaT")
    return pd.NaT if ts is pd.NaT else ts.tz_convert("UTC")


def _sides(s: pd.Series) -> pd.Series:
    return s.map({"Sell": "supply", "Purchase": "demand",
                  "S": "supply", "P": "demand"}).fillna(s)


def _normalise(raw: bytes, inner: str) -> pd.DataFrame:
    """One daily curve file -> [deliveryStart(UTC), side, price, volume].

    Two eras in the flat archives:
      2020+   CSV, CET Date + Hour 1..24 (+ "Quarter hour"/"Half hour" on the hh auction;
              the hourly auction has no sub-hour column).
      2017-19 (hh only) .xls with a Period HHMM column.
    """
    if inner.lower().endswith(".csv"):
        df = pd.read_csv(io.BytesIO(raw), skiprows=1)
        df.columns = [str(c).strip() for c in df.columns]
        # EPEX inconsistently labels the sub-hour column "Quarter hour" or "Half hour".
        df = df.rename(columns={"Quarter hour": "half_hour", "Half hour": "half_hour",
                                "Hour": "hour", "Price": "price", "Volume": "volume",
                                "Sale/Purchase": "side", "Date": "date"})
    else:
        df = pd.read_excel(io.BytesIO(raw), engine="xlrd")
        df.columns = [str(c).strip() for c in df.columns]
        # On the autumn DST day the Period cell is text ("0200B"), so coerce and keep the
        # B suffix as the second occurrence of the repeated hour.
        per = df["Period"].astype(str).str.strip().str.upper()
        df["dst_b"] = per.str.endswith("B")
        per = pd.to_numeric(per.str.rstrip("AB"), errors="coerce")
        df = df[per.notna()]
        per = per[per.notna()].astype(int)
        mins = (per // 100) * 60 + (per % 100)
        df["hour"] = mins // 60 + 1
        df["half_hour"] = (mins % 60 == 30).astype(int) + 1
        df = df.rename(columns={"Date": "date", "Side": "side",
                                "Price (GBP/MWh)": "price", "Volume (MW)": "volume"})
    if "half_hour" not in df.columns:
        df["half_hour"] = 1
    df["side"] = _sides(df["side"])
    if "dst_b" in df.columns:                    # legacy .xls: hour 3 twin came from Period
        hours = [f"{h}b" if b else str(h) for h, b in zip(df["hour"], df["dst_b"])]
    else:
        hours = df["hour"].astype(str)
    # one conversion per delivery period, not per curve point (a day holds tens of thousands of points
    # but at most 50 periods)
    keys = pd.DataFrame({"date": df["date"].to_numpy(), "hour": np.asarray(hours, dtype=str),
                         "half_hour": df["half_hour"].astype(int).to_numpy()})
    uniq = keys.drop_duplicates().copy()
    uniq["deliveryStart"] = [_ts_cet(d, h, hh) for d, h, hh in zip(uniq["date"], uniq["hour"], uniq["half_hour"])]
    df["deliveryStart"] = keys.merge(uniq, on=["date", "hour", "half_hour"], how="left")["deliveryStart"].to_numpy()
    return df[["deliveryStart", "side", "price", "volume"]]


def _normalise_legacy(raw: bytes) -> pd.DataFrame:
    """One pre-2020 per-hour .xls (hourly auction) -> [deliveryStart(UTC), side, price, volume].

    Different era, different conventions: columns are applying_date/hour/side/agg_volume/
    agg_price/order_type, and the hour is 0..23 in EUROPE/LONDON local time (not CET 1..24).

    order_type splits L = "limit" orders, B = block, X = other. Keeping L alone, L+B or
    L+B+X gives an IDENTICAL crossing (checked on 2019 against the legacy price workbooks:
    MAE GBP 0.48, 87.5% of hours within GBP 1 in all three cases), because the L rows already
    cumulate the whole book. Keep L — the extra rows only add duplicate points.
    """
    df = pd.read_excel(io.BytesIO(raw), engine="xlrd")
    df.columns = [str(c).strip() for c in df.columns]
    # The oldest era (2008-2012) has no order_type column at all — same five other
    # columns, one undifferentiated curve. Only filter when the column exists.
    if "order_type" in df.columns:
        df = df[df["order_type"].astype(str).str.upper().eq("L")]
    if df.empty:
        return pd.DataFrame(columns=["deliveryStart", "side", "price", "volume"])
    day = pd.to_datetime(df["applying_date"].iloc[0]).normalize()
    ts = (day + pd.Timedelta(hours=int(df["hour"].iloc[0]))).tz_localize(
        LONDON, ambiguous=True, nonexistent="NaT")
    out = pd.DataFrame({"deliveryStart": pd.NaT if ts is pd.NaT else ts.tz_convert("UTC"),
                        "side": _sides(df["side"]),
                        "price": df["agg_price"].astype(float),
                        "volume": df["agg_volume"].astype(float)})
    return out


def daily_frames(zf: zipfile.ZipFile, inner: str):
    """Yield normalised frames for one archive member — pre-2020 members are themselves
    zips holding 24 per-hour .xls files. Public so that gbpowerdata.build.dayahead_curves
    reads the curves the same way."""
    if inner.lower().endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(zf.read(inner))) as z2:
            for m in sorted(z2.namelist()):
                if m.lower().endswith((".xls", ".csv")):
                    yield _normalise_legacy(z2.read(m))
    elif inner.lower().endswith((".csv", ".xls")):
        yield _normalise(zf.read(inner), inner)


def _period_features(sub: pd.DataFrame) -> dict | None:
    """Anonymous-bid features for one delivery period's supply/demand step curves."""
    s, d = sub[sub["side"] == "supply"], sub[sub["side"] == "demand"]
    sp, sv = step_curve(s["price"], s["volume"], "supply")
    if len(sp) < 2:
        return None
    smax = float(sv.max())
    if smax <= 0:
        return None

    def S(p):                                # cumulative supply MW offered at <= price p
        return float(np.interp(p, sp, sv))

    feats = {"supply_floor_mw": float(sv[0]),       # block at the price floor (<= -£500)
             "supply_at_0_mw": S(0.0),
             "supply_max_mw": smax,
             "demand_max_mw": float(d["volume"].max()) if len(d) else np.nan}
    for t in THRESHOLDS:
        feats[f"supply_le_{'m' if t < 0 else ''}{abs(t)}_mw"] = S(float(t))
    for q in QUANTILES:                      # offer price at q% of total supply volume
        feats[f"supply_p_at_q{q}"] = float(np.interp(q / 100 * smax, sv, sp))
    return feats


def build(year: int, modality: str) -> None:
    rawdir = RAW_CURVE_DIRS[modality]
    zpath = next((z for z in rawdir.glob("*.zip")
                  if CURVE_RE.search(z.name) and int(CURVE_RE.search(z.name).group(1)) == year), None)
    if zpath is None:
        print(f"  {year}: no {modality} curve zip", flush=True)
        return
    rows = []
    with zipfile.ZipFile(zpath) as zf:
        for inner in sorted(zf.namelist()):
            try:
                frames = list(daily_frames(zf, inner))
            except Exception as e:                    # a stray day with an unexpected layout
                print(f"    skip {inner}: {e}", flush=True)
                continue
            for day in frames:
                if day.empty:
                    continue
                for ts, sub in day.dropna(subset=["deliveryStart"]).groupby("deliveryStart"):
                    feats = _period_features(sub)
                    if feats is None:
                        continue
                    feats["deliveryStart"] = ts
                    rows.append(feats)

    df = pd.DataFrame(rows)
    if not df.empty:
        df = (df.drop_duplicates("deliveryStart").sort_values("deliveryStart")
                .reset_index(drop=True))
        df = df[["deliveryStart"] + [c for c in df.columns if c != "deliveryStart"]]
    out = cfg.processed_dir() / f"epex_{modality}_curve_features_{year}.csv"
    df.to_csv(out, index=False)
    print(f"  {year}: {len(df):,} periods | floor {df['supply_floor_mw'].mean():.0f} MW | "
          f"<=£0 {df['supply_at_0_mw'].mean():.0f} MW -> {out.name}"
          if not df.empty else f"  {year}: 0 rows", flush=True)


def main(argv: list[str]) -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("start", type=int, nargs="?")
    p.add_argument("end", type=int, nargs="?")
    p.add_argument("--modality", default="hourly", choices=list(RAW_CURVE_DIRS),
                   help="hourly = the N2EX-comparable auction (default); hh = the 15:30 one")
    a = p.parse_args(argv[1:])
    cached = sorted({int(CURVE_RE.search(z.name).group(1))
                     for z in RAW_CURVE_DIRS[a.modality].glob("*.zip") if CURVE_RE.search(z.name)})
    if a.start is None:
        years = cached
    elif a.end is None:
        years = [a.start]
    else:
        years = list(range(a.start, a.end + 1))
    print(f"Parsing EPEX {a.modality} curve features for {years}", flush=True)
    for y in years:
        build(y, a.modality)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
