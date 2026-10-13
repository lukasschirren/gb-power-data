"""Check the aggregated order curves of the GB day-ahead auctions against their published prices, and measure the
volume each auction traded -> data/processed/{venue}_curve_checks_{year}.csv (LICENSED: local only).

Why: the day-ahead curves are the empirical stack a model of the auction is fitted to, so they must be sound before
anything is read off them: a supply curve whose cumulative volume falls as the price rises, or a pair of curves that
does not clear at the price the exchange published, is a parsing error (a swapped day and month, a daylight-saving
twin hour, a block order counted twice) or a gap in the data, not a market fact. The same arithmetic gives each
auction's traded volume, which weights the N2EX and EPEX hourly prices in the GB day-ahead blend
(gbpowerdata.build.build_dayahead_prices), so the blend no longer depends on a volume table this package does not
build.

Sources (licensed: a Nord Pool or EPEX SPOT market-data subscription; never committed or packed):
  n2ex         data/raw/nordpool/curves/{date}.json      N2EX hourly auction: per delivery hour the aggregated supply
                                                          and demand curves of the HOURLY orders (price, cumulative
                                                          volume) and every block order with its accepted volume per
                                                          hour (gbpowerdata.pull.nordpool_pull curves)
               data/raw/nordpool/n2ex_prices_n2ex_*.csv   the published hourly price
               data/raw/nordpool/flows/*.csv              the UK area's flows inside the N2EX auction: the coupled
                                                          borders and the other GB exchange ("GB2") to 2020, North Sea
                                                          Link from 29 Sep 2021 (nordpool_pull flows)
  epex_hourly  data/raw/epex/great-britain/aggregated_curves_hourly/*.zip   EPEX SPOT GB hourly auction
  epex_hh      data/raw/epex/great-britain/aggregated_curves/*.zip          EPEX SPOT GB half-hourly auction (15:30)
               data/raw/epex/great-britain/epex_gb_dayahead_{hourly,hh}_prices_*.csv   published prices
               (gbpowerdata.pull.epex_pull; the curves are read with gbpowerdata.build.parse_epex_curves)

Method, per delivery period:
  curves       each side with one volume per price (parse_epex_curves.step_curve: the full riser at a price), read
               as each exchange defines its curves between their points: Nord Pool's as piecewise linear, EPEX
               SPOT's as steps. Measured on a sample of 2022: read as steps, the EPEX curves give the published
               price to the penny in most periods, read as linear in almost none; N2EX's linear crossing gives
               its price (the rates stay in the local report, being derived from licensed data).
  monotone     supply: the volume at a price is never below the volume at a lower price; demand: never above. A
               fall of more than VOL_TOL_MW anywhere is a violation (n_supply_violations, n_demand_violations).
  crossing     the price at which supply meets demand once the volume outside the curves is added (`balance`):
               from 2021 N2EX's curves hold its hourly orders only, so its accepted block volume (blockOrders) and
               the UK area's net imports inside the auction (North Sea Link from 29 Sep 2021) are added; before
               2021, in the coupled market, its published curves already hold both (N2EX_DECOUPLED_FROM gives the
               measurement). EPEX's curves already include its blocks (epex_pull: adding them again double
               counts). price_gap = crossing - published price; imbalance_mw = the excess supply at the published
               price (positive: more offered than bid there).
  traded_mwh   the volume bought at the published price: N2EX hourly-order demand plus accepted buy blocks; EPEX
               the demand curve at the price. For an hourly auction this is MWh in the hour (MW x 1 h), for the
               half-hourly one MWh in the half-hour (MW x 0.5 h).
  clears       the curves clear at the published price: the crossing is within PRICE_TOL_GBP (or PRICE_TOL_SHARE of
               the price, where wider) of it, or the supply and demand at it differ by at most IMBALANCE_TOL_SHARE of
               the traded volume (a flat curve can move the crossing price along a step without moving the volume;
               on EPEX's step curves supply and demand at a price are intervals, and they must overlap). Empty for
               a period without a published price (EPEX's half-hourly prices are pulled from 2020 only).
  passed       False where a curve is not monotone (whatever the price), else clears (empty where that is).
               failing_dates() lists the dates with a False.
  price range  the lowest and highest price on either curve: the exchange's order price limits as the order book
               shows them (checked against data/reference/dayahead_price_limits.csv where that table exists).

Known limits: in 2016-2020 the GB auctions were coupled to the continent and to each other, so fewer of those
years' hours clear exactly than from 2021, and EPEX's net position is not in the data. Only accepted block volume is
added (a paradoxically rejected block adds nothing). The results, and the dates that fail, are licensed-derived and
stay local: the output names carry n2ex or epex, which .gitignore and the data pack refuse.

Output (one file per venue and year, rows per delivery period, UTC): deliveryStart, balance, published_price,
crossing_price, crossing_price_curves_only, price_gap, imbalance_mw, traded_mwh, sold_mwh, block_buy_mw,
block_sell_mw, net_import_mw, n_supply_points, n_demand_points, n_supply_violations, n_demand_violations,
max_violation_mw, curve_price_min, curve_price_max, monotone, clears, passed.
`failing_dates(df)` lists the delivery dates with at least one failing period.

Usage:
  python -m gbpowerdata.build.dayahead_curves n2ex 2021 2025
  python -m gbpowerdata.build.dayahead_curves epex_hourly 2023
  python -m gbpowerdata.build.dayahead_curves all            # every venue, every year with curves
"""
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

from gbpowerdata import config as cfg
from gbpowerdata.build.parse_epex_curves import daily_frames, step_curve

VENUES = ("n2ex", "epex_hourly", "epex_hh")
# GB left the single day-ahead coupling at the end of 2020. Until then Nord Pool's published UK curves already hold
# the accepted block volume and the implicit flows: measured on every 15th day of 2016-2025, the curves alone
# reproduce the published price in most hours of 2016-2020 and adding blocks or flows breaks that, while from the
# first delivery day of 2021 only the curves plus the accepted blocks (plus North Sea Link's flows from 29 Sep 2021)
# reproduce it, in nearly every hour. (The rates are derived from the licensed data and stay in the local report.)
N2EX_DECOUPLED_FROM = pd.Timestamp("2021-01-01")
VOL_TOL_MW = 1.0                 # a cumulative volume may move against the curve's direction by at most this
PRICE_TOL_GBP = 1.0              # crossing within this of the published price passes,
PRICE_TOL_SHARE = 0.01           # or within this share of it where that is wider
IMBALANCE_TOL_SHARE = 0.005      # ... or an imbalance at the published price within this share of traded volume
COLUMNS = ["deliveryStart", "balance", "published_price", "crossing_price", "crossing_price_curves_only", "price_gap",
           "imbalance_mw", "traded_mwh", "sold_mwh", "block_buy_mw", "block_sell_mw", "net_import_mw",
           "n_supply_points", "n_demand_points", "n_supply_violations", "n_demand_violations", "max_violation_mw",
           "curve_price_min", "curve_price_max", "monotone", "clears", "passed"]
HOURS = {"n2ex": 1.0, "epex_hourly": 1.0, "epex_hh": 0.5}


# ---------------------------------------------------------------------------- curve arithmetic
def violations(price, volume, side: str, tol: float = VOL_TOL_MW) -> tuple[int, float]:
    """(count, largest MW) of the places where a curve runs against its direction by more than `tol`: supply volume
    falling, demand volume rising, as the price rises. Points at one price form a riser and are compared as a group
    (its whole range against the next price's)."""
    p, v = np.asarray(price, float), np.asarray(volume, float)
    ok = np.isfinite(p) & np.isfinite(v)
    p, v = p[ok], v[ok]
    if len(p) < 2:
        return 0, 0.0
    o = np.argsort(p, kind="mergesort")
    p, v = p[o], v[o]
    start = np.r_[0, np.flatnonzero(np.diff(p)) + 1]                    # first point of each price
    lo, hi = np.minimum.reduceat(v, start), np.maximum.reduceat(v, start)
    if side == "supply":
        gap = hi[:-1] - lo[1:]       # volume lost from one price to the next
    else:
        gap = hi[1:] - lo[:-1]       # demand gained from one price to the next
    bad = gap > tol
    return int(bad.sum()), float(gap[bad].max()) if bad.any() else 0.0


def crossing(sp: np.ndarray, sv: np.ndarray, dp: np.ndarray, dv: np.ndarray, shift: float = 0.0) -> float:
    """The price at which supply(p) - demand(p) + shift first reaches zero on the piecewise-linear step curves
    (sp, sv) and (dp, dv), each sorted by price with one volume per price; NaN if it never does inside their price
    range. `shift` is the volume outside the curves (accepted sell blocks - buy blocks + net imports)."""
    if len(sp) < 2 or len(dp) < 2:
        return np.nan
    grid = np.unique(np.concatenate([sp, dp]))
    excess = np.interp(grid, sp, sv) - np.interp(grid, dp, dv) + shift
    up = np.flatnonzero(excess >= 0)
    if len(up) == 0:
        return np.nan
    i = int(up[0])
    if i == 0:
        return float(grid[0])
    x0, x1, e0, e1 = grid[i - 1], grid[i], excess[i - 1], excess[i]
    return float(x1 if e1 == e0 else x0 + (0.0 - e0) * (x1 - x0) / (e1 - e0))


def step_crossing(sp: np.ndarray, sv: np.ndarray, dp: np.ndarray, dv: np.ndarray, shift: float = 0.0) -> float:
    """The lowest price on the step curves (sp, sv) and (dp, dv) at which the volume offered at or below it (plus
    `shift`) covers the volume bid strictly above it; NaN if none in their price range."""
    if len(sp) < 1 or len(dp) < 1:
        return np.nan
    grid = np.unique(np.concatenate([sp, dp]))
    s_at = _at_or_below(sp, sv, grid)
    d_above = _above(dp, dv, grid)
    ok = np.flatnonzero(s_at + shift >= d_above)
    return float(grid[ok[0]]) if len(ok) else np.nan


def _at_or_below(p: np.ndarray, v: np.ndarray, x: np.ndarray, strict: bool = False) -> np.ndarray:
    """A step supply curve's cumulative volume offered at prices <= x (< x if strict); 0 below its first point."""
    i = np.searchsorted(p, x, side="left" if strict else "right") - 1
    return np.where(i >= 0, v[np.clip(i, 0, None)], 0.0)


def _above(p: np.ndarray, v: np.ndarray, x: np.ndarray, inclusive: bool = False) -> np.ndarray:
    """A step demand curve's cumulative volume bid at prices > x (>= x if inclusive). step_curve keeps at each demand
    price the volume bid strictly above it, so the volume above x is that of the last point at or below x (strictly
    below x if inclusive); below the first point, the first point's."""
    i = np.searchsorted(p, x, side="left" if inclusive else "right") - 1
    return v[np.clip(i, 0, None)]


def check_period(supply: pd.DataFrame, demand: pd.DataFrame, published: float, block_sell: float = 0.0,
                 block_buy: float = 0.0, net_import: float = 0.0, hours: float = 1.0, curve: str = "linear") -> dict:
    """The checks of one delivery period from its two curves (columns price, volume) and the published price.

    `curve` is how the exchange defines its curves between their points: "linear" (Nord Pool: the crossing of the
    piecewise-linear curves) or "step" (EPEX SPOT: the published price clears if, at it, the volume offered
    strictly below and at or below it overlaps the volume bid strictly above and at or above it)."""
    n_s, max_s = violations(supply["price"], supply["volume"], "supply")
    n_d, max_d = violations(demand["price"], demand["volume"], "demand")
    sp, sv = step_curve(supply["price"], supply["volume"], "supply")
    dp, dv = step_curve(demand["price"], demand["volume"], "demand")
    shift = block_sell - block_buy + net_import
    cross_fn = step_crossing if curve == "step" else crossing
    cross = cross_fn(sp, sv, dp, dv, shift)
    rec = {"published_price": published, "crossing_price": cross,
           "crossing_price_curves_only": cross_fn(sp, sv, dp, dv, 0.0),
           "block_buy_mw": block_buy, "block_sell_mw": block_sell, "net_import_mw": net_import,
           "n_supply_points": len(supply), "n_demand_points": len(demand),
           "n_supply_violations": n_s, "n_demand_violations": n_d, "max_violation_mw": max(max_s, max_d),
           "curve_price_min": float(np.nanmin(np.r_[sp, dp])) if len(sp) + len(dp) else np.nan,
           "curve_price_max": float(np.nanmax(np.r_[sp, dp])) if len(sp) + len(dp) else np.nan,
           "imbalance_mw": np.nan, "traded_mwh": np.nan, "sold_mwh": np.nan}
    if np.isfinite(published) and len(sp) >= 2 and len(dp) >= 2:
        x = np.array([published])
        if curve == "step":       # supply and demand at the price are intervals (a riser on either curve)
            s_lo, s_hi = _at_or_below(sp, sv, x, strict=True)[0] + shift, _at_or_below(sp, sv, x)[0] + shift
            d_lo, d_hi = _above(dp, dv, x)[0], _above(dp, dv, x, inclusive=True)[0]
            rec["imbalance_mw"] = max(0.0, s_lo - d_hi) - max(0.0, d_lo - s_hi)   # 0 where they overlap
            bought = min(max(d_lo, s_lo), d_hi) + block_buy
            sold = bought - block_buy + block_sell - net_import
        else:
            bought = float(np.interp(published, dp, dv)) + block_buy
            sold = float(np.interp(published, sp, sv)) + block_sell
            rec["imbalance_mw"] = sold + net_import - bought
        rec["traded_mwh"], rec["sold_mwh"] = bought * hours, sold * hours
    rec["price_gap"] = cross - published if np.isfinite(cross) and np.isfinite(published) else np.nan
    rec["monotone"] = bool(n_s == 0 and n_d == 0)
    if np.isfinite(rec["imbalance_mw"]):
        tol_price = max(PRICE_TOL_GBP, PRICE_TOL_SHARE * abs(published))
        rec["clears"] = bool((np.isfinite(rec["price_gap"]) and abs(rec["price_gap"]) <= tol_price)
                             or abs(rec["imbalance_mw"]) <= max(VOL_TOL_MW, IMBALANCE_TOL_SHARE * abs(bought)))
    else:                         # no published price (or no curve): the clearing cannot be checked
        rec["clears"] = None
    # a curve against its direction fails whatever the price; otherwise the clearing decides (unchecked: empty)
    rec["passed"] = False if not rec["monotone"] else rec["clears"]
    return rec


def failing_dates(df: pd.DataFrame, tz: str = "Europe/London") -> pd.DataFrame:
    """Delivery dates (UK local) with at least one failing period (passed False; a period without a published price
    is not checked): date, periods, failed, not_monotone, not_clearing, worst |price_gap|."""
    cols = ["date", "periods", "failed", "not_monotone", "not_clearing", "worst_price_gap"]
    if df.empty:
        return pd.DataFrame(columns=cols)
    d = df.assign(date=pd.to_datetime(df["deliveryStart"], utc=True).dt.tz_convert(tz).dt.date,
                  _failed=df["passed"].map(lambda v: v is False or v == "False" or v == 0),
                  _not_mono=~df["monotone"].astype(bool),
                  _not_clear=df["clears"].map(lambda v: v is False or v == "False" or v == 0))
    g = d.groupby("date").agg(periods=("passed", "size"), failed=("_failed", "sum"), not_monotone=("_not_mono", "sum"),
                              not_clearing=("_not_clear", "sum"),
                              worst_price_gap=("price_gap", lambda s: float(s.abs().max())))
    return g[g["failed"] > 0].reset_index()[cols]


# ---------------------------------------------------------------------------- N2EX
def n2ex_prices(raw: Path | None = None) -> pd.Series:
    raw = Path(raw) if raw is not None else cfg.raw_dir()
    files = sorted((raw / "nordpool").glob("n2ex_prices_n2ex_*.csv"))
    if not files:
        return pd.Series(dtype=float)
    p = pd.concat([pd.read_csv(f, usecols=["deliveryStart", "price"]) for f in files], ignore_index=True)
    p["deliveryStart"] = pd.to_datetime(p["deliveryStart"], utc=True)
    return p.drop_duplicates("deliveryStart", keep="last").set_index("deliveryStart")["price"].sort_index()


def n2ex_net_imports(raw: Path | None = None) -> pd.Series:
    """The UK area's net imports inside the N2EX auction per hour (MW, all its connections; 0 where none)."""
    raw = Path(raw) if raw is not None else cfg.raw_dir()
    files = sorted((raw / "nordpool" / "flows").glob("n2ex_flows_uk_*.csv"))
    if not files:
        return pd.Series(dtype=float)
    f = pd.concat([pd.read_csv(x, usecols=["deliveryStart", "net_mw"]) for x in files], ignore_index=True)
    f["deliveryStart"] = pd.to_datetime(f["deliveryStart"], utc=True)
    return f.groupby("deliveryStart")["net_mw"].sum()


def n2ex_day(path: Path, prices: pd.Series, imports: pd.Series) -> list[dict]:
    """Every delivery hour of one N2EX day file. Before N2EX_DECOUPLED_FROM the published curves already hold the
    blocks and flows, so nothing is added (balance "curves"); from it the accepted blocks and the net imports are
    (balance "curves+blocks+flows")."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    day = pd.to_datetime(data.get("deliveryDateCET") or Path(path).stem, errors="coerce")
    decoupled = bool(pd.notna(day) and day >= N2EX_DECOUPLED_FROM)
    blocks: dict[pd.Timestamp, list[float]] = {}
    for b in data.get("blockOrders") or []:
        sell = str(b.get("side", "")).lower().startswith("s")
        for iv in b.get("intervals") or []:
            acc = float(iv.get("acceptedVolume") or 0.0)
            if acc:
                t = pd.Timestamp(iv["deliveryStart"]).tz_convert("UTC")
                blocks.setdefault(t, [0.0, 0.0])[0 if sell else 1] += abs(acc)
    out = []
    for per in data.get("orderPositions") or []:
        t = pd.Timestamp(per["deliveryStart"]).tz_convert("UTC")
        sup = pd.DataFrame(per.get("supplyCurve") or [], columns=["price", "volume"])
        dem = pd.DataFrame(per.get("demandCurve") or [], columns=["price", "volume"])
        sell_b, buy_b = blocks.get(t, [0.0, 0.0]) if decoupled else (0.0, 0.0)
        flows = float(imports.get(t, 0.0)) if decoupled else 0.0
        rec = check_period(sup, dem, float(prices.get(t, np.nan)), sell_b, buy_b, flows)
        rec["deliveryStart"] = t
        rec["balance"] = "curves+blocks+flows" if decoupled else "curves"
        out.append(rec)
    return out


def n2ex_year(year: int, raw: Path | None = None) -> pd.DataFrame:
    raw = Path(raw) if raw is not None else cfg.raw_dir()
    files = sorted((raw / "nordpool" / "curves").glob(f"{year}-*.json"))
    prices, imports = n2ex_prices(raw), n2ex_net_imports(raw)
    rows = [r for f in files for r in n2ex_day(f, prices, imports)]
    return _frame(rows)


# ---------------------------------------------------------------------------- EPEX
def epex_prices(modality: str, raw: Path | None = None) -> pd.Series:
    raw = Path(raw) if raw is not None else cfg.raw_dir()
    # epex_pull's 2020+ file and, for the hourly auction, its legacy 2008-2019 file (same columns, no overlap)
    files = sorted((raw / "epex" / "great-britain").glob(f"epex_gb_dayahead_{modality}_prices_*.csv"))
    if not files:
        return pd.Series(dtype=float)
    p = pd.concat([pd.read_csv(f, usecols=["deliveryStart", "price_gbp_mwh"]) for f in files], ignore_index=True)
    p["deliveryStart"] = pd.to_datetime(p["deliveryStart"], utc=True)
    return p.drop_duplicates("deliveryStart", keep="last").set_index("deliveryStart")["price_gbp_mwh"].sort_index()


def epex_year(year: int, modality: str, raw: Path | None = None) -> pd.DataFrame:
    from gbpowerdata.pull.epex_pull import CURVE_RE

    raw = Path(raw) if raw is not None else cfg.raw_dir()
    folder = raw / "epex" / "great-britain" / ("aggregated_curves_hourly" if modality == "hourly" else "aggregated_curves")
    zpath = next((z for z in folder.glob("*.zip") if (m := CURVE_RE.search(z.name)) and int(m.group(1)) == year), None)
    if zpath is None:
        return _frame([])
    prices, hours = epex_prices(modality, raw), (1.0 if modality == "hourly" else 0.5)
    rows = []
    with zipfile.ZipFile(zpath) as zf:
        for inner in sorted(zf.namelist()):
            for day in daily_frames(zf, inner):
                for t, sub in day.dropna(subset=["deliveryStart"]).groupby("deliveryStart"):
                    rec = check_period(sub[sub["side"] == "supply"], sub[sub["side"] == "demand"],
                                       float(prices.get(t, np.nan)), hours=hours, curve="step")
                    rec["deliveryStart"] = t
                    rec["balance"] = "curves"
                    rows.append(rec)
    return _frame(rows)


def _frame(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=COLUMNS)
    d = pd.DataFrame(rows).drop_duplicates("deliveryStart").sort_values("deliveryStart").reset_index(drop=True)
    return d[COLUMNS]


def build(venue: str, year: int, raw: Path | None = None) -> pd.DataFrame:
    if venue == "n2ex":
        return n2ex_year(year, raw)
    return epex_year(year, venue.removeprefix("epex_"), raw)


def years_with_curves(venue: str, raw: Path | None = None) -> list[int]:
    raw = Path(raw) if raw is not None else cfg.raw_dir()
    if venue == "n2ex":
        return sorted({int(p.stem[:4]) for p in (raw / "nordpool" / "curves").glob("*.json")})
    from gbpowerdata.pull.epex_pull import CURVE_RE
    folder = raw / "epex" / "great-britain" / ("aggregated_curves_hourly" if venue == "epex_hourly" else "aggregated_curves")
    return sorted({int(m.group(1)) for z in folder.glob("*.zip") if (m := CURVE_RE.search(z.name))})


def output_path(venue: str, year: int) -> Path:
    return cfg.processed_dir() / f"{venue}_curve_checks_{year}.csv"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("venue", choices=[*VENUES, "all"])
    ap.add_argument("years", nargs="*", type=int, help="one year, or first and last (default: every year with curves)")
    a = ap.parse_args(argv)
    for venue in (VENUES if a.venue == "all" else (a.venue,)):
        years = (years_with_curves(venue) if not a.years else
                 [a.years[0]] if len(a.years) == 1 else list(range(a.years[0], a.years[1] + 1)))
        for y in years:
            d = build(venue, y)
            if d.empty:
                print(f"  {venue} {y}: no curves", flush=True)
                continue
            d.to_csv(output_path(venue, y), index=False)
            bad = failing_dates(d)
            checked = d["passed"].notna()
            ok = d.loc[checked, "passed"].astype(bool).mean() if checked.any() else float("nan")
            print(f"  {venue} {y}: {len(d):,} periods, {int(checked.sum()):,} with a published price, {ok:.1%} of "
                  f"those pass; {len(bad)} dates with a failing period; not monotone {int((~d['monotone']).sum())} "
                  f"periods -> {output_path(venue, y).name}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
