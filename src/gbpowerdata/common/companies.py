"""Company names to company groups, and the owners and operator of a joint venture on a given date.

Why: every register names companies its own way. DESNZ names a station's company as its survey returner ("RWE
Npower", "Co-owned by SSE Group and Cheung Kong Infrastructure Ltd"), Ofgem and LCCC name the project company
that holds the accreditation or the contract ("Race Bank Wind Farm Ltd", "East Anglia One Limited"), NESO the
applicant and its parent ("Keadby Generation Limited", parent "SSE plc"), Elexon the BSC party that trades the
unit, cut at 30 characters ("Triton Knoll Offshore Wind"). The ownership tables (gbpowerdata.build.
build_ownership) compare these registers, so every name is reduced to a group the same way, here.

A company's group, first match wins (the basis is reported with every group):
  alias      data/reference/company_groups.csv: a name the register uses -> its group, each row with its source.
             A name of 25 characters or more that is the start of exactly one alias takes that alias (Elexon
             cuts lead parties' names at 30 characters).
  name       the company's name names a group (GROUP_RULES, a regex per group).
  address    the company's address names a group ("c/o Orsted Wind A/S"), or is one of a group's own
             single-occupier sites (SITES, by postcode: RWE's Windmill Hill Business Park, SSE's Inveralmond House
             and No. 1 Forbury Place, ScottishPower's 320 St Vincent Street), each checked to be that group's
             address elsewhere in the registers. Multi-tenant buildings are not sites (70 St Mary Axe holds
             Vattenfall and Cubico; law firms and accountants register unrelated companies at one address). Only
             the RO and CfD registers carry addresses.
  ch_psc     on a date (resolve, or group_of given `when`), for a company whose Companies House number is known
             (the register's, as the CfD register gives it, else data/reference/companies_house_numbers.csv's
             for its name): its majority corporate controller on that date in Companies House's register of
             persons with significant control, followed up the chain to the first controller known by alias or
             name (gbpowerdata.common.company_control.group_by_control). Tried before cm_parent, because the PSC
             register is dated while the CM parent is today's. Only the companies pulled by
             gbpowerdata.pull.companies_house_pull have controllers.
  cm_parent  the company's parent in NESO's Capacity Market register, where that parent resolves by alias or
             name. NESO updates the parent after a sale, so it groups names; it does not date owners.
  ch_psc     failing all that, the name of the last controller up the same chain (a holding company no rule
             places), which is better than the company's own but never overrides a CM parent that names a group.
  self       otherwise the company is its own group (its name without the legal form).

Joint ventures and sales (data/reference/company_owners.csv): keyed "company:<name>" or "station:<station>" (a
station of data/reference/dukes_bmu_map.csv). A register that names the same legal entity differently (Elexon's
"Doggerbank OWF Project 1" for the CfD register's "Doggerbank Offshore Wind Farm Project 1 Projco Limited") is
tied to it by the same_as column of company_groups.csv, so the venture's rows hold under either name. Each row is
an owner with its share (blank where no source gives it), whether it operates, and the dates the row holds. A key
that has rows on a date overrides the rules above for that date: its owners are the rows (the share no source
gives stays blank; shares that add up to less than one leave the rest "unresolved") and its operator is the row
marked so, else the first owner. The owners in that table are written as groups already and are not resolved
again ("Energy Capital Partners" the owner, not DESNZ's label for Triton Power's stations).

A JOINT VENTURE COMPANY THAT TRADES (London Array Ltd, Greater Gabbard Offshore Winds Limited as BM lead parties)
trades for the venture, so as a trader it resolves to the venture's operator (basis "jv_operator").

DOCUMENTED LEAD-PARTY CHANGES (data/reference/bmu_lead_parties.csv): a BM unit's lead party over a period where a
source documents it (Elexon publishes only today's register), with sources, evidence, status and the date checked
like company_owners.csv; lead_party_at() reads it.

EVIDENCE. Every row of company_owners.csv cites its sources by id (data/reference/ownership_sources.csv: publisher,
title, publication date, kind, URL, the date it was read), says in `evidence` what they state, and carries a
status: "verified" (the cited sources state the share, the operator and the dates), "partly verified" (the
evidence says which part is not), "to verify", or "judgement" (the author's reading, with the reason). `checked`
is the date of the last check. docs/ownership_references.md lists every share with its evidence and a numbered
reference list, for checking; it is generated from the two tables:

    python -m gbpowerdata.common.companies --references        (tests/test_ownership.py fails if it is stale)

The tables are hand-curated: edit them, never regenerate them.
"""
from __future__ import annotations

import argparse
import re
import sys
from functools import lru_cache

import numpy as np
import pandas as pd

from gbpowerdata import config as cfg

UNRESOLVED = "unresolved"
GROUPS_FILE = "company_groups.csv"
OWNERS_FILE = "company_owners.csv"
SOURCES_FILE = "ownership_sources.csv"
LEADS_FILE = "bmu_lead_parties.csv"
LEADS_COLUMNS = ["unit_id", "lead_party", "valid_from", "valid_to", "sources", "evidence", "status", "checked"]
STATIONS_FILE = "dukes_bmu_map.csv"
OWNERS_COLUMNS = ["entity", "owner", "share_pct", "operator", "valid_from", "valid_to", "sources", "evidence", "status",
                  "checked"]
SOURCES_COLUMNS = ["source_id", "publisher", "title", "published", "kind", "url", "accessed"]
STATUSES = ("verified", "partly verified", "to verify", "judgement")
REFERENCES_DOC = "docs/ownership_references.md"

# group -> regex on a company's name (or address), case-insensitive, first match wins. npower: the renewables
# arm went with RWE, the supply business (npower Business Solutions) to E.ON in 2019.
GROUP_RULES = (
    ("RWE", r"\bRWE\b|\binnogy\b|\bnpower renewables\b"),
    ("E.ON", r"\bE\.?ON\b|\bnpower\b|\bPowergen\b"),
    ("SSE", r"\bSSE\b|Scottish Hydro Electric|Scottish and Southern"),
    ("ScottishPower", r"Scottish ?Power|\bSP Renewables\b|\bSP Generation\b|Iberdrola"),
    ("Orsted", r"Orsted|Ørsted|\bDONG\b|Nesa All|A\.C\. Meyers"),
    ("Uniper", r"\bUniper\b"),
    ("EDF", r"\bEDF\b"),
    ("EPUKi", r"\bEP ?UK\b|\bEPUKI\b|\bEPPDII\b|\bTTEP\b|\bEP (Langage|SHB|Lynemouth)\b"),
    ("VPI", r"\bVPI\b|\bVitol\b"),
    ("InterGen", r"\bInter ?Gen\b"),
    ("Drax", r"\bDrax\b"),
    ("Vattenfall", r"Vattenfall|\bNuon\b"),
    ("Equinor", r"Equinor|Statoil"),
    ("Statkraft", r"Statkraft"),
    ("Centrica", r"Centrica|British Gas"),
    ("ESB", r"\bESB\b|\bESBII\b"),          # not "\bESB" alone: the rules run on addresses too (Esbjerg)
    ("ENGIE", r"\bENGIE\b"),
    ("Calon", r"\bCalon\b"),
    ("Triton Power", r"\bTriton Power\b|\bSCCL\b|Saltend Cogeneration"),
    ("EIG", r"\bUK Transition\b|\bWest Burton B\b"),
    ("First Hydro", r"\bFirst Hydro\b"),
    ("National Grid", r"\bNational Grid\b"),
    ("Zenobe", r"\bZenobe\b"),
    ("Conrad", r"\bConrad\b"),
    ("Statera", r"\bStatera\b"),
    ("Tesla", r"\bTesla\b"),
    ("Gresham House", r"\bGresham House\b"),
    ("Gore Street", r"\bGore Street\b"),
    ("Octopus", r"\bOctopus\b"),
    ("Sembcorp", r"\bSembcorp\b"),
    ("Infinis", r"\bInfinis\b"),
    ("Eneco", r"\bEneco\b"),
    ("Fred Olsen", r"Fred\.? ?Olsen"),
    ("RES", r"\bRES\b|Renewable Energy Systems"),
    ("Renantis", r"Renantis|Falck"),
    ("Ventient", r"Ventient|Venitent"),
    ("Greencoat", r"Greencoat"),
    ("Ocean Winds", r"Ocean ?Winds"),
    ("EDP Renewables", r"\bEDP Renewables\b|\bEDPR\b"),
    ("Field", r"^Field\b"),
    ("Cubico", r"Cubico"),
    ("Lightsource", r"Lightsource"),
    ("Foresight", r"Foresight"),
    ("Bluefield", r"Bluefield"),
    ("NextEnergy", r"Next ?Energy"),
    ("NextPower", r"\bNextPower\b"),
    ("Equitix", r"Equitix"),
    ("Temporis", r"Temporis"),
    ("Energiekontor", r"Energiekontor"),
    ("Ecotricity", r"Ecotricity"),
    ("Banks", r"Banks Renewables|Banks Group"),
    # Brookfield bought Banks Renewables (OnPath Energy since 20 Feb 2024) on 14 Dec 2023 (Companies House); its
    # filings name "Brookfield Corporation", then "Brookfield Asset Management Ltd.". Not "Brookfield" alone: the
    # rules run on addresses too (Brookfield Road, Brookfield Business Park)
    ("Brookfield", r"\bBrookfield (?:Corporation|Asset Management|Renewable|Infrastructure)\b"),
    ("BayWa", r"BayWa"),
    ("Thrive", r"Thrive Renewables|Triodos"),
    ("Low Carbon", r"\bLow Carbon\b"),
    ("Aura Power", r"\bAura Power\b"),
    ("Island Green Power", r"Island Green Power"),
    ("Enso Energy", r"\bEnso\b"),
    ("Elgin Energy", r"\bElgin Energy\b"),
    ("Boom Power", r"\bBoom Power\b"),
    ("Exagen", r"\bExagen\b"),
    # the companies of Harmony Energy Income Trust (HEIT PW Limited, ...); those the CM register lists carry dated
    # rows in company_owners.csv, since Foresight took the trust private on 17 June 2025
    ("HEIT", r"\bHEIT\b"),
    ("TagEnergy", r"\bTAG ?ENERGY"),         # "TAGEnergy UK Limited", "TAGENERGYUK"
    ("Gridserve", r"\bGRIDSERVE\b"),
    ("SUSI Partners", r"\bSUSI\b"),          # SUSI Storage Development UK
    # Alcemi Storage Developments and its numbered project companies: Coalburn's lead party (... 4) and the CM
    # applicant (... 6) that declares Alcemi Storage Developments its parent were two groups before 15 Oct 2026
    ("Alcemi", r"\bAlcemi\b"),
    # parents that the Companies House chains of BM lead parties end at (7 Oct 2026), under one name each: "BP
    # P.L.C." for BP Gas Marketing, "The Shell Petroleum Company" for Limejump Energy, "Exxon Mobil Corporation"
    # for ESSO Petroleum, INEOS's holdings for Grangemouth CHP and INOVYN Energy, "ERG S.p.A." for Creag Riabhach and
    # Sandy Knowe, The Renewables Infrastructure Group (UK) for Freasdail, Bruntwood and Bruntwood Group for Unify
    # Energy, Community Wind Power (Holdings) for Sanquhar beside the aliases' "Community Windpower". Anchored or
    # specific, since the rules run on addresses too (Shell Green, Esso Road)
    ("BP", r"^BP\b"),
    ("Shell", r"^(?:The )?Shell (?:Petroleum|Energy|U\.?K\.?|International|Trading)\b"),
    ("ExxonMobil", r"\bExxon ?Mobil\b|^Esso\b"),
    ("INEOS", r"\bINEOS\b|\bINOVYN\b"),
    ("ERG", r"^ERG\b"),
    ("TRIG", r"\bRenewables Infrastructure Group\b|^TRIG\b"),
    ("Bruntwood", r"\bBruntwood\b"),
    ("Community Windpower", r"\bCommunity Wind ?Power\b"),
)
# a group's own single-occupier site: postcode -> group (checked 6 Oct 2026: each is the group's named address in
# other rows of the RO or CfD register; SN5 6PB also hosts EP UK's Epsilon building, so the name rules run first)
SITES = {"SN5 6PB": "RWE", "PH1 3AQ": "SSE", "RG1 3JH": "SSE", "G2 5AD": "ScottishPower"}
_POSTCODE = re.compile(r"([A-Z]{1,2}[0-9][0-9A-Z]?)\s*([0-9][A-Z]{2})", re.I)
_LEGAL = re.compile(r"\b(limited|ltd|plc|llp|inc|gmbh|se|sa|ag|bv|co|company|holdings?)\b\.?", re.I)
_TRAILING_LEGAL = re.compile(r"[\s,]*\b(limited|ltd\.?|plc|llp|\(uk\))\s*$", re.I)
_COMPILED = tuple((g, re.compile(p, re.I)) for g, p in GROUP_RULES)


# ---------------------------------------------------------------------------- names
def norm(name) -> str:
    """A company name reduced for matching: capitals, no punctuation, no legal form."""
    s = "" if name is None or (isinstance(name, float) and np.isnan(name)) else str(name).strip()
    if s.lower() in ("", "nan", "none"):
        return ""
    s = re.sub(r"[.,'’()\-/]", " ", s.replace("&", " and "))
    return re.sub(r"\s+", " ", _LEGAL.sub(" ", s)).strip().upper()


def clean(name) -> str:
    """A company name for a table: the register's spelling without its trailing legal form."""
    s = str(name).strip()
    for _ in range(3):
        s = _TRAILING_LEGAL.sub("", s).strip()
    return s


def postcode(address) -> str:
    """The last UK postcode in an address, "SN5 6PB" style; "" if none."""
    m = _POSTCODE.findall(str(address or ""))
    return f"{m[-1][0]} {m[-1][1]}".upper() if m else ""


def rule_group(text) -> str:
    """The group GROUP_RULES finds in a text, "" if none."""
    s = "" if text is None or (isinstance(text, float) and np.isnan(text)) else str(text)
    return next((g for g, rx in _COMPILED if rx.search(s)), "")


# ---------------------------------------------------------------------------- curated tables
def _reference(name: str) -> pd.DataFrame:
    return pd.read_csv(cfg.reference_dir() / name, dtype=str, keep_default_na=False)


@lru_cache(maxsize=None)
def company_groups() -> dict[str, str]:
    """data/reference/company_groups.csv: normalised name -> group."""
    table = _reference(GROUPS_FILE)
    return {norm(n): g for n, g in zip(table["name"], table["group"])}


@lru_cache(maxsize=None)
def same_as() -> dict[str, str]:
    """data/reference/company_groups.csv: normalised name -> the normalised name of the same legal entity in the
    register company_owners.csv keys it by (the same_as column), where one is given."""
    table = _reference(GROUPS_FILE)
    return {norm(n): norm(c) for n, c in zip(table["name"], table["same_as"]) if str(c).strip()}


def company_keys(name) -> list[str]:
    """The company_owners.csv keys a company name is looked up under: its own and its same_as entity's."""
    key = norm(name)
    keys = [f"company:{key}"]
    if (other := same_as().get(key)) and other != key:
        keys.append(f"company:{other}")
    return keys


@lru_cache(maxsize=None)
def company_owners() -> pd.DataFrame:
    """data/reference/company_owners.csv with normalised keys, shares as fractions and parsed dates."""
    table = _reference(OWNERS_FILE)
    parts = table["entity"].str.partition(":").reindex(columns=[0, 1, 2], fill_value="")   # an empty table has none
    kind, name = parts[0], parts[2]
    table["key"] = np.where(kind == "company", "company:" + name.map(norm), table["entity"])
    table["share"] = pd.to_numeric(table["share_pct"], errors="coerce") / 100.0
    table["is_operator"] = table["operator"].str.lower().eq("yes")
    for c in ("valid_from", "valid_to"):
        table[c] = pd.to_datetime(table[c].replace("", None), errors="coerce")
    return table


@lru_cache(maxsize=None)
def dukes_bmu_map() -> pd.DataFrame:
    """data/reference/dukes_bmu_map.csv by station: the DUKES site pattern and the station's BM units (list)."""
    table = _reference(STATIONS_FILE).set_index("station")
    table["bmus"] = table["bmu_ids"].map(lambda s: [b for b in s.split(";") if b])
    return table


@lru_cache(maxsize=None)
def ownership_sources() -> pd.DataFrame:
    """data/reference/ownership_sources.csv by source_id."""
    return _reference(SOURCES_FILE).set_index("source_id")


@lru_cache(maxsize=None)
def bmu_lead_parties() -> pd.DataFrame:
    """data/reference/bmu_lead_parties.csv with parsed dates (empty where the file is not there)."""
    path = cfg.reference_dir() / LEADS_FILE
    if not path.exists():
        return pd.DataFrame(columns=LEADS_COLUMNS)
    table = _reference(LEADS_FILE)
    for c in ("valid_from", "valid_to"):
        table[c] = pd.to_datetime(table[c].replace("", None), errors="coerce")
    return table


def lead_party_at(unit: str, when: pd.Timestamp) -> str:
    """A BM unit's documented lead party on a date ("" if none is documented)."""
    t = bmu_lead_parties()
    rows = t[(t["unit_id"] == unit) & (t["valid_from"].isna() | (t["valid_from"] <= when))
             & (t["valid_to"].isna() | (t["valid_to"] >= when))]
    return str(rows["lead_party"].iloc[0]) if len(rows) else ""


def clear_caches() -> None:
    """Forget the curated tables read so far, and Companies House's control table, the answers read from it and
    the list of numbers (after editing them, after a pull or build, or in tests)."""
    for f in (company_groups, same_as, company_owners, ownership_sources, bmu_lead_parties, dukes_bmu_map):
        f.cache_clear()
    from gbpowerdata.common import company_control      # lazily: company_control imports this module the same way
    company_control.clear_cache()


# ---------------------------------------------------------------------------- resolution
def group_of(name, cm_parents: dict | None = None, address=None, company_number="",
             when=None) -> tuple[str, str]:
    """(group, basis) of a company: basis alias, name, address, site, ch_psc, cm_parent or self (see the module
    docstring); ("", "") for a blank name. ch_psc needs `when` (the date asked about) and a Companies House number:
    `company_number`, else the one data/reference/companies_house_numbers.csv lists for the name. Without `when`
    there is no Companies House lookup (company_control resolves controllers' names that way)."""
    key = norm(name)
    if not key:
        return "", ""
    known = company_groups()
    if key in known:
        return known[key], "alias"
    if len(str(name).strip()) >= 25:
        starts = {g for k, g in known.items() if k.startswith(key)}
        if len(starts) == 1:
            return starts.pop(), "alias"
    if group := rule_group(name):
        return group, "name"
    if address is not None and not (isinstance(address, float) and np.isnan(address)):
        if group := rule_group(address):
            return group, "address"
        if group := SITES.get(postcode(address), ""):
            return group, "site"
    number, cc = "", None
    if when is not None:
        from gbpowerdata.common import company_control as cc    # lazily: company_control imports this module too
        number = cc.company_number(company_number) or cc.number_of(name)
        if number:                                  # a controller on the date known by alias or name
            group, basis = cc.group_by_control(number, when, known_only=True)
            if group:
                return group, basis
    parent = (cm_parents or {}).get(key)
    if parent and norm(parent) != key:
        group, basis = group_of(parent)
        if basis in ("alias", "name"):
            return group, "cm_parent"
    if number:                                      # a holding company no rule places: its name
        group, basis = cc.group_by_control(number, when)
        if group:
            return group, basis
    return clean(name), "self"


def dated(key: str, when: pd.Timestamp) -> pd.DataFrame:
    """The rows of company_owners.csv for `key` ("company:<normalised name>" or "station:<station>") that hold
    at `when`."""
    table = company_owners()
    rows = table[table["key"] == key]
    valid = ((rows["valid_from"].isna() | (rows["valid_from"] <= when))
             & (rows["valid_to"].isna() | (rows["valid_to"] >= when)))
    return rows[valid]


def resolve(company, when: pd.Timestamp, station: str = "", cm_parents: dict | None = None,
            address=None, company_number="") -> tuple[list[dict], str, str]:
    """The owners [{"group", "share"}], the operator and the basis of a unit held by `company` at `when`.

    company_owners.csv rows for the station come first, then those for the company; otherwise the company's
    group owns all of it and runs it. Where some rows give shares, an operator row without one is the operating
    company, not an owner (Triton Power for Saltend); where no row gives a share, every row is an owner whose
    share no source gives (share NaN). Shares that add up to less than one leave the rest UNRESOLVED.
    `company_number` is the company's Companies House number where its register gives one (basis ch_psc)."""
    for key in ([f"station:{station}"] if station else []) + company_keys(company):
        rows = dated(key, when)
        if len(rows):
            has_shares = rows["share"].notna().any()
            owners = [{"group": r.owner, "share": r.share} for r in rows.itertuples()
                      if not has_shares or pd.notna(r.share) or not r.is_operator]
            operator = next((r.owner for r in rows.itertuples() if r.is_operator), "")
            known = sum(o["share"] for o in owners if pd.notna(o["share"]))
            if owners and has_shares and all(pd.notna(o["share"]) for o in owners) and known < 1.0 - 1e-9:
                owners.append({"group": UNRESOLVED, "share": 1.0 - known})
            return owners, operator or (owners[0]["group"] if owners else ""), "curated"
    group, basis = group_of(company, cm_parents, address, company_number=company_number, when=when)
    if not group:
        return [], "", ""
    return [{"group": group, "share": 1.0}], group, basis


def trader_group(party, when: pd.Timestamp, cm_parents: dict | None = None) -> tuple[str, str]:
    """(group, basis) of a BM lead party: a joint venture's own company trades for the venture, so it resolves to
    the venture's operator where company_owners.csv names one ("jv_operator"); otherwise group_of on the date, so
    a company trading its own units is placed as it is as an owner (Companies House control included)."""
    for key in company_keys(party):
        rows = dated(key, when)
        operator = rows[rows["is_operator"]]
        if len(operator):
            return str(operator["owner"].iloc[0]), "jv_operator"
    return group_of(party, cm_parents, when=when)


# ---------------------------------------------------------------------------- the reference document
def _label(entity: str) -> str:
    kind, _, name = entity.partition(":")
    return f"{name} (station)" if kind == "station" else name


def references_markdown() -> str:
    """docs/ownership_references.md: every row of company_owners.csv with its evidence, grouped by venture, and
    the numbered list of the sources it cites (numbered in order of first citation)."""
    owners = _reference(OWNERS_FILE)
    sources = ownership_sources()
    owners = owners.assign(_label=owners["entity"].map(_label)).sort_values(["_label", "valid_from", "owner"], kind="stable")
    number: dict[str, int] = {}
    for ids in owners["sources"]:
        for i in (x.strip() for x in ids.split(";") if x.strip()):
            number.setdefault(i, len(number) + 1)
    counts = owners["status"].value_counts()
    lines = [
        "# Ownership references",
        "",
        "Every joint-venture share, sale and operator in `data/reference/company_owners.csv`, with what its sources",
        "state, for checking. Generated by `python -m gbpowerdata.common.companies --references` from that table and",
        "`data/reference/ownership_sources.csv`; edit those, not this file.",
        "",
        "Status: **verified**, the cited sources state the share, the operator and the dates; **partly verified**, the",
        "evidence says which part is not; **to verify**, not yet confirmed; **judgement**, the author's reading, with",
        "the reason. Dates are completion dates unless the evidence says otherwise; a blank From holds from before",
        "2018, a blank To until today.",
        "",
        "| Status | Rows |",
        "| --- | --- |",
        *[f"| {st} | {int(counts.get(st, 0))} |" for st in STATUSES],
        "",
    ]
    for label, rows in owners.groupby("_label", sort=False):
        lines += [f"## {label}", "", "| Owner | Share % | Operator | From | To | Status | Checked | Sources | Evidence |",
                  "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
        for r in rows.itertuples():
            refs = " ".join(f"[{number[i.strip()]}]" for i in r.sources.split(";") if i.strip())
            evidence = r.evidence.replace("|", "/")
            lines.append(f"| {r.owner} | {r.share_pct} | {'yes' if r.operator == 'yes' else ''} | {r.valid_from} | "
                         f"{r.valid_to} | {r.status} | {r.checked} | {refs} | {evidence} |")
        lines.append("")
    lines += ["## References", ""]
    for i, n in sorted(number.items(), key=lambda kv: kv[1]):
        s = sources.loc[i]
        when = f" ({s['published']})" if s["published"] else ""
        lines.append(f"{n}. {s['publisher']}{when}. {s['title']}. {s['kind'].capitalize()}. <{s['url']}> "
                     f"(accessed {s['accessed']}). `{i}`")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Company groups and joint ventures: write the reference document.")
    ap.add_argument("--references", action="store_true", help=f"write {REFERENCES_DOC} from the curated tables")
    a = ap.parse_args(argv)
    if a.references:
        path = cfg.REPO_ROOT / REFERENCES_DOC
        path.write_text(references_markdown(), encoding="utf-8", newline="\n")
        print(f"  -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
