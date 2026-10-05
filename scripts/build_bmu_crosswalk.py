"""BMU <-> station <-> CfD-contract crosswalk, for joining agents to metered dispatch.

THE GAP
    agents_{year}.csv is keyed on the LCCC contract id (INV-DRX-001, AR2-TKN-303) and
    carries no BMU column. Elexon's unit-level data - B1610 metered volumes and FPN
    physical notifications - is keyed on BMU. There is currently no join between them,
    so a modelled agent's bid behaviour cannot be checked against what the plant
    actually did. This file supplies that join.

    The Elexon register has no concept of a station: Drax is nine separate BMUs, Hornsea
    is three. The Power Station Dictionary (vendored, see data/raw/psd/PROVENANCE.md)
    supplies exactly one thing this pipeline lacks - which BMUs are the same physical
    site, and which CfD contract ids attach to that site. Its `cfd_id` is the same
    namespace as `agents.agent_id`, so the join is exact, not name-matched.

AUTHORITY
    PSD supplies the GROUPING only, and is frozen at April 2023. Every attribute -
    fuel type, capacity, GSP group, lead party - is taken from the live Elexon
    register, which is current and which agrees with PSD on fuel type for 315 of 315
    BMUs where both are populated. Where the two disagree, Elexon wins.

RETIREMENT SIGNAL
    PSD is a historical roster with no retirement dates; it still lists Didcot, Cottam,
    Longannet. `in_elexon_register` flags every BMU absent from the current register,
    which is a usable (not authoritative) retirement signal. It is NOT evidence a
    station was operational in the modelled year - use the agents file for that.

PHASE-LEVEL CONTRACTS SHARE STATION-LEVEL METERS
    Hornsea 1/2/3 are three CfDs against the same three T_HOWAO-* units, because the
    meter is at the station. Summing B1610 per agent would treble-count. The crosswalk
    deliberately does NOT carry a capacity share, because shares are year-dependent and
    this is static reference data. Apportion at point of use:

        share = agent.capacity_mw / (capacity of all agents mapping to that station)

    `n_cfd_ids_on_station` flags where this is needed (> 1).

Outputs: data/reference/bmu_crosswalk.csv    one row per (station, BMU)
         data/reference/cfd_bmu_map.csv      one row per (cfd_id, BMU)
Run:     python scripts/build_bmu_crosswalk.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from gbpowerdata import config as cfg  # noqa: E402

PSD = cfg.raw_dir() / "psd" / "ids.csv"
REF = cfg.reference_dir()
OVERRIDES = REF / "bmu_crosswalk_overrides.yaml"
OUT_SPINE = REF / "bmu_crosswalk.csv"
OUT_CFD = REF / "cfd_bmu_map.csv"

# Elexon settlement BMU ids look like T_DRAXX-1 / E_LYNE1 / C__PSMAR001.
# CfD contract ids look like INV-DRX-001 / AR2-TKN-303 / AAA-ACH-183.
CFD_ID_RE = re.compile(r"\b([A-Z]{3}-[A-Z]{3}-\d{3})\b")

# Elexon columns carried through as station/unit attributes.
ELEXON_ATTRS = {
    "bmUnitName": "bmu_name",
    "leadPartyName": "lead_party",
    "bmUnitType": "bmu_type",
    "fuelType": "elexon_fuel_type",
    "eic": "eic",
    "gspGroupId": "gsp_group_id",
    "generationCapacity": "generation_capacity_mw",
}


def latest_register() -> Path:
    """Most recent bm_units_*.csv snapshot in data/raw/."""
    files = sorted(cfg.raw_dir().glob("bm_units_*.csv"))
    if not files:
        raise FileNotFoundError("no data/raw/bm_units_*.csv - run the Elexon pull first")
    return files[-1]


def split_ids(cell: object) -> list[str]:
    """PSD packs multiple ids into one comma-separated cell."""
    if not isinstance(cell, str):
        return []
    return [p.strip() for p in cell.split(",") if p.strip()]


def load_psd_long() -> pd.DataFrame:
    """PSD stations exploded to one row per (station, settlement BMU id)."""
    d = pd.read_csv(PSD)
    rows = []
    for _, r in d.iterrows():
        sett = split_ids(r["sett_bmu_id"])
        ngc = split_ids(r["ngc_bmu_id"])
        # The two lists are positionally aligned upstream but not always the same
        # length; pad rather than zip, so a short ngc list never truncates BMUs.
        for i, bmu in enumerate(sett):
            rows.append({
                "station_id": int(r["dictionary_id"]),
                "station_name": r["name"] if isinstance(r["name"], str) else None,
                "elexon_bmu_id": bmu,
                "ngc_bmu_id": ngc[i] if i < len(ngc) else None,
            })
    return pd.DataFrame(rows).drop_duplicates(subset=["station_id", "elexon_bmu_id"])


def load_psd_cfd() -> pd.DataFrame:
    """PSD station -> CfD contract id, one row per (station, cfd_id)."""
    d = pd.read_csv(PSD)
    rows = [
        {"station_id": int(r["dictionary_id"]), "cfd_id": c, "cfd_id_source": "psd"}
        for _, r in d.iterrows()
        for c in split_ids(r["cfd_id"])
    ]
    return pd.DataFrame(rows)


def elexon_embedded_cfd(reg: pd.DataFrame) -> pd.DataFrame:
    """CfD ids Elexon embeds directly in a BMU name, e.g. C__PSMAR001-AAA-ACH-183.

    A niche convention used for supplier-hosted aggregated units (type S) that host a
    small embedded CfD project. Only a couple of units GB-wide, but it is live data and
    self-maintaining, and it picks up contracts PSD never had - Nanclach among them.
    """
    rows = []
    for _, r in reg.iterrows():
        for fld in ("bmUnitName", "elexonBmUnit", "nationalGridBmUnit"):
            m = CFD_ID_RE.search(str(r[fld]).upper())
            if m:
                rows.append({"elexon_bmu_id": r["elexonBmUnit"], "cfd_id": m.group(1),
                             "cfd_id_source": "elexon_bmu_name"})
                break
    return pd.DataFrame(rows)


def main() -> None:
    ov = yaml.safe_load(OVERRIDES.read_text(encoding="utf-8")) or {}
    restrict = {k: set(v) for k, v in (ov.get("cfd_bmu_restrict") or {}).items()}
    exclude = set(ov.get("exclude_bmus") or {})

    reg_path = latest_register()
    reg = pd.read_csv(reg_path)
    print(f"Elexon register : {reg_path.name}  ({len(reg)} BMUs)")
    print(f"PSD snapshot    : {PSD}")

    spine = load_psd_long()
    spine = spine[~spine.elexon_bmu_id.isin(exclude)]

    # --- attach live Elexon attributes; PSD supplies grouping only ------------------
    attrs = reg[["elexonBmUnit", *ELEXON_ATTRS]].rename(columns=ELEXON_ATTRS)
    attrs = attrs.rename(columns={"elexonBmUnit": "elexon_bmu_id"}).drop_duplicates("elexon_bmu_id")
    spine = spine.merge(attrs, on="elexon_bmu_id", how="left")
    spine["in_elexon_register"] = spine.bmu_name.notna()
    spine["generation_capacity_mw"] = pd.to_numeric(spine.generation_capacity_mw, errors="coerce")

    # --- CfD contract ids -----------------------------------------------------------
    cfd = load_psd_cfd().merge(spine[["station_id", "elexon_bmu_id"]], on="station_id", how="left")
    extra = elexon_embedded_cfd(reg)
    extra = extra[~extra.cfd_id.isin(set(cfd.cfd_id))]
    if len(extra):
        # These units are not in PSD at all, so they get no station; key them on the BMU.
        extra = extra.merge(spine[["elexon_bmu_id", "station_id"]], on="elexon_bmu_id", how="left")
        cfd = pd.concat([cfd, extra], ignore_index=True)

    before = len(cfd)
    keep = cfd.apply(lambda r: r.cfd_id not in restrict or r.elexon_bmu_id in restrict[r.cfd_id],
                     axis=1)
    cfd = cfd[keep]
    print(f"overrides       : {len(restrict)} cfd_bmu_restrict, "
          f"{len(exclude)} exclude_bmus  ({before - len(cfd)} rows dropped)")

    # Contracts sharing a station need capacity apportionment downstream.
    per_station = cfd.groupby("station_id").cfd_id.nunique()
    cfd["n_cfd_ids_on_station"] = cfd.station_id.map(per_station).fillna(1).astype(int)

    cfd = cfd.merge(spine.drop(columns=["station_name", "ngc_bmu_id"]),
                    on=["station_id", "elexon_bmu_id"], how="left")
    cfd = cfd.merge(spine[["station_id", "station_name"]].drop_duplicates(),
                    on="station_id", how="left")

    cols = ["cfd_id", "station_id", "station_name", "elexon_bmu_id", "bmu_name",
            "lead_party", "elexon_fuel_type", "generation_capacity_mw", "gsp_group_id",
            "in_elexon_register", "n_cfd_ids_on_station", "cfd_id_source"]
    cfd = cfd[cols].sort_values(["cfd_id", "elexon_bmu_id"])

    spine_cols = ["station_id", "station_name", "elexon_bmu_id", "ngc_bmu_id", "bmu_name",
                  "lead_party", "bmu_type", "elexon_fuel_type", "eic", "gsp_group_id",
                  "generation_capacity_mw", "in_elexon_register"]
    spine = spine[spine_cols].sort_values(["station_id", "elexon_bmu_id"])

    OUT_SPINE.parent.mkdir(parents=True, exist_ok=True)
    spine.to_csv(OUT_SPINE, index=False)
    cfd.to_csv(OUT_CFD, index=False)

    live = int(spine.in_elexon_register.sum())
    print(f"\n{OUT_SPINE}  {len(spine)} rows, "
          f"{spine.station_id.nunique()} stations, {live} live / {len(spine) - live} deregistered")
    print(f"{OUT_CFD}  {len(cfd)} rows, {cfd.cfd_id.nunique()} contracts")

    report(cfd)


def report(cfd: pd.DataFrame) -> None:
    """Match rate against each year's agents, and capacity sanity-check."""
    print("\n--- coverage of CfD agents ---")
    proc = cfg.processed_dir()
    mapped = set(cfd.cfd_id)
    worst = []
    for f in sorted(proc.glob("agents_*.csv")):
        a = pd.read_csv(f)
        c = a[a.support_regime == "CfD"]
        if not len(c):
            continue
        hit = c[c.agent_id.isin(mapped)]
        print(f"  {f.stem[-4:]}  {len(hit):3d}/{len(c):3d} contracts   "
              f"{hit.capacity_mw.sum():7,.0f} / {c.capacity_mw.sum():7,.0f} MW  "
              f"({100 * hit.capacity_mw.sum() / c.capacity_mw.sum():4.1f}% of CfD capacity)")

        # Agent capacity vs live capacity of its mapped BMUs. Flag only where the
        # station hosts ONE contract, since shared stations are expected to over-read.
        solo = cfd[cfd.n_cfd_ids_on_station == 1]
        bmu_cap = solo.groupby("cfd_id").generation_capacity_mw.sum()
        for _, r in hit.iterrows():
            if r.agent_id in bmu_cap.index and bmu_cap[r.agent_id] > 0:
                ratio = bmu_cap[r.agent_id] / r.capacity_mw
                if not 0.75 <= ratio <= 1.35:
                    worst.append((f.stem[-4:], r.agent_id, r["name"][:34],
                                  r.capacity_mw, bmu_cap[r.agent_id], ratio))
    if worst:
        print("\n--- capacity mismatches, single-contract stations (agent vs mapped BMUs) ---")
        print("    A SCREEN, NOT A VERDICT. Two distinct causes look identical here:")
        print("      (a) genuine mis-grouping - the contract covers only part of the site;")
        print("      (b) Elexon generationCapacity noise - the field is often a registered")
        print("          connection capacity well above the farm's real rating, so small")
        print("          single-BMU wind sites over-read without the mapping being wrong.")
        print("    Check the BMU names before adding a cfd_bmu_restrict override.")
        seen = set()
        for yr, aid, nm, acap, bcap, ratio in sorted(worst, key=lambda x: -abs(x[5] - 1)):
            if aid in seen:
                continue
            seen.add(aid)
            print(f"    {aid:15s} {nm:36s} agent {acap:7,.0f} MW  bmu {bcap:7,.0f} MW  x{ratio:.2f}")


if __name__ == "__main__":
    main()
