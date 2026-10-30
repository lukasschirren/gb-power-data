"""Every contract of LCCC's CfD register with its dates, term, end, status and strike price in 2024 money.

WHY. A projection of what the Contracts for Difference cost by year sums each contract's capacity from the day it
begins to the first day without it, at its strike price in one year's money: the merit-order model's policy-cost
projection reads this table for that, and the CfD figures (capacity in force by year, strike prices by round) read
the same rows. LCCC's register carries the dates and prices, but over four date columns, in two base years of money
and without each contract's status or term; this stage puts them on one row per contract, terminated ones included
(a strike figure counts terminated capacity separately), without the counterparty, its address or the site's place,
so the table can travel with the model inputs.

SOURCES.
  raw/{stage1.cfd_register} (config.yaml: CfD_Register_2026-05-22.xlsx)   LCCC's CfD register, downloaded by hand
      (data/raw/manual/README.md) and pinned for every stage. One row per contract (a project, a phase or a unit of
      one) with its start date once it has started, the expected start date, the start of its target commissioning
      window (TCW) and its target commissioning date, the current installed capacity (MW), the initial strike price
      in its base year's money and the current (indexed) one, the base year, the allocation round and the technology.
  raw/lccc/cfd_contract_portfolio_status.csv   LCCC data portal, dataset cfd-contract-portfolio-status
      (pull.lccc_pull): each contract's status. "Live (Post-FIC)" and "Live (Pre-FIC)" generate under the contract
      (after and before the final installed capacity notice); "Pre-Start Date" (milestone met, being built) and
      "Pre-MDD" (before the milestone delivery date) are contracted and not yet operating; "Terminated" contracts
      are kept with that status. Every register contract must have one.
  reference/cfd_round_params.csv   the contract term by round (15 years; 20 for wind and solar from AR7; 35 for
      Hinkley Point C).

DATES. A contract counts from its start date, else from the register's expected start date (three Live contracts
have no start date yet and count from their expected start), else from its target commissioning date (one AR7
solar farm, Rhigos, 7.6 MW). Hinkley Point C has none of these: both units are placed on 1 July 2030 (HPC_START),
mid-way through EDF's base-case year for unit 1 (EDF, Hinkley Point C project update, 23 January 2024, kept at its
2025 annual results of 20 February 2026); EDF gives no date for unit 2. `dated_by` records which rule dated each
contract (start, expected, edf, target; empty for a terminated contract without a date). A contract that is not
terminated must have a date.

TERM. build_cfd_status.contract_end, the rule cfd_status.csv uses since 13 Oct 2026. The CfD Agreement sets the
Specified Expiry Date as the 15th anniversary of the earlier of the Start Date and the last day of the target
commissioning window, the 20th for offshore, floating offshore, onshore and remote island wind and solar PV from
AR7 (generic CfD Agreement for AR8, May 2026, clause 3 and its drafting notes 4 and 5; cfd_round_params.csv,
KEY_TERM). Biomass conversions end on 31 March 2027 (the model agreement's date for them, CfD Agreement 2013; Drax
unit 1 and Lynemouth, whose low-carbon dispatchable CfDs follow from 1 April 2027 and are not in the register).
Hinkley Point C's bespoke contract runs 35 years, counted here from its placed start, since its own window terms
are not public in the register and either count ends it after 2050. `end` is the first day without the contract.
The register gives the window's start and a target commissioning date. Where that date is later it is the window's
last day (`tcw_end`: AR2's offshore phases 364 days on, AR4 and AR6 solar three months on); where it is not, the
register gives no window length and the window's start stands in for its last day, which can end a contract early
by up to the window's length if it started after its window opened. An expected start counts as the start.

STRIKE PRICES. Rounds before AR7 set strike prices in 2012 money, AR7 in 2024 money, and every contract is indexed
to the consumer price index from its base year. The register's current over initial strike price is therefore
CPI(indexation date) / CPI(base year), the same for every contract of a base year indexed on the same date, and the
ratio of the two base years' modal ratios is the factor that puts 2012 money into 2024 money as the contracts
index it (price_factor: 1.397, from two indexation dates that agree to 1e-4; DESNZ's Lynemouth summary gives
GBP 110.46 in 2012 prices as GBP 154 in 2024 prices). `strike_2024` is the initial (auction) strike price in 2024
money, before later adjustments such as the 2023 removal of balancing charges from generators; `price_factor` is
the one factor, repeated on every row since a CSV keeps no frame attributes.

COLUMNS. contract_id, project, round (the register's allocation round), round_short (FIDeR, AR1, HPC, AR2 ... AR7),
technology (the register's), tech (the owners' class: Offshore, Onshore, Solar, Nuclear, Biomass, Other),
strike_class (Offshore, Floating, Onshore, Solar, Nuclear, Biomass, Tidal, Geothermal), mw (current installed
capacity; 0 where blank), lccc_status (LCCC's wording), status (operating, contracted, terminated), start,
expected_start, tcw_start, target_commissioning (the register's dates), base_year, strike_base (the initial strike
price in the base year's money), strike_current (the register's indexed price), begin, dated_by, term_years,
tcw_end, end, strike_2024, price_factor. Dates are written as YYYY-MM-DD, blank where there is none.

Ported on 30 Oct 2026 from the research repository's scripts/fig_ownership/cfd_fleet.py (`load_all`, `_dates`,
`price_factor`, `live`), whose classes TECH and STATUS come from its cfd_holders.py; the place part (the site's
coordinates and nearest GSP region) stays there. The research table's non-terminated rows and this table's agree
on every shared column.

OUTPUT processed/cfd_contracts.csv, one row per register contract.
READ BY the merit-order model's policy-cost projection (the contract table it sums) and its CfD figures,
`processed.read_cfd_contracts()`, `modelinputs`.
RUN    python -m gbpowerdata.build.cfd_contracts [--register FILE] [--status FILE]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from gbpowerdata import config as cfg
from gbpowerdata.build.build_cfd_status import KEY_TERM, contract_end

OUT = "cfd_contracts.csv"
STATUS_FILE = "lccc/cfd_contract_portfolio_status.csv"     # under raw/
TERMS_FILE = "cfd_round_params.csv"                        # under reference/
HPC_START = pd.Timestamp("2030-07-01")                     # module docstring, DATES
# the register's technology -> the owners' class, and LCCC's status -> operating, contracted or terminated: copied
# from the research repository's scripts/fig_ownership/cfd_holders.py (TECH, STATUS), so the CfD figures there
# and this table class a contract the same way
TECH = {"Offshore Wind": "Offshore", "Floating Offshore Wind": "Offshore",
        "Onshore Wind": "Onshore", "Remote Island Wind": "Onshore",
        "Solar PV": "Solar", "Nuclear": "Nuclear",
        "Biomass Conversion": "Biomass", "Dedicated Biomass": "Biomass",
        "Advanced Conversion Technology": "Biomass", "Energy from Waste": "Biomass",
        "Tidal Stream": "Other", "Geothermal": "Other"}
STATUS = {"Live (Post-FIC)": "operating", "Live (Pre-FIC)": "operating",
          "Pre-Start Date": "contracted", "Pre-MDD": "contracted", "Terminated": "terminated"}
# the strike classes (cfd_fleet.STRIKE_CLASS there): the owners' classes with floating offshore wind, tidal stream
# and geothermal apart, since their prices differ from the class they join in TECH
STRIKE_CLASS = {"Offshore Wind": "Offshore", "Floating Offshore Wind": "Floating",
                "Onshore Wind": "Onshore", "Remote Island Wind": "Onshore", "Solar PV": "Solar",
                "Nuclear": "Nuclear", "Biomass Conversion": "Biomass", "Dedicated Biomass": "Biomass",
                "Advanced Conversion Technology": "Biomass", "Energy from Waste": "Biomass",
                "Tidal Stream": "Tidal", "Geothermal": "Geothermal"}
# allocation rounds in the order they were awarded, with the short name (cfd_fleet.ROUNDS there): DECC's eight
# investment contracts of 23 April 2014, Hinkley Point C's bespoke contract of 29 September 2016, the rounds
ROUNDS = (("Investment Contract", "FIDeR"), ("Allocation Round 1", "AR1"), ("Bespoke", "HPC"),
          ("Allocation Round 2", "AR2"), ("Allocation Round 3", "AR3"), ("Allocation Round 4", "AR4"),
          ("Allocation Round 5", "AR5"), ("Allocation Round 6", "AR6"), ("Allocation Round 7", "AR7"))
# price_factor: the band the 2012 -> 2024 factor must fall in, how closely the two indexation dates must agree,
# and how many contracts must share a ratio for it to count as an indexation date
FACTOR_BAND = (1.38, 1.41)
FACTOR_TOLERANCE = 5e-4
SHARED_MIN = 20
DATE_COLUMNS = ("start", "expected_start", "tcw_start", "target_commissioning", "begin", "tcw_end", "end")
COLUMNS = ("contract_id", "project", "round", "round_short", "technology", "tech", "strike_class", "mw",
           "lccc_status", "status", "start", "expected_start", "tcw_start", "target_commissioning", "base_year",
           "strike_base", "strike_current", "begin", "dated_by", "term_years", "tcw_end", "end", "strike_2024",
           "price_factor")


def _date(s: pd.Series) -> pd.Series:
    """The register's date strings as naive midnight timestamps; NaT where blank."""
    return pd.to_datetime(s, errors="coerce", utc=True).dt.tz_localize(None).dt.normalize()


def load_register(path: Path | None = None) -> pd.DataFrame:
    """The register snapshot config.yaml pins (or `path`), every row and column as LCCC publishes it."""
    p = Path(path) if path is not None else cfg.raw_dir() / cfg.load_config()["stage1"]["cfd_register"]
    d = pd.read_excel(p)
    d.attrs["source"] = p.name
    return d


def load_status(path: Path | None = None) -> pd.DataFrame:
    """LCCC's contract portfolio status (CFD_ID, Status, ...), from raw/lccc/ or `path`."""
    return pd.read_csv(Path(path) if path is not None else cfg.raw_dir() / STATUS_FILE)


def load_terms() -> pd.DataFrame:
    """The round parameters (reference/cfd_round_params.csv) indexed by allocation round."""
    return pd.read_csv(cfg.reference_dir() / TERMS_FILE).set_index("allocation_round")


def contracts(register: pd.DataFrame, status: pd.DataFrame, terms: pd.DataFrame) -> pd.DataFrame:
    """The table (COLUMNS) from a register frame, LCCC's status frame and the round terms (indexed by allocation
    round): one row per register contract, terminated ones included."""
    d = register.merge(status[["CFD_ID", "Status"]], left_on="contract_id", right_on="CFD_ID", how="left",
                       validate="1:1")
    if d["Status"].isna().any():
        raise AssertionError(f"cfd_contracts: {int(d['Status'].isna().sum())} register contracts have no LCCC status")
    for col, known in (("technology_type", TECH), ("technology_type", STRIKE_CLASS),
                       ("allocation_round", dict(ROUNDS))):
        unknown = set(d[col]) - set(known)
        if unknown:
            raise AssertionError(f"cfd_contracts: {col} without a class {sorted(unknown)}")
    out = pd.DataFrame({
        "contract_id": d["contract_id"], "project": d["project_name"].astype(str).str.strip(),
        "round": d["allocation_round"], "round_short": d["allocation_round"].map(dict(ROUNDS)),
        "technology": d["technology_type"], "tech": d["technology_type"].map(TECH),
        "strike_class": d["technology_type"].map(STRIKE_CLASS),
        "mw": pd.to_numeric(d["current_installed_capacity"], errors="coerce").fillna(0.0),
        "lccc_status": d["Status"], "status": d["Status"].map(STATUS),
        "start": _date(d["start_date"]), "expected_start": _date(d["expected_start_date"]),
        "tcw_start": _date(d["target_commissioning_window_start_date"]),
        "target_commissioning": _date(d["target_commissioning_date"]),
        "base_year": d["base_year"].astype(int),
        "strike_base": pd.to_numeric(d["initial_strike_price"], errors="coerce"),
        "strike_current": pd.to_numeric(d["current_strike_price"], errors="coerce"),
    })
    date_contracts(out, terms)
    f = price_factor(out)
    out["strike_2024"] = np.where(out["base_year"] == 2024, out["strike_base"], out["strike_base"] * f)
    out["price_factor"] = f
    out = out[list(COLUMNS)]
    out.attrs.update(source=f"{register.attrs.get('source', 'register')} + {Path(STATUS_FILE).name}", price_factor=f)
    return out


def date_contracts(d: pd.DataFrame, terms: pd.DataFrame) -> None:
    """Begin (start, else expected start, Hinkley Point C on HPC_START, else target commissioning), dated_by, term,
    TCW end (module docstring, TERM) and END, the first day without the contract, in place."""
    hpc = d["round"].eq("Bespoke")
    d["begin"] = d["start"].fillna(d["expected_start"])
    d.loc[hpc & d["begin"].isna(), "begin"] = HPC_START
    target = d["begin"].isna() & d["target_commissioning"].notna()
    d.loc[target, "begin"] = d.loc[target, "target_commissioning"]
    d["dated_by"] = np.select([d["start"].notna(), d["expected_start"].notna(), hpc, target],
                              ["start", "expected", "edf", "target"], "")
    live = d["status"] != "terminated"
    if d.loc[live, "begin"].isna().any():
        raise AssertionError("cfd_contracts: live contracts without a date "
                             f"{d.loc[live & d['begin'].isna(), 'project'].tolist()}")
    d["term_years"] = np.where(d["technology"].isin(KEY_TERM), d["round"].map(terms["contract_term_years_key_tech"]),
                               d["round"].map(terms["contract_term_years_other"])).astype(int)
    d["tcw_end"] = d[["tcw_start", "target_commissioning"]].max(axis=1)
    # the contract's own rule, from its begin (an expected start counts as the start; Hinkley Point C from its
    # placed start, which its bespoke terms count from)
    d["end"] = pd.to_datetime([contract_end(b, w, t, n, tech, r) for b, w, t, n, tech, r in
                               zip(d["begin"], d["tcw_start"], d["target_commissioning"], d["term_years"],
                                   d["technology"], d["round"])])
    bad = live & (d["end"] <= d["begin"])
    if bad.any():
        raise AssertionError(f"cfd_contracts: contracts ending before they begin {d.loc[bad, 'project'].tolist()}")


def price_factor(d: pd.DataFrame) -> float:
    """CPI(2024) / CPI(2012) as the contracts index it (module docstring, STRIKE PRICES): the modal current over
    initial strike ratio of the 2012-base contracts over that of the 2024-base contracts, each indexation date's
    pair checked against the other."""
    r = (d["strike_current"] / d["strike_base"]).round(4)
    modes = {b: r[d["base_year"] == b].value_counts() for b in (2012, 2024)}
    first = float(modes[2012].index[0] / modes[2024].index[0])
    # the second indexation date: the largest ratio of each base that more than SHARED_MIN contracts share
    hi = {b: float(m[m > SHARED_MIN].index.max()) for b, m in modes.items()}
    second = hi[2012] / hi[2024]
    if not (FACTOR_BAND[0] < first < FACTOR_BAND[1] and abs(first - second) < FACTOR_TOLERANCE):
        raise AssertionError(f"cfd_contracts: price factors {first:.5f} and {second:.5f} disagree")
    return first


def build(register: Path | None = None, status: Path | None = None) -> pd.DataFrame:
    """The table from the pinned register (or `register`) and LCCC's status (or `status`), written to processed/."""
    reg = load_register(register)
    out = contracts(reg, load_status(status), load_terms())
    target = cfg.processed_dir() / OUT
    target.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(target, index=False, date_format="%Y-%m-%d")
    live = out[out["status"] != "terminated"]
    by_status = (out.groupby("status")["mw"].agg(["size", "sum"]).rename(columns={"size": "contracts", "sum": "mw"})
                 .round(1))
    print(f"wrote {target} ({len(out)} contracts of {out.attrs['source']}: {len(live)} not terminated, "
          f"{live['mw'].sum() / 1e3:.2f} GW; price factor 2012 -> 2024 {out.attrs['price_factor']:.5f})")
    print(by_status.to_string())
    print("dated by (GW, not terminated):", live.groupby("dated_by")["mw"].sum().div(1e3).round(2).to_dict())
    print("ending by year (GW, not terminated):",
          live.groupby((live["end"] - pd.Timedelta(days=1)).dt.year)["mw"].sum().div(1e3).round(2).to_dict())
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--register", default=None, help="a register workbook instead of the one config.yaml pins")
    ap.add_argument("--status", default=None, help=f"a status file instead of raw/{STATUS_FILE}")
    a = ap.parse_args(argv)
    build(a.register, a.status)
    return 0


if __name__ == "__main__":
    sys.exit(main())
