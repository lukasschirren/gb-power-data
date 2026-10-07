"""The register of Balancing Mechanism (BM) units by year: every generating BM unit with its lead party,
technology, capacity and whether it produced in the year. Nothing here is estimated: every column is a register
value, an observed date or a documented rule on them.

Why: Elexon's register is the one list that names, for every unit that trades in the Balancing Mechanism, the BSC
party that trades it (the lead party), so it is the trader side of the ownership tables
(gbpowerdata.build.build_ownership) and the population of any model of firms that bid. The rules were first
written for the agent population of a day-ahead curve model (research code, not part of this repository); the
activity rule here is stricter (see "Differences" below).

Sources:
  data/raw/bm_units_*.csv                Elexon register, the latest snapshot (gbpowerdata.pull.elexon_pull
                                         bmunits): unit, lead party, fuel type, capacities, GSP group, EIC
  data/raw/fpn/{unit}.csv                physical notifications (gbpowerdata.pull.fpn_pull; from March 2016)
  data/raw/b1610/{unit}.csv              metered output (gbpowerdata.pull.b1610_pull; thermal units, from Feb 2019)
  data/raw/bod/{unit}.csv                bid-offer data (gbpowerdata.pull.elexon_bod_pull; from January 2022)
  gbpowerdata.pull.elexon_bod_pull.battery_units   the OTHER-fuel batteries (extended here to blank fuel)

Rules:
  technology  fuelType -> ccgt | ocgt | coal | nuclear | biomass | hydro | pumped_storage | wind. A blank fuelType
              (237 units, 7.9 GW in the register of 5 Jun 2026: the newer wind farms and batteries are registered
              without one) or OTHER (52 units, 2.9 GW) -> the documented technology of a closed unit
              (TECH_WHILE_ACTIVE: Fiddler's Ferry's coal units and gas turbines), else the names first and the
              unit code's type letter where the names say nothing: PUMPED STORAGE -> pumped_storage (Cruachan's
              unit of Drax Pumped Storage Limited); B / BATT / BESS / STORAGE -> battery; WIND / OFFSHORE -> wind;
              SOLAR / PV -> solar; one of the whole words of OTHER_WORDS (CHP, COGEN..., POWER, ENERGY, GAS,
              PEAK..., GENERAT..., RESERVE) -> other; else the type letter W -> wind, S -> solar; otherwise other
              (CHP, gas engines, waste).
  activity    a unit is active in a year if it produced in it: the first and last date with a notified level of
              at least MIN_LEVEL_MW (FPN) or metered output of at least MIN_METERED_MWH a half-hour (B1610),
              whichever comes first and last; for storage (battery, pumped storage) charging counts as well. The
              files cannot be read by their first and last line: a retired unit keeps sending zero notifications
              (Hinkley Point B's stop on 1 Aug 2022, its file runs to 2026), and a new one sends zeros before it
              first generates (Keadby 2: file from Oct 2020, first level Oct 2021). A day counts only with output
              in at least MIN_DAY_PERIODS distinct half-hours (an FPN half-hour often holds several segments),
              which with the thresholds keeps metering noise out (one 0.001 MWh reading of Drax unit 6 in 2024,
              one 25 MWh reading of Dungeness B in July 2025). A battery mostly notifies zero while it operates (it
              works through bids, offers and response services), so for a battery a file of notifications or bids
              is evidence too: its first date is its first output, else its first bid, else its first
              notification, and it runs while its files do. Each kind of file has its pull window, read from the
              files (the earliest and latest date of that kind); a first date within START_SLACK of its kind's
              window start is a lower bound (active_from blank, there before the pull), and so is any first date
              of a unit whose file of that kind starts there when the window opens after the panel's start
              (PANEL_START), since such a window says nothing about the time before it (Lynemouth unit 1, metered
              from the B1610 window's start on 1 Feb 2019 but in an outage until 4 Mar 2019, ran in 2018: LCCC's
              daily generation for the station's CfD then exceeds what two units can make). A last date within
              END_SLACK of the window's end means still running. A unit with bid-offer data only is dated by its
              first and last submission. A unit whose FPN and B1610 files never show output is inactive in every
              year ("no_output"), and so is a unit whose notifications --pull-missing found empty over the whole
              window ("no_notifications", recorded in data/raw/fpn_without_notifications.csv: Dogger Bank B's five
              units, 1.2 GW, notified nothing before 2026). A documented commercial closure (RETIREMENTS) ends a
              unit's activity also where its files show output later, outside the market: the winter 2022/23 coal
              contingency kept Drax units 5 and 6 and West Burton A units 1 and 2 available after their Capacity
              Market obligations ended in September 2022, and their metered output (B1610) shows them running
              until March 2023 on the system operator's instruction (activity_source "...+retirement_table"). Units
              without any file: the documented closures (RETIREMENTS), units the register carries at zero capacity
              (inactive), units with neither a file nor a fuel type and batteries (dated by their files) without
              one ("no_evidence": inactive), and otherwise active throughout ("assumed"). --pull-missing pulls the
              notifications of every unit without a file that submits them (fpn_flag), so these last rules are
              left with the units that submit none. A year the files do not reach (every kind's latest date more
              than END_SLACK before the year's end, or before the build date for the current year) takes the
              activity of the last year they reach (activity_year): a unit in an outage at the end of the pull
              still counts, one first producing after it does not.
  capacity    the register's generation capacity; for a closed unit the register lists at zero or at a remnant,
              the documented value (CAPACITY_WHILE_ACTIVE), and for another unit listed at zero that ran, the
              highest level of its physical notifications (capacity_source "register", "table" or "fpn_max").
  connection  T_ = transmission-connected, E_ = embedded but BM-registered. Supplier (2__), virtual lead party
              (V__), interconnector (I_) and other units are not in the table.

Differences from the rules this was first written with (checked 7 Oct 2026 on the 2018-2025 files, after the
notifications of the units without an activity file were pulled): those read each file's first and last line with
fixed pull starts (FPN from 2022), so a unit first producing in 2019-2021 counted as there since before 2018, a
retired unit still notifying zeros stayed active, and a unit listed at zero capacity today was inactive in every
year even where it ran. In 2018 this drops 92 units (10.6 GW: East Anglia One, Triton Knoll, Moray East, Hornsea
One and Two, Keadby 2, Dogger Bank B, King's Lynn A, batteries not yet built or notifying only zero) and adds 13
(4.3 GW: Hinkley Point B, Dungeness B, Fiddler's Ferry, Grangemouth, Ratcliffe's gas turbines); in 2025 it drops 48
(4.6 GW: Sofia's 1.8 GW and Dogger Bank B's 1.2 GW, which notified only zeros or nothing in 2025, and smaller units
without a day of output in the year) and adds 5.

Years and snapshots: 2018 to the current year, the current year as of the build date (as_of; earlier years as of
31 December; a year the activity files do not reach takes the activity of the last one they do, activity_year).
Elexon publishes only the register of the day, so each pulled snapshot (bm_units_YYYYMMDD.csv) is kept: a year
takes the latest snapshot on or before its as-of date (party_basis "register"), and where none is that old, the
earliest snapshot after it (party_basis "proxy": today's lead party standing in for the past;
gbpowerdata.build.build_ownership checks the proxy against the unit's ownership at the date). Pulling the register
every month (scripts/snapshot_registers.py) builds the history from now on.

Known limits: capacities are the register's, not by year (restored for units listed at zero); a unit available
all year but never run (a peaker held in reserve) counts as inactive in that year; a unit without any activity
file that submits no physical notifications but has a fuel type counts as active in every year ("assumed": 3
units, 55 MW in the register of 5 Jun 2026, once the notifications of the others were pulled on 7 Oct 2026). Units
that left Elexon's register before its first kept snapshot (5 Jun 2026) are in no year: Eggborough (1,960 MW coal,
closed September 2018), Cottam (2,000 MW coal, September 2019) and Aberthaw B (1,559 MW coal, March 2020) among
them (DUKES 5.11), so the early years' coal is short by their capacity.

Output: data/processed/bm_unit_register_{year}.csv, one row per T_/E_ unit of the register: year, unit_id,
ngc_id, unit_name, party_id, party_name, tech, connection, capacity_mw, demand_capacity_mw, gsp_group, fpn_flag,
is_battery, active, active_from, active_to, activity_source, activity_year, fuel_type, eic, capacity_source, as_of,
register_date, party_basis.
Read it with gbpowerdata.processed.read_bm_unit_register(year).

Usage: python -m gbpowerdata.build.bm_units [--years 2018 2025] [--pull-missing]     (~1-2 min: reads every
       FPN and B1610 file)
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from gbpowerdata import config as cfg

YEARS = tuple(range(2018, pd.Timestamp.today().year + 1))   # to the current year
FUEL_TO_TECH = {"CCGT": "ccgt", "OCGT": "ocgt", "COAL": "coal", "NUCLEAR": "nuclear", "BIOMASS": "biomass",
                "NPSHYD": "hydro", "PS": "pumped_storage", "WIND": "wind"}
OUTPUT_KINDS = ("fpn", "b1610")        # files that show output
MIN_LEVEL_MW = 1.0                     # a notified level at least this large is output
MIN_METERED_MWH = 0.5                  # metered output at least this large in a half-hour is output
MIN_DAY_PERIODS = 4                    # a day with output in fewer distinct half-hours does not count
STORAGE = ("battery", "pumped_storage")
START_SLACK = pd.Timedelta(days=7)     # a first output date this close to its window's start: there before it
PANEL_START = pd.Timestamp(f"{YEARS[0]}-01-01")   # a pull window opening later says nothing about the time before
END_SLACK = pd.Timedelta(days=45)      # a last output date this close to its window's end: still running
# Commercial closures of units the register still lists (public dates): a unit no activity file covers is
# active until then, and one whose files show output later is active only until then: the winter 2022/23 coal
# contingency kept Drax units 5 and 6 and West Burton A units 1 and 2 available outside the market, and their
# metered output (B1610) shows them running until March 2023 on the system operator's instruction.
RETIREMENTS = {
    # Drax's coal units: commercial running ended in March 2021, but they held Capacity Market agreements, and
    # notified output, to the end of the 2021/22 delivery year
    "T_DRAXX-5": "2022-09-30", "T_DRAXX-6": "2022-09-30",
    "T_WBUPS-1": "2022-09-30", "T_WBUPS-2": "2022-09-30",          # West Burton A, September 2022
    "T_WBUPS-3": "2022-09-30", "T_WBUPS-4": "2022-09-30",
    "T_RATS-1": "2024-09-30", "T_RATS-2": "2024-09-30",            # Ratcliffe-on-Soar, 30 Sep 2024
    "T_RATS-3": "2024-09-30", "T_RATS-4": "2024-09-30",
    "T_FIDL-1": "2020-03-31", "T_FIDL-2": "2020-03-31",            # Fiddler's Ferry, 31 Mar 2020
    "T_FIDL-3": "2020-03-31", "T_FIDL-4": "2020-03-31",
    "T_FIDL-2G": "2020-03-31", "T_FIDL-3G": "2020-03-31",          # its gas turbines
}
# Capacities the register has zeroed or cut to a remnant after closure, restored for the years the unit ran.
CAPACITY_WHILE_ACTIVE = {"T_RATS-1": 500.0, "T_RATS-2": 500.0, "T_RATS-3": 500.0, "T_RATS-4": 500.0,
                         # DUKES 5.11 (2018 and 2019 editions): Fiddler's Ferry 1,961 MW in four units
                         "T_FIDL-1": 490.25, "T_FIDL-2": 490.25, "T_FIDL-3": 490.25, "T_FIDL-4": 490.25}
# The technology of closed units the register lists with a blank fuel type (DUKES 5.11, 2018 and 2019 editions:
# Fiddler's Ferry coal; its gas turbines diesel/gas oil OCGT, 35 MW together, left at the register's 1 MW each).
TECH_WHILE_ACTIVE = {"T_FIDL-1": "coal", "T_FIDL-2": "coal", "T_FIDL-3": "coal", "T_FIDL-4": "coal",
                     "T_FIDL-2G": "ocgt", "T_FIDL-3G": "ocgt"}
# Names of plant classed "other" when the register gives no fuel type, matched as whole words ("Hagshaw Hill
# Repowering" is a wind farm); SOLAR or PV is read before them ("Tebworth PV Power Park").
OTHER_WORDS = re.compile(r"\b(?:CHP|COGEN\w*|POWER|ENERGY|GAS|PEAK\w*|GENERAT\w*|RESERVE)\b")
NEVER = pd.Timestamp("1900-01-01")
EMPTY_PULLS = "fpn_without_notifications.csv"   # raw folder: units whose pulled notifications came back empty
COLUMNS = ["year", "unit_id", "ngc_id", "unit_name", "party_id", "party_name", "tech", "connection",
           "capacity_mw", "demand_capacity_mw", "gsp_group", "fpn_flag", "is_battery", "active", "active_from",
           "active_to", "activity_source", "activity_year", "fuel_type", "eic", "capacity_source", "as_of",
           "register_date", "party_basis"]

Span = tuple[pd.Timestamp, pd.Timestamp]


# ---------------------------------------------------------------------------- pure rules
def _type_letter(unit: str) -> str:
    code = re.sub(r"^[A-Z0-9]+_+", "", str(unit))
    m = re.search(r"([A-Za-z])-?\d+$", code)
    return m.group(1).upper() if m else ""


def is_battery_unit(unit: str, name: str, party: str, in_battery_list: bool = False) -> bool:
    if in_battery_list:
        return True
    text = f"{name} {party}".upper().replace("PUMPED STORAGE", "")   # Drax Pumped Storage Limited runs Cruachan
    return _type_letter(unit) == "B" or any(k in text for k in ("BATT", "BESS", "STORAGE"))


def classify_tech(fuel, unit: str, name: str, party: str = "", in_battery_list: bool = False) -> str:
    fuel = None if pd.isna(fuel) else str(fuel)
    if fuel in FUEL_TO_TECH:
        return FUEL_TO_TECH[fuel]
    if unit in TECH_WHILE_ACTIVE:           # a closed unit the register lists without its fuel
        return TECH_WHILE_ACTIVE[unit]
    # OTHER or blank: the names decide first, the unit code's type letter only where the names carry no
    # information (e.g. bmUnitName == unit code)
    text = f"{name} {party}".upper()
    if "PUMPED STORAGE" in text:
        return "pumped_storage"
    if is_battery_unit(unit, name, party, in_battery_list):
        return "battery"
    if "WIND" in text or "OFFSHORE" in text:
        return "wind"
    if "SOLAR" in text or re.search(r"\bPV\b", text):
        return "solar"
    if OTHER_WORDS.search(text):
        return "other"
    letter = _type_letter(unit)
    if letter == "W":
        return "wind"
    if letter == "S":
        return "solar"
    return "other"


def pull_windows(activity: dict[str, dict[str, dict]]) -> dict[str, Span]:
    """Each kind's pull window: the earliest and latest date over all its files."""
    out: dict[str, Span] = {}
    for kinds in activity.values():
        for kind, a in kinds.items():
            if a.get("empty"):                      # a pull that found nothing does not set the window
                continue
            first, last = a["file"]
            lo, hi = out.get(kind, (first, last))
            out[kind] = (min(lo, first), max(hi, last))
    return out


def activity_window(activity: dict[str, dict], windows: dict[str, Span], unit: str = "",
                    capacity_mw: float = np.nan, fuel_known: bool = True, tech: str = "") -> dict:
    """From a unit's files ({kind: {"file": (first, last), "output": (first, last) or None, "output_any": the same
    counting charging}}) and each kind's pull window: the first active date (None if the unit produced from the
    start of the window of the kind that saw it first), the last (None if still producing at the end of a
    window) and the source (see the module docstring, also for the rules without output files)."""
    key = "output_any" if tech in STORAGE else "output"
    output = {k: a[key] for k, a in activity.items() if k in OUTPUT_KINDS and a.get(key)}
    files = {k: a["file"] for k, a in activity.items() if not a.get("empty")}
    if tech == "battery":
        fallback = next(({k: files[k]} for k in ("bod", "fpn") if k in files), {})
        starts = output or fallback
        ends = dict(files) if starts else {}            # a file spans its output, so it runs at least as long
    else:
        only_bids = "bod" in files and not any(k in files for k in OUTPUT_KINDS)
        starts = ends = output or ({"bod": files["bod"]} if only_bids else {})
    if not starts:
        kinds = [a for k, a in activity.items() if k in OUTPUT_KINDS]
        if kinds:                               # files without output, or a pull that found no notifications
            source = "no_notifications" if all(a.get("empty") for a in kinds) else "no_output"
            return {"active_from": None, "active_to": NEVER, "activity_source": source}
        if unit in RETIREMENTS:
            return {"active_from": None, "active_to": pd.Timestamp(RETIREMENTS[unit]),
                    "activity_source": "retirement_table"}
        if pd.notna(capacity_mw) and capacity_mw <= 0:
            return {"active_from": None, "active_to": NEVER, "activity_source": "zero_capacity"}
        if not fuel_known or tech == "battery":     # a battery is dated by its files: without one, no evidence
            return {"active_from": None, "active_to": NEVER, "activity_source": "no_evidence"}
        return {"active_from": None, "active_to": None, "activity_source": "assumed"}
    kind, (first, _) = min(starts.items(), key=lambda kv: kv[1][0])
    last = max(v[1] for v in ends.values())
    opens = windows[kind][0]
    # a window opening after the panel's start says nothing about the time before it: a unit whose file of that
    # kind starts with the window was there already, whatever its first output (Lynemouth unit 1, in an outage)
    registered = opens > PANEL_START and kind in files and files[kind][0] <= opens + START_SLACK
    at_start = first <= opens + START_SLACK or registered
    at_end = any(v[1] >= windows[k][1] - END_SLACK for k, v in ends.items())
    source = "+".join(sorted(starts)) + ("" if starts is output else "_file")
    to = None if at_end else last
    if unit in RETIREMENTS and (to is None or to > pd.Timestamp(RETIREMENTS[unit])):
        # a documented commercial closure ends market activity; output after it was outside the market
        to, source = pd.Timestamp(RETIREMENTS[unit]), source + "+retirement_table"
    return {"active_from": None if at_start else first, "active_to": to, "activity_source": source}


def active_in(year: int, active_from, active_to) -> bool:
    if active_from is not None and pd.notna(active_from) and pd.Timestamp(active_from).year > year:
        return False
    if active_to is not None and pd.notna(active_to) and pd.Timestamp(active_to).year < year:
        return False
    return True


def observed_year(year: int, windows: dict[str, Span]) -> int:
    """The year whose activity stands for `year`: the year itself where every kind of file reaches its end (within
    END_SLACK; for the current year, the build date), else the last year they all reach. A year after the pull (the
    current year before its files are pulled) carries that year's activity forward."""
    if not windows:
        return year
    end = min(hi for _, hi in windows.values())
    while year > YEARS[0] and end < as_of(year) - END_SLACK:
        year -= 1
    return year


# ---------------------------------------------------------------------------- readers
def _file_span(path: str) -> Span | None:
    """First and last date in a per-unit CSV without reading it all (the first date-like column)."""
    with open(path, "rb") as f:
        header = f.readline().decode(errors="ignore").strip().split(",")
        first = f.readline().decode(errors="ignore").strip()
        if not first:
            return None
        try:
            f.seek(-600, os.SEEK_END)
        except OSError:
            f.seek(0)
        last = f.read().decode(errors="ignore").strip().splitlines()[-1]
    cands = [i for i, c in enumerate(header) if re.search(r"date|time", c, re.I)]
    if not cands:
        return None
    i = cands[0]
    a = pd.to_datetime(first.split(",")[i][:10], errors="coerce")
    b = pd.to_datetime(last.split(",")[i][:10], errors="coerce")
    if pd.isna(a) or pd.isna(b):
        return None
    return (min(a, b), max(a, b))


def _span(dates: pd.Series, min_count: int = 1) -> Span | None:
    """First and last of the dates that occur at least `min_count` times."""
    counts = dates.dropna().value_counts()
    days = counts.index[counts >= min_count]
    return (days.min(), days.max()) if len(days) else None


def _output_span(path: str, kind: str) -> dict | None:
    """{"file": (first, last) date of the file, "output": (first, last) day with output (a notified level of at
    least MIN_LEVEL_MW or metered output of at least MIN_METERED_MWH in at least MIN_DAY_PERIODS distinct
    half-hours), "output_any": the same counting charging}."""
    values = ["levelFrom", "levelTo"] if kind == "fpn" else ["quantity"]
    try:
        d = pd.read_csv(path, usecols=["settlementDate", "settlementPeriod", *values])
    except (ValueError, pd.errors.EmptyDataError):
        return None
    if d.empty:
        return None
    d["day"] = pd.to_datetime(d["settlementDate"].astype(str).str[:10], errors="coerce")
    if kind == "fpn":
        level = d[values]
        gen, any_ = level.max(axis=1) >= MIN_LEVEL_MW, level.abs().max(axis=1) >= MIN_LEVEL_MW
    else:
        gen, any_ = d["quantity"] >= MIN_METERED_MWH, d["quantity"].abs() >= MIN_METERED_MWH

    def days(mask: pd.Series) -> pd.Series:       # one date per half-hour: an FPN half-hour holds several segments
        return d.loc[mask.fillna(False), ["day", "settlementPeriod"]].drop_duplicates()["day"]

    return {"file": _span(d["day"]), "output": _span(days(gen), MIN_DAY_PERIODS),
            "output_any": _span(days(any_), MIN_DAY_PERIODS)}


def activity_files() -> dict[str, dict[str, dict]]:
    """unit -> kind -> {"file", "output", "output_any"} spans (see _output_span) over data/raw/{fpn,b1610,bod}."""
    out: dict[str, dict[str, dict]] = {}
    raw = cfg.raw_dir()
    for kind in OUTPUT_KINDS:
        for p in glob.glob(str(raw / kind / "*.csv")):
            s = _output_span(p, kind)
            if s is not None and s["file"] is not None:
                out.setdefault(Path(p).stem, {})[kind] = s
    for p in glob.glob(str(raw / "bod" / "*.csv")):
        s = _file_span(p)
        if s is not None:
            out.setdefault(Path(p).stem, {})["bod"] = {"file": s, "output": None, "output_any": None}
    for unit, start, end in empty_pulls():      # pulled over the window, nothing came back: unless a file says more
        out.setdefault(unit, {}).setdefault("fpn", {"file": (start, end), "output": None, "output_any": None,
                                                     "empty": True})
    return out


def empty_pulls() -> list[tuple[str, pd.Timestamp, pd.Timestamp]]:
    """(unit, window start, window end) of every unit whose notifications --pull-missing found empty over the whole
    window (data/raw/fpn_without_notifications.csv; none without the file)."""
    path = cfg.raw_dir() / EMPTY_PULLS
    if not path.exists():
        return []
    t = pd.read_csv(path, dtype=str)
    return [(u, pd.Timestamp(a), pd.Timestamp(b)) for u, a, b in zip(t["unit_id"], t["window_from"], t["window_to"])]


def record_empty_pulls(units: list[str], window: Span) -> None:
    """Add `units` to data/raw/fpn_without_notifications.csv: their notifications were pulled over `window` and
    nothing came back (the latest record of a unit wins)."""
    path = cfg.raw_dir() / EMPTY_PULLS
    new = pd.DataFrame({"unit_id": list(units), "window_from": str(window[0].date()), "window_to": str(window[1].date()),
                        "pulled": str(pd.Timestamp.today().date())})
    old = pd.read_csv(path, dtype=str) if path.exists() else new.iloc[:0]
    t = pd.concat([old, new], ignore_index=True).drop_duplicates("unit_id", keep="last")
    t.sort_values("unit_id").to_csv(path, index=False)


def fpn_max_level(unit: str) -> float:
    """The highest level (MW) of a unit's physical notifications (data/raw/fpn/{unit}.csv); NaN without a file."""
    path = cfg.raw_dir() / "fpn" / f"{unit}.csv"
    if not path.exists():
        return np.nan
    levels = pd.read_csv(path, usecols=lambda c: c in ("levelFrom", "levelTo"))
    return float(levels.max().max()) if len(levels) else np.nan


def as_of(year: int) -> pd.Timestamp:
    """The date a year's tables describe: 31 December, or today for the current year."""
    return min(pd.Timestamp(f"{year}-12-31"), pd.Timestamp.today().normalize())


def register_files() -> dict[pd.Timestamp, Path]:
    """Every pulled snapshot of Elexon's register (data/raw/bm_units_YYYYMMDD.csv), by date."""
    out = {}
    for f in cfg.raw_dir().glob("bm_units_*.csv"):
        stamp = pd.to_datetime(f.stem.split("_")[-1], format="%Y%m%d", errors="coerce")
        if pd.notna(stamp):
            out[stamp] = f
    if not out:
        raise FileNotFoundError("no data/raw/bm_units_*.csv: run `python -m gbpowerdata.pull.elexon_pull bmunits`")
    return dict(sorted(out.items()))


def snapshot_for(when: pd.Timestamp) -> tuple[pd.Timestamp, str]:
    """(snapshot date, basis) for a date: the latest snapshot on or before it ("register"), else the earliest after
    it ("proxy")."""
    dates = list(register_files())
    before = [d for d in dates if d <= when]
    return (before[-1], "register") if before else (dates[0], "proxy")


def register_file() -> Path:
    """The latest snapshot of Elexon's register."""
    return list(register_files().values())[-1]


def register(path: Path | None = None) -> pd.DataFrame:
    """A snapshot of the register (the latest by default): its T_ and E_ units with technology, connection and
    battery flag."""
    from gbpowerdata.pull.elexon_bod_pull import battery_units

    bm = pd.read_csv(path or register_file()).drop_duplicates("elexonBmUnit")
    bm = bm.dropna(subset=["elexonBmUnit"])
    bm = bm[bm["elexonBmUnit"].astype(str).str.match(r"^(T_|E_)")].copy()
    batt = set(battery_units())
    bm["in_battery_list"] = bm["elexonBmUnit"].isin(batt)
    bm["tech"] = [classify_tech(f, u, n, p, b) for f, u, n, p, b in
                  zip(bm["fuelType"], bm["elexonBmUnit"], bm["bmUnitName"].fillna(""),
                      bm["leadPartyName"].fillna(""), bm["in_battery_list"])]
    bm["is_battery"] = bm["tech"] == "battery"
    bm["connection"] = np.where(bm["elexonBmUnit"].str.startswith("T_"), "transmission", "embedded")
    keep = {"elexonBmUnit": "unit_id", "nationalGridBmUnit": "ngc_id", "bmUnitName": "unit_name",
            "leadPartyId": "party_id", "leadPartyName": "party_name", "fuelType": "fuel_type",
            "generationCapacity": "capacity_mw", "demandCapacity": "demand_capacity_mw",
            "gspGroupName": "gsp_group", "fpnFlag": "fpn_flag", "eic": "eic"}
    return bm.rename(columns=keep)[list(keep.values()) + ["tech", "connection", "is_battery"]]


# ---------------------------------------------------------------------------- builders
def build_year(year: int, activity: dict | None = None, reg: pd.DataFrame | None = None) -> pd.DataFrame:
    """The register for `year`: every T_/E_ unit with its lead party (from the snapshot for the year's as-of date),
    technology, capacity (restored where the register lists zero for a unit that ran) and whether it produced in
    the year."""
    stamp, basis = snapshot_for(as_of(year))
    reg = register(register_files()[stamp]) if reg is None else reg.copy()
    activity = activity_files() if activity is None else activity
    windows = pull_windows(activity)
    reg["capacity_source"] = "register"
    fix = reg["unit_id"].map(CAPACITY_WHILE_ACTIVE)
    reg.loc[fix.notna(), "capacity_source"] = "table"
    reg["capacity_mw"] = reg["capacity_mw"].where(fix.isna(), fix)
    ran = (reg["capacity_mw"].fillna(0) <= 0) & reg["unit_id"].map(
        lambda u: bool((activity.get(u, {}).get("fpn") or {}).get("output_any")))
    if ran.any():
        reg.loc[ran, "capacity_mw"] = reg.loc[ran, "unit_id"].map(fpn_max_level)
        reg.loc[ran, "capacity_source"] = "fpn_max"
    act = pd.DataFrame([activity_window(activity.get(u, {}), windows, u, c, pd.notna(f), t)
                        for u, c, f, t in zip(reg["unit_id"], reg["capacity_mw"], reg["fuel_type"], reg["tech"])],
                       index=reg.index)
    df = pd.concat([reg, act], axis=1)
    obs = observed_year(year, windows)
    df["active"] = [active_in(obs, a, b) for a, b in zip(df["active_from"], df["active_to"])]
    df.insert(0, "year", year)
    df["activity_year"] = obs
    df["as_of"], df["register_date"], df["party_basis"] = as_of(year).date(), stamp.date(), basis
    return df[COLUMNS].sort_values(["party_name", "unit_id"]).reset_index(drop=True)


def undated_units(reg: pd.DataFrame, have: set[str]) -> list[str]:
    """The units --pull-missing dates: every unit without an activity file that submits physical notifications
    (fpn_flag), whichever rule dates it now ("assumed" active throughout, "no_evidence", a documented closure or a
    unit listed at zero capacity), so that its days of output date it as they date every other unit. A unit that
    submits none has nothing to pull."""
    notifies = reg["fpn_flag"].map(lambda v: str(v).strip().lower() == "true")
    return [u for u, n in zip(reg["unit_id"], notifies) if n and u not in have]


def fpn_window() -> Span:
    """The FPN files' pull window (their earliest and latest date): a newly pulled file keeps to it, so a first date
    at its start still means "there before the pull" and a last date at its end "still running"."""
    spans = [s for p in glob.glob(str(cfg.raw_dir() / "fpn" / "*.csv")) if (s := _file_span(p)) is not None]
    if not spans:
        raise FileNotFoundError("no FPN files to take the pull window from: pull them first (gbpowerdata.pull.fpn_pull)")
    return min(a for a, _ in spans), max(b for _, b in spans)


def pull_unit_fpn(unit: str, window: Span, tries: int = 4) -> bool:
    """Pull one unit's physical notifications over `window` from Elexon Insights' PN stream (free; one request a
    year, as gbpowerdata.pull.fpn_pull pulls them) into data/raw/fpn/{unit}.csv, merged with any file there. True if
    the unit notified anything, False if nothing came back over the window, None if a request still failed after
    `tries`: then nothing is written for the unit, since a file with a year missing would date it wrongly."""
    import time

    import requests

    from gbpowerdata.pull import fpn_pull

    frames = []
    for y in range(window[0].year, window[1].year + 1):
        start, end = max(window[0], pd.Timestamp(f"{y}-01-01")), min(window[1], pd.Timestamp(f"{y + 1}-01-01"))
        if start >= end:
            continue
        params = {"from": start.strftime("%Y-%m-%d"), "to": end.strftime("%Y-%m-%d"), "bmUnit": unit}
        for k in range(tries):
            try:
                r = requests.get(fpn_pull.STREAM, params=params, timeout=180)
                r.raise_for_status()
                break
            except requests.RequestException as e:  # noqa: BLE001
                if k == tries - 1:
                    print(f"  {unit} {y}: request failed ({e}); nothing written for the unit", flush=True)
                    return None
                time.sleep(2 ** k)
        if data := r.json():
            frames.append(pd.DataFrame(data)[fpn_pull.KEEP])
        time.sleep(fpn_pull.SLEEP)
    if not frames:
        return False
    out = fpn_pull.OUT / f"{unit.replace('/', '_')}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    old = pd.read_csv(out) if out.exists() else pd.DataFrame(columns=fpn_pull.KEEP)
    df = pd.concat([pd.concat(frames, ignore_index=True), old], ignore_index=True)
    df = (df.drop_duplicates(["settlementDate", "settlementPeriod", "timeFrom"])
            .sort_values(["settlementDate", "settlementPeriod", "timeFrom"]))
    df.to_csv(out, index=False)
    return True


def pull_missing_activity() -> int:
    """Date the units without an activity file (undated_units): pull their physical notifications over the FPN
    files' window (fpn_window), and record those that notified nothing over it (record_empty_pulls; a unit already
    recorded for the same window is not asked again). Returns the number of units asked for. Run once, then the
    build again."""
    have = {Path(p).stem for k in (*OUTPUT_KINDS, "bod") for p in glob.glob(str(cfg.raw_dir() / k / "*.csv"))}
    window = fpn_window()
    recorded = {u for u, a, b in empty_pulls() if (a, b) == window}
    todo = [u for u in undated_units(register(), have) if u not in recorded]
    print(f"  {len(todo)} units without an activity file -> FPN {window[0].date()} to {window[1].date()}", flush=True)
    found, empty = 0, []
    for i, u in enumerate(todo, 1):
        got = pull_unit_fpn(u, window)
        found += bool(got)
        if got is False:
            empty.append(u)
        if i % 20 == 0:
            print(f"  --- {i}/{len(todo)}, {found} with notifications", flush=True)
    if empty:
        record_empty_pulls(empty, window)
    print(f"  {found} of {len(todo)} units notified, {len(empty)} notified nothing ({EMPTY_PULLS})", flush=True)
    return len(todo)


def write(years=YEARS, out_dir: Path | None = None) -> None:
    out_dir = cfg.processed_dir() if out_dir is None else out_dir
    activity = activity_files()
    for y in years:
        d = build_year(y, activity)
        d.to_csv(out_dir / f"bm_unit_register_{y}.csv", index=False)
        a, obs = d[d["active"]], int(d["activity_year"].iloc[0])
        print(f"  {y}: {len(a):,} active units of {len(d):,} | {a['party_id'].nunique()} lead parties "
              f"({d['party_basis'].iloc[0]} {d['register_date'].iloc[0]}) | {a['capacity_mw'].sum() / 1e3:.1f} GW | "
              f"battery {int(a['is_battery'].sum())}{'' if obs == y else f' | activity of {obs}'} "
              f"-> bm_unit_register_{y}.csv", flush=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--years", nargs=2, type=int, default=[YEARS[0], YEARS[-1]])
    ap.add_argument("--pull-missing", action="store_true",
                    help="first pull the physical notifications of the units without an activity file")
    a = ap.parse_args(argv)
    years = range(a.years[0], a.years[1] + 1)
    if a.pull_missing:
        pull_missing_activity()
    write(years)
    return 0


if __name__ == "__main__":
    sys.exit(main())
