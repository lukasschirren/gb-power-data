"""Check data/reference/company_owners.csv against The Crown Estate's tables of offshore wind farm ownership.

Why: the offshore wind rows of company_owners.csv (who owns what share of each joint venture, and who runs it, over
time) were checked by hand against The Crown Estate's tables at the ends of 2018, 2019, 2020, 2023 and 2024
(ce-2018 ... ce-2024 in ownership_sources.csv). This build does that check in code, for every table pulled and
every table transcribed, so an edit to company_owners.csv, a new year's table or a corrected one shows at once
where the curated table and The Crown Estate disagree, and whether the disagreement is known and why.

Inputs:
  data/raw/crown_estate/wind_farm_ownership_{YYYYMMDD}.html  the web tables, end-2023 on (gbpowerdata.pull.
                                                              crown_estate_pull)
  data/reference/crown_estate_ownership_reports.csv          optional and LOCAL ONLY (see Source and terms): the
                                                              tables of the offshore wind operational reports for
                                                              the ends of 2018-2020, transcribed by hand (as_at,
                                                              section, farm, operator, holder, holder_printed,
                                                              share_pct, source_id, page); read where it exists.
                                                              holder is the holder's full name without its
                                                              footnote marker, completed from the table's footnote
                                                              where the report's bar cuts the name short or prints
                                                              only a share and a marker; holder_printed is the
                                                              label exactly as printed, with the marker as plain
                                                              digits straight after it ("Marubeni...3", "DBJ2",
                                                              "10.0%10"), kept to check the transcription. The
                                                              build does not read holder_printed, or any other
                                                              extra column
  data/reference/crown_estate_farms.csv                      The Crown Estate's farm name -> the company under
                                                              which company_owners.csv keys the farm (entity)
  data/reference/company_owners.csv, company_groups.csv      through gbpowerdata.common.companies

Method, for every table date and every farm that crown_estate_farms.csv maps (matched on the name without case,
accents and punctuation, so "Gwynt y Môr" and "Gwynt y Mor" are one farm):
  ours      gbpowerdata.common.companies.resolve(entity, as_at): the owners' groups and shares on that date, and
            the operator. The part the known shares leave "unresolved" is not a group and is left out.
  theirs    each holder's group by HOLDER_GROUPS (a regex on The Crown Estate's name, first match wins; a holder no
            rule names is its own group, its name without the legal form), shares summed per group. The operator
            (the lead developer for a farm under construction) goes through the same rules.
  vehicles  a company that holds one stake for several owners (VEHICLES: Ocean Winds for EDP Renewables and ENGIE,
            Diamond Green for INPEX, Kansai Electric and Mitsubishi HC Capital in Moray East): where one side names
            the vehicle and the other its owners, the owners' shares are summed into the vehicle first.
  A difference is a group on one side only (kind "group"), a share off by more than TOLERANCE_PP percentage points
  where both sides give one ("share"), or another operator ("operator"; compared where the table names one). Where
  company_owners.csv has no rows for the farm's company on the table's date (resolve() then falls back to the
  company's own group), the farm-date is one difference of kind "no_rows" (company_owners "no rows on this date",
  crown_estate the table's holdings), not a comparison with a 100% stake that company does not hold.

Known differences: KNOWN_DIFFERENCES lists the differences that are understood, each exactly as compare() reports
it: its table date (or "" for every date), farm, kind and group ("" for an operator or no_rows), the company_owners
and crown_estate values, and the reason. A difference is known only when all of them match, so an entry never hides
another difference of the same kind at that farm, on its date or later. An entry that matched nothing, of a date
among the dates compared or of no date, is reported as unused: the difference it explained has gone (corrected) or
changed, and the entry is to be removed or updated.

Farms not compared: NOT_COMPARED names the farms of the tables that crown_estate_farms.csv leaves out on purpose:
single-owner farms such as Barrow and Thanet, whose companies have no rows in company_owners.csv, and Rhyl Flats, a
joint venture without rows so far. Each entry carries the holdings every table is expected to show for the farm,
written as the build writes a table's holdings by group ("100% Orsted"; "50.1% RWE; 24.95% Greencoat UK Wind;
24.95% Macquarie"), or None for a farm held whole by any one holder (Kincardine, whose holder changed), and the
reason it is left out. A farm-date whose holdings differ from those expected (a group on one side only, or a share
off by more than TOLERANCE_PP points where both give one; the order does not matter) is reported as NOT_COMPARED
CHANGED: a sale or a new partner may mean the farm now has to be compared. A farm in neither the map nor
NOT_COMPARED is reported as NOT MAPPED.

  Port of a one-off hand check of 6 Oct 2026 (end-2023 and end-2024 tables only): its farm map is
  data/reference/crown_estate_farms.csv (with Walney 2, Robin Rigg West, Scroby Sands and the reports' spellings
  added, and names matched loosely instead of its "Gwynt" prefix rule) and its regexes are HOLDER_GROUPS, changed
  in three ways. ScottishPower is found by its own name too (the operator column says "ScottishPower Renewables");
  EDP Renewables, ENGIE, INPEX, Kansai Electric and Mitsubishi HC Capital ("Mitsubishi UFG" in the end-2023 table)
  are their own groups, and VEHICLES replaces the check's special case for Moray East (which pooled the three
  Japanese owners as Diamond Green whatever the table said); and the names of the 2018-2020 reports are added
  ("UK GIG OWF", "Global Infrastructure Partners", "PGGM & AEF", ...). The operators are compared too. The check's
  one difference, Moray West at the end of 2023, is a known difference here.

Source and terms: The Crown Estate, "Offshore wind farm ownership"
(https://www.thecrownestate.co.uk/our-business/marine/wind-farm-ownership) and its offshore wind operational reports
for 2018-2020 (ce-2018, ce-2019, ce-2020 in ownership_sources.csv, with their URLs). The Crown Estate's terms of use
(https://www.thecrownestate.co.uk/about-us/terms-of-use; see gbpowerdata.pull.crown_estate_pull) license
information downloaded from its site for the user's own use and forbid providing digital copies to third parties.
So crown_estate_ownership.csv stays on the machine that built it and is not in the data pack, and
data/reference/crown_estate_ownership_reports.csv, a digital copy of the reports' tables, is LOCAL ONLY: it must
never be published, committed, packed or passed on (.gitignore leaves out every file of data/reference/ it does not
name, and must never name this one). The build, and its tests, run without it. What the repository publishes are
the facts, which company held what share of a farm on a date, each cited to The Crown Estate in
ownership_sources.csv.

Personal data: none. The tables, the transcription and the output name companies, funds and their shares only.

Gotchas:
  - The tables name a farm differently over the years ("Hywind 2 Demonstration", "Hywind Scotland (Buchan Deep)")
    and name some holders as a vehicle or a fund manager: each spelling has its row in crown_estate_farms.csv, and
    HOLDER_GROUPS and VEHICLES do the rest. A farm name new to both the map and NOT_COMPARED fails --strict.
  - The 2018-2020 reports group some holders unlike the other years (Race Bank at the end of 2018, Sheringham Shoal
    at the end of 2020): known differences of their dates, not corrections to company_owners.csv.
  - An entry of KNOWN_DIFFERENCES without a date explains its exact difference on every date, and is reported as
    unused once no table shows it.
  - A farm of NOT_COMPARED is checked only against the holdings its entry expects, not against company_owners.csv:
    when it changes hands, --strict fails until the farm is mapped (with rows in company_owners.csv) or the entry is
    updated.
  - reports() refuses a transcribed row without a farm, operator or holder, or whose section is neither operational
    nor under construction, rather than comparing a blank.

Output: data/processed/crown_estate_ownership.csv, one row per table date, farm and holder: as_at, section, farm,
entity (blank where the map has none), operator, operator_group, holder, share_pct, group, source (the snapshot's
file name or the report's source_id), page (the report's page; blank for the web tables). The differences are
printed (compare() returns them), with each farm not compared and its reason, the farm-dates of NOT_COMPARED whose
holdings changed, the farms NOT MAPPED and the unused known differences.

Usage:
  python -m gbpowerdata.build.build_crown_estate             # writes the table, prints a summary and the differences
  python -m gbpowerdata.build.build_crown_estate --strict    # exits 1 on a difference not in KNOWN_DIFFERENCES, a
                                                             # farm NOT MAPPED, a KNOWN_DIFFERENCES entry unused, or
                                                             # a farm of NOT_COMPARED whose holdings changed
"""
from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from typing import NamedTuple

import numpy as np
import pandas as pd

from gbpowerdata import config as cfg
from gbpowerdata.common import companies as co
from gbpowerdata.pull import crown_estate_pull as ce

FARMS_FILE = "crown_estate_farms.csv"
REPORTS_FILE = "crown_estate_ownership_reports.csv"
# the columns of REPORTS_FILE the build reads; any other (holder_printed) is ignored
REPORTS_COLUMNS = ["as_at", "section", "farm", "operator", "holder", "share_pct", "source_id", "page"]
OUT_FILE = "crown_estate_ownership.csv"
TOLERANCE_PP = 0.5
KINDS = ("group", "share", "operator", "no_rows")
NO_ROWS = "no rows on this date"
OUT_COLUMNS = ["as_at", "section", "farm", "entity", "operator", "operator_group", "holder", "share_pct", "group",
               "source", "page"]
DIFF_COLUMNS = ["as_at", "farm", "entity", "kind", "group", "company_owners", "crown_estate", "known", "reason",
                "source"]

# The Crown Estate's holder (or operator) name -> the group company_owners.csv uses; regexes, case-sensitive as the
# tables are, first match wins. Funds go to their manager's group as company_owners.csv has them: GIG (Green
# Investment Group, Macquarie's since 2017) and MIRA to Macquarie, Greencoat Renewable Income and Greencoat London
# Array to Schroders Greencoat. Order matters: "Legal & General NTR Fund and Dev Bank of Japan" is one holder, NTR
# and DBJ; "Equitix and TRIG" one holder before Equitix and TRIG alone.
HOLDER_GROUPS = (
    (r"rsted", "Orsted"),                                    # Ørsted, and Orsted where the letter is lost
    (r"^RWE|[Ii]nnogy", "RWE"),
    (r"^E\.ON", "E.ON"),
    (r"^SSE", "SSE"),
    (r"Iberdrola|Scottish ?Power", "ScottishPower"),
    (r"Equinor", "Equinor"),
    (r"Vattenfall", "Vattenfall"),
    (r"EDF", "EDF"),
    (r"^ESB", "ESB"),
    (r"Masdar", "Masdar"),
    (r"China Resources", "China Resources"),
    (r"Caisse|CDPQ", "CDPQ"),
    (r"Enbridge", "Enbridge"),
    (r"GIG|Green Investment|MIRA|Macquarie", "Macquarie"),
    (r"^Greencoat UK Wind", "Greencoat UK Wind"),
    (r"Greencoat (Renewable Income|London Array)", "Schroders Greencoat"),
    (r"Equitix and TRIG", "Equitix and TRIG"),
    (r"^Equitix", "Equitix"),
    (r"TRIG|Renewables Infrastructure Group", "TRIG"),
    (r"InfraRed", "InfraRed"),
    (r"PKA", "PKA"),
    (r"PFA", "PFA"),
    (r"KIRKBI", "KIRKBI"),
    (r"PGGM ?(&|and) ?(Amp|AEF)", "PGGM and Ampere Equity Fund"),   # one 24.8% of Walney in the end-2018 table
    (r"PGGM", "PGGM"),
    (r"Amp.re Equity", "Ampere Equity Fund"),
    (r"Legal & General|\bNTR\b", "NTR and DBJ"),
    (r"Dev\.? Bank of Japan|Development Bank of Japan|DBJ", "DBJ"),
    (r"JERA", "JERA"),
    (r"Sumitomo", "Sumitomo"),
    (r"Siemens", "Siemens"),
    (r"Stadtwerke", "Stadtwerke Muenchen"),
    (r"BlackRock", "BlackRock"),
    (r"^AMF", "AMF"),
    (r"Dalmore", "Dalmore"),
    (r"Tenaga", "TNB"),
    (r"Arjun", "Arjun"),
    (r"Gravis", "Gravis"),
    (r"Universities Superannuation", "USS"),
    (r"StepStone|Stepstone", "StepStone"),
    (r"Norges", "NBIM"),
    (r"Brookfield", "Brookfield"),
    (r"AXA", "AXA IM"),
    (r"Agricole", "Credit Agricole Assurances"),
    (r"GLIL", "GLIL and Octopus"),
    (r"Octopus", "Octopus"),
    (r"SDIC", "SDIC"),
    (r"TotalEnergies", "TotalEnergies"),
    (r"PTTEP", "PTTEP"),
    (r"V.rgr.nn", "Vargronn"),
    (r"Ocean Winds", "Ocean Winds"),
    (r"EDP Renewables|\bEDPR\b", "EDP Renewables"),
    (r"^ENGIE|^Engie", "ENGIE"),
    (r"Diamond Green", "Diamond Green"),
    (r"Inpex|INPEX", "INPEX"),
    (r"Mitsubishi UF[GJ]|Mitsubishi HC", "Mitsubishi HC Capital"),   # Mitsubishi UFJ Lease, now Mitsubishi HC Capital
    (r"Kansai", "Kansai Electric"),
    (r"Ignitis", "Ignitis"),
    (r"China Three Gorges", "China Three Gorges"),
    (r"J-Power", "J-Power"),
    (r"Global Infrastructure Partners|\bGIP\b", "GIP"),
    (r"Copenhagen Infrastructure|\bCIP\b", "CIP"),
    (r"Marubeni", "Marubeni"),
    (r"Pilot Offshore", "Pilot Offshore Renewables"),
    (r"ORE Catapult|Offshore Renewable Energy Catapult|\bORE-C\b", "ORE Catapult"),
    (r"^XceCo$|^Xceco$", "XceCo"),                         # the operator of Inner Dowsing and Lynn
)
_HOLDER_RULES = tuple((re.compile(p), g) for p, g in HOLDER_GROUPS)

# a company that holds one stake for several owners: where one side of the comparison names it and the other its
# owners, the owners' shares are summed into it (see the module docstring)
VEHICLES = {
    "Ocean Winds": ("EDP Renewables", "ENGIE"),          # EDPR's and ENGIE's 50:50 offshore wind venture (2020)
    "Diamond Green": ("INPEX", "Kansai Electric", "Mitsubishi HC Capital"),   # Moray East's 33.4% (EDP, 7 May 2024)
    "Equitix and TRIG": ("Equitix", "TRIG"),             # one 25% of Hornsea 1, held together
    "GLIL and Octopus": ("GLIL", "Octopus"),             # one 12.5% of Hornsea 1, held together
    "NTR and DBJ": ("NTR", "DBJ"),                       # one 10% of East Anglia ONE, held together
    "PGGM and Ampere Equity Fund": ("PGGM", "Ampere Equity Fund"),   # one 24.8% of Walney at the end of 2018
}


class Known(NamedTuple):
    """A known difference: the values compare() reports for it on each side, and why it is expected. A value is a
    share in % as _pct writes it ("25", "6.25"), "" for a group not on that side, an operator's group, or, for a
    "no_rows" difference, NO_ROWS on the company_owners side and the table's holdings on the other."""

    company_owners: str
    crown_estate: str
    reason: str


_MORAY_WEST_2023 = (
    "the end-2023 table names Inpex as the 5% holder; Ignitis Renewables held it from the financial close (Ignitis, "
    "21 Apr 2023: Ocean Winds and Ignitis Renewables 'as a minority shareholder of 5 percent') and the end-2024 "
    "table names Ignitis, so company_owners.csv keeps Ignitis (INPEX's stake is in Moray East)")
_RACE_BANK_2018 = (
    "the end-2018 report lists 37.5% under Macquarie Capital: MEIF5's 25% and the 12.5% of the funds advised by GIG, "
    "Arjun and Gravis (orsted-2018-race-bank), which the reports from the end of 2019 list apart (Arjun and Gravis, "
    "6.3% each at the end of 2019, 6.25% from the end of 2020)")
_SHERINGHAM_SHOAL_2020 = (
    "the end-2020 report lists 40% Equitix with TRIG's 14.7% within it; the tables for the ends of 2018, 2019, 2023 "
    "and 2024 list TRIG apart (25.3% Equitix, 14.7% TRIG)")

# (table date as "YYYY-MM-DD", or "" for every date; The Crown Estate's farm name; kind; group, or "" for an operator
# or no_rows) -> the values the difference holds and why it is expected. Reported with its reason, never a failure;
# a difference with other values is not this one (see the module docstring).
KNOWN_DIFFERENCES: dict[tuple[str, str, str, str], Known] = {
    ("2023-12-31", "Moray West", "group", "Ignitis"): Known("5", "", _MORAY_WEST_2023),
    ("2023-12-31", "Moray West", "group", "INPEX"): Known("", "5", _MORAY_WEST_2023),
    # The Crown Estate names a venture's own company where company_owners.csv names the partner that runs it
    ("", "Moray East", "operator", ""): Known(
        "Ocean Winds", "Moray Offshore Windfarm (East)",
        "The Crown Estate names the project company, Moray Offshore Windfarm (East) Ltd, as operator; "
        "company_owners.csv names the partner it takes to run it, Ocean Winds (EDPR's and ENGIE's venture)"),
    ("", "Moray West", "operator", ""): Known(
        "Ocean Winds", "Moray Offshore Windfarm (West)",
        "The Crown Estate names the project company, Moray Offshore Windfarm (West) Ltd, as lead developer; "
        "company_owners.csv names its 95% owner, Ocean Winds"),
    ("", "Neart na Gaoithe", "operator", ""): Known(
        "EDF", "Neart na Gaoithe Offshore Wind",
        "The Crown Estate names the project company, Neart na Gaoithe Offshore Wind Limited, as lead developer; "
        "company_owners.csv names EDF, whose EDF Renewables leads the delivery in its evidence (esb-2019-nng)"),
    # the report tables (crown_estate_ownership_reports.csv) group some holders differently from the other years
    ("2018-12-31", "Race Bank", "share", "Macquarie"): Known("25", "37.5", _RACE_BANK_2018),
    ("2018-12-31", "Race Bank", "group", "Arjun"): Known("6.25", "", _RACE_BANK_2018),
    ("2018-12-31", "Race Bank", "group", "Gravis"): Known("6.25", "", _RACE_BANK_2018),
    ("2020-12-31", "Sheringham Shoal", "share", "Equitix"): Known("25.3", "40", _SHERINGHAM_SHOAL_2020),
    ("2020-12-31", "Sheringham Shoal", "group", "TRIG"): Known("14.7", "", _SHERINGHAM_SHOAL_2020),
}


class LeftOut(NamedTuple):
    """A farm of the tables left out of the comparison on purpose: the holdings every table is expected to show for
    it, written as _holdings writes a table's groups ("100% Orsted"), or None for a farm held whole by any one holder
    (one group, its share 100% or not given); and why it is left out."""

    holdings: str | None
    reason: str


# The farms of the tables that crown_estate_farms.csv leaves out on purpose -> the holdings expected and why (names
# matched as farm_key does). A farm with one owner has no rows in company_owners.csv, which records joint ventures and
# sales, so there is nothing to compare it with; its holdings are checked instead, so that a sale shows (see the
# module docstring). Any other farm the map does not name is NOT MAPPED, and fails --strict.
_ONE_OWNER = "one owner, so no rows in company_owners.csv"
NOT_COMPARED: dict[str, LeftOut] = {
    "Barrow": LeftOut("100% Orsted", f"100% Ørsted in every table that lists it: {_ONE_OWNER}"),
    "Blyth": LeftOut("100% E.ON", "E.ON's farm of 2000 (not Blyth Demonstration), 100% E.ON in the end-2018 report, "
                                  f"the only table that lists it: {_ONE_OWNER}"),
    "Burbo Bank": LeftOut("100% Orsted", f"100% Ørsted in every table that lists it: {_ONE_OWNER}"),
    "European Offshore Wind Deployment Centre": LeftOut(
        "100% Vattenfall", f"100% Vattenfall in every table that lists it: {_ONE_OWNER}"),
    "European Offshore Wind Deployment Centre (Aberdeen)": LeftOut(
        "100% Vattenfall", "the end-2024 table's name for the European Offshore Wind Deployment Centre, 100% "
                           f"Vattenfall in every table that lists it: {_ONE_OWNER}"),
    "Gunfleet Sands Demonstration": LeftOut("100% Orsted", f"100% Ørsted in every table that lists it: {_ONE_OWNER}"),
    "Kentish Flats": LeftOut("100% Vattenfall", f"100% Vattenfall in every table that lists it: {_ONE_OWNER}"),
    "Kentish Flats Extension": LeftOut("100% Vattenfall",
                                       f"100% Vattenfall in every table that lists it: {_ONE_OWNER}"),
    "Kincardine": LeftOut(None, "one holder in each table that lists it (Atkins at the end of 2018, Pilot Offshore "
                                "Renewables at the ends of 2023 and 2024) and no rows in company_owners.csv"),
    "Levenmouth Demonstration": LeftOut("100% ORE Catapult",
                                        f"100% ORE Catapult in every table that lists it: {_ONE_OWNER}"),
    "Rhyl Flats": LeftOut("50.1% RWE; 24.95% Greencoat UK Wind; 24.95% Macquarie",
                          "joint venture of RWE, Greencoat UK Wind and UK GIG; no company_owners rows yet"),
    "Sofia": LeftOut("100% RWE", "100% RWE in every table that lists it (under construction at the ends of 2023 and "
                                 f"2024): {_ONE_OWNER}"),
    "Thanet": LeftOut("100% Vattenfall", f"100% Vattenfall in every table that lists it: {_ONE_OWNER}"),
}


# ---------------------------------------------------------------------------- names
def holder_group(name) -> str:
    """The group of a holder (or operator) as The Crown Estate names it: the first HOLDER_GROUPS rule that matches,
    else the name itself without its legal form ("" for a blank name)."""
    s = ce.clean(name)
    if not s:
        return ""
    return next((g for rx, g in _HOLDER_RULES if rx.search(s)), co.clean(s))


def farm_key(name) -> str:
    """A farm's name for matching: no accents, case or punctuation ("Gwynt y Môr" = "Gwynt y Mor")."""
    s = unicodedata.normalize("NFKD", ce.clean(name))
    s = "".join(c for c in s if not unicodedata.combining(c)).casefold()
    return " ".join(re.sub(r"[^0-9a-z]+", " ", s).split())


# ---------------------------------------------------------------------------- inputs
def farm_map() -> pd.DataFrame:
    """data/reference/crown_estate_farms.csv: farm, entity, note."""
    return pd.read_csv(cfg.reference_dir() / FARMS_FILE, dtype=str, keep_default_na=False)


def reports() -> pd.DataFrame:
    """The hand-transcribed report tables (data/reference/crown_estate_ownership_reports.csv), as source (the
    report's source_id) and page beside the parsed columns; empty where the file is not there.

    LOCAL ONLY: the file is a digital copy of The Crown Estate's report tables, whose terms (information downloaded
    is for the user's own use; digital copies must not be passed to third parties) forbid publishing it. It is not
    in git or in any data pack and is never passed on; the build runs without it.

    Read as text (dtype=str, no value read as NaN). Only REPORTS_COLUMNS are used: holder_printed (the label as the
    report prints it) and any other extra column are ignored; a missing one raises ValueError. The section is
    normalised ("Under construction projects" -> under_construction, "Fully operational projects" -> operational),
    a share may carry "%", and a share that is neither blank nor a number, a row without a date, a row whose farm,
    operator or holder is blank, or a section that is neither raises ValueError rather than reaching the
    comparison."""
    path = cfg.reference_dir() / REPORTS_FILE
    columns = ce.COLUMNS + ["source", "page"]
    if not path.exists():
        return pd.DataFrame(columns=columns)
    t = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    missing = [c for c in REPORTS_COLUMNS if c not in t.columns]
    if missing:
        raise ValueError(f"{REPORTS_FILE}: no column {', '.join(missing)}")
    t = t[REPORTS_COLUMNS].rename(columns={"source_id": "source"})
    if (t["as_at"].str.strip() == "").any():
        raise ValueError(f"{REPORTS_FILE}: {int((t['as_at'].str.strip() == '').sum())} rows without an as_at date")
    t["as_at"] = pd.to_datetime(t["as_at"].str.strip(), format="%Y-%m-%d")
    share = t["share_pct"].str.replace("%", "", regex=False).str.strip()
    t["share_pct"] = pd.to_numeric(share.where(share != ""), errors="coerce")
    bad = (share != "") & t["share_pct"].isna()
    if bad.any():
        raise ValueError(f"{REPORTS_FILE}: shares that are no number: {sorted(set(share[bad]))}")
    for c in ("section", "farm", "operator", "holder"):
        t[c] = t[c].map(ce.clean)
    # a blank would be compared as a farm, operator or holder of its own; the file's line numbers (the header is 1)
    blank = {c: [i + 2 for i in t.index[t[c] == ""]] for c in ("farm", "operator", "holder")}
    if any(blank.values()):
        where = "; ".join(f"{c} (lines {', '.join(map(str, lines))})" for c, lines in blank.items() if lines)
        raise ValueError(f"{REPORTS_FILE}: rows with a blank {where}")
    section = t["section"].map(lambda s: "under_construction" if "construction" in s.lower()
                               else "operational" if "operational" in s.lower() else None)
    if section.isna().any():
        raise ValueError(f"{REPORTS_FILE}: sections that are neither operational nor under construction: "
                         f"{sorted(set(t.loc[section.isna(), 'section']))}")
    t["section"] = section
    return t[columns]


def snapshots() -> pd.DataFrame:
    """Every table: the pulled web tables (source: the snapshot's file name) and the transcribed report tables
    (source: the report's source_id), one row per table, farm and holder."""
    rep = reports()
    try:
        web = ce.table().assign(page="")
    except FileNotFoundError as e:
        if rep.empty:
            raise
        print(f"  WARNING: {e}; comparing the report tables only")
        web = pd.DataFrame(columns=rep.columns)
    frames = [f for f in (web, rep) if len(f)]
    t = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=rep.columns)
    t["as_at"] = pd.to_datetime(t["as_at"])
    return t


def with_groups(snap: pd.DataFrame, farms: pd.DataFrame | None = None) -> pd.DataFrame:
    """The tables with each holder's and operator's group and the farm's entity (OUT_COLUMNS)."""
    farms = farm_map() if farms is None else farms
    entity = {farm_key(f): e for f, e in zip(farms["farm"], farms["entity"])}
    t = snap.copy()
    for c in ("operator", "source", "page"):
        t[c] = t[c].fillna("") if c in t else ""
    t["entity"] = t["farm"].map(lambda f: entity.get(farm_key(f), ""))
    t["group"] = t["holder"].map(holder_group)
    t["operator_group"] = t["operator"].map(holder_group)
    return t.reindex(columns=OUT_COLUMNS)


# ---------------------------------------------------------------------------- comparison
def _sum(shares) -> float:
    """Shares of one group summed; NaN where any is not given."""
    s = pd.Series(list(shares), dtype=float)
    return float(s.sum()) if len(s) and s.notna().all() else np.nan


def _merge_vehicles(ours: dict, theirs: dict) -> tuple[dict, dict]:
    """Where one side names a vehicle and the other its owners, the owners' shares go into the vehicle."""
    ours, theirs = dict(ours), dict(theirs)
    for vehicle, members in VEHICLES.items():
        for a, b in ((ours, theirs), (theirs, ours)):
            held = [m for m in members if m in b]
            if vehicle in a and vehicle not in b and held:
                b[vehicle] = _sum(b.pop(m) for m in held)
    return ours, theirs


def _pct(x) -> str:
    return "no share" if pd.isna(x) else f"{round(float(x), 4):g}"


def _holdings(shares: dict) -> str:
    """A table's holdings by group, as the table writes them ("50% Orsted; 50% Beta Fund"; a group without a share
    by its name alone)."""
    return "; ".join(f"{_pct(s)}% {g}" if pd.notna(s) else g for g, s in shares.items())


_HOLDING = re.compile(r"(\d+(?:\.\d+)?)% (.+)")


def _holdings_of(text: str) -> dict:
    """The groups and shares of holdings written as _holdings writes them (its inverse; a group without a share has
    NaN)."""
    out = {}
    for part in text.split("; "):
        m = _HOLDING.fullmatch(part)
        out[m[2] if m else part] = float(m[1]) if m else np.nan
    return out


def _as_expected(theirs: dict, expected: str | None, tolerance: float) -> bool:
    """Whether a table's holdings by group are those a NOT_COMPARED entry expects: the same groups, in any order,
    each share within `tolerance` points where both give one (as compare() compares shares); for None, one group,
    its share 100% or not given."""
    if expected is None:
        return len(theirs) == 1 and all(pd.isna(s) or abs(s - 100.0) <= tolerance + 1e-9 for s in theirs.values())
    return not _differences(_holdings_of(expected), theirs, "", "", tolerance)


def not_compared_changed(t: pd.DataFrame, not_compared: dict | None = None,
                         tolerance: float = TOLERANCE_PP) -> list[tuple]:
    """The farm-dates of the farms `not_compared` (default NOT_COMPARED) names whose holdings are not those the entry
    expects (_as_expected), one per table (source) date and farm, in the order of farm and date: (farm as the table
    names it, as_at "YYYY-MM-DD", the table's holdings as _holdings writes them, the holdings expected or None).
    `t` is the tables with their groups and entities (with_groups); a farm the farm map names is compared instead,
    and not checked here."""
    not_compared = NOT_COMPARED if not_compared is None else not_compared
    expected = {farm_key(f): holdings for f, (holdings, _) in not_compared.items()}
    left_out = t[(t["entity"] == "") & t["farm"].map(lambda f: farm_key(f) in expected)].copy()
    left_out["as_at"] = pd.to_datetime(left_out["as_at"])
    out = []
    for (_, as_at, farm), fr in left_out.groupby(["source", "as_at", "farm"], sort=True, dropna=False):
        theirs = {g: _sum(s) for g, s in fr.groupby("group", sort=False)["share_pct"]}
        holdings = expected[farm_key(farm)]
        if not _as_expected(theirs, holdings, tolerance):
            out.append((farm, f"{as_at:%Y-%m-%d}", _holdings(theirs), holdings))
    return sorted(out, key=lambda x: (farm_key(x[0]), x[1]))


def _differences(ours: dict, theirs: dict, ours_op: str, theirs_op: str, tolerance: float) -> list[dict]:
    out = []
    for g in sorted(set(ours) | set(theirs), key=str.casefold):
        if g not in ours:
            out.append({"kind": "group", "group": g, "company_owners": "", "crown_estate": _pct(theirs[g])})
        elif g not in theirs:
            out.append({"kind": "group", "group": g, "company_owners": _pct(ours[g]), "crown_estate": ""})
        elif pd.notna(ours[g]) and pd.notna(theirs[g]) and abs(ours[g] - theirs[g]) > tolerance + 1e-9:
            out.append({"kind": "share", "group": g, "company_owners": _pct(ours[g]), "crown_estate": _pct(theirs[g])})
    if theirs_op and co.norm(ours_op) != co.norm(theirs_op):
        out.append({"kind": "operator", "group": "", "company_owners": ours_op, "crown_estate": theirs_op})
    return out


def _known_key(index: dict, known: dict, when: str, farm: str, d: dict):
    """The KNOWN_DIFFERENCES key that explains difference `d` (of `farm` on `when`) exactly, its own date before
    every date; None if none does."""
    for date in (when, ""):
        key = index.get((date, farm_key(farm), d["kind"], d["group"]))
        if key is not None:
            company_owners, crown_estate, _ = known[key]
            if company_owners == d["company_owners"] and crown_estate == d["crown_estate"]:
                return key
    return None


def compare(snap: pd.DataFrame | None = None, farms: pd.DataFrame | None = None,
            tolerance: float = TOLERANCE_PP, known: dict | None = None,
            not_compared: dict | None = None) -> pd.DataFrame:
    """The differences between company_owners.csv and The Crown Estate's tables (DIFF_COLUMNS), one row each: per
    table (source) date and mapped farm, a group on one side only, a share off by more than `tolerance` percentage
    points, or another operator; or, where company_owners.csv has no rows for the farm's company on that date, one
    "no_rows" difference. company_owners / crown_estate hold the share (in %, "" where the group is not on that
    side, "no share" where it is without one), the operator, or for no_rows NO_ROWS and the table's holdings.
    known/reason come from `known` (default KNOWN_DIFFERENCES), matched exactly (date or "", farm, kind, group and
    both values). attrs: "compared", the farm-dates compared; "not_compared", the farms of the tables that
    `not_compared` (default NOT_COMPARED: farm -> (holdings expected, reason)) names, each with its reason, as
    {farm as the tables name it: reason}; "not_compared_changed", those farms' farm-dates whose holdings are not
    those expected (not_compared_changed()); "unmapped", the farms in neither the farm map nor `not_compared`;
    "unused_known", the keys of `known` that matched no difference, of a date compared or of no date."""
    snap = snapshots() if snap is None else snap
    known = KNOWN_DIFFERENCES if known is None else known
    not_compared = NOT_COMPARED if not_compared is None else not_compared
    index = {(when, farm_key(farm), kind, group): (when, farm, kind, group) for when, farm, kind, group in known}
    t = with_groups(snap, farms)
    t["as_at"] = pd.to_datetime(t["as_at"])
    rows, compared, dates, used = [], 0, set(), set()
    for (source, as_at, farm), fr in t[t["entity"] != ""].groupby(["source", "as_at", "farm"], sort=True, dropna=False):
        entity = fr["entity"].iloc[0]
        when = f"{as_at:%Y-%m-%d}"
        compared += 1
        dates.add(when)
        theirs = {g: _sum(s) for g, s in fr.groupby("group", sort=False)["share_pct"]}
        owners, operator, basis = co.resolve(entity, as_at)
        if basis != "curated":      # no rows on this date: resolve() fell back to the company's own group, no owner
            found = [{"kind": "no_rows", "group": "", "company_owners": NO_ROWS, "crown_estate": _holdings(theirs)}]
        else:
            ours: dict[str, list] = {}
            for o in owners:
                if o["group"] != co.UNRESOLVED:
                    ours.setdefault(o["group"], []).append(o["share"] * 100.0 if pd.notna(o["share"]) else np.nan)
            mine, crown = _merge_vehicles({g: _sum(v) for g, v in ours.items()}, theirs)
            theirs_op = next((g for g in fr["operator_group"] if g), "")
            found = _differences(mine, crown, operator, theirs_op, tolerance)
        for d in found:
            key = _known_key(index, known, when, farm, d)
            if key is not None:
                used.add(key)
            rows.append({"as_at": when, "farm": farm, "entity": entity, **d, "known": key is not None,
                         "reason": known[key][2] if key is not None else "", "source": source})
    out = pd.DataFrame(rows, columns=DIFF_COLUMNS)
    out["known"] = out["known"].astype(bool)
    out.attrs["compared"] = compared
    names = sorted(set(t.loc[t["entity"] == "", "farm"]), key=str.casefold)
    reasons = {farm_key(f): reason for f, (_, reason) in not_compared.items()}
    out.attrs["not_compared"] = {f: reasons[farm_key(f)] for f in names if farm_key(f) in reasons}
    out.attrs["not_compared_changed"] = not_compared_changed(t, not_compared, tolerance)
    out.attrs["unmapped"] = [f for f in names if farm_key(f) not in reasons]
    out.attrs["unused_known"] = [k for k in known if k not in used and (k[0] == "" or k[0] in dates)]
    return out


# ---------------------------------------------------------------------------- report
def summary(snap: pd.DataFrame, diffs: pd.DataFrame) -> str:
    """The tables, the counts of compare(), each farm not compared with its reason, and one line for each farm-date
    of NOT_COMPARED that changed, farm NOT MAPPED and KNOWN_DIFFERENCES entry UNUSED."""
    dates = sorted({f"{d:%Y-%m-%d}" for d in pd.to_datetime(snap["as_at"])})
    known = int(diffs["known"].sum())
    unmapped, unused = diffs.attrs.get("unmapped", []), diffs.attrs.get("unused_known", [])
    changed = diffs.attrs.get("not_compared_changed", [])
    lines = [f"  tables: {len(dates)} dates ({', '.join(dates)}), {snap['farm'].nunique()} farm names, "
             f"{len(snap)} holdings",
             f"  compared: {diffs.attrs.get('compared', 0)} farm-dates; {len(diffs)} differences, {known} known, "
             f"{len(diffs) - known} not explained; {len(unmapped)} farm names not mapped; {len(unused)} known "
             f"differences unused; {len(changed)} farm-dates of NOT_COMPARED changed"]
    for farm, reason in diffs.attrs.get("not_compared", {}).items():
        lines.append(f"  not compared: {farm} -- {reason}")
    for farm, when, holdings, expected in changed:
        lines.append(f"  NOT_COMPARED CHANGED: {farm} {when} {holdings} "
                     f"(expected: {'any one holder' if expected is None else expected})")
    for farm in unmapped:
        lines.append(f"  NOT MAPPED: {farm} (in neither {FARMS_FILE} nor NOT_COMPARED)")
    for when, farm, kind, group in unused:
        what = ", ".join(x for x in (when or "every date", farm, kind, group) if x)
        lines.append(f"  UNUSED: the KNOWN_DIFFERENCES entry ({what}) matches no difference: corrected, or changed?")
    return "\n".join(lines)


def describe(diffs: pd.DataFrame) -> str:
    """The differences, one line each."""
    lines = []
    for r in diffs.itertuples(index=False):
        if r.kind == "no_rows":
            what = (f"no rows in company_owners.csv for {r.entity} on this date; The Crown Estate's table: "
                    f"{r.crown_estate}")
        elif r.kind == "operator":
            what = f"operator: {r.company_owners} in company_owners.csv, {r.crown_estate} in The Crown Estate's table"
        elif r.kind == "share":
            what = (f"{r.group}: {r.company_owners}% in company_owners.csv, {r.crown_estate}% in The Crown Estate's "
                    "table")
        elif r.company_owners == "":
            what = f"{r.group} ({r.crown_estate}%) in The Crown Estate's table, not in company_owners.csv"
        else:
            what = f"{r.group} ({r.company_owners}%) in company_owners.csv, not in The Crown Estate's table"
        tag = f"KNOWN: {r.reason}" if r.known else "NOT EXPLAINED"
        lines.append(f"  {r.as_at} {r.farm} [{r.source}] {what} -- {tag}")
    return "\n".join(lines)


def write(snap: pd.DataFrame | None = None) -> pd.DataFrame:
    """data/processed/crown_estate_ownership.csv from every table; returns it."""
    snap = snapshots() if snap is None else snap
    t = with_groups(snap)
    t["as_at"] = pd.to_datetime(t["as_at"]).dt.strftime("%Y-%m-%d")
    t = t.sort_values(["as_at", "section", "farm"], kind="stable")
    path = cfg.processed_dir() / OUT_FILE
    t.to_csv(path, index=False)
    print(f"  {len(t)} holdings in {t.groupby('as_at')['farm'].nunique().sum()} farm tables -> {path}")
    return t


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 on a difference not in KNOWN_DIFFERENCES, a farm NOT MAPPED (in neither the farm "
                         "map nor NOT_COMPARED), a KNOWN_DIFFERENCES entry that matched nothing, or a farm of "
                         "NOT_COMPARED whose holdings are not those it expects")
    a = ap.parse_args(argv)
    snap = snapshots()
    write(snap)
    diffs = compare(snap)
    print(summary(snap, diffs))
    if len(diffs):
        print(describe(diffs))
    failed = ((not diffs["known"].all()) or bool(diffs.attrs["unmapped"]) or bool(diffs.attrs["unused_known"])
              or bool(diffs.attrs["not_compared_changed"]))
    return 1 if a.strict and failed else 0


if __name__ == "__main__":
    sys.exit(main())
