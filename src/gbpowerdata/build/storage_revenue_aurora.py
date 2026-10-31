"""Aurora Energy Research's estimate of what each GB battery earned, by unit, day and market, from its leaderboard
export -> data/processed/storage_revenue_aurora_{year}.csv and storage_units_aurora.csv (LICENSED: local only, never
committed or packed).

Why: storage_revenue_{y} estimates each storage unit's margin from public data, stream by stream, and its benchmarks
are NESO's spend on each service and DESNZ's capacity, both fleet totals. Aurora's Flexplorer (in Aurora's Flexible
Energy Service subscription, https://auroraer.com/) estimates the same per asset for its subscribers and exports its
GB leaderboard per day, unit and market. Put next to storage_revenue_{y} unit by unit, it shows where the open method
and a commercial one part (the wholesale valuation, the BM, the units each counts), and it states each unit's energy
capacity and optimiser, which the open data give only in part (storage_fleet's MWh comes from a declared MDV or a
Capacity Market duration class; its optimiser is the bidder in NESO's auctions). It is a second estimate, not a
measurement: Aurora reads the same public notifications, acceptances and auction results, the price a battery traded
its position at is published by no one, and Aurora's methodology is not public. Nothing here changes an open table,
and no open table reads this one: storage_fleet and storage_revenue_{y} stay built from open data only.

Source: the leaderboard export of Flexplorer for Great Britain, downloaded by hand by a subscriber as
leaderboard-gbr-{from}-{to}.zip (one CSV inside; the dates are the range requested, not the range covered) into
data/raw/aurora/ (data/raw/manual/README.md). Its terms are the subscription's: the export and everything derived from
it stay on the subscriber's machine, and numbers taken from it stay out of committed docs and docstrings. Every path
of this stage carries "aurora", which .gitignore, tests/test_repo_hygiene.py and the data pack's licensed-data guard
(datapack.LICENSED) all refuse.

The export: one row per unit, UK local date and market the unit traded in that day, with the unit's attributes
repeated on every row. Columns as Aurora names them: local_date, unit id (Elexon's BM unit id: T_ and E_ units, and
supplier 2__ and virtual lead party V__ units), trading market, region (Great Britain only), balancing zone, battery
name, battery duration (h), storage capacity (MWh), optimiser, registered party (the unit's lead party), commissioned
date (empty in the 2026 export), installed capacity (MW), volume charge and discharge (MWh per MW), cashflow charge
and discharge (GBP per kW). A volume or cashflow is per MW (kW) of that day's installed capacity, and a side the unit
did not trade on is empty. In the wholesale market and the BM the volume is energy (charging negative) and the
cashflow its value (paid to the unit positive, paid by it negative). In the response and reserve services both
volumes are positive, read here as the MW-hours held on each side (the export does not define them), and the cashflow
is the payment for them. Imbalance and Capacity Market payments are not among the markets.

Method:
  read     every leaderboard-gbr-*.zip or .csv in data/raw/aurora/; where two exports hold the same unit, date and
           market, the one reaching the later date wins (then the newer file), so a later download replaces the days
           an earlier one also held.
  markets  the export's names -> wholesale, bm, dc, dm, dr, qr, br (MARKETS); a name not listed stops the build, so a
           market new to a later export is mapped, not dropped.
  scale    MWh = volume x installed MW, GBP = cashflow x installed MW x 1000: the basis of storage_revenue_{y}'s GBP,
           so the two compare unit by unit.
  months   monthly(t) sums a unit's days by calendar month of the local date, with a column per market named as in
           storage_revenue_{y} (wholesale_gbp, bm_gbp, anc_{dc,dm,dr,qr,br}_gbp), total_gbp, and gbp_per_kw_yr over the
           days the unit has rows (storage_revenues.annualise). storage_revenue_{y}'s months are UTC: a local month
           in British Summer Time starts an hour before the UTC one.
  compare  compare(monthly(t), storage_revenue_{y}) puts each stream side by side per unit and month (suffixes
           _aurora and _open; the open bm_gbp is bm_offer_gbp + bm_bid_gbp), with each side's total over these
           streams only (the open table's SFFR, DFFR, SR and STOR are left out, as Aurora has none of them).

Outputs (data/processed/):
  storage_revenue_aurora_{y}.csv  one row per unit, local date and market: date, unit_id, market, capacity_mw,
      charge_mwh, discharge_mwh, charge_gbp, discharge_gbp, gbp (charge + discharge, an empty side counted as zero).
  storage_units_aurora.csv  one row per unit: unit_id, unit_name, capacity_mw (its last day's), energy_mwh,
      duration_h, optimiser, lead_party, balancing_zone, commissioned, first_date, last_date (its first and last day
      with a row).
Read them with gbpowerdata.processed.read_storage_revenue_aurora(year[, monthly=True]) and read_storage_units_aurora().

Usage: python -m gbpowerdata.build.storage_revenue_aurora
"""
from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

import pandas as pd

from gbpowerdata import config as cfg
from gbpowerdata.build.storage_revenues import annualise

PATTERN = "leaderboard-gbr-*"
RAW = {"local_date": "date", "unit id": "unit_id", "trading market": "market", "region": "region",
       "balancing zone": "balancing_zone", "battery name": "unit_name", "battery duration, h": "duration_h",
       "storage capacity, mwh": "energy_mwh", "optimiser": "optimiser", "registered party": "lead_party",
       "commissioned date": "commissioned", "installed capacity, mw": "capacity_mw",
       "volume charge, mwh/mw": "charge_mwh_per_mw", "volume discharge, mwh/mw": "discharge_mwh_per_mw",
       "cashflow charge, gbp/kw": "charge_gbp_per_kw", "cashflow discharge, gbp/kw": "discharge_gbp_per_kw"}
MARKETS = {"Wholesale Market": "wholesale", "Balancing Market": "bm", "Dynamic Containment": "dc",
           "Dynamic Moderation": "dm", "Dynamic Regulation": "dr", "Quick Reserve": "qr", "Balancing Reserve": "br"}
ANCILLARY = ("dc", "dm", "dr", "qr", "br")
STREAMS = ["wholesale_gbp", "bm_gbp"] + [f"anc_{s}_gbp" for s in ANCILLARY]
COLUMNS = ["date", "unit_id", "market", "capacity_mw", "charge_mwh", "discharge_mwh", "charge_gbp", "discharge_gbp",
           "gbp"]
UNIT_COLUMNS = ["unit_id", "unit_name", "capacity_mw", "energy_mwh", "duration_h", "optimiser", "lead_party",
                "balancing_zone", "commissioned", "first_date", "last_date"]


# ---------------------------------------------------------------------------- read
def read_export(path: Path) -> pd.DataFrame:
    """One export (.zip holding one CSV, or the CSV itself) with RAW's column names; raises on a missing column."""
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as z:
            names = [n for n in z.namelist() if n.lower().endswith(".csv")]
            if len(names) != 1:
                raise ValueError(f"{path.name}: expected one CSV inside, found {names}")
            with z.open(names[0]) as f:
                d = pd.read_csv(f)
    else:
        d = pd.read_csv(path)
    missing = sorted(set(RAW) - set(d.columns))
    if missing:
        raise ValueError(f"{path.name}: columns missing from the export: {missing}")
    d = d[list(RAW)].rename(columns=RAW)
    d["date"] = pd.to_datetime(d["date"]).dt.normalize()
    return d


def read(raw: Path | None = None) -> pd.DataFrame:
    """Every export in `raw` (default data/raw/aurora/), the later-reaching one winning where two hold the same unit,
    date and market."""
    raw = cfg.raw_dir() / "aurora" if raw is None else Path(raw)
    files = [p for p in raw.glob(PATTERN) if p.suffix.lower() in (".zip", ".csv")]
    if not files:
        raise SystemExit(f"no {PATTERN}.zip in {raw}: export Flexplorer's GB leaderboard there "
                         "(data/raw/manual/README.md)")
    parts = [read_export(p) for p in files]
    order = sorted(range(len(files)), key=lambda i: (parts[i]["date"].max(), files[i].stat().st_mtime))
    d = pd.concat([parts[i] for i in order], ignore_index=True)
    d = d.drop_duplicates(["date", "unit_id", "market"], keep="last")
    unknown = sorted(set(d["market"]) - set(MARKETS))
    if unknown:
        raise ValueError(f"markets not in MARKETS: {unknown}; map them before building")
    d["market"] = d["market"].map(MARKETS)
    return d.sort_values(["date", "unit_id", "market"]).reset_index(drop=True)


# ---------------------------------------------------------------------------- build
def revenue(d: pd.DataFrame) -> pd.DataFrame:
    """The export's per-MW volumes and per-kW cashflows as MWh and GBP per unit, date and market."""
    out = d[["date", "unit_id", "market", "capacity_mw"]].copy()
    for side in ("charge", "discharge"):
        out[f"{side}_mwh"] = d[f"{side}_mwh_per_mw"] * d["capacity_mw"]
        out[f"{side}_gbp"] = d[f"{side}_gbp_per_kw"] * d["capacity_mw"] * 1000.0
    out["gbp"] = out[["charge_gbp", "discharge_gbp"]].sum(axis=1, min_count=1)
    return out[COLUMNS]


def units(d: pd.DataFrame) -> pd.DataFrame:
    """One row per unit: its attributes on its last day in the export, and its first and last day with a row."""
    last = d.sort_values("date").drop_duplicates("unit_id", keep="last").set_index("unit_id")
    span = d.groupby("unit_id")["date"].agg(first_date="min", last_date="max")
    u = last.join(span).reset_index()
    return u[UNIT_COLUMNS].sort_values("unit_id").reset_index(drop=True)


def monthly(t: pd.DataFrame) -> pd.DataFrame:
    """One row per unit and month (YYYY-MM of the local date): days with a row, the mean installed MW over them, GBP
    per market in storage_revenue_{y}'s column names, total_gbp and gbp_per_kw_yr."""
    t = t.assign(month=pd.to_datetime(t["date"]).dt.strftime("%Y-%m"))
    day = t.drop_duplicates(["unit_id", "date"])
    base = day.groupby(["unit_id", "month"]).agg(days=("date", "nunique"), capacity_mw=("capacity_mw", "mean"))
    gbp = t.pivot_table(index=["unit_id", "month"], columns="market", values="gbp", aggfunc="sum")
    gbp = gbp.rename(columns=lambda m: "wholesale_gbp" if m == "wholesale" else "bm_gbp" if m == "bm" else f"anc_{m}_gbp")
    m = base.join(gbp.reindex(columns=STREAMS)).reset_index()
    m[STREAMS] = m[STREAMS].fillna(0.0)
    m["total_gbp"] = m[STREAMS].sum(axis=1)
    m["gbp_per_kw_yr"] = annualise(m["total_gbp"], m["capacity_mw"], m["days"])
    return m


def compare(aurora: pd.DataFrame, open_: pd.DataFrame) -> pd.DataFrame:
    """Per unit and month in both tables: each stream of monthly(...) (suffix _aurora) next to storage_revenue_{y}'s
    (suffix _open; bm_gbp = bm_offer_gbp + bm_bid_gbp), each side's total over these streams, and the open table's
    has_fpn and fpn_coverage (its wholesale_gbp is empty where has_fpn is false)."""
    o = open_.assign(bm_gbp=open_["bm_offer_gbp"].fillna(0) + open_["bm_bid_gbp"].fillna(0))
    keep = ["unit_id", "month"] + [c for c in ("kind", "capacity_mw", "has_fpn", "fpn_coverage") if c in o]
    o = o[keep + STREAMS].rename(columns={c: f"{c}_open" for c in STREAMS + ["capacity_mw"]})
    a = aurora[["unit_id", "month", "days", "capacity_mw"] + STREAMS].rename(
        columns={c: f"{c}_aurora" for c in STREAMS + ["capacity_mw"]})
    c = a.merge(o, on=["unit_id", "month"], how="inner")
    for side in ("aurora", "open"):
        c[f"total_gbp_{side}"] = c[[f"{s}_{side}" for s in STREAMS]].sum(axis=1, min_count=1)
    return c.sort_values(["month", "unit_id"]).reset_index(drop=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--raw", type=Path, default=None, help="folder of the exports (default data/raw/aurora/)")
    a = ap.parse_args(argv)
    d = read(a.raw)
    t = revenue(d)
    out = cfg.processed_dir()
    for y, g in t.groupby(t["date"].dt.year):
        path = out / f"storage_revenue_aurora_{y}.csv"
        g.to_csv(path, index=False, date_format="%Y-%m-%d")
        print(f"  {path.name}: {g['unit_id'].nunique()} units, {g['date'].min():%Y-%m-%d} to "
              f"{g['date'].max():%Y-%m-%d}, {len(g)} rows", flush=True)
    u = units(d)
    u.to_csv(out / "storage_units_aurora.csv", index=False, date_format="%Y-%m-%d")
    print(f"  storage_units_aurora.csv: {len(u)} units, {u['capacity_mw'].sum():.0f} MW", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
