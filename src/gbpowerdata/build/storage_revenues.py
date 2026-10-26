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
  bm_offer_mwh, bm_bid_mwh   the accepted volumes behind them (Elexon's indicative period volumes, DISPTAV, the whole
                accepted volume; ebocf_pull --dataset volumes): offers positive, bids negative. The notified energy
                plus these is the unit's position after the BM (docs/AUDIT.md A9-8); empty, not zero, for a month
                without the volume files.
  anc_{dc,dm,dr,sffr,dffr,qr,sr,br,stor}   payments for frequency response and reserve
                (gbpowerdata.build.ancillary_services) where NESO names the unit by its BM unit id: dynamic
                containment, moderation and regulation, static and dynamic FFR (the monthly tenders from January 2019
                and the weekly auctions of December 2019 to November 2021, valued as accepted: within 6% of NESO's
                spend in every month of 2023/24, 70% above it in 2022/23, docs/AUDIT.md A10-5), quick, slow and balancing
                reserve, and STOR's availability (from April 2021). Empty (not zero) before January 2019, when no
                unit-level results were published (ancillary_published).
  total         wholesale + bm + ancillary: a gross margin, before network charges, optimisers' fees, Capacity
                Market payments and imbalance.
  wholesale_imrp   the same notified position valued at LCCC's Intermittent Market Reference Price instead
                (gbpowerdata.common.lccc.imrp: the GB day-ahead hourly price, the N2EX and EPEX auction prices
                weighted by their traded volumes since 2021, open data under the OGL); not part of total. The MID
                prices the position at the half-hour's short-term trades, the IMRP at trading all of it in the
                day-ahead auctions; a battery that moves its position after the auction earns neither exactly.
  cm_gbp        the Capacity Market payments of the agreements linked to the unit (gbpowerdata.build.capacity_market:
                the obligation's share x the auction's indexed price x the month's weighting factor; cm_obligation_mw
                the de-rated MW obligation behind it), from the month the unit entered the market (storage_fleet's
                entry_date, its first evidence of trading; else its first trading month in the table) and in every
                month after, outages included: a unit registered but not yet trading is taken as not yet built, as a
                new build is paid only once built. Zero for a unit linked to no agreement; empty before entry and
                without the capacity_market tables. Not part of total: it is an entitlement before suspensions and
                penalties, and a link by name is an inference (basis in capacity_market_links).

Gaps (what the total leaves out or gets wrong; docs/storage_revenues.md):
  - trading skill and re-trading: the whole notified position is valued at one index price, so a trader that
    bought low and sold high within the day is credited only with the index; tolls, floors and fees between an
    owner and its optimiser are not seen;
  - imbalance: metered output that differs from the notified and accepted position is settled at the system price;
    Elexon publishes each battery unit's metered output (B1610, in gbpowerdata.build.generation_battery), not yet
    read here;
  - Capacity Market payments in total (they are in cm_gbp, for the agreements linked to the unit: 88 of the BM
    storage units by Oct 2026; a T_/E_ unit whose CMU names it otherwise has cm_gbp zero, a supplier or virtual lead
    party unit has it empty);
  - ancillary services before 2019, FFR contracts of 2018 or earlier running into 2019 (the tender reports on NESO's
    portal begin with the round of December 2018), the Enhanced Frequency Response contracts of the 2016 tender (no
    unit-level table) and services sold through an aggregated or non-BM unit;
  - every battery outside the BM (non-BM units sell only to NESO: ancillary_by_unit has their payments).

Units: the battery and pumped storage units active in the year (gbpowerdata.build.bm_units: T_ and E_, kind "bm"), with
their capacity, lead party, trader (the lead party's group in gbpowerdata.build.build_ownership) and optimiser (the
group of the company that bid the unit into NESO's auctions with the largest payments in the month; blank without
any); and the supplier (2__) and virtual lead party (V__) batteries of gbpowerdata.build.storage_fleet trading in the
year (kind "supplier", "vlp"; fleet_units): notified and paid in the BM like the others, from the fleet's entry_date
to its last_seen, named as Elexon's register names them, with capacity_mw the largest MW NESO accepted them for
(capacity_source ancillary_max_mw, a lower bound: no gbp_per_kw_yr) and no trader (the ownership tables cover T_ and
E_ units). A supplier or virtual lead party unit may hold several sites (EDF's "Aggregate Eastern 02").
days = the days of the month inside the unit's activity (bm_units' active_from and active_to); trading = whether
the unit did anything in the market in the month (a notified position, a BM cashflow or an ancillary payment). The
register dates a battery by its files, so a battery registered and notifying only zeros before it trades is active
without trading: in 2025, 24 T_/E_ batteries (1.38 GW, 20% of the batteries' capacity-days) had no notified position, BM
cashflow or ancillary payment, among them Coalburn (from October), Uskmouth (from September) and Thornton Battery
(all year); seven of them first appear in the BM cashflows during 2026. A fleet average is taken over the trading
months (as an index of operating assets would count them), and
gbp_per_kw_yr = total / capacity in kW x 365 / days, the month's margin at an annual rate (none for a unit
registered below 2 MW, a pumped storage station's pumping unit such as Cruachan's T_CRUAD-1: compare such a
station as a whole).

Inputs: data/raw/fpn/{unit}.csv (gbpowerdata.pull.fpn_pull), data/raw/mid_apx_*.csv (gbpowerdata.pull.elexon_pull
mid), data/raw/system_prices/ (gbpowerdata.pull.system_price_pull), data/raw/ebocf/ (gbpowerdata.pull.ebocf_pull),
data/raw/lccc/imrp_actuals.csv (gbpowerdata.pull.lccc_pull imrp-actuals; optional, for wholesale_imrp_gbp),
data/raw/bm_volumes/ (gbpowerdata.pull.ebocf_pull --dataset volumes; optional, for bm_offer_mwh and bm_bid_mwh), and the
processed bm_unit_register_{y}, ownership_bmu_{y}, ancillary_by_unit_{y}, and capacity_market_{y} with
capacity_market_links and storage_fleet (optional, for cm_gbp). A year is built only when
the notifications, the MID and the BM cashflows cover all of it (check_inputs); the current year waits for them.
Nothing licensed is read: the MID comes from Elexon, not from the day-ahead auctions (N2EX, EPEX), and the output
may be shared on the terms of Elexon's and NESO's data.

Output: one row per unit and month (UTC): year, month, unit_id, ngc_id, unit_name, tech, kind, connection,
capacity_mw, capacity_source, lead_party, trader, optimiser, days, has_fpn, fpn_coverage, discharge_mwh, charge_mwh,
bm_offer_mwh, bm_bid_mwh, wholesale_gbp, bm_offer_gbp, bm_bid_gbp, anc_dc_gbp ... anc_stor_gbp, ancillary_published,
total_gbp, gbp_per_kw_yr, price_fallback_share, wholesale_imrp_gbp, cm_obligation_mw, cm_gbp. has_fpn
says whether the unit's notifications reach the month's last half-hour; where they do not, the MWh and wholesale_gbp
are empty (unknown), not zero. fpn_coverage is the share of the month's half-hours inside the unit's activity that
hold a notification: Elexon's archive misses whole days for every unit (notified_share lists them; 40% of November
2020 is missing), and the MWh and wholesale_gbp count the notified half-hours only, so they understate such a month by
about 1 - fpn_coverage (divide by it for an estimate of the whole month).
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
from gbpowerdata.common.elexon import fpn_energy

STORAGE = ("battery", "pumped_storage")
FLEET_KINDS = ("supplier", "vlp")                       # storage_fleet's kinds of unit outside T_ and E_ in the BM
LOWER_BOUND = ("ancillary_max_mw",)                     # a capacity_source that bounds the capacity from below only
SERVICES = ("dc", "dm", "dr", "sffr", "dffr", "qr", "sr", "br", "stor")
ANCILLARY_FROM = pd.Timestamp("2019-01-01", tz="UTC")   # first month with unit-level results (the FFR tenders)
GBP = ["wholesale_gbp", "bm_offer_gbp", "bm_bid_gbp"] + [f"anc_{s}_gbp" for s in SERVICES]
COLUMNS = (["year", "month", "unit_id", "ngc_id", "unit_name", "tech", "kind", "connection", "capacity_mw",
            "capacity_source", "lead_party", "trader", "optimiser", "days", "has_fpn", "fpn_coverage", "trading",
            "discharge_mwh", "charge_mwh", "bm_offer_mwh", "bm_bid_mwh"] + GBP
           + ["ancillary_published", "total_gbp", "gbp_per_kw_yr", "price_fallback_share", "wholesale_imrp_gbp",
              "cm_obligation_mw", "cm_gbp"])
MIN_CAPACITY_MW = 2.0             # below this a unit gets no GBP/kW rate (annualise)


# ---------------------------------------------------------------------------- inputs
def mid_prices(raw: Path | None = None) -> pd.Series:
    """Elexon's market index price (APX/EPEX GB) per half-hour, where it had volume; every mid_apx_*.csv pull
    (gbpowerdata.common.elexon.mid_prices: a period without trades is published at price 0 and left out)."""
    from gbpowerdata.common import elexon

    try:
        return elexon.mid_prices(raw)
    except FileNotFoundError as e:
        raise SystemExit(str(e)) from None


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


def accepted_volumes(year: int | None = None, raw: Path | None = None) -> tuple[pd.DataFrame, set[str]]:
    """The storage units' accepted BM volumes (gbpowerdata.pull.ebocf_pull --dataset volumes): startTime (UTC),
    bmUnit, side and volume_mwh (offers positive, bids negative) of `year` (every year by default), and the months
    (YYYY-MM) that have a volume file."""
    folder = (cfg.raw_dir() if raw is None else Path(raw)) / "bm_volumes"
    files = sorted(folder.glob(f"bm_volumes_{year if year is not None else '*'}-*.csv"))
    cols = ["startTime", "bmUnit", "side", "volume_mwh"]
    parts = [p for p in (pd.read_csv(f, usecols=cols) for f in files) if len(p)]     # quiet months hold no rows
    d = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=cols)
    d["startTime"] = pd.to_datetime(d["startTime"], utc=True)
    return d, {f.stem.split("_")[-1] for f in files}


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
    """The year's active storage units: the register's T_ and E_ units with their trader (the lead party's group), and
    storage_fleet's supplier and virtual lead party units trading in the year (fleet_units)."""
    from gbpowerdata import processed as P

    reg = P.read_bm_unit_register(year, active_only=True)
    u = reg[reg["tech"].isin(STORAGE)].copy()
    try:
        tr = P.read_ownership_bmu(year, role="trader")[["unit_id", "group"]].drop_duplicates("unit_id")
        u = u.merge(tr.rename(columns={"group": "trader"}), on="unit_id", how="left", validate="1:1")
    except FileNotFoundError:
        u["trader"] = pd.NA
    u = u.rename(columns={"party_name": "lead_party"}).assign(kind="bm")
    if "capacity_source" not in u:
        u["capacity_source"] = "register"
    other = fleet_units(year)
    return pd.concat([u, other], ignore_index=True) if len(other) else u.reset_index(drop=True)


def fleet_units(year: int, processed: Path | None = None) -> pd.DataFrame:
    """storage_fleet's supplier (2__) and virtual lead party (V__) units trading in `year` (from entry_date to
    last_seen), as rows of units(): capacity_mw is the largest MW NESO accepted the unit for (capacity_source
    ancillary_max_mw, a lower bound), connection and trader are blank (the ownership tables cover T_ and E_ units).
    Empty without the table."""
    path = (cfg.processed_dir() if processed is None else Path(processed)) / "storage_fleet.csv"
    if not path.exists():
        return pd.DataFrame()
    f = pd.read_csv(path)
    f = f[f["kind"].isin(FLEET_KINDS)]
    entry, seen = pd.to_datetime(f["entry_date"]), pd.to_datetime(f["last_seen"])
    f = f[(entry <= pd.Timestamp(f"{year}-12-31")) & (seen >= pd.Timestamp(f"{year}-01-01"))]
    return pd.DataFrame({"unit_id": f["unit_id"], "ngc_id": f["ngc_id"], "unit_name": f["unit_name"],
                         "tech": f["tech"], "kind": f["kind"], "connection": pd.NA, "capacity_mw": f["capacity_mw"],
                         "capacity_source": f["capacity_source"], "lead_party": f["lead_party"], "trader": pd.NA,
                         "active_from": f["entry_date"], "active_to": f["last_seen"]}).reset_index(drop=True)


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


def notified_share(notified: pd.DatetimeIndex, year: int, active_from, active_to) -> pd.Series:
    """Per month of `year` (YYYY-MM), the share of the half-hours inside the unit's activity that hold a notification.

    Elexon's archive of physical notifications misses whole days for every unit at once (they come back empty from
    its PN stream today as well): 2 Oct and 9-10 Nov 2018, 9-18 Jan and 9-10 Aug 2019, 7 and 20 Jul 2020, 18 days of
    November 2020, eight days of February and two of March 2021 (gbpowerdata.build.stage2d_wind_farms lists them).
    A missing half-hour is an unknown position, not a zero one, so a month's MWh and wholesale_gbp understate it by
    about 1 - fpn_coverage."""
    days = pd.date_range(f"{year}-01-01", f"{year}-12-31", freq="D")
    lo = pd.Timestamp(active_from) if pd.notna(active_from) and str(active_from) != "" else days[0]
    hi = pd.Timestamp(active_to) if pd.notna(active_to) and str(active_to) != "" else days[-1]
    start = max(lo.normalize(), days[0]).tz_localize("UTC")
    end = (min(hi.normalize(), days[-1]) + pd.Timedelta(days=1)).tz_localize("UTC")
    spine = pd.date_range(start, end, freq="30min", inclusive="left")
    if spine.empty:
        return pd.Series(dtype=float)
    have = pd.Series(spine.isin(notified), index=spine)
    return have.groupby(spine.strftime("%Y-%m")).mean()


def valued_at(energy: pd.Series, price: pd.Series) -> pd.Series:
    """Per month (YYYY-MM): the energy valued at `price` over the half-hours it prices; NaN for a month it prices none
    (no price is not a price of zero)."""
    p = price.reindex(energy.index)
    month = energy.index.strftime("%Y-%m")
    gbp = (energy * p).groupby(month).sum(min_count=1)
    return gbp.where(p.notna().groupby(month).any())


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


def annualise(total_gbp, capacity_mw, days, capacity_source=None):
    """GBP per kW per year from a total over `days`; none for a unit registered with less than MIN_CAPACITY_MW
    (a pumped storage station's pumping unit, as Cruachan's T_CRUAD-1 at 1 MW, whose charging belongs to the
    station: compare such stations as a whole), and none where the capacity only bounds the unit's from below
    (capacity_source in LOWER_BOUND: a rate over it would overstate the unit's)."""
    mw = np.asarray(capacity_mw, float)
    d = np.asarray(days, float)
    ok = (mw >= MIN_CAPACITY_MW) & (d > 0)
    if capacity_source is not None:
        ok &= ~pd.Series(capacity_source).isin(LOWER_BOUND).to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(ok, np.asarray(total_gbp, float) / (mw * 1000.0) * 365.0 / d, np.nan)


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


def capacity_payments(year: int, processed: Path | None = None) -> pd.DataFrame | None:
    """(unit, month) -> cm_obligation_mw and cm_gbp: the Capacity Market obligations and payments of the agreements
    linked to the unit (gbpowerdata.build.capacity_market: capacity_market_{y} x capacity_market_links' share); None
    without those tables."""
    processed = cfg.processed_dir() if processed is None else Path(processed)
    pay, links = processed / f"capacity_market_{year}.csv", processed / "capacity_market_links.csv"
    if not (pay.exists() and links.exists()):
        return None
    p = pd.read_csv(pay, usecols=["month", "agreement_id", "auction_id", "obligation_mw", "payment_gbp"])
    p = p.merge(pd.read_csv(links, usecols=["agreement_id", "auction_id", "unit_id", "share"]),
                on=["agreement_id", "auction_id"])
    p["month"] = pd.to_datetime(p["month"]).dt.strftime("%Y-%m")
    p["cm_obligation_mw"] = p["obligation_mw"] * p["share"]
    p["cm_gbp"] = p["payment_gbp"] * p["share"]
    return p.groupby(["unit_id", "month"])[["cm_obligation_mw", "cm_gbp"]].sum()


def optimisers(anc: pd.DataFrame) -> pd.Series:
    """(unit, month) -> the participant group with the largest ancillary payments."""
    if anc.empty:
        return pd.Series(dtype=object)
    g = anc.groupby(["elexon_unit", "month", "participant_group"])["revenue_gbp"].sum().reset_index()
    g = g.sort_values("revenue_gbp", ascending=False).drop_duplicates(["elexon_unit", "month"])
    return g.set_index(["elexon_unit", "month"])["participant_group"]


# ---------------------------------------------------------------------------- build
def build_year(year: int, energy: dict[str, pd.Series], mid: pd.Series, imrp: pd.Series | None = None) -> pd.DataFrame:
    imrp = pd.Series(dtype=float) if imrp is None else imrp
    u = units(year)
    sp = system_prices(year)
    cash = ebocf(year)
    cash["month"] = month_of(cash["startTime"])
    bm = cash.pivot_table(index=["bmUnit", "month"], columns="side", values="cashflow_gbp", aggfunc="sum")
    vol, vol_months = accepted_volumes(year)
    vol["month"] = month_of(vol["startTime"])
    bm_mwh = vol.pivot_table(index=["bmUnit", "month"], columns="side", values="volume_mwh", aggfunc="sum")
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
        wi = valued_at(e[(e.index >= lo) & (e.index < hi)], imrp) if e is not None else pd.Series(dtype=float)
        e_end = e.index.max() if e is not None and len(e) else None
        share = notified_share(e.index, year, r.active_from, r.active_to) if e is not None else pd.Series(dtype=float)
        for month, n in days.items():
            if n == 0:
                continue
            last = pd.Timestamp(f"{month}-01", tz="UTC") + pd.offsets.MonthBegin(1) - pd.Timedelta(minutes=30)
            covered = e_end is not None and e_end >= last      # the file reaches the month's last half-hour
            row = {"year": year, "month": month, "unit_id": r.unit_id, "ngc_id": r.ngc_id, "unit_name": r.unit_name,
                   "tech": r.tech, "kind": r.kind, "connection": r.connection, "capacity_mw": r.capacity_mw,
                   "capacity_source": r.capacity_source, "lead_party": r.lead_party, "trader": r.trader,
                   "optimiser": opt.get((r.unit_id, month), pd.NA), "days": int(n), "has_fpn": covered}
            if covered:
                ww = w.reindex([month]).fillna(0.0).iloc[0]
                row.update(discharge_mwh=ww["discharge_mwh"], charge_mwh=ww["charge_mwh"],
                           wholesale_gbp=ww["wholesale_gbp"], price_fallback_share=ww["price_fallback_share"],
                           fpn_coverage=float(share.get(month, np.nan)),
                           # zero for a month without notifications, as wholesale_gbp; empty without the IMRP
                           wholesale_imrp_gbp=float(wi.get(month, np.nan if imrp.empty else 0.0)))
            else:
                row.update(discharge_mwh=np.nan, charge_mwh=np.nan, wholesale_gbp=np.nan, price_fallback_share=np.nan,
                           fpn_coverage=np.nan, wholesale_imrp_gbp=np.nan)
            row["bm_offer_gbp"] = _value(bm, "offer", (r.unit_id, month))
            row["bm_bid_gbp"] = _value(bm, "bid", (r.unit_id, month))
            for side in ("offer", "bid"):
                row[f"bm_{side}_mwh"] = _value(bm_mwh, side, (r.unit_id, month)) if month in vol_months else np.nan
            published = pd.Timestamp(f"{month}-01", tz="UTC") >= ANCILLARY_FROM
            for s in SERVICES:
                row[f"anc_{s}_gbp"] = _value(anc_m, s.upper(), (r.unit_id, month)) if published else np.nan
            row["ancillary_published"] = published
            rows.append(row)
    out = pd.DataFrame(rows)
    if out.empty:
        return pd.DataFrame(columns=COLUMNS)
    out["total_gbp"] = out[GBP].sum(axis=1, min_count=1)
    out["gbp_per_kw_yr"] = annualise(out["total_gbp"], out["capacity_mw"], out["days"], out["capacity_source"])
    out["trading"] = trading(out)
    out[["cm_obligation_mw", "cm_gbp"]] = capacity_columns(out, capacity_payments(year))
    return out[COLUMNS]


def capacity_columns(t: pd.DataFrame, cm: pd.DataFrame | None, processed: Path | None = None) -> pd.DataFrame:
    """cm_obligation_mw and cm_gbp per row of `t` (unit_id, month, kind, trading), from capacity_payments' `cm`: from
    the unit's entry (built_months: one registered but silent is taken as not yet built, and a new build is paid only
    once built) in every month after it, outages included; zero for a T_/E_ unit with no linked agreement, empty for a
    supplier or virtual lead party unit without one (their CMUs are not linked by unit); empty without the tables."""
    if cm is None:
        return pd.DataFrame({"cm_obligation_mw": np.nan, "cm_gbp": np.nan}, index=t.index)
    key = list(zip(t["unit_id"], t["month"]))
    none = np.where(t["kind"].eq("bm"), 0.0, np.nan)
    built = built_months(t, processed)
    return pd.DataFrame({c: pd.Series([cm[c].get(k, d) for k, d in zip(key, none)], index=t.index).where(built)
                         for c in ("cm_obligation_mw", "cm_gbp")})


def built_months(t: pd.DataFrame, processed: Path | None = None) -> pd.Series:
    """Per row: whether the unit had entered the market by the month (storage_fleet's entry_date); for a unit the
    fleet table does not date (or without it), whether it traded in that month or an earlier one of the table."""
    processed = cfg.processed_dir() if processed is None else Path(processed)
    path = processed / "storage_fleet.csv"
    entry = pd.Series(dtype=object)
    if path.exists():
        f = pd.read_csv(path, usecols=["unit_id", "entry_date"]).dropna()
        entry = f.drop_duplicates("unit_id").set_index("unit_id")["entry_date"].astype(str).str[:7]
    first = t[t["trading"].astype(bool)].groupby("unit_id")["month"].min()
    since = t["unit_id"].map(entry).fillna(t["unit_id"].map(first))
    return since.notna() & (t["month"] >= since.fillna("9999-99"))


def annual(t: pd.DataFrame) -> pd.DataFrame:
    """One row per unit and year: GBP and MWh summed over the months, days and trading days counted, the optimiser of
    the largest ancillary payments, and the margin at an annual rate over all its days and over its trading days."""
    keys = [c for c in ("year", "unit_id", "ngc_id", "unit_name", "tech", "kind", "connection", "capacity_mw",
                        "capacity_source", "lead_party", "trader") if c in t]
    sums = (["days", "trading_days", "discharge_mwh", "charge_mwh"]
            + [c for c in ("bm_offer_mwh", "bm_bid_mwh") if c in t] + GBP + ["total_gbp"]
            + [c for c in ("wholesale_imrp_gbp", "cm_gbp") if c in t])
    t = t.assign(trading_days=t["days"].where(t["trading"].astype(bool), 0))
    a = t.groupby(keys, dropna=False)[sums].sum(min_count=1).reset_index()
    if "fpn_coverage" in t:                 # days-weighted over the months with notifications
        cov = t.dropna(subset=["fpn_coverage"]).assign(_w=lambda x: x["fpn_coverage"] * x["days"])
        cov = cov.groupby("unit_id")[["_w", "days"]].sum()
        a["fpn_coverage"] = a["unit_id"].map(cov["_w"] / cov["days"].where(cov["days"] > 0))
    anc = t.assign(_anc=t[[f"anc_{s}_gbp" for s in SERVICES]].sum(axis=1))
    top = anc[anc["optimiser"].notna()].groupby(["unit_id", "optimiser"])["_anc"].sum().reset_index()
    top = top.sort_values("_anc", ascending=False).drop_duplicates("unit_id").set_index("unit_id")["optimiser"]
    a["optimiser"] = a["unit_id"].map(top)
    source = a["capacity_source"] if "capacity_source" in a else None
    a["gbp_per_kw_yr"] = annualise(a["total_gbp"], a["capacity_mw"], a["days"], source)
    a["gbp_per_kw_yr_trading"] = annualise(a["total_gbp"], a["capacity_mw"], a["trading_days"], source)
    return a


def build(years) -> dict[int, pd.DataFrame]:
    from gbpowerdata.common import lccc

    mid = mid_prices()
    imrp = lccc.imrp()
    if imrp.empty:
        print("  no data/raw/lccc/imrp_actuals.csv: wholesale_imrp_gbp left empty "
              "(python -m gbpowerdata.pull.lccc_pull imrp-actuals)", flush=True)
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
        out[y] = build_year(y, energy, mid, imrp)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--years", nargs=2, type=int, default=[2018, 2025])
    a = ap.parse_args(argv)
    for y, t in build(range(a.years[0], a.years[1] + 1)).items():
        path = cfg.processed_dir() / f"storage_revenue_{y}.csv"
        t.to_csv(path, index=False)
        a = annual(t[t["tech"] == "battery"])
        for label, b in (("T_/E_ batteries", a[a["kind"] == "bm"]), ("supplier and VLP batteries", a[a["kind"] != "bm"])):
            if b.empty:
                continue
            streams = (b[GBP].sum() / 1e6).round(1)
            rated = b[~b["capacity_source"].isin(LOWER_BOUND)]
            tw = (rated["capacity_mw"] * rated["trading_days"] / 365).sum()
            print(f"  {path.name}: {label} {len(b)} ({b['capacity_mw'].sum() / 1e3:.2f} GW), GBP m "
                  f"{streams[streams != 0].to_dict()}, GBP/kW/yr over trading months "
                  f"{rated['total_gbp'].sum() / tw / 1e3 if tw else float('nan'):.0f}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
