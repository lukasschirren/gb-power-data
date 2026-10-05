# Hand-downloaded source data

Most of `data/raw/` is written by a puller in `src/gbpowerdata/pull/` and can be deleted and
re-fetched. The files below cannot: they were downloaded by hand (no API, a sign-in, or a one-off
request), so this note records where each came from. **Back them up**: `data/raw/` is not in git.
When you add a hand-downloaded source, record its URL, what was taken, when, and its gaps.

## Files the pipeline reads

Everything here is only needed to **re-run** the stages that read it: what the pipeline takes
from each file is already in the processed table named in the last column, which ships in the
processed data pack. The files themselves ship in the **inputs pack**
(`python -m gbpowerdata.datapack unpack gb-power-data_inputs_<date>.zip`), because most are
snapshots a source later replaces (REPD quarters, the live CfD register) and cannot be fetched
again at the same version.

| File (under `data/raw/`) | Source | Read by | Acquired | Captured in (processed) |
| --- | --- | --- | --- | --- |
| `CfD_Register_2026-05-22.xlsx` | LCCC CfD Register export (lowcarboncontracts.uk) | `build.stage1_tag_plants`, `stage1_spatial_join`, `stage3_build_agents`, `build_cfd_status`, `pull.build_zone_sites` (name set in `config.yaml`) | 22 May 2026 | `cfd_status`, `powerplants_tagged_{y}` |
| `repd_q1_2026.csv` | DESNZ Renewable Energy Planning Database, quarterly extract (gov.uk) | `common.repd` (any `repd_*.csv`; latest wins) | Q1 2026 | `cfd_status` (commissioning), `agents_{y}`, CF denominators |
| `espeni.csv` | ESPENI: reconciled half-hourly GB demand with embedded wind and solar (Wilson et al., Zenodo) | `build.stage2_build_timeseries` | May 2026 | `demand_{y}`, `capacity_factors_{y}` |
| `gis/gsp_regions_20220314.geojson` | NESO data portal, "GIS Boundaries for GB Grid Supply Points" (EPSG:27700) | `common.gsp` | — | `gsp_id`/`gsp_group` in `powerplants_located_{y}`, `agents_{y}` |
| `gis/dno_license_areas_20240503.geojson` | NESO data portal, "GIS Boundaries for GB DNO License Areas" | `common.gsp` | — | group names |
| `ofgem/cap_prelevelised_2026-05.xlsx` | Ofgem default tariff cap, pre-levelised rates model | `build.build_cap_tariff` | May 2026 | `cap_tariff_by_region` (complete) |
| `manual/dno_duos/` | DNO charging statements; see below | `build.build_duos_tariffs` | Jul 2026 | `duos_domestic_tariffs` (complete) |
| `manual/desnz_subnational/` | DESNZ subnational electricity consumption; see below | `build.build_subnational_domestic` | Aug 2026 | `domestic_supply_by_year` (complete) |

Three more inputs are **not** in the inputs pack:

| File (under `data/raw/`) | Source | Why not packed |
| --- | --- | --- |
| `powerplants.csv` | powerplantmatching (PyPSA) merged European plant roster, CC BY 4.0; stage 1 keeps the GB rows | `python -m gbpowerdata.pull.ppm_pull` downloads the pinned release (v0.8.1, byte-identical to the file used since May 2026) and verifies its checksum |
| `psd/ids.csv` | OSUKED Power Station Dictionary, MIT licence; see `../psd/PROVENANCE.md` | small, so it is tracked in git |
| `pecd/masks/ANCI_PE{ON,OF}-mask_PECD4.2_fv1.nc` | Copernicus CDS `sis-energy-pecd` region masks (240 MB; one-off request, see `common/pecd_regions.py`) | only rebuild the PECD weight tables, which are tracked in `data/reference/` |

Naming convention inside `manual/`: `<publisher>_<dataset>`, lowercase, underscores.

---

## `manual/dno_duos/`: Distribution Use of System charges

**161 files** across six DNO groups (`electricity_north_west`, `national_grid`,
`northern_powergrid`, `sp_energy_networks`, `ssen`, `uk_power_networks`), covering all
**14 licence areas**.

- **What**: "Schedule of charges and other tables" workbooks, one per licence area per charging
  year (April–March). The domestic tariff is in the `Annex 1 LV, HV and UMS charges` sheet (name
  varies by DNO): the row `Domestic Aggregated ...` gives red/amber/green unit charges (p/kWh) and
  a fixed charge (p/MPAN/day).
- **Why manual**: 14 licensees, 6 websites, no API, inconsistent formats and file names. Some
  files download with numeric names (Northern Powergrid) and carry their identity only inside the
  workbook, so always identify a file by its content.
- **Not included**: `embedded`/`IDNO` variants present in some folders are embedded-network
  tariffs, not the main schedule; the parser excludes them.

| Area | Years held | Gap |
| --- | --- | --- |
| `_A` East England, `_C` London, `_F` North East, `_J` South East, `_M` Yorkshire | 2017–2027 | — |
| `_G` North West | 2018–2027 | — |
| `_H` Southern, `_P` North Scotland (SSEN) | 2020–2027 | **2018–19** |
| `_D` N Wales & Mersey, `_N` South Scotland (SP Energy Networks) | 2021–2027 | **2018–20** |
| `_B` East Midlands, `_E` West Midlands, `_K` South Wales, `_L` South West (NGED) | 2022–2027 | **2018–21** |

The NGED gap is because pre-2022 statements are published under the **Western Power
Distribution** name; the others reflect each DNO's archive depth.

## `manual/desnz_subnational/`: subnational electricity consumption statistics

**1 file**: `Subnational_electricity_consumption_statistics_2005-2024.xlsx`.

- **What**: DESNZ National Statistics, "Subnational electricity consumption statistics 2005 to
  2024" (released 18 Dec 2025). One worksheet per year; the Great Britain total is row code
  `K03000001` ("Great Britain (inc unallocated)"). Gives, per year, domestic and non-domestic
  consumption (GWh) and meter counts (thousands). Scope is GB only (Northern Ireland excluded).
- **Source**: <https://www.gov.uk/government/collections/sub-national-electricity-consumption-data>
- **Gap**: the latest year is 2024; 2025 needs a back-cast.
- **Output**: `processed/domestic_supply_by_year.csv`.
