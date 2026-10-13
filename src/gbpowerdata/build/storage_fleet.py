"""The storage fleet: every battery and pumped storage unit the open data name, with its power and energy capacity
and the dates it entered and left the market -> data/processed/storage_fleet.csv.

Why: a model of storage entry and exit needs each unit's power (MW), its energy (MWh) and the dates it began and
stopped trading. The BM unit register (gbpowerdata.build.bm_units) dates units by their output, for the ownership
tables, and carries no energy capacity; this table dates a storage unit by the first evidence of trading of any
kind, adds the batteries that sell only to NESO (supplier, virtual lead party and non-BM units), and gives an
energy capacity where an open source states one, with the source.

Sources (all open; Elexon BMRS data licence, NESO Open Data Licence):
  data/raw/bm_units_*.csv            Elexon's BM unit register, every kept snapshot (gbpowerdata.build.bm_units.register:
                                     the T_ and E_ battery and pumped storage units, capacity, demand capacity, lead
                                     party, GSP group; the newest snapshot naming a unit gives its attributes), and
                                     the name and lead party of the supplier and virtual lead party units (register_names)
  data/raw/fpn/{unit}.csv            physical notifications (gbpowerdata.pull.fpn_pull, --storage-fleet for the supplier
                                     and virtual lead party units; bm_units --pull-missing)
  data/raw/ebocf/ebocf_*.csv         the storage units' Balancing Mechanism cashflows, the supplier and virtual lead
                                     party units' included (gbpowerdata.pull.ebocf_pull)
  data/processed/ancillary_by_unit_{y}.csv   NESO's frequency response and reserve results by unit (the FFR tenders
                                     from January 2019, the auctions from October 2020; gbpowerdata.build.ancillary_services)
  data/raw/bm_dynamic/dynamic_*.csv, submissions_{MDV,MDP}_*.csv   snapshots of the BM dynamic data and every MDV
                                     and MDP submission (gbpowerdata.pull.bm_dynamic_pull, --submissions; optional):
                                     MDV, the maximum delivery volume (MWh) a unit declares it can deliver over its
                                     maximum delivery period MDP (minutes); Grid Code BC1, Appendix A
  data/raw/neso/cm_register/components_*.csv   NESO's Capacity Market register, the newest snapshot (optional): a
                                     component whose Component ID is the unit's Elexon or National Grid id, and its
                                     storage duration class ("Storage (Duration 2h)"), with its postcode
  data/processed/capacity_market_links.csv, capacity_market_agreements.csv   the storage BM units' CM agreements
                                     (gbpowerdata.build.capacity_market, by component id or by name; optional)
  data/raw/neso/ancillary/eac_by_unit_*.csv    NESO's Enduring Auction Capability results: each unit's postcode
                                     (from Nov 2023), for the supplier, virtual lead party and non-BM batteries

Rules:
  registered_from   the first date of the unit's notification file. A unit notifies, zeros at first, once it is
                    registered, so this bounds its registration from above; Elexon publishes no registration date.
  first_notified    the first day with a notified level of at least 1 MW in at least 4 half-hours, charging included
                    (bm_units.output_span, the register's activity rule); last_notified the last such day. For every
                    unit with an Elexon id: T_, E_, and the supplier and virtual lead party units.
  first_bm_action   the first settlement period with a non-zero BM cashflow (EBOCF); last_bm_action the last.
  first_ancillary   the first delivery period with an accepted MW in NESO's results; last_ancillary the last.
  tech              for a unit outside T_ and E_, battery where its most frequent technology label in NESO's results
                    outside the FFR tenders (else in them) is a battery's (Battery, Batteries, ...): the tenders label
                    a unit by its provider's category ("DSF: Storage (for export)") where the auctions say Battery.
  entry_date        the earliest of the three first dates: the first evidence of trading. entry_censored says the
                    source that gives it opens within ENTRY_SLACK of that date (notifications from Mar 2016, BM
                    cashflows from Jan 2018, ancillary results from 1 Jan 2019), so the unit may have traded before.
                    For a supplier or virtual lead party unit, its first result in NESO's services, the evidence that
                    it is a battery: such a unit can hold other sites, and 13 of them were in the BM more than 90 days
                    before it (UK Power Reserve's East Midlands unit from 2019, its first battery result in December
                    2024), so their earlier notifications and BM actions (first_notified, first_bm_action) are not
                    taken as the battery's. A single-site unit that traded before its first result (Habitat's Potmans
                    Lane, V__JHABI009, for four months) is dated late by this.
  last_seen         the latest of the three last dates.
  exit_date         for a BM unit, last_seen where it lies more than EXIT_SLACK before the end of the data of every
                    source (else blank: still trading at the end of the data). A unit seen only in NESO's results
                    gets none: one that stops appearing there may have moved to a BM unit id or to the energy markets
                    alone (95 of 97 such disappearances by Oct 2026). operating(fleet, date) counts it while it is
                    seen (last_seen), so a unit that moved is not counted twice.
  capacity_mw       the register's generation capacity; for a unit outside T_ and E_ the largest MW NESO accepted it
                    for (capacity_source "ancillary_max_mw": a lower bound).
  energy_mwh        MDV where the unit declares a plausible one (the largest declared value between MDV_MIN_H and
                    MDV_MAX_H hours at its capacity, in a snapshot or a submission; 0, 1 and 99,999 are
                    placeholders), else the CM register's duration class x capacity (the class rounds the duration
                    down to its step, so a lower bound), else blank; energy_source says which (mdv,
                    cm_duration_class). duration_h = energy_mwh / capacity_mw.
  cm_duration_h     the duration class of a component whose Component ID is the unit's id, else of the CM agreement
                    linked to the BM unit (capacity_market: the latest to have started, the largest of its year, so a
                    small later extension of a site does not stand for its battery), else, for a unit outside the BM
                    units, of the CM storage components at its EAC postcode (one class in their latest delivery year);
                    cm_duration_basis says which (component_id, capacity_market_link, postcode). Where a unit also
                    declares MDV, the two agree within half the class for 59 of 65 units (all 15 by component id;
                    10 Oct 2026).

Known limits: registration dates are bounded, not observed. Energy capacity is stated for 238 of 395 batteries (72%
of their capacity; 10 Oct 2026): MDV is declared by about a third of them and often as a placeholder, a CM duration
class is a lower bound, a name or postcode link is an inference, and DESNZ states it has no reliable source for
battery energy capacity (Grid-scale battery storage statistics, 30 Jun 2026). Batteries that are neither in the BM nor
sold to NESO (most distribution-connected sites) are in no source here: the DNO embedded capacity registers would add
them (docs/DATA_GAPS.md).

Output: data/processed/storage_fleet.csv, one row per unit: unit_id, ngc_id, kind (bm, supplier, vlp, non_bm), tech,
unit_name, lead_party, participant, gsp_group, capacity_mw, capacity_source, demand_capacity_mw, energy_mwh,
energy_source, duration_h, mdv_mwh, mdp_min, cm_duration_h, cm_duration_basis, registered_from, first_notified,
first_bm_action, first_ancillary, entry_date, entry_censored, last_notified, last_bm_action, last_ancillary,
last_seen, exit_date, in_latest_register, as_of.
Read it with gbpowerdata.processed.read_storage_fleet(); operating(fleet, date) gives the units trading on a date.

Usage: python -m gbpowerdata.build.storage_fleet
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from gbpowerdata import config as cfg

STORAGE = ("battery", "pumped_storage")
MDV_PLACEHOLDERS = (0.0, 1.0, 99999.0)
MDV_MIN_H, MDV_MAX_H = 0.25, 24.0          # a declared MDV outside these hours at the unit's capacity is not its energy
ENTRY_SLACK = pd.Timedelta(days=7)
EXIT_SLACK = pd.Timedelta(days=45)
BATTERY_LABEL = re.compile(r"^batter", re.I)   # NESO's technology labels: Batteries, Battery, BATTERY, BATTERIES
DURATION = re.compile(r"duration\s*([\d.]+)\s*h", re.I)
POSTCODE = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?)\s*(\d[A-Z]{2})\b")
COLUMNS = ["unit_id", "ngc_id", "kind", "tech", "unit_name", "lead_party", "participant", "gsp_group", "capacity_mw",
           "capacity_source", "demand_capacity_mw", "energy_mwh", "energy_source", "duration_h", "mdv_mwh", "mdp_min",
           "cm_duration_h", "cm_duration_basis", "registered_from", "first_notified", "first_bm_action",
           "first_ancillary", "entry_date", "entry_censored", "last_notified", "last_bm_action", "last_ancillary",
           "last_seen", "exit_date", "in_latest_register", "as_of"]


# ---------------------------------------------------------------------------- rules
def kind_of(unit_id) -> str:
    u = str(unit_id)
    if u.startswith(("T_", "E_")):
        return "bm"
    if u.startswith("2__"):
        return "supplier"
    if u.startswith("V__"):
        return "vlp"
    return "non_bm"


def plausible_mdv(mdv: pd.Series, capacity_mw: float) -> float:
    """The largest declared MDV (MWh) that is not a placeholder and lies between MDV_MIN_H and MDV_MAX_H hours at the
    unit's capacity; NaN if none."""
    v = pd.to_numeric(mdv, errors="coerce").dropna()
    v = v[~v.isin(MDV_PLACEHOLDERS)]
    if not np.isfinite(capacity_mw) or capacity_mw <= 0:
        return np.nan
    v = v[(v >= MDV_MIN_H * capacity_mw) & (v <= MDV_MAX_H * capacity_mw)]
    return float(v.max()) if len(v) else np.nan


def entry_exit(first: dict[str, pd.Timestamp], last: dict[str, pd.Timestamp], windows: dict[str, tuple]) -> dict:
    """entry_date, entry_censored and exit_date from each source's first and last date (NaT where it saw nothing) and
    each source's data window (start, end)."""
    firsts = {k: v for k, v in first.items() if pd.notna(v)}
    lasts = {k: v for k, v in last.items() if pd.notna(v)}
    if not firsts:
        return {"entry_date": pd.NaT, "entry_censored": False, "exit_date": pd.NaT}
    src, entry = min(firsts.items(), key=lambda kv: kv[1])
    censored = bool(src in windows and entry <= windows[src][0] + ENTRY_SLACK)
    end = max(lasts.values())
    data_end = min(w[1] for w in windows.values()) if windows else end
    return {"entry_date": entry, "entry_censored": censored,
            "exit_date": end if end < data_end - EXIT_SLACK else pd.NaT}


def operating(fleet: pd.DataFrame, when) -> pd.DataFrame:
    """The units trading on `when`: entered on or before it, and for a BM unit not exited before it; a unit seen only
    in NESO's results counts while it is seen there (last_seen within EXIT_SLACK of `when`), so one that moved to a BM
    unit id is not counted twice."""
    when = pd.Timestamp(when)
    entry = pd.to_datetime(fleet["entry_date"])
    exit_ = pd.to_datetime(fleet["exit_date"])
    seen = pd.to_datetime(fleet["last_seen"]) if "last_seen" in fleet else pd.Series(pd.NaT, index=fleet.index)
    bm = fleet["kind"].eq("bm") if "kind" in fleet else pd.Series(True, index=fleet.index)
    still = np.where(bm, exit_.isna() | (exit_ >= when), seen >= when - EXIT_SLACK)
    return fleet[(entry <= when) & still]


# ---------------------------------------------------------------------------- sources
def register_units() -> pd.DataFrame:
    """Every T_/E_ storage unit of any kept register snapshot, its attributes from the newest snapshot naming it."""
    from gbpowerdata.build import bm_units as B

    frames = []
    for stamp, path in B.register_files().items():
        r = B.register(path)
        r = r[r["tech"].isin(STORAGE)].assign(snapshot=stamp)
        frames.append(r)
    reg = pd.concat(frames, ignore_index=True).sort_values("snapshot").drop_duplicates("unit_id", keep="last")
    latest = max(B.register_files())
    reg["in_latest_register"] = reg["snapshot"] == latest
    return reg.rename(columns={"party_name": "lead_party"}).reset_index(drop=True)


def register_names() -> pd.DataFrame:
    """unit_name, lead_party and gsp_group of every unit of any kind in a kept register snapshot (the newest snapshot
    naming it wins): the names of the supplier and virtual lead party units, which register_units leaves out because
    the register gives them no fuel type."""
    from gbpowerdata.build import bm_units as B

    cols = {"elexonBmUnit": "unit_id", "bmUnitName": "unit_name", "leadPartyName": "lead_party",
            "gspGroupName": "gsp_group"}
    frames = [pd.read_csv(p, usecols=list(cols)).assign(snapshot=s) for s, p in B.register_files().items()]
    r = pd.concat(frames, ignore_index=True).dropna(subset=["elexonBmUnit"]).sort_values("snapshot")
    return r.drop_duplicates("elexonBmUnit", keep="last").rename(columns=cols)[list(cols.values())]


def notification_dates(units, raw: Path) -> tuple[pd.DataFrame, tuple | None]:
    """registered_from, first_notified and last_notified per unit, and the notification files' window."""
    from gbpowerdata.build import bm_units as B

    rows, lo, hi = [], None, None
    for u in units:
        f = raw / "fpn" / f"{u}.csv"
        if not f.exists():
            continue
        s = B.output_span(str(f), "fpn")
        if not s or s["file"] is None:
            continue
        first, last = s["file"]
        lo, hi = min(lo or first, first), max(hi or last, last)
        out = s.get("output_any")
        rows.append({"unit_id": u, "registered_from": first, "first_notified": out[0] if out else pd.NaT,
                     "last_notified": out[1] if out else pd.NaT})
    cols = ["unit_id", "registered_from", "first_notified", "last_notified"]
    return pd.DataFrame(rows, columns=cols), ((lo, hi) if lo is not None else None)


def bm_action_dates(raw: Path) -> tuple[pd.DataFrame, tuple | None]:
    """First and last settlement period with a non-zero BM cashflow per unit (EBOCF), and the files' window."""
    files = sorted((raw / "ebocf").glob("ebocf_*.csv"))
    if not files:
        return pd.DataFrame(columns=["unit_id", "first_bm_action", "last_bm_action"]), None
    e = pd.concat([pd.read_csv(f, usecols=["startTime", "bmUnit", "cashflow_gbp"]) for f in files], ignore_index=True)
    e["day"] = pd.to_datetime(e["startTime"], utc=True).dt.tz_localize(None).dt.normalize()
    # the window: the first month pulled, to the last day with any cashflow (the current month runs to yesterday)
    first_month = min(pd.Period(re.search(r"(\d{4}-\d{2})", f.stem).group(1), "M") for f in files)
    window = (first_month.start_time, e["day"].max())
    e = e[e["cashflow_gbp"].fillna(0) != 0]
    g = e.groupby("bmUnit")["day"].agg(["min", "max"]).reset_index()
    g.columns = ["unit_id", "first_bm_action", "last_bm_action"]
    return g, window


def id_key(unit) -> str:
    """A NESO unit id with its punctuation dropped: NESO spells one unit differently across its result files
    (AFFR1 in the 2020-21 tenders, AFFR-1 in the auctions from Sep 2021; GBND_2 and GBND-2)."""
    return re.sub(r"[^A-Z0-9]", "", str(unit).upper())


def ancillary_dates(processed: Path, ng_ids: dict[str, str] | None = None) -> tuple[pd.DataFrame, tuple | None]:
    """Per unit in NESO's results (ancillary_by_unit_{y}): its Elexon id where it has one, else its NESO id in the
    latest spelling (spellings that differ only in punctuation are one unit, id_key), its technology and company, the
    largest accepted MW, the first and last delivery with an accepted MW; and the results' window. `ng_ids` maps
    id_key(National Grid id) -> Elexon id, for the units ancillary_services left unmapped because of a spelling; a
    NESO id spelled as the Elexon id itself finds it too (NESO names Hutton E_ARNKB-2 in some files and ARNKB-2 in
    others, which made it two units)."""
    files = sorted(processed.glob("ancillary_by_unit_*.csv"))
    if not files:
        return pd.DataFrame(), None
    cols = ["delivery_start", "unit", "elexon_unit", "participant", "technology", "mw", "source"]
    a = pd.concat([pd.read_csv(f, usecols=lambda c: c in cols, low_memory=False) for f in files], ignore_index=True)
    a = a[a["mw"] > 0]
    # the FFR tenders label a unit by its provider's category ("DSF: Storage (for export)") where NESO's auctions say
    # "Battery": a unit's technology is its most frequent label outside the tenders, else in them
    tender = (a["source"].astype(str).str.startswith("ffr_post_tender") if "source" in a
              else pd.Series(False, index=a.index))
    a["label"] = a["technology"].where(~tender)
    a["day"] = pd.to_datetime(a["delivery_start"], utc=True).dt.tz_localize(None).dt.normalize()
    a["norm"] = a["unit"].map(id_key)
    if ng_ids:
        known = {**{id_key(v): v for v in ng_ids.values()}, **ng_ids}
        a["elexon_unit"] = a["elexon_unit"].fillna(a["norm"].map(known))
    a["key"] = a["elexon_unit"].where(a["elexon_unit"].notna(), a["norm"])
    a = a.sort_values("day")

    def mode(s: pd.Series):                     # the most frequent value; blank where every row is
        m = s.dropna().mode()
        return m.iat[0] if len(m) else pd.NA

    g = a.groupby("key").agg(ngc_id=("unit", "last"), technology=("label", mode), any_label=("technology", mode),
                             participant=("participant", mode), max_mw=("mw", "max"),
                             first_ancillary=("day", "min"), last_ancillary=("day", "max")).reset_index()
    g["technology"] = g["technology"].fillna(g.pop("any_label"))
    has_elexon = g["key"].isin(set(a["elexon_unit"].dropna()))
    g["unit_id"] = g["key"].where(has_elexon, g["ngc_id"])       # a non-BM unit: NESO's latest spelling
    return g.drop(columns="key"), (a["day"].min(), a["day"].max())


def mdv_declarations(raw: Path) -> pd.DataFrame:
    """Every MDV and MDP value per unit: the BM dynamic data snapshots (dynamic_*.csv) and every submission
    (submissions_{MDV,MDP}_*.csv, gbpowerdata.pull.bm_dynamic_pull --submissions); empty without either."""
    folder = raw / "bm_dynamic"
    frames = []
    snaps = sorted(folder.glob("dynamic_*.csv"))
    if snaps:
        d = pd.concat([pd.read_csv(f) for f in snaps], ignore_index=True)
        d = d[d["dataset"].isin(["MDV", "MDP"])]
        frames.append(d.rename(columns={"bmUnit": "unit_id"})[["unit_id", "dataset", "value"]])
    for ds, col in (("MDV", "volumeMax"), ("MDP", "periodMax")):
        parts = [pd.read_csv(f) for f in sorted(folder.glob(f"submissions_{ds}_*.csv")) if f.stat().st_size > 0]
        parts = [p for p in parts if col in p and len(p)]
        if parts:
            s = pd.concat(parts, ignore_index=True)
            frames.append(pd.DataFrame({"unit_id": s["bmUnit"], "dataset": ds, "value": s[col]}))
    if not frames:
        return pd.DataFrame(columns=["unit_id", "dataset", "value"])
    return pd.concat(frames, ignore_index=True).dropna(subset=["unit_id"])


def cm_durations(raw: Path) -> pd.DataFrame:
    """Per Component ID that names a unit: its storage duration class (hours) in the newest CM register snapshot, from
    the latest delivery year that states one."""
    files = sorted((raw / "neso" / "cm_register").glob("components_*.csv"))
    if not files:
        return pd.DataFrame(columns=["component_id", "cm_duration_h"])
    c = pd.read_csv(files[-1], dtype=str, usecols=["Component ID", "Generating Technology Class", "Delivery Year"])
    c["cm_duration_h"] = pd.to_numeric(c["Generating Technology Class"].str.extract(DURATION)[0], errors="coerce")
    c = c.dropna(subset=["cm_duration_h"]).sort_values("Delivery Year")
    c["component_id"] = c["Component ID"].astype(str).str.strip().str.upper()
    return c.drop_duplicates("component_id", keep="last")[["component_id", "cm_duration_h"]]


def cm_link_durations(processed: Path, as_of: pd.Timestamp | None = None) -> pd.Series:
    """unit_id -> the storage duration class (hours) of the Capacity Market agreements linked to the unit
    (gbpowerdata.build.capacity_market: capacity_market_links, by component id or by name): the latest agreement that
    has started by `as_of` (today), the largest by connection capacity among those of one year, so that a small
    later extension of a site (Broxburn's and Cathkin's 7 MW, 9 h CMUs from 2027) does not stand for its battery;
    the first one to start where none has. Empty without those tables."""
    links, agr = processed / "capacity_market_links.csv", processed / "capacity_market_agreements.csv"
    if not (links.exists() and agr.exists()):
        return pd.Series(dtype=float)
    m = pd.read_csv(links).merge(pd.read_csv(agr, usecols=["agreement_id", "auction_id", "duration_h", "connection_mw",
                                                            "first_delivery_year"]), on=["agreement_id", "auction_id"])
    m = m.dropna(subset=["duration_h"])
    now = pd.Timestamp.today() if as_of is None else pd.Timestamp(as_of)
    year = now.year if now.month >= 10 else now.year - 1                   # the delivery year in progress
    m["started"] = m["first_delivery_year"] <= year
    m["order"] = np.where(m["started"], m["first_delivery_year"], -m["first_delivery_year"])
    m = m.sort_values(["started", "order", "connection_mw"])
    return m.drop_duplicates("unit_id", keep="last").set_index("unit_id")["duration_h"]


def postcode_of(text) -> str | None:
    """The UK postcode in a text, without its space ("Holes Bay, Poole BH15 1AA" -> "BH151AA"); None if none."""
    m = POSTCODE.search(str(text).upper())
    return m.group(1) + m.group(2) if m else None


def eac_postcodes(raw: Path) -> pd.Series:
    """id_key(NESO unit) -> its postcode in the Enduring Auction Capability results (from Nov 2023; the most frequent
    where a unit's rows differ), the one open source of a postcode for supplier, virtual lead party and non-BM units."""
    files = sorted((raw / "neso" / "ancillary").glob("eac_by_unit_*.csv"))
    if not files:
        return pd.Series(dtype=object)
    e = pd.concat([pd.read_csv(f, usecols=["auctionUnit", "postCode"], dtype=str) for f in files], ignore_index=True)
    e["postcode"] = e["postCode"].map(postcode_of)
    e = e.dropna(subset=["postcode"])
    e["key"] = e["auctionUnit"].map(id_key)
    return e.groupby("key")["postcode"].agg(lambda s: s.mode().iat[0])


def cm_postcode_durations(raw: Path) -> pd.Series:
    """postcode -> the storage duration class (hours) of the CM storage components at it, in the latest delivery year
    that states one; left out where that year's components at the postcode differ in class."""
    files = sorted((raw / "neso" / "cm_register").glob("components_*.csv"))
    if not files:
        return pd.Series(dtype=float)
    c = pd.read_csv(files[-1], dtype=str, usecols=["Generating Technology Class", "Delivery Year", "Location and Post Code"])
    c["duration"] = pd.to_numeric(c["Generating Technology Class"].str.extract(DURATION)[0], errors="coerce")
    c["postcode"] = c["Location and Post Code"].map(postcode_of)
    c = c.dropna(subset=["duration", "postcode"])
    c["year"] = pd.to_numeric(c["Delivery Year"], errors="coerce")
    last = c[c["year"] == c.groupby("postcode")["year"].transform("max")]
    one = last.groupby("postcode")["duration"].nunique() == 1
    return last[last["postcode"].isin(one[one].index)].groupby("postcode")["duration"].first()


# ---------------------------------------------------------------------------- build
def build(raw: Path | None = None, processed: Path | None = None) -> pd.DataFrame:
    raw = cfg.raw_dir() if raw is None else Path(raw)
    processed = cfg.processed_dir() if processed is None else Path(processed)
    from gbpowerdata.build import ancillary_services as A

    reg = register_units()
    bm, w_bm = bm_action_dates(raw)
    anc, w_anc = ancillary_dates(processed, {id_key(k): v for k, v in A.elexon_ids().items()})

    # BM storage units of the register
    f = reg.copy()
    if not anc.empty:
        f = f.merge(anc[["unit_id", "participant", "first_ancillary", "last_ancillary"]], on="unit_id", how="left")
    f["kind"] = "bm"
    f["capacity_source"] = "register"
    # batteries outside T_ and E_ that NESO names (supplier, virtual lead party and non-BM units), with the register's
    # name and lead party for those it lists
    if not anc.empty:
        other = anc[~anc["unit_id"].isin(f["unit_id"]) & anc["technology"].astype(str).str.match(BATTERY_LABEL)].copy()
        other = other.assign(kind=other["unit_id"].map(kind_of), tech="battery", capacity_mw=other["max_mw"],
                             capacity_source="ancillary_max_mw",
                             in_latest_register=other["unit_id"].map(kind_of) != "non_bm")
        other = other.merge(register_names(), on="unit_id", how="left")
        f = pd.concat([f, other.drop(columns=["max_mw", "technology"])], ignore_index=True)
    # every unit with an Elexon id, joined to its notifications and BM cashflows (the supplier and virtual lead party
    # units' too, where ebocf_pull and fpn_pull --storage-fleet have pulled them)
    notes, w_fpn = notification_dates(f.loc[f["kind"] != "non_bm", "unit_id"], raw)
    f = f.merge(notes, on="unit_id", how="left").merge(bm, on="unit_id", how="left")
    windows = {k: w for k, w in (("notified", w_fpn), ("bm_action", w_bm), ("ancillary", w_anc)) if w is not None}
    for c in ("first_notified", "last_notified", "first_bm_action", "last_bm_action", "first_ancillary",
              "last_ancillary", "registered_from"):
        if c not in f:
            f[c] = pd.NaT
        f[c] = pd.to_datetime(f[c])
    # a supplier or virtual lead party unit is known to be a battery from NESO's results: it enters with them
    by_result = f["kind"].isin(["supplier", "vlp"]).to_numpy()
    dates = [entry_exit({"notified": pd.NaT if b else r.first_notified, "bm_action": pd.NaT if b else r.first_bm_action,
                         "ancillary": r.first_ancillary},
                        {"notified": r.last_notified, "bm_action": r.last_bm_action, "ancillary": r.last_ancillary},
                        windows) for r, b in zip(f.itertuples(index=False), by_result)]
    f = pd.concat([f.reset_index(drop=True), pd.DataFrame(dates)], axis=1)
    f["last_seen"] = f[["last_notified", "last_bm_action", "last_ancillary"]].max(axis=1)
    # a unit seen only in NESO's results that stops appearing there may have moved to a BM unit id or to the energy
    # markets alone: no exit date (95 of 97 such "exits" by Oct 2026 were of these units), last_seen says when it was
    f.loc[f["kind"] != "bm", "exit_date"] = pd.NaT

    # energy: declared MDV, else the CM duration class
    dyn = mdv_declarations(raw)
    mdv = {u: plausible_mdv(g.loc[g["dataset"] == "MDV", "value"], cap)
           for u, cap in zip(f["unit_id"], f["capacity_mw"]) for g in [dyn[dyn["unit_id"] == u]]} if len(dyn) else {}
    mdp = dyn[dyn["dataset"] == "MDP"].groupby("unit_id")["value"].max() if len(dyn) else pd.Series(dtype=float)
    f["mdv_mwh"] = f["unit_id"].map(mdv).astype(float) if mdv else np.nan
    f["mdp_min"] = f["unit_id"].map(mdp).astype(float) if len(mdp) else np.nan
    cm = cm_durations(raw).set_index("component_id")["cm_duration_h"]
    by_id = f["unit_id"].astype(str).str.upper().map(cm).fillna(f["ngc_id"].astype(str).str.upper().map(cm))
    by_link = f["unit_id"].map(cm_link_durations(processed))
    codes = eac_postcodes(raw)
    by_code = f["ngc_id"].map(id_key).map(codes).map(cm_postcode_durations(raw)).where(f["kind"] != "bm")
    f["cm_duration_h"] = by_id.fillna(by_link).fillna(by_code)
    f["cm_duration_basis"] = np.select([by_id.notna(), by_link.notna(), by_code.notna()],
                                       ["component_id", "capacity_market_link", "postcode"], default=None)
    f["energy_mwh"] = f["mdv_mwh"].where(f["mdv_mwh"].notna(), f["cm_duration_h"] * f["capacity_mw"])
    f["energy_source"] = np.where(f["mdv_mwh"].notna(), "mdv",
                                  np.where(f["cm_duration_h"].notna(), "cm_duration_class", None))
    f["duration_h"] = (f["energy_mwh"] / f["capacity_mw"].where(f["capacity_mw"] > 0)).round(2)
    f["as_of"] = pd.Timestamp.today().normalize().date()
    for c in COLUMNS:
        if c not in f:
            f[c] = pd.NA
    return f[COLUMNS].sort_values(["kind", "tech", "unit_id"]).reset_index(drop=True)


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description=__doc__.split("\n\n")[0]).parse_args(argv)
    f = build()
    out = cfg.processed_dir() / "storage_fleet.csv"
    f.to_csv(out, index=False, date_format="%Y-%m-%d")
    b = f[f["tech"] == "battery"]
    now = operating(b, pd.Timestamp.today().normalize())
    print(f"  {out.name}: {len(f)} units ({len(b)} batteries: {b['kind'].value_counts().to_dict()}); batteries trading "
          f"now {now['capacity_mw'].sum() / 1e3:.2f} GW, energy stated for {int(b['energy_mwh'].notna().sum())} "
          f"({b['energy_source'].value_counts().to_dict()})", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
