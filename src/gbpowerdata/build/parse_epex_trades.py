"""Reduce the EPEX GB intraday-continuous TRADE archives to a per-delivery-period panel.

This is the finest-grained thing in the whole EPEX subscription: every individual
continuous trade, with its price, volume and — uniquely — its EXECUTION TIME. The
day-ahead products only tell you where a market settled; these tell you when and how the
position was built, which is what makes them worth having for an agent-based model.

Input: data/raw/epex/great-britain/intraday/continuous_trades_zips/
       Continuous_Trades{-,_}GB{-,_}YYYY.zip

THREE archive eras, and four ways to double count. All handled here:
  * layout — 2016-18 monthly .xls, 2019 mixed daily .xls/.csv, 2020 daily .csv,
    2021-25 daily .csv.zip (a nested zip). 2021/2022 ship BOTH a .csv and a .csv.zip
    for the same day, so inner files are indexed by date and the .csv.zip preferred;
    taking both would double every 2021 trade.
  * legs — in the MODERN schema every trade appears TWICE, once as the BUY leg and once
    as the SELL leg, sharing a TradeId. We keep the BUY leg. The LEGACY .xls schema has
    no Side column and is already one row per trade — do NOT de-leg it.
  * units — legacy volume is MW and modern is MWh. Legacy is converted with the
    contract's own duration, so a 50 MW half-hour becomes 25 MWh.
  * timezone — legacy stamps are UK LOCAL, modern are UTC.
  * products — several contracts share a delivery window (half-hour, 2-hour, 4-hour
    blocks). Mixing them counts the same energy twice, so the panel is built from the
    half-hourly contract only and the rest are just tallied.

A delivery period also trades across several sessions, and a yearly archive can carry
days belonging to its neighbour, so rows are re-aggregated per period at the end and
clipped to the requested year.

Output: data/processed/epex_trades_halfhourly_{year}.csv, one row per delivery half-hour
  deliveryStart, n_trades, volume_mwh, vwap_gbp, price_min, price_max, price_first,
  price_last, vw_lead_hours, self_trade_share, udb_share
`vw_lead_hours` is the volume-weighted hours between execution and delivery start — how
early, on average, that period's energy actually traded.

Usage:
  python -m gbpowerdata.build.parse_epex_trades 2016 2025
  python -m gbpowerdata.build.parse_epex_trades 2023
"""

from __future__ import annotations

import argparse
import io
import re
import sys
import warnings
import zipfile

import numpy as np
import pandas as pd

from gbpowerdata import config as cfg

warnings.filterwarnings("ignore", module="xlrd")

RAW = cfg.raw_dir() / "epex" / "great-britain" / "intraday" / "continuous_trades_zips"
YEAR_RE = re.compile(r"Continuous_Trades[-_]GB[-_](\d{4})\.zip$")
DATE_RE = re.compile(r"(\d{8})")
MONTH_RE = re.compile(r"UK_Continuous_(\d{6})\.xls$", re.I)
LONDON = "Europe/London"
HH = "GB_Half_Hour_Power"
COLS = ["TradeId", "Product", "deliveryStart", "execution", "Price", "Volume",
        "SelfTrade", "UserDefinedBlock"]


def _product_from_hours(hours: pd.Series) -> np.ndarray:
    """Name the contract from its own delivery duration.

    More robust than the Instrument/Product label: the 2019 workbooks leave Instrument
    entirely blank, so duration is the only thing that identifies a half-hour contract.
    """
    h = hours.round(2)
    return np.where(h.eq(0.5), HH,
                    np.where(h.eq(1.0), "GB_Hour_Power",
                             "GB_Other_" + h.astype(str) + "H"))


# The CSV header was renamed between the 2020 and 2021 platforms; map both onto one set.
_CSV_ALIASES = {
    "TradeId": ("TradeId", "TradeID"),
    "Product": ("Product",),
    "DeliveryStart": ("DeliveryStart", "Delivery Start"),
    "DeliveryEnd": ("DeliveryEnd", "Delivery End"),
    "ExecutionTime": ("ExecutionTime", "Execution time"),
    "Side": ("Side",),
    "Price": ("Price",),
    "Volume": ("Volume", "Quantity (MW)"),
    "SelfTrade": ("SelfTrade", "Is Self Trade"),
    "UserDefinedBlock": ("UserDefinedBlock",),
}


def _pick(df: pd.DataFrame, key: str):
    for c in _CSV_ALIASES[key]:
        if c in df.columns:
            return df[c], c
    return None, None


def _normalise_modern(df: pd.DataFrame) -> pd.DataFrame:
    """CSV era: UTC stamps, mirrored BUY/SELL legs sharing a trade id.

    Two header generations. The 2020 one calls the volume column "Quantity (MW)" and
    means MW, not MWh — multiplying by the contract duration is what keeps 2020 volumes
    on the same footing as every other year.
    """
    side, _ = _pick(df, "Side")
    tid, _ = _pick(df, "TradeId")
    if side is None or tid is None:
        return pd.DataFrame(columns=COLS)
    keep = side.astype(str).str.upper() == "BUY"
    df = df[keep]
    if df.empty:
        return pd.DataFrame(columns=COLS)
    tid, _ = _pick(df, "TradeId")
    df = df.loc[~tid.duplicated()]

    start, _ = _pick(df, "DeliveryStart")
    end, _ = _pick(df, "DeliveryEnd")
    ex, _ = _pick(df, "ExecutionTime")
    vol, vol_col = _pick(df, "Volume")
    prod, _ = _pick(df, "Product")
    tid, _ = _pick(df, "TradeId")
    st, en = (pd.to_datetime(start, utc=True, errors="coerce"),
              pd.to_datetime(end, utc=True, errors="coerce"))
    volume = pd.to_numeric(vol, errors="coerce")
    if vol_col and "MW)" in vol_col:                       # MW -> MWh via the duration
        volume = volume * ((en - st).dt.total_seconds() / 3600.0)
    self_t, _ = _pick(df, "SelfTrade")
    udb, _ = _pick(df, "UserDefinedBlock")
    return pd.DataFrame({
        "TradeId": tid.astype(str),
        "Product": prod.astype(str) if prod is not None else
                   _product_from_hours((en - st).dt.total_seconds() / 3600.0),
        "deliveryStart": st,
        "execution": pd.to_datetime(ex, utc=True, errors="coerce", format="mixed"),
        "Price": pd.to_numeric(df["Price"], errors="coerce"),
        "Volume": volume,
        "SelfTrade": (self_t.astype(str).str.upper().eq("Y") if self_t is not None
                      else pd.Series(False, index=df.index)),
        "UserDefinedBlock": (udb.astype(str).str.upper().eq("Y") if udb is not None
                             else pd.Series(False, index=df.index)),
    })


def _normalise_legacy(df: pd.DataFrame) -> pd.DataFrame:
    """XLS era: UK-local stamps, volume in MW, one row per trade (no Side column)."""
    start = pd.to_datetime(df["Start (UK Local)"], errors="coerce")
    stop = pd.to_datetime(df["Stop (UK Local)"], errors="coerce")
    exec_ = pd.to_datetime(df["Timestamp (UK Local)"], errors="coerce")
    hours = (stop - start).dt.total_seconds() / 3600.0

    def to_utc(s):
        return (s.dt.tz_localize(LONDON, ambiguous=True, nonexistent="shift_forward")
                 .dt.tz_convert("UTC"))

    return pd.DataFrame({
        "TradeId": df["Trade Id"].astype(str),
        "Product": _product_from_hours(hours),
        "deliveryStart": to_utc(start),
        "execution": to_utc(exec_),
        "Price": pd.to_numeric(df["Price (GBP)"], errors="coerce"),
        "Volume": pd.to_numeric(df["Volume (MW)"], errors="coerce") * hours,  # MW -> MWh
        "SelfTrade": False,
        "UserDefinedBlock": False,
    })


def _read_inner(zf: zipfile.ZipFile, inner: str) -> pd.DataFrame:
    """One archive member (nested .csv.zip, plain .csv, or .xls) -> normalised trades."""
    raw = zf.read(inner)
    low = inner.lower()
    if low.endswith(".csv.zip"):
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            name = next((n for n in z.namelist() if n.lower().endswith(".csv")), None)
            if name is None:
                return pd.DataFrame(columns=COLS)
            raw = z.read(name)
        low = ".csv"
    if low.endswith(".csv"):
        # Some generations lead with a "# ..." comment line, others start at the header.
        head = raw[:2000].decode("utf-8", "replace").lstrip()
        df = pd.read_csv(io.BytesIO(raw), skiprows=1 if head.startswith("#") else 0)
        if df.empty:
            return pd.DataFrame(columns=COLS)
        return _normalise_modern(df)
    df = pd.read_excel(io.BytesIO(raw), engine="xlrd")
    if df.empty or "Trade Id" not in df.columns:
        return pd.DataFrame(columns=COLS)
    return _normalise_legacy(df)


def _inner_index(zf: zipfile.ZipFile) -> list[str]:
    """One member per delivery day, preferring the nested .csv.zip when a day ships twice."""
    rank = {".csv.zip": 0, ".csv": 1, ".xls": 2}

    def ext(n):
        low = n.lower()
        return ".csv.zip" if low.endswith(".csv.zip") else \
               ".csv" if low.endswith(".csv") else ".xls" if low.endswith(".xls") else ""

    best: dict[str, tuple[int, str]] = {}
    for n in sorted(zf.namelist()):
        e = ext(n)
        if not e:
            continue
        m = MONTH_RE.search(n) or DATE_RE.search(n)
        key = m.group(1) if m else n            # monthly workbooks key on YYYYMM
        r = rank[e]
        if key not in best or r < best[key][0]:
            best[key] = (r, n)
    return [n for _, n in sorted(best.values(), key=lambda t: t[1])]


def _panel(df: pd.DataFrame) -> pd.DataFrame:
    df = df.dropna(subset=["deliveryStart", "execution", "Price", "Volume"])
    df = df[df["Volume"] > 0]
    if df.empty:
        return pd.DataFrame()
    df = df.sort_values("execution")
    df["pv"] = df["Price"] * df["Volume"]
    df["lv"] = ((df["deliveryStart"] - df["execution"]).dt.total_seconds() / 3600.0) \
        * df["Volume"]
    df["sv"] = df["SelfTrade"].astype(float) * df["Volume"]
    df["uv"] = df["UserDefinedBlock"].astype(float) * df["Volume"]
    g = df.groupby("deliveryStart")
    return pd.DataFrame({
        "n_trades": g.size(), "volume_mwh": g["Volume"].sum(),
        "pv": g["pv"].sum(), "lv": g["lv"].sum(), "sv": g["sv"].sum(), "uv": g["uv"].sum(),
        "price_min": g["Price"].min(), "price_max": g["Price"].max(),
        "price_first": g["Price"].first(), "price_last": g["Price"].last(),
    }).reset_index()


def build(year: int) -> None:
    zpath = next((z for z in RAW.glob("*.zip")
                  if YEAR_RE.search(z.name) and int(YEAR_RE.search(z.name).group(1)) == year),
                 None)
    if zpath is None:
        print(f"  {year}: no trade archive", flush=True)
        return
    frames, products = [], {}
    with zipfile.ZipFile(zpath) as zf:
        inners = _inner_index(zf)
        for i, inner in enumerate(inners):
            try:
                df = _read_inner(zf, inner)
            except Exception as e:
                print(f"    skip {inner}: {e}", flush=True)
                continue
            if df.empty:
                continue
            for p, c in df["Product"].value_counts().items():
                products[p] = products.get(p, 0) + int(c)
            hh = df[df["Product"] == HH]
            if not hh.empty:
                frames.append(_panel(hh))
            if (i + 1) % 100 == 0:
                print(f"    {year}: {i + 1}/{len(inners)} files", flush=True)

    if not frames:
        print(f"  {year}: no half-hourly trades (products seen: {products})", flush=True)
        return
    d = pd.concat(frames, ignore_index=True)
    g = d.groupby("deliveryStart")
    out = pd.DataFrame({
        "n_trades": g["n_trades"].sum(), "volume_mwh": g["volume_mwh"].sum(),
        "vwap_gbp": g["pv"].sum() / g["volume_mwh"].sum(),
        "price_min": g["price_min"].min(), "price_max": g["price_max"].max(),
        "price_first": g["price_first"].first(), "price_last": g["price_last"].last(),
        "vw_lead_hours": g["lv"].sum() / g["volume_mwh"].sum(),
        "self_trade_share": g["sv"].sum() / g["volume_mwh"].sum(),
        "udb_share": g["uv"].sum() / g["volume_mwh"].sum(),
    }).reset_index().sort_values("deliveryStart")
    out = out[out["deliveryStart"].dt.year == year]        # drop neighbour-year spillover
    path = cfg.processed_dir() / f"epex_trades_halfhourly_{year}.csv"
    out.to_csv(path, index=False)
    top = ", ".join(f"{p}:{c:,}" for p, c in
                    sorted(products.items(), key=lambda kv: -kv[1])[:4])
    vwap = (out["vwap_gbp"] * out["volume_mwh"]).sum() / out["volume_mwh"].sum()
    print(f"  {year}: {len(out):,} periods | {out['n_trades'].sum():,.0f} trades | "
          f"mean {out['volume_mwh'].mean():.0f} MWh/period | VWAP GBP {vwap:.2f} | "
          f"lead {out['vw_lead_hours'].mean():.1f} h -> {path.name}", flush=True)
    print(f"        products: {top}", flush=True)


def main(argv: list[str]) -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("start", type=int, nargs="?")
    p.add_argument("end", type=int, nargs="?")
    a = p.parse_args(argv[1:])
    cached = sorted({int(YEAR_RE.search(z.name).group(1)) for z in RAW.glob("*.zip")
                     if YEAR_RE.search(z.name)})
    years = cached if a.start is None else \
        [a.start] if a.end is None else list(range(a.start, a.end + 1))
    print(f"Parsing EPEX GB intraday trades for {years}", flush=True)
    for y in years:
        build(y)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
