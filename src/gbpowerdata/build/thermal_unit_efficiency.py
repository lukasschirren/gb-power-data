"""Each GB thermal unit's net electrical efficiency from the JRC Open Power Plants Database, for stage 3's station
efficiencies -> data/reference/thermal_unit_efficiency.csv (tracked; a small table derived from a slow-to-fetch source).

WHY. Stage 3 used to give a gas plant without a measured efficiency the median of JRC's GB CCGT units commissioned in the
same period (tech_parameters.yaml efficiency_vintage). The medians get the fleet's level right (0.477 GCV against the
curve's 0.479 on the 2025 CCGTs) but not which plant is the more efficient: across the 21 2025 CCGT stations with a
manufacturer's rating the two rank the stations with a correlation of 0.29 (26 Oct 2026). Peterhead, dated 1980 by
DUKES and clamped to the curve's oldest anchor, sat at 0.414 against its rating's 0.486; Marchwood and Severn at
powerplantmatching's 0.58 LHV against their ratings' 0.54. Each station's own rating fixes the order within the gas
stack, which decides which plant and which trader runs.

THE TABLE. One row per GB unit of JRC_OPEN_UNITS.csv (country United Kingdom, unit EIC issued in GB, prefix 48W:
Northern Ireland's units, 47W, are on the island of Ireland's market, outside the model) of type Fossil Gas, Fossil
Hard coal or Fossil Oil: eic_g (the unit's EIC, as Elexon's register carries it), eic_p, name_g, name_p, capacity_g (MW), type_g,
year_commissioned, eff (net electrical efficiency as JRC publishes it; OEM ratings are conventionally on the lower
heating value, LHV) and best_source. JRC v1.00 dates from December 2019, so units commissioned since (Keadby 2,
Hirwaun, Spalding's expansion) are not in it.

HOW STAGE 3 USES IT (gbpowerdata.build.stage3_build_agents, THERMAL PLANT WITH BM UNITS). A CCGT station takes the
capacity-weighted mean of its units' OEM_derived efficiencies, joined by EIC, put on the gross basis of the gas price by
tech_parameters.yaml's ppm_efficiency_basis_factor (0.900); a station without one keeps the vintage curve. JRC types
every unit Fossil Gas and cannot tell open from combined cycle, so open-cycle stations (DUKES single cycle) keep the
open-cycle curve; class-derived values are a class's typical figure and emissions-derived ones an annual average with
part load, so neither replaces the curve.

Usage:  python -m gbpowerdata.build.thermal_unit_efficiency      (after pull.jrc_ppdb_pull)
Source: JRC-PPDB-OPEN v1.00 (Zenodo record 3574566), CC BY 4.0; thermal_parameter_sources.csv id jrc-ppdb-open.
"""

from __future__ import annotations

import sys
import zipfile

import pandas as pd

from gbpowerdata import config as cfg
from gbpowerdata.pull import jrc_ppdb_pull as J

TYPES = ("Fossil Gas", "Fossil Hard coal", "Fossil Oil")
GB_EIC = "48W"                     # the GB issuing office's EIC prefix (docstring, THE TABLE)
COLUMNS = ["eic_g", "eic_p", "name_g", "name_p", "capacity_g", "type_g", "year_commissioned", "eff", "best_source"]
OUT = "thermal_unit_efficiency.csv"


def _member(z: zipfile.ZipFile, name: str) -> str:
    hits = [n for n in z.namelist() if n.endswith(name)]
    if len(hits) != 1:
        raise FileNotFoundError(f"{name}: {len(hits)} entries in {J.FILE}")
    return hits[0]


def build() -> pd.DataFrame:
    path = J.out_path()
    if not path.exists():
        sys.exit(f"{path} missing: run python -m gbpowerdata.pull.jrc_ppdb_pull")
    with zipfile.ZipFile(path) as z:
        units = pd.read_csv(z.open(_member(z, "JRC_OPEN_UNITS.csv")))
        perf = pd.read_csv(z.open(_member(z, "JRC_OPEN_PERFORMANCE.csv")))
    d = units[units["country"].eq("United Kingdom") & units["type_g"].isin(TYPES)
              & units["eic_g"].astype(str).str.startswith(GB_EIC)]
    # keyed on the plant and unit EIC together: units without a unit EIC (none in GB) repeat a blank eic_g
    d = d.merge(perf[["eic_p", "eic_g", "eff", "best_source"]], on=["eic_p", "eic_g"], how="left", validate="1:1")
    d = d[COLUMNS].sort_values(["type_g", "name_p", "name_g"]).reset_index(drop=True)
    if d["eic_g"].duplicated().any():
        raise ValueError("thermal_unit_efficiency: a unit EIC appears twice")
    return d


def main() -> None:
    d = build()
    out = cfg.reference_dir() / OUT
    d.to_csv(out, index=False)
    print(f"{len(d)} GB thermal units -> {out}")
    print(d.groupby(["type_g", "best_source"], dropna=False).size().to_string())


if __name__ == "__main__":
    main()
