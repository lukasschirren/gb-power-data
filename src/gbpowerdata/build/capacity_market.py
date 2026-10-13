"""The Capacity Market: what every auction pays per kW in each delivery year, the monthly weighting factors, the de-rating
factors, every capacity agreement's obligation, its monthly payments, and the agreements of the storage BM units
-> data/processed/capacity_market_auctions.csv, capacity_market_weights.csv, capacity_market_derating.csv,
capacity_market_agreements.csv, capacity_market_links.csv and capacity_market_{y}.csv.

Why: capacity payments are a storage unit's one revenue stream fixed years ahead (up to 15 delivery years for a new
build), and the one a model of entry needs as an input rather than an outcome (docs/AUDIT.md A9-4). NESO's register
says who holds which obligation, the regulations what it pays, and LCCC publishes what was paid.

Sources (all open):
  data/raw/neso/cm_register/cmu_*.csv, components_*.csv   NESO's Capacity Market register, the newest snapshot
                         (gbpowerdata.pull.cm_register_pull; NESO Open Data Licence): every capacity market unit
                         (CMU) per auction, its agreement, capacity obligation, traded obligations and termination
  data/raw/neso/cm_register/auction_static_*.csv          the clearing price (GBP/kW/year) and base period per auction
  data/raw/neso/cm_register/auction_capacity_cost_*.csv   capacity awarded per auction and delivery year
  data/raw/neso/cm_register/derating_factors_*.csv        de-rating factors per auction and technology class
  data/raw/lccc/cm_capacity_obligation_by_auction.csv     LCCC's capacity obligation and capacity payments paid, by
                         auction and month (gbpowerdata.pull.lccc_pull; Open Government Licence v3.0)
  data/raw/ons/cpi_index_d7bt.csv                         ONS CPI INDEX 00: ALL ITEMS 2015=100 (gbpowerdata.pull
                         .ons_pull; Open Government Licence v3.0)
  data/raw/bm_units_*.csv                                 Elexon's BM unit register (the storage units for the links)

Rules: The Electricity Capacity Regulations 2014 (SI 2014/2043), Schedule 1, paragraphs 2 and 3 as in force for the
delivery years 2016/17-2025/26 (legislation.gov.uk, the version of 1 Jan 2025; Open Government Licence v3.0). A
delivery year runs from 1 October to 30 September (regulation 2).
  price_gbp_per_kw_year  what an obligation pays per kW per year (para. 3(5)-(6)): the auction's clearing price, for a
                    T-4 auction (and the T-3 auction of 2019, regulation 87C(2)(a)) times CPI_x / CPI_base, where
                    CPI_base is the mean monthly CPI over the auction's base period (1 October to 30 April, NESO's
                    "Base Period for the Agreement") and CPI_x the mean over the winter (1 October to 30 April) before
                    the delivery year; for a T-1 or transitional auction the clearing price itself.
  weighting_factor  month m's share of the year's payment (para. 2): GB demand in that calendar month over the 3 years
                    before, fixed by EMR Settlement before the delivery year. EMR Settlement publishes the factors
                    under terms that reserve all rights, so they are derived here from LCCC's open payments: in a
                    month where an auction's obligation did not change, payment = obligation x price x factor exactly,
                    and a change within the month lowers the payment (para. 3(3A)), so the factor is the largest
                    payment / (obligation x price) over the auctions holding at least WF_MIN_MW in their own delivery
                    years (basis "lccc_payments"). Checked on 10 Oct 2026 against EMR Settlement's historical file:
                    within 1e-7 for 2022/23-2025/26 and 2e-4 for 2017/18-2021/22, once that file's labels of 2018/19 to
                    2020/21 are rotated (it prints 2018/19's factors under 2020/21, 2019/20's under 2018/19 and
                    2020/21's under 2019/20). LCCC's labels are the right ones: the factors recomputed as para. 2
                    defines them from Elexon's transmission demand (ITSDO, the 3 years to May) lie within 0.0022 of
                    LCCC's for 2019/20 and 2020/21 and 0.0040 of the file's, and only LCCC's 2020/21 carries the low
                    April and May of the 2020 lockdown (7.59% and 7.21%; ITSDO 7.63% and 7.25%). 2016/17, from the
                    transitional auction alone, within 3e-3. A year's derived factors sum to 0.99984-1.0 from 2017/18. The
                    one month of a delivery year LCCC has not reported yet is 1 minus the other eleven ("residual"); a
                    year with more missing takes the shape of the three years before, scaled to the rest of the year
                    ("estimated"; 2026/27's lies within 4.2e-3 of EMR Settlement's published factors).
  obligation_mw     an agreement's capacity obligation under one auction, per day: the "Auction Acquired Capacity
                    Obligation" over each delivery year the agreement is valid for, plus the obligations traded in
                    (positive) or out (negative) under that auction ("List of Traded Capacity Obligations" with "Period
                    for which the transfer applies"; a secondary trading row, type ST, holds traded obligations only),
                    nothing from the date the agreement was terminated. The register's "Capacity obligation Summary"
                    states the agreement's total over its auctions, a check (summary_mismatches). A month's obligation
                    is the mean over its days, as transferred obligations pay pro rata to days (para. 3(3)-(3A)).
  payment_gbp       weighting_factor x price x obligation (para. 3(3)): the payment the agreement is entitled to for
                    the month. Not deducted: suspensions (the register states only whether an agreement is suspended
                    now, `suspended`), penalties for system stress events (para. 5-6), withheld or repaid payments; not
                    added: over-delivery payments. A new build CMU is paid only once built (LCCC: obligations and
                    payments "can also be delayed and lost through failure to complete New Build CMU milestones"), which
                    the register does not date. Over the months LCCC reports (reconcile), the payments here are 0.4-5.5%
                    above LCCC's in the 15 auction years where new build CMUs take under 15% of them (the suspended
                    agreements), equal or above where new build takes most of them, and up to twice LCCC's where it
                    was late (T-4-2024 in 2025/26); never more than 0.1% below. Measured 10 Oct 2026, asserted in
                    tests/realdata.
  storage           battery, pumped_storage or compressed_air from the CMU's primary fuel; the auctions to 2020/21
                    state no fuel and call every storage CMU "Storage": a pumped storage station by its name
                    (Dinorwig, Ffestiniog, Foyers, Cruachan), any other a battery (an inference).
  links             the storage BM units (T_/E_ batteries and pumped storage) each agreement belongs to: a component
                    whose Component ID is the unit's Elexon or National Grid id (basis "component_id"), else, for a
                    storage CMU metered as a BM unit (CM Unit Type CMRS), every distinctive word of the unit's
                    register name in the CMU's name or component descriptions (basis "name": an inference, which the
                    capacity check bounds: the CMU's connection capacity may not exceed LINK_CAPACITY_SLACK x the
                    units' capacity + 1 MW). share splits an agreement over its units by capacity.

Known limits: the register is today's, so an obligation traded and later reversed is as the register now states it;
penalties and suspensions are not in the payments; batteries outside the BM (most CM storage, Non CMRS) are linked to
no unit here (docs/DATA_GAPS.md B1: postcodes against the DNO registers); some sites register one CMU per phase and
the name rule splits it over every unit of the site.

Outputs (data/processed/):
  capacity_market_auctions.csv    one row per auction and delivery year it pays for: auction_id (LCCC's form,
                                  "T-4-2020"), auction_name, auction_type, first_delivery_year, delivery_year,
                                  clearing_price_gbp_per_kw_year, base_period, cpi_base, cpi_x, cpi_ratio,
                                  price_gbp_per_kw_year, awarded_mw, cost_at_clearing_price_gbp
  capacity_market_weights.csv     delivery_year, month, weighting_factor, basis
  capacity_market_derating.csv    auction_id, auction_name, primary_fuel, technology_class, duration_h, derating_factor
  capacity_market_agreements.csv  one row per agreement and auction: agreement_id, auction_id, auction_name,
                                  auction_type, row_type (own, traded), cmu_id, cm_unit_name, parent_company,
                                  transmission_or_distribution, cm_unit_type, cm_unit_category, primary_fuel,
                                  technology, storage (battery, pumped_storage, compressed_air; storage_kind),
                                  duration_h, connection_mw, derated_mw, acquired_mw, delivery_years,
                                  first_delivery_year, last_delivery_year, terminated_on, suspended, component_ids
                                  (the components named by a BM unit id)
  capacity_market_links.csv       agreement_id, auction_id, cmu_id, unit_id, unit_name, basis, share
  capacity_market_{y}.csv         per agreement, auction and month of year y: month, delivery_year, agreement_id,
                                  auction_id, cmu_id, cm_unit_category, primary_fuel, technology, storage, duration_h,
                                  transmission_or_distribution, obligation_mw, price_gbp_per_kw_year,
                                  weighting_factor, weighting_basis, payment_gbp
Read them with gbpowerdata.processed.read_capacity_market(year) and read_capacity_market_table(name).

Usage: python -m gbpowerdata.build.capacity_market [--years 2018 2026]
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from gbpowerdata import config as cfg
from gbpowerdata.common import ons

AUCTION = re.compile(r"^(\d{4})-\d{2} \((T-4|T-3|T-1|TR)\)")
INDEXED = ("T-4", "T-3")                 # para. 3(5) and regulation 87C(2)(a)
WF_MIN_MW = 100.0                        # the auctions whose payments give the weighting factors
LINK_CAPACITY_SLACK = 1.1
SEGMENT = re.compile(r"(\d{2}/\d{2}/\d{4})\s*-\s*(\d{2}/\d{2}/\d{4})\s*:\s*(-?[\d.]+)\s*MW")
TRADE = re.compile(r"(T\d+)\s*:\s*(-?[\d.]+)\s*MW")
PERIOD = re.compile(r"(T\d+)\s*:\s*(\d{2}/\d{2}/\d{4})\s*-\s*(\d{2}/\d{2}/\d{4})")
DURATION = re.compile(r"duration\s*([\d.]+)\s*h", re.I)
MONTHS = {m: i for i, m in enumerate(["January", "February", "March", "April", "May", "June", "July", "August",
                                      "September", "October", "November", "December"], 1)}
STORAGE_FUEL = {"Storage - Battery": "battery", "Storage - Pumped": "pumped_storage", "Storage - Compressed Air": "compressed_air"}
PUMPED = re.compile(r"dinorwig|ffestiniog|foyers|cruachan", re.I)   # GB's four pumped storage stations
GENERIC = {"battery", "batteries", "storage", "bess", "ess", "energy", "power", "station", "system", "systems", "limited",
           "ltd", "plc", "the", "and", "site", "project", "unit", "cmu", "phase", "extension", "farm", "park", "solar",
           "grid", "hour", "hours", "pumped", "scheme"}
LCCC_FILE = "cm_capacity_obligation_by_auction.csv"
PAYMENT_ATTRS = ["agreement_id", "auction_id", "cmu_id", "cm_unit_category", "primary_fuel", "technology", "storage",
                 "duration_h", "transmission_or_distribution"]
SINGLE = ("auctions", "weights", "derating", "agreements", "links")


# ---------------------------------------------------------------------------- auctions and prices
def auction_key(name: str) -> tuple[str, int] | None:
    """(type, first delivery year) of a NESO auction name: "2020-21 (T-4) Four Year ..." -> ("T-4", 2020)."""
    m = AUCTION.match(str(name))
    return (m.group(2), int(m.group(1))) if m else None


def auction_id(name: str) -> str | None:
    """LCCC's identifier of an auction: "T-4-2020" for the 2020-21 T-4 auction."""
    k = auction_key(name)
    return f"{k[0]}-{k[1]}" if k else None


def delivery_year_of(month: pd.Timestamp) -> int:
    """The delivery year (its first year) a month falls in: October to December open one."""
    return month.year if month.month >= 10 else month.year - 1


def newest(raw: Path, stem: str) -> Path | None:
    files = sorted((raw / "neso" / "cm_register").glob(f"{stem}_*.csv"))
    return files[-1] if files else None


def read_text(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")


def auctions(static: pd.DataFrame) -> pd.DataFrame:
    """One row per auction from NESO's static data, with its LCCC id, type, first delivery year, clearing price and the
    first year of its base period (blank for T-1 and transitional auctions)."""
    s = static.copy()
    k = s["Auction Name"].map(auction_key)
    s = s[k.notna()]
    k = k[k.notna()]
    return pd.DataFrame({
        "auction_id": s["Auction Name"].map(auction_id), "auction_name": s["Auction Name"],
        "auction_type": [t for t, _ in k], "first_delivery_year": [y for _, y in k],
        "clearing_price_gbp_per_kw_year": pd.to_numeric(s["Clearing Price_GBP per kW per year"], errors="coerce"),
        "base_period": pd.to_numeric(s["Base Period for the Agreement"].str.extract(r"(\d{4})/")[0], errors="coerce"),
        "target_mw": pd.to_numeric(s["Auction Target Capacity_MW"], errors="coerce"),
    }).reset_index(drop=True)


def cpi_ratio(cpi: pd.Series, auction_type: str, base_period, delivery_year: int) -> tuple[float, float, float]:
    """(CPI_base, CPI_x, ratio) for an obligation of `auction_type` in `delivery_year` (para. 3(5)-(6)): 1 for T-1 and
    transitional auctions; NaN where a winter's CPI is not yet published."""
    if auction_type not in INDEXED:
        return np.nan, np.nan, 1.0
    base = ons.winter_mean(cpi, int(base_period)) if pd.notna(base_period) else np.nan
    x = ons.winter_mean(cpi, delivery_year - 1)
    return base, x, x / base


def prices(auct: pd.DataFrame, capcost: pd.DataFrame, cpi: pd.Series) -> pd.DataFrame:
    """Per auction and delivery year it pays for (NESO's capacity-and-cost rows): the indexed price."""
    c = capcost.assign(auction_id=capcost["Auction Name"].map(auction_id),
                       delivery_year=pd.to_numeric(capcost["Delivery Year"].str[:4], errors="coerce"),
                       awarded_mw=pd.to_numeric(capcost["Capacity Awarded"], errors="coerce"),
                       cost_at_clearing_price_gbp=pd.to_numeric(capcost["Forecast Cost_GBP"], errors="coerce"))
    c = c.dropna(subset=["auction_id", "delivery_year"]).astype({"delivery_year": int})
    p = auct.merge(c[["auction_id", "delivery_year", "awarded_mw", "cost_at_clearing_price_gbp"]], on="auction_id")
    r = [cpi_ratio(cpi, t, b, y) for t, b, y in zip(p["auction_type"], p["base_period"], p["delivery_year"])]
    p["cpi_base"], p["cpi_x"], p["cpi_ratio"] = zip(*r) if r else ([], [], [])
    p["price_gbp_per_kw_year"] = p["clearing_price_gbp_per_kw_year"] * p["cpi_ratio"]
    cols = ["auction_id", "auction_name", "auction_type", "first_delivery_year", "delivery_year",
            "clearing_price_gbp_per_kw_year", "base_period", "cpi_base", "cpi_x", "cpi_ratio", "price_gbp_per_kw_year",
            "awarded_mw", "cost_at_clearing_price_gbp"]
    return p[cols].sort_values(["first_delivery_year", "auction_type", "delivery_year"]).reset_index(drop=True)


def derating(table: pd.DataFrame) -> pd.DataFrame:
    """NESO's de-rating factors with the auction id and the storage duration class in hours."""
    return pd.DataFrame({
        "auction_id": table["Auction Name"].map(auction_id), "auction_name": table["Auction Name"],
        "primary_fuel": table["Primary Fuel Type"], "technology_class": table["Generating Technology Class"],
        "duration_h": pd.to_numeric(table["Generating Technology Class"].str.extract(DURATION)[0], errors="coerce"),
        "derating_factor": pd.to_numeric(table["De Rating Factor"], errors="coerce")})


# ---------------------------------------------------------------------------- weighting factors
def lccc_payments(raw: Path) -> pd.DataFrame:
    """LCCC's capacity payments by auction and month: auction_id, delivery_year, month, obligation_mw, payment_gbp,
    suspended."""
    path = raw / "lccc" / LCCC_FILE
    if not path.exists():
        raise FileNotFoundError(f"{path} missing: run `python -m gbpowerdata.pull.lccc_pull capacity-obligation-by-auction`")
    t = pd.read_csv(path)
    month = pd.to_datetime(t["Calendar_Year"].astype(str) + "-" + t["Calendar_Month"].map(MONTHS).astype("Int64").astype(str)
                           + "-01", errors="coerce")
    return pd.DataFrame({"auction_id": t["Auction_Identifier"], "delivery_year": t["Delivery_Year"].astype(str).str[:4]
                         .pipe(pd.to_numeric, errors="coerce"), "month": month,
                         "obligation_mw": pd.to_numeric(t["Auction_Acquired_Capacity_Obligation_MW"], errors="coerce"),
                         "payment_gbp": pd.to_numeric(t["Capacity_Payment_GBP"], errors="coerce"),
                         "suspended": t["Capacity_Payment_Suspension_Flag"].fillna("").astype(str)})


def weighting_factors(paid: pd.DataFrame, price: pd.DataFrame, through: int | None = None) -> pd.DataFrame:
    """Per delivery year and month: the factor implied by LCCC's payments (see the module docstring), the residual
    month, or an estimate from the three years before; delivery years from LCCC's first to `through` (default: the
    last LCCC reports)."""
    p = paid[(paid["suspended"] == "Not Suspended") & (paid["obligation_mw"] >= WF_MIN_MW)]
    p = p.merge(price[["auction_id", "auction_type", "first_delivery_year", "delivery_year", "price_gbp_per_kw_year"]],
                on=["auction_id", "delivery_year"])
    own = np.where(p["auction_type"].isin(INDEXED), p["delivery_year"] >= p["first_delivery_year"],
                   p["delivery_year"] == p["first_delivery_year"])
    p = p[own & (p["price_gbp_per_kw_year"] > 0)]
    implied = p["payment_gbp"] / (p["obligation_mw"] * p["price_gbp_per_kw_year"] * 1000.0)
    wf = implied.groupby([p["delivery_year"].astype(int), p["month"]]).max().to_dict()
    first = int(paid["delivery_year"].min())
    last = int(through if through is not None else paid["delivery_year"].max())
    rows = []
    for dy in range(first, last + 1):
        months = pd.date_range(f"{dy}-10-01", periods=12, freq="MS")
        known = {m: wf[(dy, m)] for m in months if (dy, m) in wf}
        if len(known) == 12:
            rows += [(dy, m, v, "lccc_payments") for m, v in known.items()]
        elif len(known) == 11:
            rows += [(dy, m, known[m], "lccc_payments") if m in known else (dy, m, 1.0 - sum(known.values()), "residual")
                     for m in months]
        else:   # the months LCCC has not reported: the last three years' shape, scaled to the rest of the year
            prev = pd.DataFrame(rows, columns=["delivery_year", "month", "weighting_factor", "basis"])
            prev = prev[prev["delivery_year"].between(dy - 3, dy - 1)]
            if prev.empty:
                continue
            est = prev.groupby(prev["month"].dt.month)["weighting_factor"].mean()
            todo = [m for m in months if m not in known]
            scale = (1.0 - sum(known.values())) / sum(est[m.month] for m in todo)
            rows += [(dy, m, known[m], "lccc_payments") if m in known else (dy, m, est[m.month] * scale, "estimated")
                     for m in months]
    return pd.DataFrame(rows, columns=["delivery_year", "month", "weighting_factor", "basis"])


# ---------------------------------------------------------------------------- agreements and obligations
def parse_date(s: str) -> pd.Timestamp:
    return pd.to_datetime(s, format="%d/%m/%Y", errors="coerce")


def trades(listed: str, periods: str) -> list[tuple[pd.Timestamp, pd.Timestamp, float]]:
    """The traded obligations of one register row: (start, end inclusive, MW), from "T1: -3.900 MW; ..." and
    "T1: 28/11/2024 - 11/12/2024; ..."."""
    mw = {t: float(v) for t, v in TRADE.findall(str(listed))}
    span = {t: (parse_date(a), parse_date(b)) for t, a, b in PERIOD.findall(str(periods))}
    return [(span[t][0], span[t][1], v) for t, v in mw.items() if t in span]


def summary(text: str) -> list[tuple[pd.Timestamp, pd.Timestamp, float]]:
    """The register's "Capacity obligation Summary": (start, end inclusive, MW) segments."""
    return [(parse_date(a), parse_date(b), float(v)) for a, b, v in SEGMENT.findall(str(text))]


def delivery_years(text: str) -> list[int]:
    return sorted({int(y) for y in re.findall(r"(\d{4})/\d{4}", str(text))})


def storage_kind(primary_fuel: str, technology: str, name: str) -> str:
    """battery, pumped_storage or compressed_air from the fuel; the auctions to 2020/21 state no fuel and call every
    storage CMU "Storage": a pumped storage station by its name, any other storage CMU a battery (an inference: the
    other storage of those years was batteries); "" for a CMU that is not storage."""
    if primary_fuel in STORAGE_FUEL:
        return STORAGE_FUEL[primary_fuel]
    if not primary_fuel and str(technology).startswith("Storage"):
        return "pumped_storage" if PUMPED.search(str(name)) else "battery"
    return ""


def agreements(cmu: pd.DataFrame, components: pd.DataFrame | None = None) -> pd.DataFrame:
    """One row per awarded agreement and auction of NESO's register (an agreement holding obligations traded from
    several auctions has a row for each)."""
    a = cmu[cmu["Capacity Agreement Awarded"] == "Yes"].copy()
    a = a[a["Auction Name"].map(auction_key).notna()]
    ids = None
    if components is not None and len(components):
        bmish = components[components["Component ID"].str.match(r"^(T_|E_|2__|V__)", na=False)]
        ids = bmish.groupby(["Auction Name", "CMU ID"])["Component ID"].agg(lambda s: ";".join(sorted(set(s))))
    dys = a["Delivery Years for which Agreement Valid"].map(delivery_years)
    out = pd.DataFrame({
        "agreement_id": a["Unique Agreement Identifier"], "auction_id": a["Auction Name"].map(auction_id),
        "auction_name": a["Auction Name"], "auction_type": a["Auction Name"].map(lambda n: auction_key(n)[0]),
        "row_type": np.where(a["Type"].eq("ST"), "traded", "own"), "cmu_id": a["CMU ID"],
        "cm_unit_name": a["CM Unit Name"], "parent_company": a["Parent Company"],
        "transmission_or_distribution": a["Transmission or Distribution"], "cm_unit_type": a["CM Unit Type"],
        "cm_unit_category": a["CM Unit Category"], "primary_fuel": a["Primary Fuel Type"], "technology": a["CMU Technology"],
        "storage": [storage_kind(f, t, n) for f, t, n in zip(a["Primary Fuel Type"], a["CMU Technology"], a["CM Unit Name"])],
        "duration_h": pd.to_numeric(a["CMU Technology"].str.extract(DURATION)[0], errors="coerce"),
        "connection_mw": pd.to_numeric(a["Connection or DSR Capacity"], errors="coerce"),
        "derated_mw": pd.to_numeric(a["De Rated Capacity"], errors="coerce"),
        "acquired_mw": pd.to_numeric(a["Auction Acquired Capacity Obligation"], errors="coerce").fillna(0.0),
        "delivery_years": a["Delivery Years for which Agreement Valid"],
        "first_delivery_year": dys.map(lambda d: d[0] if d else np.nan),
        "last_delivery_year": dys.map(lambda d: d[-1] if d else np.nan),
        "terminated_on": parse_date(a["Date of Termination of Capacity Agreement"].where(
            a["Capacity Agreement has been Terminated"].eq("Yes"), "")),
        "suspended": a["Has Capacity Agreement been Suspended"],
        "traded": a["List of Traded Capacity Obligations"], "traded_periods": a["Period for which the transfer applies"],
        "obligation_summary": a["Capacity obligation Summary"]})
    out["component_ids"] = [ids.get((n, c), "") if ids is not None else "" for n, c in zip(a["Auction Name"], a["CMU ID"])]
    return out.reset_index(drop=True)


def segments(agr: pd.DataFrame) -> pd.DataFrame:
    """Every obligation segment of every agreement row: row (index into agr), start, end (inclusive), mw. The acquired
    obligation over each valid delivery year of an own row, plus the row's traded obligations; cut at termination."""
    rows = []
    for i, r in enumerate(agr.itertuples(index=False)):
        segs = []
        if r.row_type == "own" and r.acquired_mw:
            segs += [(pd.Timestamp(y, 10, 1), pd.Timestamp(y + 1, 9, 30), r.acquired_mw) for y in delivery_years(r.delivery_years)]
        segs += trades(r.traded, r.traded_periods)
        stop = r.terminated_on
        for s, e, mw in segs:
            if pd.isna(s) or pd.isna(e):
                continue
            if pd.notna(stop):
                if s >= stop:
                    continue
                e = min(e, stop - pd.Timedelta(days=1))
            rows.append((i, s, e, mw))
    return pd.DataFrame(rows, columns=["row", "start", "end", "mw"])


def monthly_obligation(seg: pd.DataFrame, months: pd.DatetimeIndex) -> pd.DataFrame:
    """Per segment row and month: the mean obligation over the month's days (MW); rows with none dropped."""
    if seg.empty:
        return pd.DataFrame(columns=["row", "month", "obligation_mw"])
    s = seg["start"].values.astype("datetime64[D]")[:, None]
    e = seg["end"].values.astype("datetime64[D]")[:, None]
    ms = months.values.astype("datetime64[D]")[None, :]
    me = (months + pd.offsets.MonthEnd(0)).values.astype("datetime64[D]")[None, :]
    days = (np.minimum(e, me) - np.maximum(s, ms)).astype(int) + 1
    days = np.clip(days, 0, None)
    mwdays = days * seg["mw"].values[:, None]
    per = pd.DataFrame(mwdays).assign(row=seg["row"].values).groupby("row").sum()
    long = per.reset_index().melt(id_vars="row", var_name="k", value_name="mwdays")
    long = long[long["mwdays"] != 0]
    long["month"] = months[long["k"].astype(int).values]
    long["obligation_mw"] = long["mwdays"] / long["month"].dt.days_in_month
    return long[["row", "month", "obligation_mw"]].reset_index(drop=True)


def summary_mismatches(agr: pd.DataFrame, seg: pd.DataFrame, tol_mw: float = 0.01) -> pd.DataFrame:
    """Agreements whose rows' obligations do not add up to the register's summary on the summary's segment starts."""
    out = []
    for aid, idx in agr.groupby("agreement_id").groups.items():
        text = agr.loc[idx[0], "obligation_summary"]
        if not text:
            continue
        s = seg[seg["row"].isin(idx)]
        for a, _, mw in summary(text):
            got = s.loc[(s["start"] <= a) & (s["end"] >= a), "mw"].sum()
            if abs(got - mw) > tol_mw:
                out.append((aid, a, mw, got))
    return pd.DataFrame(out, columns=["agreement_id", "date", "summary_mw", "rows_mw"])


def payments(agr: pd.DataFrame, seg: pd.DataFrame, price: pd.DataFrame, weights: pd.DataFrame, year: int) -> pd.DataFrame:
    """The payment of every agreement row in each month of `year` (see payment_gbp in the module docstring)."""
    months = pd.date_range(f"{year}-01-01", periods=12, freq="MS")
    ob = monthly_obligation(seg, months)
    p = ob.join(agr[PAYMENT_ATTRS], on="row")
    p["delivery_year"] = p["month"].map(delivery_year_of)
    p = p.merge(price[["auction_id", "delivery_year", "price_gbp_per_kw_year"]], on=["auction_id", "delivery_year"], how="left")
    w = weights.rename(columns={"basis": "weighting_basis"})
    p = p.merge(w, on=["delivery_year", "month"], how="left")
    p["payment_gbp"] = p["weighting_factor"] * p["price_gbp_per_kw_year"] * 1000.0 * p["obligation_mw"]
    keep = ["month", "delivery_year", *PAYMENT_ATTRS, "obligation_mw", "price_gbp_per_kw_year", "weighting_factor",
            "weighting_basis", "payment_gbp"]
    return p[keep].sort_values(["month", "auction_id", "agreement_id"]).reset_index(drop=True)


def reconcile(pay: pd.DataFrame, paid: pd.DataFrame) -> pd.DataFrame:
    """Per auction and delivery year, over the months LCCC reports: the payments here against LCCC's (every
    suspension flag), their ratio, and the share of the payments here that go to new build CMUs (which LCCC pays
    only once they are built)."""
    key = ["auction_id", "delivery_year", "month"]
    nb = pay["cm_unit_category"].str.startswith("New Build", na=False)
    ours = pay.assign(new_build_gbp=pay["payment_gbp"].where(nb, 0.0)).groupby(key)[["payment_gbp", "new_build_gbp"]].sum()
    theirs = paid.groupby(key)["payment_gbp"].sum().rename("lccc_payment_gbp")
    m = ours.join(theirs, how="inner").reset_index()
    r = m.groupby(["auction_id", "delivery_year"]).agg(months=("month", "nunique"), payment_gbp=("payment_gbp", "sum"),
                                                       new_build_gbp=("new_build_gbp", "sum"),
                                                       lccc_payment_gbp=("lccc_payment_gbp", "sum")).reset_index()
    r["ratio"] = r["payment_gbp"] / r["lccc_payment_gbp"]
    r["new_build_share"] = r["new_build_gbp"] / r["payment_gbp"]
    return r.drop(columns="new_build_gbp")


# ---------------------------------------------------------------------------- links to storage BM units
def id_key(s) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(s).upper())


def name_words(text: str) -> tuple:
    """The distinctive words of a name in order: camel case split, lower case, words of three letters or more, without
    the generic ones (battery, storage, energy, ...)."""
    t = re.sub(r"([a-z])([A-Z])", r"\1 \2", str(text))
    return tuple(dict.fromkeys(w for w in re.findall(r"[a-z]{3,}", t.lower()) if w not in GENERIC))


def name_tokens(text: str) -> frozenset:
    return frozenset(name_words(text))


def name_match(unit_name: str | tuple, cm_text: str) -> bool:
    """Every distinctive word of the unit's name (or the words given) is a word of the CMU's text or, of four letters
    or more, part of a word run together there; or the words run together (six letters or more) are ("Holes Bay" in
    "HOLESBAY")."""
    u = unit_name if isinstance(unit_name, tuple) else name_words(unit_name)
    if not u:
        return False
    words = name_tokens(cm_text)
    joined = re.sub(r"[^a-z]", "", str(cm_text).lower())
    run = "".join(u)
    return all(w in words or (len(w) >= 4 and w in joined) for w in u) or (len(run) >= 6 and run in joined)


def storage_links(agr: pd.DataFrame, components: pd.DataFrame, units: pd.DataFrame) -> pd.DataFrame:
    """The storage BM units each storage agreement belongs to (rules in the module docstring); `units` has unit_id,
    ngc_id, unit_name and capacity_mw."""
    store = agr[agr["storage"].astype(str) != ""]
    if store.empty or units.empty:
        return pd.DataFrame(columns=["agreement_id", "auction_id", "cmu_id", "unit_id", "unit_name", "basis", "share"])
    comp = components.copy()
    comp["conn"] = pd.to_numeric(comp["Connection or DSR Capacity"], errors="coerce")
    by_cmu = comp.groupby(["Auction Name", "CMU ID"]).agg(
        ids=("Component ID", lambda s: {id_key(x) for x in s}), conn=("conn", lambda s: s[s > 0].sum()),
        text=("Description of CMU Components", lambda s: " ".join(sorted(set(s)))))
    u = units.assign(capacity_mw=pd.to_numeric(units["capacity_mw"], errors="coerce").fillna(0.0))
    key = {id_key(x): uid for uid, ng in zip(u["unit_id"], u["ngc_id"]) for x in (uid, ng) if pd.notna(x)}
    cap = u.set_index("unit_id")["capacity_mw"]
    names = u.set_index("unit_id")["unit_name"]
    tokens = {uid: name_words(n) for uid, n in names.items()}
    rows = []
    for r in store.itertuples(index=False):
        c = by_cmu.loc[(r.auction_name, r.cmu_id)] if (r.auction_name, r.cmu_id) in by_cmu.index else None
        hit = sorted({key[k] for k in (c["ids"] if c is not None else ()) if k in key})
        basis = "component_id"
        if not hit and r.cm_unit_type == "CMRS":
            text = f"{r.cm_unit_name} {c['text'] if c is not None else ''}"
            hit = sorted(uid for uid, t in tokens.items() if name_match(t, text))
            basis = "name"
            conn = c["conn"] if c is not None else 0.0
            if hit and conn > LINK_CAPACITY_SLACK * cap[hit].sum() + 1.0:
                hit = []                                  # a larger CMU than the units: another project of the site
        if not hit:
            continue
        total = cap[hit].sum()
        for uid in hit:
            rows.append((r.agreement_id, r.auction_id, r.cmu_id, uid, names[uid], basis,
                         cap[uid] / total if total > 0 else 1.0 / len(hit)))
    return pd.DataFrame(rows, columns=["agreement_id", "auction_id", "cmu_id", "unit_id", "unit_name", "basis", "share"])


# ---------------------------------------------------------------------------- build
def build(years: list[int], raw: Path | None = None) -> dict[str, pd.DataFrame]:
    raw = cfg.raw_dir() if raw is None else Path(raw)
    paths = {s: newest(raw, s) for s in ("cmu", "components", "auction_static", "auction_capacity_cost", "derating_factors")}
    missing = [s for s, p in paths.items() if p is None]
    if missing:
        raise FileNotFoundError(f"no data/raw/neso/cm_register/{missing}_*.csv: run `python -m gbpowerdata.pull.cm_register_pull`")
    cpi = ons.cpi_index(raw)
    auct = auctions(read_text(paths["auction_static"]))
    price = prices(auct, read_text(paths["auction_capacity_cost"]), cpi)
    paid = lccc_payments(raw)
    weights = weighting_factors(paid, price, through=max(delivery_year_of(pd.Timestamp(max(years), 12, 1)),
                                                         int(paid["delivery_year"].max())))
    components = read_text(paths["components"])
    agr = agreements(read_text(paths["cmu"]), components)
    seg = segments(agr)
    out = {"auctions": price, "weights": weights, "derating": derating(read_text(paths["derating_factors"])),
           "agreements": agr.drop(columns=["traded", "traded_periods", "obligation_summary"])}
    try:
        from gbpowerdata.build.storage_fleet import register_units
        units = register_units()
    except FileNotFoundError:
        units = pd.DataFrame(columns=["unit_id", "ngc_id", "unit_name", "capacity_mw"])
    out["links"] = storage_links(agr, components, units)
    for y in years:
        out[y] = payments(agr, seg, price, weights, y)
    out["_check"] = {"summary_mismatches": summary_mismatches(agr, seg), "reconcile": reconcile(
        pd.concat([out[y] for y in years], ignore_index=True), paid), "snapshot": paths["cmu"].name}
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--years", nargs=2, type=int, default=[2018, dt.date.today().year], metavar=("FIRST", "LAST"))
    a = ap.parse_args(argv)
    years = list(range(a.years[0], a.years[1] + 1))
    out = build(years)
    proc = cfg.processed_dir()
    proc.mkdir(parents=True, exist_ok=True)
    for name in SINGLE:
        out[name].to_csv(proc / f"capacity_market_{name}.csv", index=False)
    for y in years:
        out[y].to_csv(proc / f"capacity_market_{y}.csv", index=False)
        s = out[y].groupby("storage")["payment_gbp"].sum() / 1e6
        print(f"  {y}: GBP {out[y]['payment_gbp'].sum() / 1e6:,.1f}m to {out[y]['agreement_id'].nunique():,} agreements "
              f"(batteries {s.get('battery', 0):,.1f}m, pumped storage {s.get('pumped_storage', 0):,.1f}m)")
    chk = out["_check"]
    rec = chk["reconcile"]
    existing = rec[rec["new_build_share"] < 0.05]
    print(f"  register {chk['snapshot']}: {len(out['agreements']):,} agreement rows; obligations differing from the "
          f"register's summary in {chk['summary_mismatches']['agreement_id'].nunique()} agreements")
    print(f"  against LCCC's payments by auction and delivery year: ratio {rec['ratio'].min():.4f}-{rec['ratio'].max():.4f}; "
          f"{existing['ratio'].min():.4f}-{existing['ratio'].max():.4f} where new build takes under 5%")
    links = out["links"]
    print(f"  storage links: {links['unit_id'].nunique()} BM units, {links['agreement_id'].nunique()} agreements "
          f"({links['basis'].value_counts().to_dict()})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
