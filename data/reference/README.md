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
| `company_groups.csv` | a company name a register uses → its group, and `same_as`, the name of the same legal entity in `company_owners.csv`; each row with its source | `common.companies`, `build.build_ownership` |
| `company_owners.csv` | joint ventures and sales: owners with shares, the operator, validity dates, sources (ids into `ownership_sources.csv`), evidence, status (`verified`, `partly verified`, `to verify`, `judgement`) and the date checked, keyed `company:<name>` or `station:<station>`; listed with its evidence in `docs/ownership_references.md` (`python -m gbpowerdata.common.companies --references` after an edit) | `common.companies`, `build.build_ownership` |
| `ownership_sources.csv` | every source `company_owners.csv`, `bmu_lead_parties.csv` and `bmu_left_register.csv` cite: id, publisher, title, date published, kind, URL, date accessed | `common.companies` (the reference document), tests |
| `bmu_lead_parties.csv` | documented lead parties of a BM unit over a period, where the kept register snapshots do not cover the date; columns of evidence as `company_owners.csv`. So far the units of `bmu_left_register.csv`, whose lead parties no kept snapshot names: the company that trades the group's other thermal units, or the station's own company (status `judgement`) | `common.companies`, `build.build_ownership` |
| `bmu_left_register.csv` | the BM units that left Elexon's register before its first kept snapshot (5 Jun 2026): Elexon and National Grid ids and EIC (the Power Station Dictionary), fuel type, the unit's share of the station's DUKES 5.11 capacity, documented closure, sources (ids into `ownership_sources.csv`), evidence, the date checked; their notifications are cut from Elexon's all-units stream by `pull.fpn_left_register_pull`, which also scans for the units it lacks | `build.bm_units`, `pull.fpn_left_register_pull`, tests |
| `dukes_bmu_map.csv` | the main gas, coal, nuclear, pumped-storage and biomass stations: DUKES site pattern, technology class, BM units | `build.build_ownership` |
| `crown_estate_farms.csv` | The Crown Estate's farm names (one row per spelling; matched without case, accents and punctuation) -> the company under which `company_owners.csv` keys the farm, with the register that names that company | `build.build_crown_estate`, tests |
| `thermal_parameters.csv` | operating and cost parameters of thermal plant (CCGT, OCGT, engines, coal, oil, nuclear, biomass, and the fuels' emission factors and NCV/GCV ratios) from 22 sources: one row per technology, class, parameter and source, with value, range, unit, basis (heating value, output, price year), region, locator (sheet and cell, or table and page), status (`transcribed`, `converted` for a unit change only, `derived` from data) and `gb_default` = `yes` on the recommended GB value; explained, with the comparison against PyPSA, in `docs/thermal_parameters.md` | no stage yet (models read it); tests |
| `thermal_parameter_sources.csv` | every source `thermal_parameters.csv` cites: id, publisher, title, date published, kind, URL, date accessed, licence | tests |
| `official_statistics.csv` | official totals the built tables are reconciled with: DESNZ (DUKES 2026: demand, wind and solar generation, pumped storage, grid-scale battery capacity), NESO's annual balancing services spend by service, LCCC's CfD net payments; one row per statistic, scope (UK or GB), period and year, with value, unit, publisher, title, URL, locator (sheet and cell, or the quoted sentence), licence, status (`verified`: read from the source by hand; `to verify`) and date checked | `checks.official`, `tests/realdata` |
| `investment_parameters.csv` | investment inputs published only in PDF reports, transcribed with locators: CEPA's 2025 hurdle rates for DESNZ (Table E.1 by technology, lithium batteries 8.90%; Table E.2's ranges by risk rating; the merchant uplift; Europe Economics' 2018 rates from its Table 5.24) and Mott MacDonald's 2018 storage costs for BEIS (lithium-ion for frequency response, 1 h, and for arbitrage, 4 h, and pumped hydro: capex, O&M, infrastructure and pre-development costs 2018-2050 in 2012 prices, round-trip efficiency, lifetime, cycle life); the columns of `investment_inputs.csv`, status `transcribed`, `converted` or `derived`; not packed (the reports' notices reserve their copyright: values cited, documents not passed on) | `processed.read_investment_inputs`, tests |
| `investment_parameter_sources.csv` | every source of `investment_parameters.csv` and `build.investment_inputs`: id, publisher, title, date published, kind, URL, date accessed, licence | `processed.read_investment_inputs`, tests |
| `companies_house_numbers.csv` | the companies whose persons with significant control are pulled: Companies House number (eight characters as text: zero-padded, prefixes such as SC kept), the register's name, why it is listed; seeded 6 Oct 2026 with the 183 CfD counterparties of at least 30 MW that resolve to themselves | `pull.companies_house_pull`, `common.company_control` (a company's number by its name) |

**Local only, never committed:** `crown_estate_ownership_reports.csv`, The Crown Estate's operational
offshore wind ownership tables at the ends of 2018, 2019 and 2020, transcribed by hand from its offshore wind
operational reports (`ce-2018`, `ce-2019`, `ce-2020` in `ownership_sources.csv`): as_at, section, farm,
operator, holder (the full name, completed from the table's footnote where the bar cuts it short),
holder_printed (the label as printed, with its footnote marker), share_pct, source_id, page. The Crown
Estate's terms allow own use only and forbid passing digital copies to third parties, so `.gitignore` keeps it
out; `build.build_crown_estate` reads it where it exists, and the tables can be transcribed again from the
reports the source ids cite.

## Derived: tracked for convenience, rebuild when their inputs change

Each is cheap to store but needs large or slow inputs to rebuild (the FPN pull, the FUELHH series,
the PECD masks).

| File | Rebuilt by | Read by |
| --- | --- | --- |
| `bmu_crosswalk.csv`, `cfd_bmu_map.csv` | `python scripts/build_bmu_crosswalk.py` | `scripts/build_wind_farm_map.py` |
| `wind_farm_map.csv` | `python scripts/build_wind_farm_map.py` | `build.stage2d_wind_farms` |
| `ninja_sites_by_zone.csv` | `python -m gbpowerdata.pull.build_zone_sites` | `pull.renninja_pull --sites-file`, `build.stage2b_zone_cf` |
| `tech_flexibility_empirical.csv` | `python -m gbpowerdata.build.analyze_flexibility` | `build.stage3_build_agents` |
| `bm_dynamic_by_tech.csv` | `python -m gbpowerdata.build.bm_dynamic --pull` | the GB rows of `thermal_parameters.csv` (a test checks they agree) |
| `nuclear_availability_by_year.csv` | `python -m gbpowerdata.build.nuclear_availability` | `build.stage3_build_agents` |
| `nuts2_to_gsp_group_area_weights.csv` | `python -m gbpowerdata.common.pecd_regions --build-nuts2-gsp` | `common.pecd_regions`, `build.pecd_national_cf` |
| `pecd_onshore_zone_to_nuts2.csv`, `pecd_offshore_zone_to_nuts2.csv` | `python -m gbpowerdata.common.pecd_regions --build-wind-zones` | `build.pecd_build` |
