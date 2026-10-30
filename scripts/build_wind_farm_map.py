"""The transmission wind-farm map: every wind BM unit with a physical-notification record, linked to
its station, its REPD site(s), its location and its support contract.

WHY. The merit-order comb gives every wind agent either the national CF or (--vre-profile zonal)
its GSP group's reanalysis shape, so no two farms in a zone differ. Observed per-unit output
exists for the transmission and BM-registered fleet: the Final Physical Notification (FPN,
data/raw/fpn/, gbpowerdata.pull.fpn_pull), 206 wind units and 27 GW (Oct 2026: 169 transmission T_ units,
25.7 GW, and 37 embedded E_ units, 1.3 GW, whose notifications `bm_units --pull-missing` fetched). Priced at the caprec clearing, the
per-unit capture spread is about twice the 14-zone one (sd GBP 3.5-5.5/MWh, 2022-23). This map is
what lets gbpowerdata.build.stage2d_wind_farms and the comb's --vre-profile farm give the RO part of
that fleet one agent per farm. It records FACTS only; the regime and band RULES live in stage2d.

WHAT EACH ROW CARRIES
    elexon_bmu_id, bmu_name, bmu_capacity_mw   Elexon BM unit register (data/raw/bm_units_*.csv)
    station                                    Power Station Dictionary name (data/raw/psd/ids.csv),
                                               else the unit's code (T_SGRWO-3 -> SGRWO)
    repd_ref_ids, repd_site, repd_capacity_mw, repd_operational, is_offshore, x_osgb, y_osgb
                                               the REPD rows of the unit: an override's ids, else the
                                               station's (the dictionary's REPD ids first, else a
                                               site-name token match, score >= NAME_MIN); earliest
                                               operational date, capacity-weighted coordinates
    gsp_group                                  gbpowerdata.common.gsp.tag_osgb on those coordinates - the
                                               same snap stage3 uses to zone the offshore aggregates
    cfd, cfd_ids                               LCCC contract links (data/reference/cfd_bmu_map.csv)
    fpn_state, first_power                     "pre_record": positive within PRE_RECORD_DAYS of the
                                               earliest FPN record of ANY unit (2016-03-01), so it was
                                               commissioned before the record; "observed": first
                                               positive half-hour after that (first power); "never":
                                               no positive FPN (not yet built)
    match_method, qa_flag, note                how the REPD link was made; capacity ratio REPD/BMU
                                               outside [0.5, 2] or no REPD; an override's reason
    data/reference/wind_farm_map_overrides.csv (elexon_bmu_id, repd_ref_ids, note, bmu_capacity_mw) pins
    a unit's REPD rows, or corrects the register's capacity where it is plainly wrong (apply_capacity_
    overrides; since 27 Oct 2026, for Bad a Cheo, which Elexon lists at 270 MW against REPD's 26.7 and
    whose notified output is a 3.5% capacity factor on 270 MW); every override states why.

A unit's ERA is decided per unit, not per station: stations such as Gordonbush or Aikengall pair
an RO-era original with a post-2017 extension under one name, and an extension's units only appear
in the FPN record when they first generate.

Output: data/reference/wind_farm_map.csv
Run:    python scripts/build_wind_farm_map.py
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from gbpowerdata import config as cfg  # noqa: E402
from gbpowerdata.common import gsp  # noqa: E402

RAW = cfg.raw_dir()
REF = cfg.reference_dir()
OUT = REF / "wind_farm_map.csv"
OVR = REF / "wind_farm_map_overrides.csv"
NAME_MIN = 0.34        # token Jaccard; below it a name match is not trusted
PRE_RECORD_DAYS = 31   # positive within a month of the record's start = already running
STOP = {"wind", "farm", "windfarm", "windfarms", "offshore", "onshore", "wf", "owf", "bmu", "the",
        "ltd", "limited", "generation", "power", "station", "project", "energy", "extension",
        "phase", "a", "b", "c", "and", "of", "gen", "array", "zone", "scheme", "site", "renewable",
        "renewables", "plc", "uk", "community"}


def _toks(s: str) -> set[str]:
    s = re.sub(r"[^a-z0-9 ]+", " ", str(s).lower())
    return {t for t in s.split() if t not in STOP and not t.isdigit() and len(t) > 1}


def _repd() -> pd.DataFrame:
    rp = pd.read_csv(next(RAW.glob("repd_*.csv")), encoding="latin-1", low_memory=False)
    rp = rp[rp["Technology Type"].astype(str).str.contains("Wind", case=False)].copy()
    rp["id_new"] = rp["Ref ID"].astype(str).str.strip()
    rp["id_old"] = rp["Old Ref ID"].astype(str).str.strip()
    rp["cap"] = pd.to_numeric(rp["Installed Capacity (MWelec)"], errors="coerce")
    rp["op"] = pd.to_datetime(rp["Operational"], dayfirst=True, errors="coerce")
    rp["off"] = rp["Technology Type"].astype(str).str.contains("Offshore", case=False)
    rp["x"] = pd.to_numeric(rp["X-coordinate"], errors="coerce")
    rp["y"] = pd.to_numeric(rp["Y-coordinate"], errors="coerce")
    rp["tok"] = rp["Site Name"].map(_toks)
    return rp


def _summary(hit: pd.DataFrame, how: str) -> dict:
    if hit.empty:
        return dict(repd_ref_ids="", repd_site="", repd_capacity_mw=np.nan, repd_operational=pd.NaT,
                    is_offshore=np.nan, x_osgb=np.nan, y_osgb=np.nan, match_method="none")
    c = hit.dropna(subset=["x", "y", "cap"])
    w = c["cap"].sum() > 0
    return dict(repd_ref_ids=";".join(hit["id_new"]), repd_site=" | ".join(hit["Site Name"].astype(str)),
                repd_capacity_mw=float(hit["cap"].sum()), repd_operational=hit["op"].min(),
                is_offshore=bool(hit["off"].any()),
                x_osgb=float(np.average(c["x"], weights=c["cap"])) if w else np.nan,
                y_osgb=float(np.average(c["y"], weights=c["cap"])) if w else np.nan,
                match_method=how)


def _fpn_first(bmu: str) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
    """(first record, first positive half-hour) of a unit's FPN file."""
    d = pd.read_csv(RAW / "fpn" / f"{bmu}.csv", usecols=["timeFrom", "levelFrom", "levelTo"])
    if d.empty:
        return None, None
    t = pd.to_datetime(d["timeFrom"], utc=True)
    pos = (d["levelFrom"] > 0) | (d["levelTo"] > 0)
    return t.min(), (t[pos].min() if pos.any() else None)


def apply_capacity_overrides(w: pd.DataFrame, ovr: pd.DataFrame) -> pd.DataFrame:
    """The register's capacity, replaced for each unit whose override gives one (ovr indexed by elexon_bmu_id, its
    bmu_capacity_mw a number or empty); every other unit keeps the register's."""
    w = w.copy()
    cap = (pd.to_numeric(ovr["bmu_capacity_mw"], errors="coerce").dropna() if "bmu_capacity_mw" in ovr
           else pd.Series(dtype=float))
    fix = w["elexon_bmu_id"].isin(cap.index)
    w.loc[fix, "bmu_capacity_mw"] = w.loc[fix, "elexon_bmu_id"].map(cap).astype(float)
    return w


def build() -> pd.DataFrame:
    bm = pd.read_csv(next(RAW.glob("bm_units_*.csv")))
    fpn = {f[:-4] for f in os.listdir(RAW / "fpn") if f.endswith(".csv")}
    w = bm[(bm["fuelType"].astype(str).str.upper() == "WIND") & bm["elexonBmUnit"].isin(fpn)][
        ["elexonBmUnit", "bmUnitName", "generationCapacity"]].rename(
        columns={"elexonBmUnit": "elexon_bmu_id", "bmUnitName": "bmu_name",
                 "generationCapacity": "bmu_capacity_mw"})
    # the register lists some units more than once (one row per NGC id); one row per Elexon unit
    w = w.sort_values("bmu_capacity_mw", ascending=False).drop_duplicates("elexon_bmu_id")
    w["code"] = (w["elexon_bmu_id"].str.replace(r"^[TE]_", "", regex=True)
                 .str.replace(r"-\d+$", "", regex=True))
    psd = pd.read_csv(RAW / "psd" / "ids.csv", dtype=str)
    rows = [dict(elexon_bmu_id=b.strip(), station=r["name"],
                 psd_repd=f"{r['new_repd_id']},{r['old_repd_id']}")
            for _, r in psd.iterrows() for b in str(r["sett_bmu_id"]).split(",")
            if b.strip() and b.strip() != "nan"]
    w = w.merge(pd.DataFrame(rows).drop_duplicates("elexon_bmu_id"), on="elexon_bmu_id", how="left")
    w["station"] = w["station"].fillna(w["code"])

    rp = _repd()
    live = rp[rp["op"].notna()]                       # a name match only against built sites
    station = {}
    for st, g in w.groupby("station"):
        ids = {i.strip() for s in g["psd_repd"].dropna() for i in s.split(",")
               if i.strip() and i.strip() != "nan"}
        hit, how = rp[rp["id_new"].isin(ids) | rp["id_old"].isin(ids)], "psd_id"
        if hit.empty:
            t = _toks(st) | set().union(*[_toks(n) for n in g["bmu_name"]])
            sc = live["tok"].map(lambda s: len(s & t) / max(1, len(s | t)) if s else 0.0)
            hit, how = ((live[sc >= sc.max() - 1e-9], f"name:{sc.max():.2f}")
                        if len(sc) and sc.max() >= NAME_MIN else (rp.iloc[:0], "none"))
        station[st] = _summary(hit, how)

    ovr = (pd.read_csv(OVR, dtype=str).set_index("elexon_bmu_id") if OVR.exists()
           else pd.DataFrame(columns=["repd_ref_ids", "note", "bmu_capacity_mw"]))
    recs = []
    for _, u in w.iterrows():
        rec = dict(station[u["station"]], note="")
        if u["elexon_bmu_id"] in ovr.index:
            o = ovr.loc[u["elexon_bmu_id"]]
            ids = {i.strip() for i in str(o.get("repd_ref_ids", "")).split(";") if i.strip() and i.strip() != "nan"}
            if ids:                                     # an override may correct the capacity alone (below)
                rec = _summary(rp[rp["id_new"].isin(ids)], "override")
            rec = dict(rec, note=o.get("note", ""))
        recs.append(dict(elexon_bmu_id=u["elexon_bmu_id"], **rec))
    w = w.merge(pd.DataFrame(recs), on="elexon_bmu_id", how="left")
    w = apply_capacity_overrides(w, ovr)
    unused = sorted(set(ovr.index) - set(w["elexon_bmu_id"]))
    if unused:
        print(f"  WARN overrides for units not in the FPN wind set: {unused}")

    cfd = pd.read_csv(REF / "cfd_bmu_map.csv")
    ids = cfd.groupby("elexon_bmu_id")["cfd_id"].agg(lambda s: ";".join(sorted(set(s))))
    w["cfd_ids"] = w["elexon_bmu_id"].map(ids).fillna("")
    w["cfd"] = w["cfd_ids"] != ""

    fp = {b: _fpn_first(b) for b in w["elexon_bmu_id"]}
    rec0 = min(v[0] for v in fp.values() if v[0] is not None)        # the record's own start
    first = pd.to_datetime(w["elexon_bmu_id"].map(lambda b: fp[b][1]), utc=True)
    pre = first.notna() & (first <= rec0 + pd.Timedelta(days=PRE_RECORD_DAYS))
    w["fpn_state"] = np.where(first.isna(), "never", np.where(pre, "pre_record", "observed"))
    w["first_power"] = first.where(w["fpn_state"] == "observed")
    w["fpn_record_start"] = rec0

    loc = w.dropna(subset=["x_osgb", "y_osgb"])
    loc = gsp.tag_osgb(loc, x="x_osgb", y="y_osgb")[["elexon_bmu_id", "gsp_group"]]
    w = w.merge(loc, on="elexon_bmu_id", how="left")

    unit_ids = w.groupby("repd_ref_ids")["bmu_capacity_mw"].transform("sum")
    ratio = w["repd_capacity_mw"] / unit_ids
    w["qa_flag"] = np.where(w["repd_ref_ids"].fillna("") == "", "no_repd",
                   np.where((ratio < 0.5) | (ratio > 2.0), "capacity_ratio", ""))
    cols = ["elexon_bmu_id", "bmu_name", "bmu_capacity_mw", "station", "repd_ref_ids", "repd_site",
            "repd_capacity_mw", "repd_operational", "is_offshore", "x_osgb", "y_osgb", "gsp_group",
            "cfd", "cfd_ids", "fpn_state", "first_power", "fpn_record_start", "match_method",
            "qa_flag", "note"]
    return w[cols].sort_values(["station", "elexon_bmu_id"]).reset_index(drop=True)


def main() -> None:
    w = build()
    w.to_csv(OUT, index=False)
    print(f"{len(w)} wind units ({w['bmu_capacity_mw'].sum():,.0f} MW) -> {OUT}")
    for col in ("match_method", "qa_flag", "fpn_state"):
        print(w.groupby(w[col].fillna("")).agg(units=("elexon_bmu_id", "size"),
                                               mw=("bmu_capacity_mw", "sum")).round(0).to_string(), "\n")


if __name__ == "__main__":
    main()
