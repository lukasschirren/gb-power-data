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
| `thermal_parameters.csv` | operating and cost parameters of thermal plant (CCGT, OCGT, engines, coal, oil, nuclear, biomass, and the fuels' emission factors and NCV/GCV ratios) from 22 sources: one row per technology, class, parameter and source, with value, range, unit, basis (heating value, output, price year), region, locator (sheet and cell, or table and page), status (`transcribed`, `converted` for a unit change only, `derived` from data) and `gb_default` = `yes` on the recommended GB value; explained, with the comparison against PyPSA, in `docs/thermal_parameters.md` | `build.stage3_build_agents` (availability: NESO's de-rating factors); models read it; tests |
| `thermal_unit_efficiency.csv` | each GB gas, hard-coal and oil unit of the JRC Open Power Plants Database v1.00 (Zenodo record 3574566, CC BY 4.0): unit and plant EIC, names, capacity, type, commissioning year, net electrical efficiency as published (`eff`, OEM ratings conventionally LHV) and its `best_source` (OEM_derived, emissions_*_derived, Class_derived); stage 3 gives each CCGT station its units' OEM ratings, joined by EIC | `pull.jrc_ppdb_pull`, `build.thermal_unit_efficiency`; `build.stage3_build_agents`, tests |
| `thermal_station_bmu.csv` | each powerplantmatching thermal plant with BM units (`ppm_name`, `ppm_fueltype`) → its stations (one plant may hold two, Keadby and Keadby 2), each with technology and fuel (DUKES 5.11 where it differs: Killingholme, Peterborough and Glanford Brigg are single cycle, Indian Queens burns gas oil), commissioning year (DUKES 5.11, else powerplantmatching or the register), BM units (`bmu_ids`, `;`-separated; none for Roosecote, which has no generating unit), source and note; stage 3 sizes each station by its units' activity in the register (docs/AUDIT.md A7-8) | `build.stage3_build_agents`, tests |
| `thermal_parameter_sources.csv` | every source `thermal_parameters.csv` cites: id, publisher, title, date published, kind, URL, date accessed, licence | tests |
| `official_statistics.csv` | official totals the built tables are reconciled with: DESNZ (DUKES 2026: demand, wind and solar generation, pumped storage, grid-scale battery capacity), NESO's annual balancing services spend by service, LCCC's CfD net payments; one row per statistic, scope (UK or GB), period and year, with value, unit, publisher, title, URL, locator (sheet and cell, or the quoted sentence), licence, status (`verified`: read from the source by hand; `to verify`) and date checked | `checks.official`, `tests/realdata` |
| `investment_parameters.csv` | investment inputs published only in PDF reports, transcribed with locators: CEPA's 2025 hurdle rates for DESNZ (Table E.1 by technology, lithium batteries 8.90%; Table E.2's ranges by risk rating; the merchant uplift; Europe Economics' 2018 rates from its Table 5.24) and Mott MacDonald's 2018 storage costs for BEIS (lithium-ion for frequency response, 1 h, and for arbitrage, 4 h, and pumped hydro: capex, O&M, infrastructure and pre-development costs 2018-2050 in 2012 prices, round-trip efficiency, lifetime, cycle life); the columns of `investment_inputs.csv`, status `transcribed`, `converted` or `derived`; not packed (the reports' notices reserve their copyright: values cited, documents not passed on) | `processed.read_investment_inputs`, tests |
| `investment_parameter_sources.csv` | every source of `investment_parameters.csv` and `build.investment_inputs`: id, publisher, title, date published, kind, URL, date accessed, licence | `processed.read_investment_inputs`, tests |
| `rego_prices.csv` | REGO prices (GBP per certificate = GBP/MWh) as freely readable pages state them, 2018-2026: when observed, the vintage as stated and its generation months (`vintage_basis` `stated`, `inferred` from context, or `none`), technology, value or low-high (or a bound), `basis` (traded, bid, offer, auction average, forecast, approximate), source id, the quote as locator, status (`transcribed`, `converted` from pence, `derived` from words); e-POWER's e-REGO auction track record 2019-2024 and C-Zero's monthly reports 2023-2025 the main series; Argus's licensed assessments left out; not packed (the pages reserve their copyright: figures cited with their quotes) | `build.rego`, `processed.read_rego`, tests |
| `rego_price_sources.csv` | every page `rego_prices.csv` cites: id, publisher, title, date published, kind, URL (Internet Archive copies where the page is gone), date accessed, terms | `processed.read_rego`, tests |
| `rego_statistics.csv` | official figures of the REGO market by disclosure period (April to March): DESNZ's fuel mix disclosure data table 2014/15-2025/26 (loss factor, residual and UK fuel mix shares; final editions, older ones from the UK Government Web Archive) and the EU Guarantees of Origin Ofgem recognised for GB fuel mix disclosure 2015/16-2022/23; one row per statistic and period with value, unit, publisher, title, URL, locator, licence (OGL v3.0), status (`verified` against the document, `derived` where summed from Ofgem's workbooks) and date checked | `build.rego`, `processed.read_rego`, tests |
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
