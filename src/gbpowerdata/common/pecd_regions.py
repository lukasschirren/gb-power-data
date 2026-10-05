"""PECD region weight tables: NUTS-2 <-> gsp_group (geometry) and PECD offshore zone -> NUTS-2
(hand-curated).

PECD v4.2 (`gbpowerdata.pull.pecd_pull`) delivers onshore wind, solar PV and temperature already
aggregated to NUTS-2 by the CDS server -- no weighting needed there. Two things still need a
weight table of our own:

  1. NUTS-2 -> gsp_group, so the same NUTS-2 output can be re-expressed at the ABM's own 14
     GSP-group zones (`gbpowerdata.common.gsp`) for the locational phase. This is pure geometry --
     computed ONCE from public boundary polygons, independent of PECD, tech or year -- so it is
     built here as an area overlay (same CRS/pattern as `gsp.py`'s point-in-polygon join, just
     polygon-polygon) and cached to a reference CSV rather than recomputed per run.
     `python -m gbpowerdata.common.pecd_regions --build-nuts2-gsp` writes it.

  2. PECD wind zone -> NUTS-2, for BOTH onshore and offshore wind. This was originally assumed to
     apply to offshore only (NUTS-2 was assumed to cover onshore server-side, the way it does for
     solar and temperature) -- the live CDS constraints endpoint corrected that: neither onshore
     nor offshore wind has a NUTS-2 (or SZOF) option in pecd4_2 at all, only PEON/P2ON and
     PEOF/P2OF energy zones, published at PECD's own bespoke GB split (`UK01`..`UK05`, `UKNI`
     onshore; 12 coastal sub-zones offshore) that isn't derivable from the zone CODE alone.

     The dataset itself publishes the fix: CDS's `peon_region_mask`/`peof_region_mask` variables
     (`gbpowerdata.pull.pecd_pull` doesn't fetch these -- see `build_wind_zone_nuts2_weights()`'s
     docstring for the one-off request) are NetCDFs with a `region` coordinate holding the real
     zone codes and a `mask(region, latitude, longitude)` array giving each 0.25 deg grid cell's
     FRACTIONAL coverage by that region (source: "DTU-PECD40-Polygons_VF20230127 by ENTSO-E" per
     the file's own attrs -- the official zone shapefile, rasterised). That's the authoritative
     geometry this module was missing; `build_wind_zone_nuts2_weights()` point-locates every
     nonzero cell into a NUTS-2 region (via `locate_nuts2()`, `within` then `nearest` for offshore
     cells with no land underneath) and mask-weight-sums per (zone, nuts2), which is how
     `data/reference/pecd_onshore_zone_to_nuts2.csv` / `..._offshore_zone_to_nuts2.csv` were
     actually built (`--build-wind-zones`), not hand-curated after all. `wind_zone_weights()`
     still loads and validates whatever ends up in those CSVs, and still raises (does not silently
     drop) if a zone code appears in a pull that the table doesn't cover -- the spatial analogue of
     the pipeline's "flag missing hours, never fill" rule -- in case PECD ever adds a zone.

Both weight tables have the same shape (`from_zone, nuts2, weight`, weights summing to 1 per
`from_zone`) so `reweight_wide()` applies either one, and so does the NUTS-2 -> gsp_group table.
"""

from __future__ import annotations

import sys

import pandas as pd

from gbpowerdata import config as cfg
from gbpowerdata.common import gsp

NUTS2_GSP_WEIGHTS_CSV = "nuts2_to_gsp_group_area_weights.csv"
ONSHORE_ZONE_WEIGHTS_CSV = "pecd_onshore_zone_to_nuts2.csv"
OFFSHORE_ZONE_WEIGHTS_CSV = "pecd_offshore_zone_to_nuts2.csv"
MASK_DIR = cfg.raw_dir() / "pecd" / "masks"
# region-mask filename -> (technology's onshore/offshore GB zone codes, weight-table CSV)
WIND_MASKS = {
    "onshore": ("ANCI_PEON-mask_PECD4.2_fv1.nc", ONSHORE_ZONE_WEIGHTS_CSV),
    "offshore": ("ANCI_PEOF-mask_PECD4.2_fv1.nc", OFFSHORE_ZONE_WEIGHTS_CSV),
}


def load_nuts2_regions_gb() -> "gpd.GeoDataFrame":  # noqa: F821 - geopandas imported lazily below
    """GB NUTS-2 polygons (code starts with 'UK') from the GISCO boundary file, reprojected to
    `gsp.REGION_CRS` so they overlay the GSP-group polygons directly."""
    import geopandas as gpd

    files = sorted(cfg.raw_dir().glob("gis/nuts2_boundaries_*.geojson"))
    if not files:
        sys.exit("No NUTS-2 boundary file; run `python -m gbpowerdata.pull.nuts_boundaries_pull` first.")
    g = gpd.read_file(files[-1])
    code_col = "NUTS_ID" if "NUTS_ID" in g.columns else "id"
    g = g.rename(columns={code_col: "nuts2"})[["nuts2", "geometry"]]
    g = g[g["nuts2"].astype(str).str.startswith("UK")].to_crs(gsp.REGION_CRS)
    g["geometry"] = g.geometry.buffer(0)
    return g.reset_index(drop=True)


def locate_nuts2(lons, lats) -> "np.ndarray":  # noqa: F821
    """NUTS-2 code for each (lon, lat) WGS84 point: `within` first, `nearest` for points with no
    land underneath (offshore grid cells) -- same two-step pattern as `gsp._locate()`."""
    import geopandas as gpd
    import numpy as np

    nuts2 = load_nuts2_regions_gb()
    pts = gpd.GeoDataFrame(geometry=gpd.points_from_xy(lons, lats), crs=gsp.WGS84).to_crs(gsp.REGION_CRS)
    within = gpd.sjoin(pts, nuts2, how="left", predicate="within")
    within = within[~within.index.duplicated(keep="first")]
    out = np.full(len(pts), None, dtype=object)
    hit = within["nuts2"].notna().to_numpy()
    out[hit] = within.loc[hit, "nuts2"].to_numpy()
    unmatched = np.flatnonzero(~hit)
    if len(unmatched):
        near = gpd.sjoin_nearest(pts.iloc[unmatched], nuts2, how="left")
        near = near[~near.index.duplicated(keep="first")]
        out[unmatched] = near["nuts2"].to_numpy()
    return out


def build_wind_zone_nuts2_weights(tech: str) -> pd.DataFrame:
    """Real ENTSO-E zone geometry, not a guess: CDS's `peon_region_mask`/`peof_region_mask`
    NetCDFs (`gbpowerdata.pull.pecd_pull` doesn't fetch these -- one-off, pulled directly with
    `cdsapi.Client().retrieve("sis-energy-pecd", {"pecd_version": ["pecd4_2"], "file_version":
    ["fv1"], "variable": ["peon_region_mask"]})`, ~34-86 MB, cache under `data/raw/pecd/masks/`
    after unzipping) give each 0.25 deg grid cell's FRACTIONAL coverage by every PECD zone. For
    every GB zone (region code starting "UK"), every cell with nonzero coverage is point-located
    into a NUTS-2 region (`locate_nuts2`, cell centre) and its mask fraction summed into that
    (zone, nuts2) pair -- so a zone straddling two NUTS-2 regions splits its weight by how much of
    its rasterised area falls in each, not by an arbitrary guess. Weights are renormalised to sum
    to 1 per zone (grid quantisation can leave the raw sum a little off 1.0)."""
    import xarray as xr

    nc_name, _ = WIND_MASKS[tech]
    path = MASK_DIR / nc_name
    if not path.exists():
        sys.exit(f"{path} missing -- pull the {tech} region mask first (see this function's "
                 f"docstring for the one-off cdsapi request).")
    ds = xr.open_dataset(path)
    gb_zones = [str(r) for r in ds["region"].values if str(r).startswith("UK")]

    rows = []
    for zone in gb_zones:
        cell = ds["mask"].sel(region=zone)
        nz = cell.where(cell > 0, drop=True).stack(cell=("latitude", "longitude")).dropna("cell")
        if nz.size == 0:
            continue
        lats = nz["latitude"].values
        lons = nz["longitude"].values
        weights = nz.values
        nuts2 = locate_nuts2(lons, lats)
        cell_df = pd.DataFrame({"nuts2": nuts2, "w": weights})
        per_nuts2 = cell_df.groupby("nuts2")["w"].sum()
        per_nuts2 = (per_nuts2 / per_nuts2.sum()).round(6)
        for n2, w in per_nuts2.items():
            rows.append({"pecd_zone": zone, "nuts2": n2, "weight": w})
    ds.close()
    return pd.DataFrame(rows).sort_values(["pecd_zone", "nuts2"]).reset_index(drop=True)


def build_nuts2_gsp_group_weights() -> pd.DataFrame:
    """Area-overlay NUTS-2 against the (dissolved) GSP-group polygons: for each NUTS-2 region,
    the share of its area falling in each gsp_group. Weights sum to 1 per nuts2 (regions with no
    GB land overlap, e.g. entirely-offshore slivers, are dropped -- offshore goes through the
    separate hand-curated table, not this geometric one)."""
    nuts2 = load_nuts2_regions_gb()
    groups = gsp.load_gsp_regions()[["gsp_group", "geometry"]].dissolve(by="gsp_group").reset_index()

    overlay = nuts2.overlay(groups, how="intersection", keep_geom_type=False)
    overlay["area"] = overlay.geometry.area
    totals = overlay.groupby("nuts2")["area"].transform("sum")
    overlay["weight"] = (overlay["area"] / totals).round(6)
    out = overlay[["nuts2", "gsp_group", "weight"]].sort_values(["nuts2", "gsp_group"])
    return out.reset_index(drop=True)


def nuts2_gsp_group_weights() -> pd.DataFrame:
    path = cfg.reference_dir() / NUTS2_GSP_WEIGHTS_CSV
    if not path.exists():
        sys.exit(f"{path} missing; run `python -m gbpowerdata.common.pecd_regions --build-nuts2-gsp`.")
    return pd.read_csv(path)


def _wind_zone_weights(csv_name: str, zone_col: str, zone_codes: list[str]) -> pd.DataFrame:
    """Load a hand-curated wind zone -> NUTS-2 table and check it covers every zone code actually
    present in a pull. Raises (does not drop rows) on any uncovered zone or a bad weight sum."""
    path = cfg.reference_dir() / csv_name
    if not path.exists():
        sys.exit(f"{path} missing; see its header comment for how to fill it in.")
    w = pd.read_csv(path, comment="#")
    missing = sorted(set(zone_codes) - set(w[zone_col]))
    if missing:
        sys.exit(f"{path.name} has no mapping for wind zone(s) {missing}; add a row per zone "
                 f"(weights summing to 1 across the NUTS-2 codes it should split into) before "
                 f"building capacity factors for it.")
    # Tolerance, not exact equality: grid-cell quantisation in the mask-derived tables
    # (build_wind_zone_nuts2_weights) leaves residuals of a few 1e-6 after rounding.
    sums = w.groupby(zone_col)["weight"].sum()
    bad = sums[(sums - 1.0).abs() > 1e-3]
    if not bad.empty:
        sys.exit(f"{path.name}: weights per {zone_col} must sum to 1.0 (+/-0.001), got {bad.to_dict()}")
    return w[[zone_col, "nuts2", "weight"]]


def onshore_zone_weights(zone_codes: list[str]) -> pd.DataFrame:
    return _wind_zone_weights(ONSHORE_ZONE_WEIGHTS_CSV, "pecd_onshore_zone", zone_codes)


def offshore_zone_weights(zone_codes: list[str]) -> pd.DataFrame:
    return _wind_zone_weights(OFFSHORE_ZONE_WEIGHTS_CSV, "pecd_offshore_zone", zone_codes)


def reweight_wide(wide: pd.DataFrame, weights: pd.DataFrame, from_col: str, tech_suffix: str) -> pd.DataFrame:
    """Re-express a wide {from_zone}_{tech} CF frame at the target zone in `weights` (columns
    `from_col`, target zone, `weight`). Capacity factor is intensive, so combining more than one
    source zone into the same target is a WEIGHTED AVERAGE (sum(w*v)/sum(w)), never a weighted
    sum -- a plain sum would double-count wherever two source zones share a target. `wide` is
    indexed by time; its columns are `f"{zone}_{tech_suffix}"` for zone in weights[from_col]."""
    target_col = [c for c in weights.columns if c not in (from_col, "weight")][0]
    long = wide.melt(ignore_index=False, var_name="col", value_name="value").reset_index()
    time_col = long.columns[0]
    long["zone"] = long["col"].str.removesuffix(f"_{tech_suffix}")
    merged = long.merge(weights.rename(columns={from_col: "zone"}), on="zone", how="inner")
    merged["weighted"] = merged["value"] * merged["weight"]
    grouped = merged.groupby([time_col, target_col])
    out = (grouped["weighted"].sum() / grouped["weight"].sum()).unstack(target_col)
    out.columns = [f"{c}_{tech_suffix}" for c in out.columns]
    return out


def main(argv: list[str]) -> None:
    if "--build-nuts2-gsp" in argv:
        w = build_nuts2_gsp_group_weights()
        out = cfg.reference_dir() / NUTS2_GSP_WEIGHTS_CSV
        w.to_csv(out, index=False)
        print(f"Saved {len(w)} rows ({w['nuts2'].nunique()} NUTS-2 x "
              f"{w['gsp_group'].nunique()} gsp_group) -> {out.name}")
    elif "--build-wind-zones" in argv:
        for tech, (_, csv_name) in WIND_MASKS.items():
            w = build_wind_zone_nuts2_weights(tech)
            zone_col = f"pecd_{tech}_zone"
            w = w.rename(columns={"pecd_zone": zone_col})
            w["basis"] = "ENTSO-E PECD region mask (0.25deg fractional coverage), area-weighted onto NUTS-2"
            w["note"] = ""
            out = cfg.reference_dir() / csv_name
            w.to_csv(out, index=False)
            print(f"Saved {len(w)} rows ({w[zone_col].nunique()} {tech} zones x "
                  f"{w['nuts2'].nunique()} NUTS-2) -> {out.name}")
    else:
        print(__doc__)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
