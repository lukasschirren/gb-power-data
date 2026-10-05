"""Build one representative renewables.ninja site per (tech, GSP group).

The locational CF gap (per the phase scope) is that today's capacity factor is a
single national series per tech. This derives, for each of the 14 GSP groups and
each renewable tech, ONE capacity-weighted-centroid coordinate from the located
fleet, so renewables.ninja can pull a per-zone reanalysis CF there. Aggregating
the per-zone CF back to national (capacity-weighted) reproduces the copperplate
series, so this is additive.

Sources of located generators:
  - onshore wind / solar : powerplants_located_{year}.csv (PPM lat/lon + gsp_group)
  - offshore wind        : CfD register (lat/lon + authoritative gsp_group) plus
                           REPD operational offshore (OSGB coords -> gsp_group),
                           so the centroid sits at sea where the wind resource is.

Output: data/reference/ninja_sites_by_zone.csv  (same schema as ninja_sites.csv,
plus gsp_group + tech), consumed by `renninja_pull.py --sites-file`.
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from gbpowerdata import config as cfg
from gbpowerdata.common import gsp
from gbpowerdata.common import repd

CFG = cfg.load_config()
YEAR = int(CFG["year"])

# Turbine / panel defaults mirror data/reference/ninja_sites.csv.
DEFAULTS = {
    "wind_offshore": dict(hub_height_m=120, turbine="Vestas V164 8000", tilt="", azim=""),
    "wind_onshore": dict(hub_height_m=80, turbine="Vestas V90 2000", tilt="", azim=""),
    "solar": dict(hub_height_m="", turbine="", tilt=35, azim=180),
}


def _wcentroid(df: pd.DataFrame, lat: str, lon: str, w: str) -> tuple[float, float]:
    m = df[[lat, lon, w]].apply(pd.to_numeric, errors="coerce").dropna()
    m = m[m[w] > 0]
    if m.empty:
        return (np.nan, np.nan)
    return (round(np.average(m[lat], weights=m[w]), 4),
            round(np.average(m[lon], weights=m[w]), 4))


def onshore_solar_sites() -> pd.DataFrame:
    loc = pd.read_csv(cfg.processed_dir() / f"powerplants_located_{YEAR}.csv",
                      keep_default_na=False, na_values=[""])
    loc["Capacity"] = pd.to_numeric(loc["Capacity"], errors="coerce")
    onshore = loc[(loc["Fueltype"] == "Wind") & (loc["Technology"] != "Offshore")].copy()
    solar = loc[loc["Fueltype"] == "Solar"].copy()
    rows = []
    for tech_kind, sub in (("wind_onshore", onshore), ("solar", solar)):
        for zone, g in sub.groupby("gsp_group"):
            lat, lon = _wcentroid(g, "lat", "lon", "Capacity")
            if np.isnan(lat):
                continue
            rows.append(_row(tech_kind, zone, lat, lon))
    return pd.DataFrame(rows)


def offshore_sites() -> pd.DataFrame:
    reg = pd.read_excel(cfg.raw_dir() / CFG["stage1"]["cfd_register"])
    reg = reg[reg["technology_type"].astype(str).str.contains("Offshore", na=False)]
    reg = reg.dropna(subset=["latitude", "longitude"]).copy()
    reg_off = reg.rename(columns={"latitude": "lat", "longitude": "lon",
                                  "current_installed_capacity": "cap"})
    # gsp_group: register's authoritative value, else snap the coordinate.
    snap = gsp.tag_latlon(reg_off, "lat", "lon")
    reg_off["gsp_group"] = reg_off["gsp_group"].where(reg_off["gsp_group"].notna(),
                                                      snap["gsp_group"].values)

    repd_off = repd.operational_frame(YEAR, "offshore").rename(columns={"capacity_mw": "cap"})
    repd_off = repd_off.dropna(subset=["x_osgb", "y_osgb"])
    # REPD coords are OSGB; convert to lat/lon for ninja via a round-trip GeoDataFrame.
    import geopandas as gpd
    pts = gpd.GeoDataFrame(repd_off, geometry=gpd.points_from_xy(repd_off["x_osgb"], repd_off["y_osgb"]),
                           crs=gsp.REGION_CRS).to_crs(gsp.WGS84)
    repd_off["lat"], repd_off["lon"] = pts.geometry.y.values, pts.geometry.x.values
    repd_off = gsp.tag_osgb(repd_off, "x_osgb", "y_osgb")

    both = pd.concat([reg_off[["lat", "lon", "cap", "gsp_group"]],
                      repd_off[["lat", "lon", "cap", "gsp_group"]]], ignore_index=True)
    both["cap"] = pd.to_numeric(both["cap"], errors="coerce")
    rows = []
    for zone, g in both.groupby("gsp_group"):
        lat, lon = _wcentroid(g, "lat", "lon", "cap")
        if np.isnan(lat):
            continue
        rows.append(_row("wind_offshore", zone, lat, lon))
    return pd.DataFrame(rows)


def _row(kind: str, zone: str, lat: float, lon: float) -> dict:
    tech = {"wind_offshore": "offshore", "wind_onshore": "onshore", "solar": "solar"}[kind]
    return {"site": f"{tech}_{zone}", "kind": kind, "lat": lat, "lon": lon,
            "gsp_group": zone, "tech": tech, **DEFAULTS[kind]}


def main() -> None:
    sites = pd.concat([offshore_sites(), onshore_solar_sites()], ignore_index=True)
    cols = ["site", "kind", "lat", "lon", "hub_height_m", "turbine", "tilt", "azim",
            "gsp_group", "tech"]
    sites = sites[cols].sort_values(["tech", "gsp_group"]).reset_index(drop=True)
    out = cfg.reference_dir() / "ninja_sites_by_zone.csv"
    sites.to_csv(out, index=False)
    print(f"Built {len(sites)} per-zone sites (weighting year {YEAR}) -> {out.name}")
    print(sites.groupby("tech").size().to_dict())
    print(sites.to_string())


if __name__ == "__main__":
    sys.exit(main())
