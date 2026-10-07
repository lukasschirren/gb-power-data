"""What each storage unit in the Balancing Mechanism earned, estimated from public data, by unit and month
-> data/processed/storage_revenue_{year}.csv.

Why: a model of storage needs a check on the money, not only on the dispatch: a battery agent that learns to trade
should earn about what the GB fleet earned, in the same markets and in about the same shares, and a model of who
bids needs to know which traders and optimisers earn the most per MW. Commercial services estimate this per asset
(Aurora's Flexplorer, Modo's index) for their subscribers. This table does the same from public data only, with
every stream in its own column, so a model can be compared on the markets it has.

Streams (GBP per unit and month):
  wholesale     the unit's position as it notified it before gate closure (its final physical notification, the
                net of what it traded day-ahead and intraday) valued at Elexon's market index price (MID, APX/EPEX
                GB: the volume-weighted price of the half-hour's short-term trades, published by Elexon); where the
                MID has no volume, at the system price (price_fallback_share). Discharging earns, charging costs.
                The price at which a position was actually traded is not public, so this is an estimate.
  bm_offer, bm_bid   the cashflow of the unit's accepted Balancing Mechanism offers and bids as Elexon derives it
                (EBOCF, gbpowerdata.pull.ebocf_pull): positive paid to the unit, negative paid by it.
  anc_{dc,dm,dr,sffr,qr,sr,br}   payments for frequency response and reserve (gbpowerdata.build.ancillary_services)
                where NESO names the unit by its BM unit id: dynamic containment, moderation and regulation, static
                FFR, quick, slow and balancing reserve. Empty (not zero) before 2 Oct 2020, when no unit-level
                results were published (ancillary_published).
  total         wholesale + bm + ancillary: a gross margin, before network charges, optimisers' fees, Capacity
                Market payments and imbalance.

Gaps (what the total leaves out or gets wrong; docs/storage_revenues.md):
  - trading skill and re-trading: the whole notified position is valued at one index price, so a trader that
    bought low and sold high within the day is credited only with the index; tolls, floors and fees between an
    owner and its optimiser are not seen;
  - imbalance: metered output that differs from the notified and accepted position is settled at the system price;
    batteries' metered output per unit is not published;
  - Capacity Market payments (a fixed GBP/kW, not trading income; NESO's register links few batteries to BM units);
  - ancillary services before October 2020 (FFR tenders, EFR contracts), services sold through an aggregated or
    non-BM unit, and every battery outside the BM or registered as a virtual lead party unit (V__).

Units: the battery and pumped storage units active in the year (gbpowerdata.build.bm_units: T_ and E_), with their
capacity, lead party, trader (the lead party's group in gbpowerdata.build.build_ownership) and optimiser (the group
of the company that bid the unit into NESO's auctions with the largest payments in the month; blank without any).
days = the days of the month inside the unit's activity (bm_units' active_from and active_to); trading = whether
the unit did anything in the market in the month (a notified position, a BM cashflow or an ancillary payment). The
register dates a battery by its files, so a battery registered and notifying only zeros before it trades is active
without trading: in 2025, 24 batteries (1.38 GW, 20% of the batteries' capacity-days) had no notified position, BM
cashflow or ancillary payment, among them Coalburn (from October), Uskmouth (from September) and Thornton Battery
(all year); seven of them first appear in the BM cashflows during 2026. A fleet average is taken over the trading
months (as an index of operating assets would count them), and
gbp_per_kw_yr = total / capacity in kW x 365 / days, the month's margin at an annual rate (none for a unit
registered below 2 MW, a pumped storage station's pumping unit such as Cruachan's T_CRUAD-1: compare such a
station as a whole).

Inputs: data/raw/fpn/{unit}.csv (gbpowerdata.pull.fpn_pull), data/raw/mid_apx_*.csv (gbpowerdata.pull.elexon_pull
mid), data/raw/system_prices/ (gbpowerdata.pull.system_price_pull), data/raw/ebocf/ (gbpowerdata.pull.ebocf_pull),
and the processed bm_unit_register_{y}, ownership_bmu_{y} and ancillary_by_unit_{y}. A year is built only when
the notifications, the MID and the BM cashflows cover all of it (check_inputs); the current year waits for them.
Nothing licensed is read: the MID comes from Elexon, not from the day-ahead auctions (N2EX, EPEX), and the output
may be shared on the terms of Elexon's and NESO's data.

Output: one row per unit and month (UTC): year, month, unit_id, ngc_id, unit_name, tech, connection, capacity_mw,
lead_party, trader, optimiser, days, has_fpn, discharge_mwh, charge_mwh, wholesale_gbp, bm_offer_gbp, bm_bid_gbp,
anc_dc_gbp ... anc_br_gbp, ancillary_published, total_gbp, gbp_per_kw_yr, price_fallback_share. has_fpn says whether
the unit's notifications reach the month's last half-hour; where they do not, the MWh and wholesale_gbp are empty
(unknown), not zero.
Read it with gbpowerdata.processed.read_storage_revenue(year), or (..., annual=True) for one row per unit.

Usage: python -m gbpowerdata.build.storage_revenues [--years 2018 2025]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from gbpowerdata import config as cfg

STORAGE = ("battery", "pumped_storage")
SERVICES = ("dc", "dm", "dr", "sffr", "qr", "sr", "br")
ANCILLARY_FROM = pd.Timestamp("2020-10-01", tz="UTC")   # first month with unit-level results (2 Oct 2020)
GBP = ["wholesale_gbp", "bm_offer_gbp", "bm_bid_gbp"] + [f"anc_{s}_gbp" for s in SERVICES]
COLUMNS = (["year", "month", "unit_id", "ngc_id", "unit_name", "tech", "connection", "capacity_mw", "lead_party",
            "trader", "optimiser", "days", "has_fpn", "trading", "discharge_mwh", "charge_mwh"] + GBP
           + ["ancillary_published", "total_gbp", "gbp_per_kw_yr", "price_fallback_share"])
MAX_SEGMENT_H = 0.5 + 1e-9        # a notification segment lies within its half-hour
MIN_CAPACITY_MW = 2.0             # below this a unit gets no GBP/kW rate (annualise)


# ---------------------------------------------------------------------------- inputs
def fpn_energy(path: Path) -> pd.Series:
    """A unit's notified energy per half-hour (MWh, signed: export positive), indexed by the UTC start of the
    settlement period: each segment's mean level x its duration, summed over the period's segments."""
    t = pd.read_csv(path, usecols=["timeFrom", "timeTo", "levelFrom", "levelTo"])
    t = t.drop_duplicates(["timeFrom", "timeTo"], keep="last")
    t0 = pd.to_datetime(t["timeFrom"], utc=True)
    t1 = pd.to_datetime(t["timeTo"], utc=True)
    hours = (t1 - t0).dt.total_seconds() / 3600
    if (hours > MAX_SEGMENT_H).any() or (hours < 0).any():
        raise AssertionError(f"storage_revenues: {path.name}: a notification segment outside its half-hour")
    mwh = (t["levelFrom"].astype(float) + t["levelTo"].astype(float)) / 2 * hours
    return mwh.groupby(t0.dt.floor("30min")).sum().rename_axis("startTime")


def mid_prices(raw: Path | None = None) -> pd.Series:
    """Elexon's market index price (APX/EPEX GB) per half-hour, where it had volume; every mid_apx_*.csv pull."""
    raw = cfg.raw_dir() if raw is None else Path(raw)
    files = sorted(raw.glob("mid_apx_*.csv"))
    if not files:
        raise SystemExit("no data/raw/mid_apx_*.csv: run python -m gbpowerdata.pull.elexon_pull mid")
    m = pd.concat([pd.read_csv(f) for f in files], ignore_index=True)
    m = m[m["dataProvider"].astype(str).str.upper().str.startswith("APX") & (m["volume"] > 0)]
    m["startTime"] = pd.to_datetime(m["startTime"], utc=True)
    return m.drop_duplicates("startTime", keep="last").set_index("startTime")["price"].sort_index()


def system_prices(year: int) -> pd.Series:
    from gbpowerdata.build import build_system_prices as SP
    return SP.build(year)["price_gbp_per_mwh"]


def ebocf(year: int, raw: Path | None = None) -> pd.DataFrame:
    """The year's BM cashflows of the storage units (gbpowerdata.pull.ebocf_pull), with the UTC start time."""
    raw = (cfg.raw_dir() if raw is None else Path(raw)) / "ebocf"
    files = [raw / f"ebocf_{year}-{m:02d}.csv" for m in range(1, 13)]
    have = [f for f in files if f.exists()]
    d = pd.concat([pd.read_csv(f) for f in have], ignore_index=True) if have else pd.DataFrame(
        columns=["startTime", "bmUnit", "side", "cashflow_gbp"])
    d["startTime"] = pd.to_datetime(d["startTime"], utc=True)
    return d


def check_inputs(year: int, fpn_end: pd.Timestamp, mid: pd.Series, raw: Path | None = None) -> list[str]:
    """What keeps the year from being built: notifications, MID or BM cashflows that stop before its end."""
    raw = (cfg.raw_dir() if raw is None else Path(raw)) / "ebocf"
    end = pd.Timestamp(f"{year}-12-31 23:30", tz="UTC")
    missing = []
    if fpn_end < end:
        missing.append(f"the notifications end on {fpn_end:%Y-%m-%d} (python -m gbpowerdata.pull.fpn_pull)")
    if mid.empty or mid.index.max() < end - pd.Timedelta(days=1):
        missing.append("the MID ends before the year's end (python -m gbpowerdata.pull.elexon_pull mid)")
    months = [m for m in range(1, 13) if not (raw / f"ebocf_{year}-{m:02d}.csv").exists()]
    if months:
        missing.append(f"BM cashflows of months {months} (python -m gbpowerdata.pull.ebocf_pull)")
    return missing


def units(year: int) -> pd.DataFrame:
    """The year's active storage units with their trader (the lead party's group)."""
    from gbpowerdata import processed as P

    reg = P.read_bm_unit_register(year, active_only=True)
    u = reg[reg["tech"].isin(STORAGE)].copy()
    try:
        tr = P.read_ownership_bmu(year, role="trader")[["unit_id", "group"]].drop_duplicates("unit_id")
        u = u.merge(tr.rename(columns={"group": "trader"}), on="unit_id", how="left", validate="1:1")
    except FileNotFoundError:
        u["trader"] = pd.NA
    return u.rename(columns={"party_name": "lead_party"}).reset_index(drop=True)


def ancillary(year: int) -> pd.DataFrame:
    """The year's ancillary payments to units with an Elexon id (gbpowerdata.build.ancillary_services); empty
    before the first unit-level results."""
    if year < ANCILLARY_FROM.year:
        return pd.DataFrame({"delivery_start": pd.Series(dtype="datetime64[ns, UTC]"),
                             "elexon_unit": pd.Series(dtype=object), "service": pd.Series(dtype=object),
                             "participant_group": pd.Series(dtype=object), "revenue_gbp": pd.Series(dtype=float)})
    path = cfg.processed_dir() / f"ancillary_by_unit_{year}.csv"
    if not path.exists():
        raise SystemExit(f"{path.name} is missing: run python -m gbpowerdata.build.ancillary_services")
    a = pd.read_csv(path, usecols=["delivery_start", "elexon_unit", "service", "participant_group", "revenue_gbp"])
    a["delivery_start"] = pd.to_datetime(a["delivery_start"], utc=True)
    return a[a["elexon_unit"].notna()]


# ---------------------------------------------------------------------------- arithmetic
def month_of(t: pd.Series) -> pd.Series:
    return t.dt.tz_convert("UTC").dt.strftime("%Y-%m")


def active_days(year: int, active_from, active_to) -> pd.Series:
    """Days of each month of `year` inside [active_from, active_to] (blank = open), indexed by YYYY-MM."""
    days = pd.date_range(f"{year}-01-01", f"{year}-12-31", freq="D")
    lo = pd.Timestamp(active_from) if pd.notna(active_from) and str(active_from) != "" else days[0]
    hi = pd.Timestamp(active_to) if pd.notna(active_to) and str(active_to) != "" else days[-1]
    inside = days[(days >= lo.normalize()) & (days <= hi.normalize())]
    out = pd.Series(1, index=inside).groupby(inside.strftime("%Y-%m")).sum()
    return out.reindex(pd.Index(sorted(set(days.strftime("%Y-%m")))), fill_value=0)


def wholesale(energy: pd.Series, mid: pd.Series, sp: pd.Series) -> pd.DataFrame:
    """Per month: discharge and charge MWh, the value of the position at the MID (else the system price) and the
    share of the energy valued at the system price."""
    price = mid.reindex(energy.index)
    fallback = price.isna()
    price = price.fillna(sp.reindex(energy.index))
    unpriced = price.isna() & (energy != 0)
    if unpriced.any():                      # a gap in both pulls: left out of the value, and said so
        print(f"    {int(unpriced.sum())} half-hours with a notified position but no MID or system price "
              f"({energy[unpriced].abs().sum():.0f} MWh) are not valued", flush=True)
    e = energy.to_frame("mwh").assign(gbp=energy * price, fb=energy.abs().where(fallback, 0.0))
    g = e.groupby(month_of(e.index.to_series()))
    out = pd.DataFrame({"discharge_mwh": g["mwh"].apply(lambda s: s.clip(lower=0).sum()),
                        "charge_mwh": g["mwh"].apply(lambda s: -s.clip(upper=0).sum()),
                        "wholesale_gbp": g["gbp"].sum()})
    moved = g["mwh"].apply(lambda s: s.abs().sum())
    out["price_fallback_share"] = (g["fb"].sum() / moved.where(moved > 0)).fillna(0.0)
    return out


def annualise(total_gbp, capacity_mw, days):
    """GBP per kW per year from a total over `days`; none for a unit registered with less than MIN_CAPACITY_MW
    (a pumped storage station's pumping unit, as Cruachan's T_CRUAD-1 at 1 MW, whose charging belongs to the
    station: compare such stations as a whole)."""
    mw = np.asarray(capacity_mw, float)
    d = np.asarray(days, float)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where((mw >= MIN_CAPACITY_MW) & (d > 0), np.asarray(total_gbp, float) / (mw * 1000.0) * 365.0 / d,
                        np.nan)


def _value(table: pd.DataFrame, col: str, key: tuple) -> float:
    """A pivot table's value at (unit, month), zero where the unit had none."""
    if col not in table:
        return 0.0
    v = table[col].get(key, 0.0)
    return 0.0 if pd.isna(v) else float(v)


def trading(t: pd.DataFrame) -> pd.Series:
    """Whether a unit-month did anything in the market: a notified position, a BM cashflow or an ancillary payment."""
    anc = [f"anc_{s}_gbp" for s in SERVICES]
    return ((t[["discharge_mwh", "charge_mwh"]].fillna(0).sum(axis=1) > 0)
            | (t[["bm_offer_gbp", "bm_bid_gbp"]].abs().sum(axis=1) > 0)
            | (t[anc].fillna(0).abs().sum(axis=1) > 0))


def optimisers(anc: pd.DataFrame) -> pd.Series:
    """(unit, month) -> the participant group with the largest ancillary payments."""
    if anc.empty:
        return pd.Series(dtype=object)
    g = anc.groupby(["elexon_unit", "month", "participant_group"])["revenue_gbp"].sum().reset_index()
    g = g.sort_values("revenue_gbp", ascending=False).drop_duplicates(["elexon_unit", "month"])
    return g.set_index(["elexon_unit", "month"])["participant_group"]


# ---------------------------------------------------------------------------- build
def build_year(year: int, energy: dict[str, pd.Series], mid: pd.Series) -> pd.DataFrame:
    u = units(year)
    sp = system_prices(year)
    cash = ebocf(year)
    cash["month"] = month_of(cash["startTime"])
    bm = cash.pivot_table(index=["bmUnit", "month"], columns="side", values="cashflow_gbp", aggfunc="sum")
    anc = ancillary(year).copy()
    anc["month"] = month_of(anc["delivery_start"])
    anc_m = anc.pivot_table(index=["elexon_unit", "month"], columns="service", values="revenue_gbp", aggfunc="sum")
    opt = optimisers(anc)
    lo, hi = pd.Timestamp(f"{year}-01-01", tz="UTC"), pd.Timestamp(f"{year + 1}-01-01", tz="UTC")
    rows = []
    for r in u.itertuples(index=False):
        days = active_days(year, r.active_from, r.active_to)
        e = energy.get(r.unit_id)
        w = wholesale(e[(e.index >= lo) & (e.index < hi)], mid, sp) if e is not None else None
        e_end = e.index.max() if e is not None and len(e) else None
        for month, n in days.items():
            if n == 0:
                continue
            last = pd.Timestamp(f"{month}-01", tz="UTC") + pd.offsets.MonthBegin(1) - pd.Timedelta(minutes=30)
            covered = e_end is not None and e_end >= last      # the file reaches the month's last half-hour
            row = {"year": year, "month": month, "unit_id": r.unit_id, "ngc_id": r.ngc_id, "unit_name": r.unit_name,
                   "tech": r.tech, "connection": r.connection, "capacity_mw": r.capacity_mw,
                   "lead_party": r.lead_party, "trader": r.trader, "optimiser": opt.get((r.unit_id, month), pd.NA),
                   "days": int(n), "has_fpn": covered}
            if covered:
                ww = w.reindex([month]).fillna(0.0).iloc[0]
                row.update(discharge_mwh=ww["discharge_mwh"], charge_mwh=ww["charge_mwh"],
                           wholesale_gbp=ww["wholesale_gbp"], price_fallback_share=ww["price_fallback_share"])
            else:
                row.update(discharge_mwh=np.nan, charge_mwh=np.nan, wholesale_gbp=np.nan, price_fallback_share=np.nan)
            row["bm_offer_gbp"] = _value(bm, "offer", (r.unit_id, month))
            row["bm_bid_gbp"] = _value(bm, "bid", (r.unit_id, month))
            published = pd.Timestamp(f"{month}-01", tz="UTC") >= ANCILLARY_FROM
            for s in SERVICES:
                row[f"anc_{s}_gbp"] = _value(anc_m, s.upper(), (r.unit_id, month)) if published else np.nan
            row["ancillary_published"] = published
            rows.append(row)
    out = pd.DataFrame(rows)
    if out.empty:
        return pd.DataFrame(columns=COLUMNS)
    out["total_gbp"] = out[GBP].sum(axis=1, min_count=1)
    out["gbp_per_kw_yr"] = annualise(out["total_gbp"], out["capacity_mw"], out["days"])
    out["trading"] = trading(out)
    return out[COLUMNS]


def annual(t: pd.DataFrame) -> pd.DataFrame:
    """One row per unit and year: GBP and MWh summed over the months, days and trading days counted, the optimiser of
    the largest ancillary payments, and the margin at an annual rate over all its days and over its trading days."""
    keys = ["year", "unit_id", "ngc_id", "unit_name", "tech", "connection", "capacity_mw", "lead_party", "trader"]
    sums = ["days", "trading_days", "discharge_mwh", "charge_mwh"] + GBP + ["total_gbp"]
    t = t.assign(trading_days=t["days"].where(t["trading"].astype(bool), 0))
    a = t.groupby(keys, dropna=False)[sums].sum(min_count=1).reset_index()
    anc = t.assign(_anc=t[[f"anc_{s}_gbp" for s in SERVICES]].sum(axis=1))
    top = anc[anc["optimiser"].notna()].groupby(["unit_id", "optimiser"])["_anc"].sum().reset_index()
    top = top.sort_values("_anc", ascending=False).drop_duplicates("unit_id").set_index("unit_id")["optimiser"]
    a["optimiser"] = a["unit_id"].map(top)
    a["gbp_per_kw_yr"] = annualise(a["total_gbp"], a["capacity_mw"], a["days"])
    a["gbp_per_kw_yr_trading"] = annualise(a["total_gbp"], a["capacity_mw"], a["trading_days"])
    return a


def build(years) -> dict[int, pd.DataFrame]:
    mid = mid_prices()
    files = {}
    for y in years:
        for uid in units(y)["unit_id"]:
            p = cfg.raw_dir() / "fpn" / f"{uid}.csv"
            if p.exists():
                files[uid] = p
    energy = {uid: fpn_energy(p) for uid, p in files.items()}
    fpn_end = max((e.index.max() for e in energy.values() if len(e)), default=pd.Timestamp(0, tz="UTC"))
    out = {}
    for y in years:
        missing = check_inputs(y, fpn_end, mid)
        if missing:
            print(f"  {y}: not built: " + "; ".join(missing), flush=True)
            continue
        out[y] = build_year(y, energy, mid)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--years", nargs=2, type=int, default=[2018, 2025])
    a = ap.parse_args(argv)
    for y, t in build(range(a.years[0], a.years[1] + 1)).items():
        path = cfg.processed_dir() / f"storage_revenue_{y}.csv"
        t.to_csv(path, index=False)
        b = annual(t[t["tech"] == "battery"])
        streams = (b[GBP].sum() / 1e6).round(1)
        tw = (b["capacity_mw"] * b["trading_days"] / 365).sum()
        print(f"  {path.name}: {t['unit_id'].nunique()} units; batteries {len(b)} "
              f"({b['capacity_mw'].sum() / 1e3:.2f} GW), GBP m {streams[streams != 0].to_dict()}, "
              f"GBP/kW/yr over trading months {b['total_gbp'].sum() / tw / 1e3 if tw else float('nan'):.0f}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
