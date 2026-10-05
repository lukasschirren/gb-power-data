# Reference tables

Small lookup tables the pipeline reads. They are tracked in git (see the allowlist in
`.gitignore`) because the pipeline cannot run without them; everything else in this folder is
ignored, including the credential files the pullers read (`*token*.txt`, `*credential*.txt`).

## Hand-curated: edit these, never regenerate them

| File | What it holds | Read by |
| --- | --- | --- |
| `plant_overrides.yaml` | data-quality corrections to the powerplantmatching roster | `build.stage1_tag_plants` |
| `cfd_overrides.yaml` | CfD assignments the stage-1 name matcher misses, or where one roster row bundles capacity across regimes or unbuilt phases | `build.stage1_tag_plants` |
| `benchmarks_{year}.csv` | published capacity by support regime, reported (not enforced) against stage 1 | `build.stage1_tag_plants` |
| `gsp_overrides.csv` | plants whose nearest-GSP snap is wrong (offshore farms) | `common.gsp`, `stage1_spatial_join`, `common.repd` |
| `cfd_round_params.csv` | contract terms per allocation round: negative-price rule, term, strike base year, reference prices, indexation | `build.build_cfd_status` |
| `tech_parameters.yaml` | per-technology efficiency, emission and cost parameters of the agent table | `build.stage3_build_agents` |
| `gsp_group_demand_weights.csv` | annual demand (GWh) per GSP group, the weights that split national demand | `build.stage2c_zone_demand` |
| `ninja_sites.csv` | national renewables.ninja reference sites | `pull.renninja_pull`, `pull.pecd_pull`, `build.pecd_build` |
| `bmu_crosswalk_overrides.yaml` | corrections to the Power Station Dictionary grouping (which BMUs hold a CfD at a shared site) | `scripts/build_bmu_crosswalk.py` |
| `wind_farm_map_overrides.csv` | wind BMU → REPD rows pinned by hand, each with its reason | `scripts/build_wind_farm_map.py` |

## Derived: tracked for convenience, rebuild when their inputs change

Each is cheap to store but needs large or slow inputs to rebuild (the FPN pull, the FUELHH series,
the PECD masks).

| File | Rebuilt by | Read by |
| --- | --- | --- |
| `bmu_crosswalk.csv`, `cfd_bmu_map.csv` | `python scripts/build_bmu_crosswalk.py` | `scripts/build_wind_farm_map.py` |
| `wind_farm_map.csv` | `python scripts/build_wind_farm_map.py` | `build.stage2d_wind_farms` |
| `ninja_sites_by_zone.csv` | `python -m gbpowerdata.pull.build_zone_sites` | `pull.renninja_pull --sites-file`, `build.stage2b_zone_cf` |
| `tech_flexibility_empirical.csv` | `python -m gbpowerdata.build.analyze_flexibility` | `build.stage3_build_agents` |
| `nuclear_availability_by_year.csv` | `python -m gbpowerdata.build.nuclear_availability` | `build.stage3_build_agents` |
| `nuts2_to_gsp_group_area_weights.csv` | `python -m gbpowerdata.common.pecd_regions --build-nuts2-gsp` | `common.pecd_regions`, `build.pecd_national_cf` |
| `pecd_onshore_zone_to_nuts2.csv`, `pecd_offshore_zone_to_nuts2.csv` | `python -m gbpowerdata.common.pecd_regions --build-wind-zones` | `build.pecd_build` |
