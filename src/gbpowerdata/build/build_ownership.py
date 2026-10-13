"""Who owns, runs and trades GB generation, by register and by BM unit, for each year.

Why: market structure needs owners kept apart from traders. A gas station is traded by its owner's own company;
a battery is often traded by an optimiser for its owner; an offshore wind farm is owned by a joint venture that one
of its owners runs. No single register says all of that. Five public registers each name a company for part of
the fleet, from their own angle, and these tables put them side by side, reduced to company groups the same way
(gbpowerdata.common.companies), with the joint ventures' shares from a sourced, hand-curated table.

Three roles:
  owner     who holds the equity, with shares where a source gives them (a joint venture has several owners; a
            share no source gives is left blank; the part the known shares do not cover is "unresolved").
  operator  the company that runs the unit and bids for its owners: a single owner is its own operator; a joint
            venture's operator is the one company_owners.csv marks.
  trader    the BSC party registered to trade the unit in the Balancing Mechanism (its lead party in Elexon's
            register) at the year's as-of date: a documented change or the register snapshot of the time, else
            today's standing in, checked against the unit's change of hands (see the BM-unit table below).

Registers (what each one's company is, and which records count in a year):
  dukes  DESNZ, DUKES 5.11 (gbpowerdata.pull.dukes_pull): the company that returned the survey of major power
         producers, mostly the owning group; the edition sheet "DUKES <year + 1>" lists the stations operating at
         the end of May of year + 1 and stands for the end of `year` (the newest edition, "5.11 Full list", for the
         year before it), so a station that closed between January and May (Fiddler's Ferry and Aberthaw B, 31
         March 2020) is missing from the year before's records; the links to BM units read the edition before for
         it, and for a station whose BM units produced in the year but that the year's lists leave out (Sutton
         Bridge's CCGT in the lists for 2022-2024) the latest earlier list that has it (dukes_company). GB
         stations only. The editions to 2021 list 382-390 GB stations a year, those from 2022 1,263-1,317 (more
         renewables): a break in coverage, not in the fleet. record_id is DESNZ's site code, else (the
         editions to 2021 and a few later rows) "site | technology", with the company where two rows still share
         one (DESNZ's "Sites with capacity < 20 MW" total of each company).
  ro     Ofgem, register of RO accredited stations (hand-downloaded, data/raw/manual/README.md): the accreditation
         holder, mostly a project company, today's. GB stations of at least RO_MIN_MW that were issued ROCs for
         output in the year (Ofgem's certificate report, same download), so the coal stations accredited for
         co-firing that have long closed (Longannet, Didcot A, Kingsnorth and others: 79 stations, 10.9 GW of the
         register's 16.6 GW of "bioenergy") drop out. Ofgem writes the certificate counts with thousands
         separators ("22,608"). Without the certificate report: every station whose support runs in the year (accredited by
         its end; support ends 20 years after accreditation, 31 March 2037 at the latest), status "accredited".
         The certificates name the generator, but today's for every past month (checked 6 Oct 2026: no station's
         generator changes across 2015-2026), so they date output, not holders. Without the register the RO
         records and the wind farms' RO links are left out, with a warning.
  cfd    LCCC, CfD register (data/raw/{stage1.cfd_register}) with LCCC's status (gbpowerdata.pull.lccc_pull): the
         counterparty, a project company, with its Companies House number (eight characters as text: the
         register drops leading zeros, "9171944" for 09171944). In a year: "operating" if the
         contract started by the year's end, else "contracted" if its allocation round had reported (LCCC's
         auction outcomes; the investment contracts of 2014 and Hinkley Point C's of 2016 before them), neither
         terminated nor at the end of its term by then (cfd_expiry, from build_cfd_status.contract_end).
  cm     NESO, Capacity Market register (gbpowerdata.pull.cm_register_pull): the applicant and its declared
         parent; the auction agreements in force in the delivery year from October of the year, secondary trades
         left out and agreements terminated during the year kept (cm_in_force). Capacity
         is the connection capacity, with the de-rated capacity beside it. The parent is today's (see the
         puller's notes). The class is the Primary Fuel Type's, else, where NESO leaves that blank (most
         agreements of the earlier auctions), the CMU Technology's (cm_class).
  bm     Elexon, BM unit register by year (gbpowerdata.build.bm_units): the trader of every BM unit active in
         the year, as in the BM-unit table (whose register column says whether the lead party is a documented
         one, the year's snapshot's, today's standing in, or replaced by the operator at the date).

Links to BM units: the CfD units through LCCC's mapping (the T_/E_ units mapped in the year; the metering units C__
are not BM units), the main thermal, nuclear, pumped-storage and biomass stations through
data/reference/dukes_bmu_map.csv (a DUKES site pattern and the station's units, matched within one technology
class, so EDF's Sutton Bridge solar farm stays off Calon's CCGT), the transmission wind farms through
data/reference/wind_farm_map.csv and a match of the farm's name to the RO register's stations (every distinctive
word of the farm's name in the station's name; the holder with the most matched capacity), and the CM units
through their components, whose Component ID is the BM unit (Elexon's id, or National Grid's without the prefix:
"SUTB-1") for 220 of the register's 655 units; most batteries' components are sites, not BM units.

YEARS. 2018 to the current year. A year describes its last day, the current year the build date (as_of in every
row); DUKES has no list beyond its latest edition, which stands for the current year too. Dated rows of
company_owners.csv (joint ventures, sales, and companies that changed group, such as West Burton B Limited) are
read at the as-of date, so owners, operators and the groups of trading companies change over the years.

The BM-unit table takes each active unit's owners and operator from the first register that links to it: CfD,
then DUKES (curated station rows first), then RO, then CM. Where that register names a company without dated rows
and the unit's lead party is a joint venture's own company with dated rows in company_owners.csv, the venture's rows
give the owners (register "bm", basis "curated"): Gunfleet Sands I and II, whose RO holder Orsted Burbo (UK) Limited
also holds Burbo Bank, are Orsted's, DBJ's and Marubeni's (JERA's from 2019). A unit none links to takes its lead
party as owner
(register "bm", basis "lead_party"), a proxy that holds for a station's own company (Seagreen Wind Energy, Corby
Power) and not for a battery traded by an optimiser, so a battery none links to stays "unresolved". Its trader is
the lead party's group, or the venture's operator where the lead party is a joint venture's own company
("jv_operator"). The lead party comes from data/reference/bmu_lead_parties.csv where a documented change covers the
date (register "curated"), else from the year's register snapshot ("bm"). Where only a later snapshot exists
("bm_proxy": today's lead party standing in for a past year), the proxy is checked against the unit's ownership:
if the unit's operator at the date differs from its operator at the snapshot's date, the unit changed hands since,
and its trader at the date is taken to be its operator then (register "operator_at_date", a judgement: Damhead
Creek and Rye House were Drax's until January 2021, VPI trades them today).

Technology classes (tech_class, one vocabulary across the registers): offshore_wind, onshore_wind, wind (a BM
wind unit not in the farm map and transmission-connected), solar, hydro, pumped_storage, battery, gas, coal, oil,
nuclear, bioenergy, marine, interconnector, dsr, other.

Spelling: a group no rule, alias or curated row names keeps a register's spelling, and the registers spell one
company differently (LCCC's "CLEVE HILL SOLAR PARK", Elexon's "Cleve Hill Solar Park"), so each normalised name
takes one spelling in every table and year (one_spelling): mixed case before capitals only, then the most capital
letters, then the shortest.

Personal data: the RO register gives organisation and station addresses, and small stations are often held by
individuals; addresses are used only to group holders (never written), and stations under RO_MIN_MW are left out.
The CM register's contact columns are dropped by its puller and never read here (the readers name their columns).

Outputs (data/processed/):
  ownership_{year}.csv      one row per register record, role and group: year, as_of, register, record_id,
                            record_name, tech_class, technology, capacity_mw, derated_mw, status, company,
                            company_number, role, group, share, basis, station, bmu_ids
  ownership_bmu_{year}.csv  one row per active BM unit, role and group: year, as_of, unit_id, unit_name, tech_class,
                            connection, capacity_mw, role, group, share, company, basis, register, record_id
Read them with gbpowerdata.processed.read_ownership(year) and read_ownership_bmu(year). basis is how the
company became the group (curated, alias, name, address, site, ch_psc, cm_parent, self, jv_operator, lead_party;
"none" for an unresolved unit). ch_psc, the company's controller on the date in Companies House's register of persons
with significant control, needs a pull (gbpowerdata.pull.companies_house_pull, then
gbpowerdata.build.build_company_control); without one the tables are as before.

Usage: python -m gbpowerdata.build.build_ownership [--years 2018 2026]
       (after python -m gbpowerdata.build.bm_units for the same years and the year of the latest register
       snapshot, against which earlier years' proxies are checked; without it they stay unchecked, with a warning)
"""
from __future__ import annotations

import argparse
import re
import sys
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from gbpowerdata import config as cfg
from gbpowerdata.build.bm_units import as_of, register_files
from gbpowerdata.common import companies as co
from gbpowerdata.common import company_control as cc

YEARS = tuple(range(2018, pd.Timestamp.today().year + 1))   # to the current year, as of the build date
ROLES = ("owner", "operator", "trader")
TECH_CLASSES = ("offshore_wind", "onshore_wind", "wind", "solar", "hydro", "pumped_storage", "battery", "gas",
                "coal", "oil", "nuclear", "bioenergy", "marine", "interconnector", "dsr", "other")
GB = ("England", "Scotland", "Wales")
RO_MIN_MW = 1.0
RO_YEARS = 20
RO_END_LATEST = pd.Timestamp("2037-03-31")
# contracts outside the allocation rounds: the FIDeR investment contracts (awarded April 2014) and Hinkley Point C
# (signed 29 September 2016); both before the panel, so only "by the year's end" matters
OUTSIDE_ROUNDS = {"Investment Contract": "2014-04-30", "Bespoke": "2016-09-29"}
CM_COLUMNS = [
    "Auction Name", "Type", "Delivery Year", "CMU ID", "Name of Applicant", "CM Unit Name", "Parent Company",
    "Primary Fuel Type", "CMU Technology", "Connection or DSR Capacity", "De Rated Capacity",
    "Capacity Agreement Awarded", "Capacity Agreement has been Terminated", "Date of Termination of Capacity Agreement",
    "Delivery Years for which Agreement Valid",
]
CM_NAMES = {"Auction Name": "auction", "Delivery Year": "delivery_year", "CMU ID": "cmu_id",
            "Name of Applicant": "applicant", "CM Unit Name": "cmu_name", "Parent Company": "parent",
            "Primary Fuel Type": "fuel", "CMU Technology": "cmu_technology", "Connection or DSR Capacity": "capacity_mw",
            "De Rated Capacity": "derated_mw"}
RECORD_COLUMNS = ["year", "as_of", "register", "record_id", "record_name", "tech_class", "technology", "capacity_mw",
                  "derated_mw", "status", "company", "company_number", "role", "group", "share", "basis", "station",
                  "bmu_ids"]
BMU_COLUMNS = ["year", "as_of", "unit_id", "unit_name", "tech_class", "connection", "capacity_mw", "role", "group", "share",
               "company", "basis", "register", "record_id"]
LINK_ORDER = ("cfd", "dukes", "ro", "cm")
# the farm map's station name -> words of the RO register's station name, where the names differ
WIND_ALIASES = {
    "Pen y Cymoedd Wind Farm": "PyC",            # registered as PyC Wind Farm
    "Sheringham Shoals Windfarm": "Sheringham Shoal",
    "Aberdeen Bay": "Aberdeen Offshore Windfarm",
    "Dunmglass Wind Farm": "Dunmaglass",
    "AChruach Wind Farm": "Chruach",
    "Aikengall 2 Wind Farm Generation": "Aikengall II",
    # one station of three units in the farm map; the RO register has Clyde Windfarm (North), (Central), (South)
    "Clyde Central Windfarm, Clyde North Windfarm, Clyde South Windfarm": "Clyde Windfarm",
}
GENERIC_WORDS = set("wind winds windfarm windfarms farm farms offshore onshore power ltd limited the of phase i ii iii "
                    "a b c g n p ro generation extension".split())


# ---------------------------------------------------------------------------- technology classes
def dukes_class(technology: str) -> str:
    t = str(technology).lower()
    if "pumped" in t:
        return "pumped_storage"
    if "offshore" in t:
        return "offshore_wind"
    if "onshore" in t or "wind" in t:
        return "onshore_wind"
    if "solar" in t:
        return "solar"
    if "nuclear" in t:
        return "nuclear"
    if "hydro" in t:
        return "hydro"
    if "coal" in t:
        return "coal"
    if "diesel" in t or "gas oil" in t:
        return "oil"
    if "gas" in t:
        return "gas"
    if any(k in t for k in ("biomass", "bioenergy", "waste", "msw")):
        return "bioenergy"
    return "other"


def ro_class(technology: str) -> str:
    t = str(technology).lower()
    if "offshore" in t:
        return "offshore_wind"
    if "wind" in t:
        return "onshore_wind"
    if "photovoltaic" in t or "solar" in t:
        return "solar"
    if "hydro" in t:
        return "hydro"
    if "tidal" in t or "wave" in t:
        return "marine"
    if any(k in t for k in ("landfill", "sewage", "fuelled", "biomass", "waste", "gas")):
        return "bioenergy"       # the RO's gases are landfill and sewage gas
    return "other"


CFD_CLASS = {"Offshore Wind": "offshore_wind", "Floating Offshore Wind": "offshore_wind",
             "Onshore Wind": "onshore_wind", "Remote Island Wind": "onshore_wind", "Solar PV": "solar",
             "Nuclear": "nuclear", "Tidal Stream": "marine", "Advanced Conversion Technology": "bioenergy",
             "Dedicated Biomass": "bioenergy", "Energy from Waste": "bioenergy", "Biomass Conversion": "bioenergy",
             "Geothermal": "other"}
CM_CLASS = {"Gas": "gas", "Coal": "coal", "Coal mine methane": "gas", "Diesel": "oil", "Distillate": "oil",
            "Oil": "oil", "Nuclear": "nuclear", "Hydro": "hydro", "Storage - Pumped": "pumped_storage",
            "Storage - Battery": "battery", "Storage - Compressed Air": "other", "Interconnector": "interconnector",
            "DSR": "dsr", "Biomass": "bioenergy", "Bio-fuel": "bioenergy", "Waste": "bioenergy",
            "Onshore Wind": "onshore_wind", "Offshore Wind": "offshore_wind", "Solar": "solar"}
BM_CLASS = {"ccgt": "gas", "ocgt": "gas", "coal": "coal", "nuclear": "nuclear", "biomass": "bioenergy",
            "hydro": "hydro", "pumped_storage": "pumped_storage", "battery": "battery", "solar": "solar",
            "other": "other"}
# CMU Technology, read where NESO leaves Primary Fuel Type blank: its "Storage", "Coal/biomass" and the like name no
# fuel, so the pumped-storage stations, the energy-from-waste plants and Drax's biomass units go by their names
PUMPED_NAMES = re.compile(r"DINORWIG|FFESTINIOG|CRUACHAN|FOYERS|PUMPED", re.I)
WASTE_NAMES = re.compile(r"EFW|\bERFS?\b|\bERC\b|ENERGY RECOVERY|WASTE|RECYCLING|ENFINIUM|\bMFE\b|\bFCC\b|\bSITA\b", re.I)
DRAX_BIOMASS = re.compile(r"\bDRAX ?(UNIT )?0?[1-4]\b|\bDRX_0?[1-4]\b", re.I)
INTERCONNECTORS = re.compile(r"\((France|Netherlands|Belgium|Norway|Ireland|Northern Ireland|Denmark)\)", re.I)


def cm_class(fuel, technology, name: str = "", applicant: str = "") -> str:
    """A CM unit's class: its Primary Fuel Type's (CM_CLASS), else its CMU Technology's."""
    fuel = fuel.strip() if isinstance(fuel, str) and fuel.strip().lower() not in ("", "nan") else ""
    if fuel:
        return CM_CLASS.get(fuel, "other")
    t, names = str(technology or "").lower(), f"{name} {applicant}"
    if INTERCONNECTORS.search(t):
        return "interconnector"
    if t.startswith("dsr"):
        return "dsr"
    if t.startswith("storage"):
        return "pumped_storage" if PUMPED_NAMES.search(names) else "battery"
    if "energy from waste" in t or WASTE_NAMES.search(names):
        return "bioenergy"
    if t.startswith("biomass") or ("biomass" in t and DRAX_BIOMASS.search(names)):
        return "bioenergy"
    if "coal" in t:
        return "coal"
    for word, cls in (("nuclear", "nuclear"), ("hydro", "hydro"), ("offshore wind", "offshore_wind"),
                      ("onshore wind", "onshore_wind")):
        if word in t:
            return cls
    if "diesel" in t or t.startswith("oil"):
        return "oil"
    if any(k in t for k in ("ccgt", "ocgt", "chp", "reciprocating", "gas")):
        return "gas"
    return "solar" if "solar" in t else "other"


# ---------------------------------------------------------------------------- readers
def _newest(folder: Path, pattern: str, key=None) -> Path:
    files = sorted(folder.glob(pattern), key=key or (lambda p: p.name))
    if not files:
        raise FileNotFoundError(f"no {pattern} under {folder}")
    return files[-1]


def _ofgem_stamp(p: Path) -> str:
    """Ofgem names its downloads ..._DD-MM-YYYY_HH-MM.csv: sort them by date, not by name."""
    m = re.search(r"(\d{2})-(\d{2})-(\d{4})_(\d{2})-(\d{2})", p.name)
    return f"{m[3]}{m[2]}{m[1]}{m[4]}{m[5]}" if m else p.name


@lru_cache(maxsize=None)
def _dukes_book() -> tuple[Path, tuple[str, ...]]:
    path = _newest(cfg.raw_dir() / "dukes", "DUKES_5.11_*.xlsx")
    return path, tuple(pd.ExcelFile(path).sheet_names)


@lru_cache(maxsize=None)
def dukes_stations(year: int) -> pd.DataFrame:
    """DESNZ's GB stations at the end of `year`: site, record_id, company, technology, tech_class, capacity_mw,
    sheet. attrs["sheet"] names the edition sheet read."""
    path, sheets = _dukes_book()
    sheet = f"DUKES {year + 1}" if f"DUKES {year + 1}" in sheets else "5.11 Full list"
    edition = int(re.search(r"(\d{4})", path.stem.split("_")[-1])[1])
    if sheet == "5.11 Full list" and year + 1 < edition:
        raise ValueError(f"{path.name} has no sheet for the end of {year}")   # the latest list stands for later years
    raw = pd.read_excel(path, sheet_name=sheet, header=None)
    header = next(i for i in range(25) if any("Company" in str(c) for c in raw.iloc[i]))
    t = pd.read_excel(path, sheet_name=sheet, header=header)
    t.columns = [str(c).split(" [")[0].split("\n")[0].strip() for c in t.columns]
    t = t.rename(columns={"Station Name": "Site Name"})
    t["Company Name"] = t["Company Name"].ffill()          # the older editions name a company once per block
    t = t[t["Site Name"].notna() & (t["Site Name"].astype(str).str.strip() != "Site Name")
          & (t["Company Name"].astype(str).str.strip() != "Company Name")].copy()
    if "Country" in t:
        t = t[t["Country"].isin(GB)]
    else:                                                    # the editions to 2021 give a region
        t = t[~t["Location"].astype(str).str.contains("Northern Ireland")]
    tech_cols = [c for c in ("Technology", "Type", "Primary Fuel", "Fuel") if c in t]
    t["technology"] = t[tech_cols].astype(str).agg(" / ".join, axis=1).str.replace(" / nan", "", regex=False)
    cap = next(c for c in t.columns if "apacity" in c)
    code = t["DESNZ site code"].astype(str) if "DESNZ site code" in t else None
    out = pd.DataFrame({
        "site": t["Site Name"].astype(str).str.strip(),
        "company": t["Company Name"].astype(str).str.strip(),
        "technology": t["technology"],
        "capacity_mw": pd.to_numeric(t[cap], errors="coerce"),
    })
    # DESNZ's site code, else (the editions to 2021, a few later rows) site and technology, with the company where two
    # rows still share those (the "Sites with capacity < 20 MW" total of each company)
    fallback = out["site"] + " | " + out["technology"]
    fallback = fallback.where(~fallback.duplicated(keep=False),
                              out["site"] + " | " + out["company"] + " | " + out["technology"])
    has_code = (code != "nan") & code.str.strip().ne("") if code is not None else pd.Series(False, index=out.index)
    out["record_id"] = (code if code is not None else out["site"]).where(has_code, fallback)
    out["tech_class"] = out["technology"].map(dukes_class)
    out = out.reset_index(drop=True)
    out.attrs["sheet"] = sheet
    return out


@lru_cache(maxsize=None)
def ro_register() -> pd.DataFrame:
    """Ofgem's RO stations in GB of at least RO_MIN_MW: record_id, station, company (the holder), address (for
    grouping only), technology, tech_class, capacity_mw (declared net capacity), accredited, ro_end."""
    path = _newest(cfg.raw_dir() / "ofgem", "RO_Accredited_Stations_*.csv", key=_ofgem_stamp)
    t = pd.read_csv(path, encoding="utf-8-sig", low_memory=False, dtype=str)
    t = t[t["Country"].isin(GB)]
    out = pd.DataFrame({
        "record_id": t["Accreditation reference"].str.strip(),
        "station": t["Station name"].astype(str).str.strip(),
        "company": t["Organisation name"].astype(str).str.strip(),
        "address": t["Organisation address"],
        "technology": t["Technology"].astype(str),
        "capacity_mw": pd.to_numeric(t["Station DNC in kW"].str.replace(",", ""), errors="coerce") / 1e3,
        "accredited": pd.to_datetime(t["Effective date"], dayfirst=True, errors="coerce"),
    })
    out["tech_class"] = out["technology"].map(ro_class)
    out["ro_end"] = (out["accredited"] + pd.DateOffset(years=RO_YEARS)).clip(upper=RO_END_LATEST)
    out = out[out["capacity_mw"] >= RO_MIN_MW].reset_index(drop=True)
    out.attrs["source"] = path.name
    return out


@lru_cache(maxsize=None)
def ro_or_none() -> pd.DataFrame | None:
    """ro_register(), or None (with a warning) where the hand-downloaded register is not there."""
    try:
        return ro_register()
    except FileNotFoundError as e:
        print(f"  WARNING: {e}; the RO register (data/raw/manual/README.md) is left out")
        return None


@lru_cache(maxsize=None)
def ro_output_years() -> dict[str, frozenset] | None:
    """Accreditation reference -> the calendar years with output for which ROCs were issued (Ofgem's certificate
    report, RO_Certificates_*.csv; GB stations); None without the report."""
    try:
        path = _newest(cfg.raw_dir() / "ofgem", "RO_Certificates_*.csv", key=_ofgem_stamp)
    except FileNotFoundError:
        return None
    t = pd.read_csv(path, encoding="utf-8-sig", dtype=str,
                    usecols=["Accreditation reference", "Country", "Output period", "Number of certificates"])
    count = pd.to_numeric(t["Number of certificates"].str.replace(",", "", regex=False), errors="coerce")
    t = t[t["Country"].isin(GB) & (count > 0)]                    # Ofgem writes thousands with a comma: "22,608"
    year = pd.to_datetime(t["Output period"], format="%b %Y", errors="coerce").dt.year
    return {ref: frozenset(int(y) for y in ys.dropna()) for ref, ys in year.groupby(t["Accreditation reference"].str.strip())}


def ro_in_year(table: pd.DataFrame, year: int) -> pd.DataFrame:
    """The RO stations that count in `year`, with their status: issued ROCs for output in the year where the
    certificate report is there ("generating"), else every station whose support runs in the year
    ("accredited")."""
    out = ro_output_years()
    if out is not None:
        t = table[table["record_id"].map(lambda r: year in out.get(r, ()))]
        return t.assign(status="generating")
    t = table[(table["accredited"] <= as_of(year)) & (table["ro_end"] >= pd.Timestamp(f"{year}-01-01"))]
    return t.assign(status="accredited")


@lru_cache(maxsize=None)
def cfd_register() -> pd.DataFrame:
    """LCCC's register by contract: counterparty, company number, address (grouping only), project, technology,
    tech_class, capacity_mw, round, round_date, start, termination, LCCC status."""
    raw, lccc = cfg.raw_dir(), cfg.raw_dir() / "lccc"
    t = pd.read_excel(raw / cfg.load_config()["stage1"]["cfd_register"],
                      converters={"counterparty_registration_no": str})
    status = pd.read_csv(lccc / "cfd_contract_portfolio_status.csv").drop_duplicates("CFD_ID").set_index("CFD_ID")
    rounds = pd.read_csv(lccc / "cfd_auction_outcomes.csv")
    rounds = pd.to_datetime(rounds["Publication_Date"].str[:10]).groupby(rounds["Auction"]).min()
    when = {f"Allocation Round {k[2:]}": v for k, v in rounds.items() if str(k).startswith("AR")}
    when.update({k: pd.Timestamp(v) for k, v in OUTSIDE_ROUNDS.items()})
    cap = pd.to_numeric(t["current_installed_capacity"], errors="coerce")
    out = pd.DataFrame({
        "record_id": t["contract_id"].astype(str),
        "project": t["project_name"].astype(str),
        "company": t["counterparty_name"].astype(str).str.strip(),
        "company_number": t["counterparty_registration_no"].map(cc.company_number),     # leading zeros back
        "address": t["counterparty_address"],
        "technology": t["technology_type"].astype(str),
        "capacity_mw": cap.fillna(pd.to_numeric(t["initial_installed_capacity"], errors="coerce")),
        "round": t["allocation_round"].astype(str),
        "start": pd.to_datetime(t["start_date"], errors="coerce"),
        "terminated": pd.to_datetime(t["termination_date"], errors="coerce"),
    })
    out["round_date"] = out["round"].map(when)
    if unknown := sorted(set(out.loc[out["round_date"].isna(), "round"])):
        print(f"  WARNING: CfD rounds without a date (their contracts count only once started): {unknown}")
    out["lccc_status"] = out["record_id"].map(status["Status"])
    out["tech_class"] = out["technology"].map(CFD_CLASS).fillna("other")
    out["expiry"] = cfd_expiry(t)
    return out


def cfd_expiry(register: pd.DataFrame) -> pd.Series:
    """Each contract's first day without it, by the CfD Agreement's term (build_cfd_status.contract_end): NaT for a
    contract that has not started."""
    from gbpowerdata.build.build_cfd_status import KEY_TERM, contract_end
    terms = pd.read_csv(cfg.reference_dir() / "cfd_round_params.csv").set_index("allocation_round")
    def date(c: str) -> pd.Series:
        if c not in register:
            return pd.Series(pd.NaT, index=register.index, dtype="datetime64[ns]")
        return pd.to_datetime(register[c], errors="coerce")
    start, tcw, tcd = date("start_date"), date("target_commissioning_window_start_date"), date("target_commissioning_date")
    out = []
    for i, (r, tech) in enumerate(zip(register["allocation_round"].astype(str), register["technology_type"].astype(str))):
        if r not in terms.index:
            out.append(pd.NaT)
            continue
        n = terms.loc[r, "contract_term_years_key_tech" if tech in KEY_TERM else "contract_term_years_other"]
        out.append(contract_end(start.iloc[i], tcw.iloc[i], tcd.iloc[i], int(n), tech, r))
    return pd.Series(out, index=register.index, dtype="datetime64[ns]")


def cfd_in_year(table: pd.DataFrame, year: int) -> pd.DataFrame:
    """The contracts that count in `year` with their status then: operating (started by the year's end) or
    contracted (its round had reported), and neither terminated nor ended (its term over, `expiry`) by the year's
    end. A contract LCCC lists as terminated without a date counts in no year. No contract ends before 1 April 2027
    (the biomass conversions), so the term changes nothing up to the 2026 table."""
    end = as_of(year)
    t = table.copy()
    undated_end = t["lccc_status"].eq("Terminated") & t["terminated"].isna()
    gone = (t["terminated"] <= end) | undated_end
    if "expiry" in t:
        gone |= t["expiry"].notna() & (t["expiry"] <= end)
    t["status"] = np.where(t["start"] <= end, "operating", np.where(t["round_date"] <= end, "contracted", ""))
    return t[(t["status"] != "") & ~gone]


@lru_cache(maxsize=None)
def cfd_bmus(year: int) -> dict[str, list[str]]:
    """LCCC's mapping: contract -> the T_/E_ BM units mapped to it at some time in `year`."""
    m = pd.read_csv(cfg.raw_dir() / "lccc" / "cfd_to_bm_unit_mapping.csv")
    m = m[m["BMU_Id"].astype(str).str.match(r"^[TE]_")]
    start = pd.to_datetime(m["Effective_From"].astype(str).str[:10], errors="coerce")
    stop = pd.to_datetime(m["Effective_date_to"].astype(str).str[:10], errors="coerce")
    m = m[(start.isna() | (start <= as_of(year))) & (stop.isna() | (stop >= pd.Timestamp(f"{year}-01-01")))]
    return m.groupby("CFD_Id")["BMU_Id"].apply(lambda s: sorted(set(s))).to_dict()


def bm_register(year: int) -> pd.DataFrame:
    path = cfg.processed_dir() / f"bm_unit_register_{year}.csv"
    if not path.exists():
        raise FileNotFoundError(f"{path} is missing: run `python -m gbpowerdata.build.bm_units` first")
    return pd.read_csv(path)


@lru_cache(maxsize=None)
def _cm_stamp() -> str:
    return _newest(cfg.raw_dir() / "neso" / "cm_register", "cmu_*.csv").stem.split("_")[-1]


@lru_cache(maxsize=None)
def cm_units() -> pd.DataFrame:
    path = cfg.raw_dir() / "neso" / "cm_register" / f"cmu_{_cm_stamp()}.csv"
    return pd.read_csv(path, encoding="utf-8-sig", usecols=CM_COLUMNS, low_memory=False, dtype=str)


@lru_cache(maxsize=None)
def cm_components() -> pd.DataFrame:
    """Auction Name, CMU ID and Component ID of every component (the newest snapshot, the CMU file's date)."""
    path = cfg.raw_dir() / "neso" / "cm_register" / f"components_{_cm_stamp()}.csv"
    return pd.read_csv(path, encoding="utf-8-sig", usecols=["Auction Name", "CMU ID", "Component ID"],
                       low_memory=False, dtype=str)


def cm_in_force(units: pd.DataFrame, year: int) -> pd.DataFrame:
    """The agreements in force in the delivery year from October of `year`: awarded at auction, valid for
    "<year>/<year + 1>" and not terminated before that year began (1 October). A row sits under its auction's first
    delivery year, so a 15-year agreement from an earlier auction is found by its list of valid years, not by
    "Delivery Year". Secondary trades (Type ST) are left out: such a row is a unit that took over part of another
    unit's obligation for a while and won nothing at auction itself (its "Auction Acquired Capacity Obligation" is
    0; build.capacity_market moves its traded obligation), so counting it added the whole unit (31 to 201 units a
    year in 2018-2026, 184 and 1.2 GW de-rated in 2025). Until 13 Oct 2026 an agreement terminated at any date was
    left out of every year, so the units that delivered and were terminated later (19 to 120 a year, 1-2.3 GW of
    obligation in 2019-2024) were missing from the years they held."""
    valid = units["Delivery Years for which Agreement Valid"].astype(str).str.contains(f"{year}/{year + 1}", regex=False)
    awarded = units["Capacity Agreement Awarded"].astype(str).str.lower().eq("yes")
    terminated = units["Capacity Agreement has been Terminated"].astype(str).str.lower().eq("yes")
    when = units.get("Date of Termination of Capacity Agreement", pd.Series(pd.NA, index=units.index))
    ended = pd.to_datetime(when, format="%d/%m/%Y", errors="coerce")
    alive = ~terminated | (ended >= pd.Timestamp(year, 10, 1))
    traded = units.get("Type", pd.Series("", index=units.index)).astype(str).str.strip().eq("ST")
    return units[valid & awarded & alive & ~traded]


@lru_cache(maxsize=None)
def cm_parents() -> dict[str, str]:
    """Applicant (normalised) -> its declared parent (the latest auction that names one; today's parent)."""
    t = cm_units().dropna(subset=["Parent Company"])
    t = t[t["Parent Company"].str.strip().str.lower().ne("nan") & t["Parent Company"].str.strip().ne("")]
    t = t.assign(_dy=pd.to_numeric(t["Delivery Year"], errors="coerce")).sort_values("_dy")
    return {co.norm(a): str(p).strip() for a, p in zip(t["Name of Applicant"], t["Parent Company"])}


# ---------------------------------------------------------------------------- links
def _words(name: str) -> frozenset:
    text = re.sub(r"[^a-z0-9 ]", " ", str(name).lower())
    return frozenset(w for w in text.split() if w not in GENERIC_WORDS and len(w) > 1 and not w.isdigit())


@lru_cache(maxsize=None)
def farm_ro_links() -> pd.DataFrame:
    """The farm map's stations (data/reference/wind_farm_map.csv) matched to RO stations: station, bmu_ids (list),
    is_offshore, ro_ids (list), holder, address. Every distinctive word of the farm's name must be in the RO
    station's name; the holder with the most matched capacity is the farm's."""
    farms = pd.read_csv(cfg.reference_dir() / "wind_farm_map.csv").dropna(subset=["station", "elexon_bmu_id"])
    farms["station"] = farms["station"].astype(str).str.strip()     # the map has "Sheringham Shoals Windfarm "
    ro = ro_or_none()
    if ro is None:
        return pd.DataFrame(columns=["station", "bmu_ids", "is_offshore", "ro_ids", "holder", "address"])
    wind = ro[ro["tech_class"].isin(["offshore_wind", "onshore_wind"])]
    ro_words = wind["station"].map(_words)
    rows = []
    for station, units in farms.groupby("station"):
        words = _words(WIND_ALIASES.get(station, station))
        hit = wind[[bool(words) and words <= w for w in ro_words]] if words else wind.iloc[:0]
        holder = address = ""
        ids: list[str] = []
        if len(hit):
            holder = hit.groupby("company")["capacity_mw"].sum().idxmax()
            chosen = hit[hit["company"] == holder]
            ids, address = chosen["record_id"].tolist(), chosen["address"].iloc[0]
        off = units["is_offshore"].dropna()
        rows.append({"station": station, "bmu_ids": sorted(set(units["elexon_bmu_id"])),
                     "is_offshore": bool(off.astype(bool).any()) if len(off) else np.nan,
                     "ro_ids": ids, "holder": holder, "address": address})
    return pd.DataFrame(rows)


def _station_of(record: pd.Series, stations: pd.DataFrame) -> str:
    """The dukes_bmu_map station a DUKES record belongs to: same class, pattern matches the site."""
    for name, s in stations.iterrows():
        if record["tech_class"] == s["tech_class"] and re.search(s["dukes_pattern"], record["site"], flags=re.I):
            return name
    return ""


@lru_cache(maxsize=None)
def dukes_with_stations(year: int) -> pd.DataFrame:
    """dukes_stations(year) with the dukes_bmu_map station of each record ("" if none)."""
    t = dukes_stations(year).copy()
    stations = co.dukes_bmu_map()
    t["station"] = [_station_of(r, stations) for _, r in t.iterrows()]
    t.attrs["sheet"] = dukes_stations(year).attrs["sheet"]
    return t


def dukes_company(station: str, year: int) -> tuple[str, str]:
    """(company, record_id) of a station at the end of `year`: its largest matching DUKES record; a station that
    closed in the year is not in that year's list, so the edition before is read next. A station whose BM units
    produced in the year but that the year's lists leave out (Sutton Bridge's CCGT in the lists for 2022-2024)
    takes the latest earlier list that has it; a closed station (no BM unit active) does not."""
    def found(y: int) -> tuple[str, str] | None:
        try:
            t = dukes_with_stations(y)
        except (FileNotFoundError, ValueError):
            return None
        hit = t[t["station"] == station].sort_values("capacity_mw", ascending=False)
        return (hit["company"].iloc[0], hit["record_id"].iloc[0]) if len(hit) else None

    for y in (year, year - 1):
        if hit := found(y):
            return hit
    stations = co.dukes_bmu_map()
    units = set(stations.loc[station, "bmus"]) if station in stations.index else set()
    if units and units & set(bm_register(year).query("active")["unit_id"]):
        for y in range(year - 2, YEARS[0] - 2, -1):
            if hit := found(y):
                return hit
    return "", ""


def component_units(year: int) -> pd.DataFrame:
    """CM components whose Component ID is a BM unit of the year's register (Elexon's id, or National Grid's id
    without the prefix): Auction Name, CMU ID, unit_id."""
    reg = bm_register(year)
    ids = {**{str(n).strip(): u for n, u in zip(reg["ngc_id"], reg["unit_id"]) if pd.notna(n)},
           **{u: u for u in reg["unit_id"]}}
    comp = cm_components().copy()
    comp["unit_id"] = comp["Component ID"].astype(str).str.strip().map(ids)
    return comp.dropna(subset=["unit_id"])[["Auction Name", "CMU ID", "unit_id"]]


def cm_bmu_links(year: int) -> pd.DataFrame:
    """The CM units in force in `year` linked to BM units through their components (component_units): unit_id,
    cmu_id, applicant, parent."""
    force = cm_in_force(cm_units(), year)
    m = force.merge(component_units(year), on=["Auction Name", "CMU ID"], how="inner")
    m = m.assign(_d=pd.to_numeric(m["De Rated Capacity"], errors="coerce")).sort_values("_d", ascending=False)
    return (m.drop_duplicates("unit_id")
             .rename(columns={"CMU ID": "cmu_id", "Name of Applicant": "applicant", "Parent Company": "parent"})
             [["unit_id", "cmu_id", "applicant", "parent"]])


# ---------------------------------------------------------------------------- tables
def _roles(owners: list[dict], operator: str, basis: str) -> list[dict]:
    out = [{"role": "owner", "group": o["group"], "share": o["share"], "basis": basis} for o in owners]
    if operator:
        out.append({"role": "operator", "group": operator, "share": 1.0, "basis": basis})
    return out


def _cm_owner(applicant, parent, when, cm) -> tuple[list[dict], str, str]:
    """A CM unit's owners: the applicant resolved (curated, alias, name, its parent); where that leaves it its
    own group and the row declares a parent, the parent's group."""
    owners, operator, basis = co.resolve(applicant, when, cm_parents=cm)
    has_parent = pd.notna(parent) and str(parent).strip().lower() not in ("", "nan")
    if basis == "self" and has_parent and co.norm(parent) != co.norm(applicant):
        group = co.group_of(parent)[0]
        return [{"group": group, "share": 1.0}], group, "cm_parent"
    return owners, operator, basis


def records(year: int, spellings: dict[str, str] | None = None) -> pd.DataFrame:
    """One row per register record, role and group for `year` (see the module docstring); `spellings` as
    one_spelling takes them."""
    when, cm = as_of(year), cm_parents()
    rows: list[dict] = []

    def add(base: dict, roles: list[dict]):
        for r in roles:
            rows.append({**base, **r})

    stations = co.dukes_bmu_map()
    d = dukes_with_stations(year)
    for r in d.itertuples():
        owners, operator, basis = co.resolve(r.company, when, station=r.station, cm_parents=cm)
        add({"register": "dukes", "record_id": r.record_id, "record_name": r.site, "tech_class": r.tech_class,
             "technology": r.technology, "capacity_mw": r.capacity_mw, "status": d.attrs["sheet"],
             "company": r.company, "station": r.station,
             "bmu_ids": ";".join(stations.loc[r.station, "bmus"]) if r.station else ""},
            _roles(owners, operator, basis))

    register = ro_or_none()
    ro = ro_in_year(register, year) if register is not None else pd.DataFrame(columns=["record_id"])
    links = farm_ro_links()
    ro_bmus = {i: b for ids, b in zip(links["ro_ids"], links["bmu_ids"]) for i in ids}
    for r in ro.itertuples():
        owners, operator, basis = co.resolve(r.company, when, cm_parents=cm, address=r.address)
        add({"register": "ro", "record_id": r.record_id, "record_name": r.station, "tech_class": r.tech_class,
             "technology": r.technology, "capacity_mw": r.capacity_mw, "status": r.status,
             "company": r.company, "bmu_ids": ";".join(ro_bmus.get(r.record_id, []))},
            _roles(owners, operator, basis))

    bmus = cfd_bmus(year)
    for r in cfd_in_year(cfd_register(), year).itertuples():
        owners, operator, basis = co.resolve(r.company, when, cm_parents=cm, address=r.address,
                                             company_number=r.company_number)
        add({"register": "cfd", "record_id": r.record_id, "record_name": r.project, "tech_class": r.tech_class,
             "technology": r.technology, "capacity_mw": r.capacity_mw, "status": r.status, "company": r.company,
             "company_number": r.company_number, "bmu_ids": ";".join(bmus.get(r.record_id, []))},
            _roles(owners, operator, basis))

    force = cm_in_force(cm_units(), year).rename(columns=CM_NAMES)
    force["derated_mw"] = pd.to_numeric(force["derated_mw"], errors="coerce")
    force["capacity_mw"] = pd.to_numeric(force["capacity_mw"], errors="coerce")
    force = force.sort_values("derated_mw", ascending=False).drop_duplicates("cmu_id")
    comp = component_units(year)
    cm_bmus = comp.groupby(["Auction Name", "CMU ID"])["unit_id"].apply(lambda s: ";".join(sorted(set(s))))
    for r in force.itertuples(index=False):
        owners, operator, basis = _cm_owner(r.applicant, r.parent, when, cm)
        add({"register": "cm", "record_id": r.cmu_id, "record_name": r.cmu_name,
             "tech_class": cm_class(r.fuel, r.cmu_technology, r.cmu_name, r.applicant),
             "technology": " / ".join(x.strip() for x in (r.fuel, r.cmu_technology)
                                      if isinstance(x, str) and x.strip().lower() not in ("", "nan")),
             "capacity_mw": r.capacity_mw, "derated_mw": r.derated_mw, "status": f"in force {year}/{year + 1}",
             "company": r.applicant, "bmu_ids": cm_bmus.get((r.auction, r.cmu_id), "")},
            _roles(owners, operator, basis))

    for r in bm_register(year).query("active").itertuples():
        t = _trader(r, year, cm)            # the BM-unit table's trader: documented, the year's snapshot, or checked
        add({"register": "bm", "record_id": r.unit_id, "record_name": r.unit_name, "tech_class": bm_class(r),
             "technology": r.tech, "capacity_mw": r.capacity_mw, "status": "active", "company": t["company"],
             "bmu_ids": r.unit_id},
            [{"role": "trader", "group": t["group"], "share": 1.0, "basis": t["basis"]}])

    out = pd.DataFrame(rows).reindex(columns=RECORD_COLUMNS)
    out["year"], out["as_of"] = year, when.date()
    out["company"] = out["company"].map(lambda s: co.clean(s) if isinstance(s, str) and s else s)
    return one_spelling(out, spellings)


@lru_cache(maxsize=None)
def _offshore_units() -> dict[str, bool]:
    links = farm_ro_links()
    return {u: bool(o) for units, o in zip(links["bmu_ids"], links["is_offshore"]) if pd.notna(o) for u in units}


def bm_class(r) -> str:
    """A BM unit's class: the register's technology; a wind unit offshore or onshore by the farm map, onshore if
    embedded, else "wind"."""
    if r.tech != "wind":
        return BM_CLASS.get(r.tech, "other")
    off = _offshore_units().get(r.unit_id)
    if off is not None:
        return "offshore_wind" if off else "onshore_wind"
    return "onshore_wind" if r.connection == "embedded" else "wind"


def bmu_links(year: int) -> dict[str, dict[str, dict]]:
    """unit -> register -> {"company", "record_id", "station", "address", "parent", "company_number"}: every
    register that names a company for the unit in `year`."""
    out: dict[str, dict[str, dict]] = {}

    def put(unit, register, **kw):
        out.setdefault(unit, {}).setdefault(register, kw)

    cfd = cfd_in_year(cfd_register(), year).set_index("record_id")
    for cid, units in cfd_bmus(year).items():
        if cid in cfd.index:
            for u in units:
                put(u, "cfd", company=cfd.loc[cid, "company"], record_id=cid, address=cfd.loc[cid, "address"],
                    company_number=cfd.loc[cid, "company_number"])
    for station, s in co.dukes_bmu_map().iterrows():
        company, rid = dukes_company(station, year)
        for u in s["bmus"]:
            put(u, "dukes", company=company, record_id=rid, station=station)
    for f in farm_ro_links().itertuples():
        if f.holder:
            for u in f.bmu_ids:
                put(u, "ro", company=f.holder, record_id=";".join(f.ro_ids), address=f.address)
    for r in cm_bmu_links(year).itertuples(index=False):
        put(r.unit_id, "cm", company=r.applicant, record_id=r.cmu_id, parent=r.parent)
    return out


@lru_cache(maxsize=None)
def _unit_owners(year: int) -> dict[str, tuple[list[dict], str]]:
    """unit -> (owner and operator rows, operator group) for every active BM unit of `year`, at the year's as-of
    date: the first register that links to the unit, else its lead party as owner (not for a battery), else
    unresolved."""
    when, cm = as_of(year), cm_parents()
    links = bmu_links(year)
    out = {}
    for r in bm_register(year).query("active").itertuples():
        rows, operator = [], ""
        for register in LINK_ORDER:
            link = links.get(r.unit_id, {}).get(register)
            if not link:
                continue
            if register == "cm":
                owners, operator, basis = _cm_owner(link["company"], link.get("parent"), when, cm)
            else:
                owners, operator, basis = co.resolve(link["company"], when, station=link.get("station", ""),
                                                     cm_parents=cm, address=link.get("address"),
                                                     company_number=link.get("company_number", ""))
            if not owners:
                continue
            rows = [{**x, "company": link["company"], "register": register, "record_id": link["record_id"]}
                    for x in _roles(owners, operator, basis)]
            break
        if rows and rows[0]["basis"] != "curated" and pd.notna(r.party_name):
            # a joint venture's own company that trades the unit carries the venture's dated rows, which describe the
            # unit better than a register naming another company (Gunfleet Sands: the RO register's holder, Orsted
            # Burbo (UK), also holds Burbo Bank, which is Orsted's alone)
            owners, jv_operator, basis = co.resolve(r.party_name, when, cm_parents=cm)
            if basis == "curated":
                operator = jv_operator
                rows = [{**x, "company": r.party_name, "register": "bm", "record_id": r.unit_id}
                        for x in _roles(owners, operator, basis)]
        if not rows and r.tech != "battery" and pd.notna(r.party_name):
            owners, operator, basis = co.resolve(r.party_name, when, cm_parents=cm)
            rows = [{**x, "company": r.party_name, "register": "bm", "record_id": r.unit_id}
                    for x in _roles(owners, operator, basis if basis == "curated" else "lead_party")]
        if not rows:
            operator = ""
            rows = [{"role": role, "group": co.UNRESOLVED, "share": 1.0, "company": "", "basis": "none",
                     "register": "", "record_id": ""} for role in ("owner", "operator")]
        out[r.unit_id] = (rows, operator)
    return out


def _trader(r, year: int, cm) -> dict:
    """The trader row of a BM unit for `year` (see the module docstring: curated lead party, the year's register
    snapshot, or today's register checked against the unit's change of hands)."""
    when = as_of(year)
    lead = co.lead_party_at(r.unit_id, when)
    if lead:
        group, basis = co.trader_group(lead, when, cm)
        return {"role": "trader", "group": group or co.UNRESOLVED, "share": 1.0, "company": lead, "basis": basis,
                "register": "curated", "record_id": r.unit_id}
    party = r.party_name if pd.notna(r.party_name) else ""
    group, basis = co.trader_group(party, when, cm) if party else ("", "")
    register = "bm"
    if getattr(r, "party_basis", "register") == "proxy":
        register = "bm_proxy"
        rows, then = _unit_owners(year).get(r.unit_id, ([], ""))
        snap_year = pd.Timestamp(r.register_date).year
        try:
            now = _unit_owners(snap_year).get(r.unit_id, ([], ""))[1] if snap_year != year else then
        except FileNotFoundError:           # the snapshot's year is not built: the proxy stays unchecked
            _warn_once(f"bm_unit_register_{snap_year}.csv is not built, so the proxies of {year} stay unchecked "
                       f"(python -m gbpowerdata.build.bm_units --years {snap_year} {snap_year})")
            now = ""
        # only a dated source can show a change of hands (a curated row, or the year's DESNZ list); a difference in
        # spelling or in which register links the unit in each year is not one
        dated_source = any(x["role"] == "operator" and (x["basis"] == "curated" or x["register"] == "dukes") for x in rows)
        if dated_source and then and now and co.norm(then) != co.norm(now) and co.UNRESOLVED not in (then, now):
            group, basis, register = then, "operator_at_date", "operator_at_date"
    return {"role": "trader", "group": group or co.UNRESOLVED, "share": 1.0, "company": party,
            "basis": basis or "none", "register": register, "record_id": r.unit_id}


def bmu_roles(year: int, spellings: dict[str, str] | None = None) -> pd.DataFrame:
    """One row per active BM unit, role and group for `year` (see the module docstring); `spellings` as
    one_spelling takes them."""
    cm = cm_parents()
    owners = _unit_owners(year)
    rows = []
    for r in bm_register(year).query("active").itertuples():
        base = {"unit_id": r.unit_id, "unit_name": r.unit_name, "tech_class": bm_class(r),
                "connection": r.connection, "capacity_mw": r.capacity_mw}
        rows += [{**base, **x} for x in owners[r.unit_id][0]]
        rows.append({**base, **_trader(r, year, cm)})
    out = pd.DataFrame(rows).reindex(columns=BMU_COLUMNS)
    out["year"], out["as_of"] = year, as_of(year).date()
    out["company"] = out["company"].map(lambda s: co.clean(s) if isinstance(s, str) and s else s)
    return one_spelling(out, spellings)


_WARNED: set[str] = set()


def _warn_once(message: str) -> None:
    if message not in _WARNED:
        _WARNED.add(message)
        print(f"  WARNING: {message}", flush=True)


def preferred_spelling(spellings) -> str:
    """The spelling of a name the tables use: mixed case before capitals only, then the most capital letters (an
    acronym kept: "AMP Projects FinCo", not "Amp Projects Finco"), then the shortest, then the first
    alphabetically."""
    return min(spellings, key=lambda s: (s == s.upper(), -sum(c.isupper() for c in s), len(s), s))


def _spellings() -> dict[str, str]:
    """Normalised name -> its preferred spelling (single-spaced), over every company and parent name the registers
    give, so the choice is the same in every year and table."""
    names = list(cfd_register()["company"])
    cm = cm_units()
    names += list(cm["Name of Applicant"]) + list(cm["Parent Company"])
    if (ro := ro_or_none()) is not None:
        names += list(ro["company"])
    for y in YEARS:
        try:
            names += list(dukes_stations(y)["company"])
        except (FileNotFoundError, ValueError):
            continue
    try:
        for path in register_files().values():
            names += list(pd.read_csv(path, usecols=["leadPartyName"])["leadPartyName"])
    except (FileNotFoundError, ValueError):
        pass
    by: dict[str, set] = {}
    for n in names:
        if isinstance(n, str) and (key := co.norm(n)):
            by.setdefault(key, set()).add(re.sub(r"\s+", " ", co.clean(n)))
    return {k: preferred_spelling(v) for k, v in by.items()}


def one_spelling(t: pd.DataFrame, spellings: dict[str, str] | None = None) -> pd.DataFrame:
    """`t` with each group in its one spelling (_spellings, read here unless given); the groups that rules,
    aliases and curated rows name keep theirs."""
    spellings = _spellings() if spellings is None else spellings
    known = ({g for g, _ in co.GROUP_RULES} | set(co.company_groups().values())
             | set(co.company_owners()["owner"]) | {co.UNRESOLVED})
    to = {g: g if g in known else spellings.get(co.norm(g), g) for g in t["group"].dropna().unique()
          if isinstance(g, str)}
    t["group"] = t["group"].map(lambda g: to.get(g, g))
    return t


def summary(rec: pd.DataFrame, bmu: pd.DataFrame) -> str:
    """Capacity per register and the BM units' owner coverage, for the build log."""
    owners = rec[rec["role"].isin(["owner", "trader"])].copy()
    owners["mw"] = owners["capacity_mw"] * owners["share"].fillna(0)
    by = owners.groupby("register").agg(records=("record_id", "nunique"), gw=("mw", lambda s: s.sum() / 1e3))
    unit = bmu[bmu["role"] == "owner"].copy()
    unit["mw"] = unit["capacity_mw"] * unit["share"].fillna(0)
    resolved = unit.loc[unit["group"] != co.UNRESOLVED, "mw"].sum() / max(unit["mw"].sum(), 1e-9)
    strict = unit.loc[~unit["basis"].isin(["none", "lead_party"]), "mw"].sum() / max(unit["mw"].sum(), 1e-9)
    regs = " | ".join(f"{k} {int(v.records):,} records {v.gw:.1f} GW" for k, v in by.iterrows())
    return f"{regs} || BM units' owner: {strict:.0%} of capacity from a register, {resolved:.0%} with lead parties"


def write(years=YEARS, out_dir: Path | None = None) -> None:
    out_dir = cfg.processed_dir() if out_dir is None else out_dir
    spellings = _spellings()
    for y in years:
        rec, bmu = records(y, spellings), bmu_roles(y, spellings)
        rec.to_csv(out_dir / f"ownership_{y}.csv", index=False)
        bmu.to_csv(out_dir / f"ownership_bmu_{y}.csv", index=False)
        print(f"  {y}: {summary(rec, bmu)} -> ownership_{y}.csv, ownership_bmu_{y}.csv", flush=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--years", nargs=2, type=int, default=[YEARS[0], YEARS[-1]])
    a = ap.parse_args(argv)
    write(range(a.years[0], a.years[1] + 1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
