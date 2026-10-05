"""REPD (Renewable Energy Planning Database) helper.

Provides the physical commissioning dates and the time-masked OPERATIONAL
capacity by technology that the panel needs — so Stage 2's CF denominator and
Stage 3's agent capacity use what was actually built in year t, not PPM nameplate
(which bundles unbuilt future phases, e.g. Dogger Bank at full 3.6 GW from 2023).

Source: DESNZ Renewable Energy Planning Database, free quarterly extract from
gov.uk -> data/raw/repd_*.csv.
"""

from __future__ import annotations

from functools import lru_cache

import pandas as pd

from gbpowerdata import config as cfg
from gbpowerdata.common import naming
from gbpowerdata.common.naming import normalise as _normalise

TECH = {"offshore": "Wind Offshore", "onshore": "Wind Onshore", "solar": "Solar"}

# Stop words for the CfD-name -> REPD-site keyword match (commissioned_date).
_REPD_STOP = {"PROJECT", "OFFSHORE", "ONSHORE", "PHASE",
              "EXTENSION", "WINDFARM", "ENERGY", "POWER"}


def _to_date(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, format="%d/%m/%Y", errors="coerce")


@lru_cache(maxsize=1)
def load_repd() -> pd.DataFrame:
    path = sorted(cfg.raw_dir().glob("repd_*.csv"))[-1]
    df = pd.read_csv(path, encoding="cp1252", low_memory=False)
    out = pd.DataFrame({
        "site": df["Site Name"].astype(str),
        "tech": df["Technology Type"].astype(str),
        "status": df["Development Status (short)"].astype(str),
        "country": df["Country"].astype(str),
        "capacity_mw": pd.to_numeric(df["Installed Capacity (MWelec)"], errors="coerce"),
        "cfd_capacity_mw": pd.to_numeric(df.get("CfD Capacity (MW)"), errors="coerce"),
        "operational": _to_date(df["Operational"]),
        "x_osgb": pd.to_numeric(df.get("X-coordinate"), errors="coerce"),
        "y_osgb": pd.to_numeric(df.get("Y-coordinate"), errors="coerce"),
    })
    decom = next((c for c in df.columns if "decommission" in c.lower()), None)
    out["decommissioned"] = _to_date(df[decom]) if decom else pd.NaT
    out["site_norm"] = out["site"].map(_normalise)
    return out[~out["country"].str.contains("Northern Ireland", na=False)].reset_index(drop=True)


def operational_capacity(year: int, tech: str, commissioned_by: int | None = None) -> float:
    """Total installed capacity (MW) of `tech` physically operational in `year`.

    `commissioned_by` caps the commissioning date (e.g. 2017 to isolate the
    RO-era fleet that commissioned before the RO closed to new accreditation).
    """
    df = load_repd()
    end = pd.Timestamp(f"{year}-12-31")
    if commissioned_by is not None:
        end = min(end, pd.Timestamp(f"{commissioned_by}-12-31"))
    start = pd.Timestamp(f"{year}-01-01")
    m = (df["tech"].str.contains(TECH[tech], na=False)
         & df["operational"].notna() & (df["operational"] <= end)
         & (df["decommissioned"].isna() | (df["decommissioned"] >= start)))
    return float(df.loc[m, "capacity_mw"].sum())


def operational_frame(year: int, tech: str, commissioned_by: int | None = None) -> pd.DataFrame:
    """REPD rows of `tech` physically operational in `year` (same mask as
    `operational_capacity`), keeping site / capacity / OSGB coordinates."""
    df = load_repd()
    end = pd.Timestamp(f"{year}-12-31")
    if commissioned_by is not None:
        end = min(end, pd.Timestamp(f"{commissioned_by}-12-31"))
    start = pd.Timestamp(f"{year}-01-01")
    m = (df["tech"].str.contains(TECH[tech], na=False)
         & df["operational"].notna() & (df["operational"] <= end)
         & (df["decommissioned"].isna() | (df["decommissioned"] >= start)))
    return df.loc[m].copy()


def operational_by_zone(year: int, tech: str, commissioned_by: int | None = None) -> pd.Series:
    """Operational capacity (MW) of `tech` in `year`, summed per gsp_group.

    Offshore farms sit in the sea; gsp.tag_osgb snaps them to the nearest onshore
    GSP and gsp.apply_overrides corrects the known offshore connection-point
    mismatches (see data/reference/gsp_overrides.csv)."""
    from gbpowerdata.common import gsp  # local import: keeps the geo dependency optional for the panel
    frame = operational_frame(year, tech, commissioned_by)
    if frame.empty:
        return pd.Series(dtype=float)
    located = gsp.tag_osgb(frame, "x_osgb", "y_osgb")
    located = gsp.apply_overrides(located, key_col="site")
    return located.groupby("gsp_group")["capacity_mw"].sum()


def commissioned_date(name: str, tech_hint: str | None = None) -> pd.Timestamp | None:
    """Best-effort REPD operational date for a CfD project name (keyword match)."""
    df = load_repd()
    if tech_hint:
        df = df[df["tech"].str.contains(TECH.get(tech_hint, tech_hint), na=False)]
    kw = naming.keyword(name, stop=_REPD_STOP, fallback=None)
    if kw is None:
        return None
    hits = df[df["site_norm"].str.contains(kw, na=False) & df["operational"].notna()]
    return hits["operational"].min() if not hits.empty else None
