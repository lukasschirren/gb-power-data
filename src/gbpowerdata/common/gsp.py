"""GSP / GSP-Group geolocation helper.

Locates any point (a power plant) inside Britain's Grid Supply Point regions and
returns both the fine ``gsp_id`` (~330 GSP regions) and the coarse 14-zone
``gsp_group`` (``_A``..``_P``). This is the spatial backbone of the locational
phase: the copperplate panel is unchanged, but every agent can now be tagged to a
zone, and gsp_id -> gsp_group is a lossless rollup (the demand/CF series live at
the 14-group level for now; refining to per-GSP needs no re-tagging).

Geometry source (free, gitignored under data/raw/gis/):
  - GSP regions   : NESO "GIS Boundaries for GB Grid Supply Points" (EPSG:27700),
                    one polygon per GSP region carrying ``GSPs`` + ``GSPGroup``.
  - DNO areas     : NESO "GIS Boundaries for GB DNO Licence Areas" (14 polygons,
                    ``Name`` = _A.._P) — used only for friendly group names.

Offshore / coastal plants fall in the sea where no GSP polygon covers them; they
connect at an *onshore* GSP, so unmatched points snap to the NEAREST region
(``located_method == "nearest"``). Genuinely wrong snaps (offshore farms whose
nearest land GSP isn't the real connection) are correctable via
data/reference/gsp_overrides.csv without touching this code.
"""

from __future__ import annotations

from functools import lru_cache

import geopandas as gpd
import pandas as pd

from gbpowerdata import config as cfg

REGION_CRS = "EPSG:27700"   # OSGB36 British National Grid (NESO native)
WGS84 = "EPSG:4326"


@lru_cache(maxsize=1)
def load_gsp_regions() -> gpd.GeoDataFrame:
    """~330 GSP region polygons with gsp_id (GSPs) + gsp_group (GSPGroup)."""
    path = sorted(cfg.raw_dir().glob("gis/gsp_regions_*.geojson"))[-1]
    g = gpd.read_file(path)
    g = g.rename(columns={"GSPs": "gsp_id", "GSPGroup": "gsp_group"})
    g = g[["gsp_id", "gsp_group", "geometry"]].to_crs(REGION_CRS)
    g["geometry"] = g.geometry.buffer(0)  # repair any self-intersections
    return g.reset_index(drop=True)


@lru_cache(maxsize=1)
def load_dno_areas() -> gpd.GeoDataFrame:
    """14 DNO licence-area polygons; Name = _A.._P, with friendly Area/DNO names."""
    path = sorted(cfg.raw_dir().glob("gis/dno_license_areas_*.geojson"))[-1]
    d = gpd.read_file(path).rename(columns={"Name": "gsp_group"})
    return d[["gsp_group", "Area", "DNO", "DNO_Full", "geometry"]].to_crs(REGION_CRS)


@lru_cache(maxsize=1)
def group_names() -> dict:
    """_A.._P -> human-readable licence-area name (e.g. 'East England')."""
    d = load_dno_areas()
    return dict(zip(d["gsp_group"], d["Area"]))


def _locate(pts: gpd.GeoDataFrame) -> pd.DataFrame:
    """Point-in-polygon against GSP regions; unmatched points snap to nearest.

    Returns a frame aligned to `pts.index` with gsp_id, gsp_group, located_method
    ('within' | 'nearest' | 'missing' when the point has no geometry).
    """
    regions = load_gsp_regions()
    # Keep geometry only so caller columns (e.g. an existing gsp_group) don't
    # collide with the region attributes during the spatial join.
    pts = gpd.GeoDataFrame(geometry=pts.geometry, crs=pts.crs)
    valid = pts.geometry.notna() & ~pts.geometry.is_empty

    out = pd.DataFrame(index=pts.index,
                       data={"gsp_id": pd.NA, "gsp_group": pd.NA, "located_method": "missing"})

    sub = pts[valid]
    if sub.empty:
        return out

    within = gpd.sjoin(sub, regions, how="left", predicate="within")
    # A point on a shared border can match >1 region; keep the first.
    within = within[~within.index.duplicated(keep="first")]
    hit = within["gsp_id"].notna()
    out.loc[within.index[hit], ["gsp_id", "gsp_group"]] = within.loc[hit, ["gsp_id", "gsp_group"]].values
    out.loc[within.index[hit], "located_method"] = "within"

    unmatched = within.index[~hit]
    if len(unmatched):
        near = gpd.sjoin_nearest(sub.loc[unmatched], regions, how="left")
        near = near[~near.index.duplicated(keep="first")]
        out.loc[near.index, ["gsp_id", "gsp_group"]] = near[["gsp_id", "gsp_group"]].values
        out.loc[near.index, "located_method"] = "nearest"
    return out


_LOC_COLS = ["gsp_id", "gsp_group", "located_method"]


def _join_location(df: pd.DataFrame, pts: gpd.GeoDataFrame) -> pd.DataFrame:
    """Attach _locate() output, overwriting any pre-existing location columns."""
    return df.drop(columns=[c for c in _LOC_COLS if c in df.columns]).join(_locate(pts))


def tag_latlon(df: pd.DataFrame, lat: str = "lat", lon: str = "lon") -> pd.DataFrame:
    """Return df with gsp_id, gsp_group, located_method from WGS84 lat/lon."""
    lonv = pd.to_numeric(df[lon], errors="coerce")
    latv = pd.to_numeric(df[lat], errors="coerce")
    geom = gpd.points_from_xy(lonv, latv)
    pts = gpd.GeoDataFrame(df.copy(), geometry=geom, crs=WGS84).to_crs(REGION_CRS)
    return _join_location(df, pts)


def tag_osgb(df: pd.DataFrame, x: str = "X-coordinate", y: str = "Y-coordinate") -> pd.DataFrame:
    """Return df with gsp_id, gsp_group, located_method from OSGB easting/northing."""
    xv = pd.to_numeric(df[x], errors="coerce")
    yv = pd.to_numeric(df[y], errors="coerce")
    pts = gpd.GeoDataFrame(df.copy(), geometry=gpd.points_from_xy(xv, yv), crs=REGION_CRS)
    return _join_location(df, pts)


def apply_overrides(df: pd.DataFrame, key_col: str) -> pd.DataFrame:
    """Pin specific rows to a zone via data/reference/gsp_overrides.csv.

    CSV columns: match_col, match_value, gsp_id, gsp_group. For each row, set the
    zone where df[match_col] == match_value (substring, case-insensitive). Lets
    offshore farms that snap to the wrong onshore GSP be corrected by name.
    """
    path = cfg.reference_dir() / "gsp_overrides.csv"
    if not path.exists():
        return df
    ov = pd.read_csv(path, keep_default_na=False, na_values=[""])
    df = df.copy()
    for _, o in ov.iterrows():
        col = o["match_col"]
        if col not in df.columns:
            continue
        m = df[col].astype(str).str.contains(str(o["match_value"]), case=False, na=False)
        if not m.any():
            continue
        if pd.notna(o.get("gsp_id")):
            df.loc[m, "gsp_id"] = o["gsp_id"]
        if pd.notna(o.get("gsp_group")):
            df.loc[m, "gsp_group"] = o["gsp_group"]
        df.loc[m, "located_method"] = "override"
    return df
