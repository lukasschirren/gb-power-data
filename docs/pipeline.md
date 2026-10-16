# Pipeline map

Every stage, in the order a fresh machine runs them, with what each reads and writes. Paths are
relative to `data/` (or wherever `config.yaml` / `GBPOWERDATA_CONFIG` points). Each module's
docstring has the method, the source quirks it handles, and its full CLI.

```text
 sources ──pull──► raw/ (immutable snapshots) ──build──► processed/ (per-year panels)
                     ▲                           ▲
         manual downloads (raw/manual, ...)      reference/ (overrides, crosswalks, weights)
```

## 1. Pull: source to `raw/`

`raw/` holds source snapshots: build stages only read it. Sizes are for the full 2016–2025 window.

| Module (`python -m gbpowerdata.pull.<x>`) | Source | Access | Writes | Size |
| --- | --- | --- | --- | --- |
| `elexon_pull` | Elexon BMRS: MID (APX), FUELHH, ITSDO, INDO, INDOD, BM-unit register | free | `raw/{mid_apx,fuelhh,itsdo,indo,indod}_*.csv`, `raw/bm_units_*.csv` | ~0.3 GB |
| `system_price_pull` | Elexon: cash-out price, NIV, accepted volumes | free | `raw/system_prices/` | 28 MB |
| `forecast_pull` | Elexon + NESO D-1 forecasts (WINDFOR, DGWS, NDF, MELNGC, INDGEN, LOLPDRM, SYSWARN, embedded wind/solar) | free | `raw/forecasts/` | 0.3 GB |
| `fpn_pull [--storage-fleet]` | Elexon per-unit physical notifications; `--storage-fleet`: every unit of `storage_fleet` with an Elexon id, its supplier (2__) and virtual lead party (V__) batteries included | free, slow (per unit) | `raw/fpn/{bmu}.csv` | 3.6 GB |
| `fpn_left_register_pull [--pull-only \| --cut-only]` | Elexon's all-units physical notifications, a day a request, Mar 2016 to Mar 2020: the units no kept register snapshot holds (the per-unit queries return nothing for them), cut to FPN files for the units of `reference/bmu_left_register.csv` (Cottam, Aberthaw B, Eggborough, Deeside), and a scan of every unregistered unit with output; `--sample`: an hour a week to 2025, the check of the later years | free, about 35 s a month | `raw/fpn_unregistered/{YYYY-MM}.csv.gz`, `raw/fpn/{bmu}.csv` of those units, `raw/fpn_left_register.csv`, `bmu_unregistered_scan.csv`, `bmu_unregistered_sample.csv` | 20 MB (49 months); 0.6 MB a day transferred |
| `elexon_bod_pull` | Elexon per-unit bid-offer data and acceptances | free, slow | `raw/bod/`, `raw/boalf/` | 4.5 GB |
| `b1610_pull [--units BMU ...]` | Elexon per-unit metered generation: the register's thermal T_ units, or the named units (the embedded CCGTs: E_SHOS-1, E_GYAR-1, E_KLYN-A-1, E_PETEM1, E_CORB-1, E_FAWN-1, E_FELL-1, E_BRGG-1) | free, slow | `raw/b1610/` | 0.6 GB; 5 MB a unit for 2019-2025 |
| `mels_pull` | Elexon MEL/PN/BOD for chosen days | free | `raw/mels/` | 0.2 GB |
| `bm_dynamic_pull [dates] [--sp 24]` | Elexon BM dynamic data of every unit at one settlement period (SEL, SIL, run-up and run-down rates, NDZ, NTO, NTB, MZT, MNZT, MDV, MDP) with its MEL and PN; default the 15th of Jan, Apr, Jul and Oct 2018–2025; `--submissions [DATASET ...]`: every submission of the named dynamic datasets since Sep 2016, by month (default MDV and MDP; MZT, MNZT, NDZ, SEL, RURE, RDRE for thermal plant's minimum times, notice, stable level and run rates; supplier and virtual lead party units included) | free | `raw/bm_dynamic/{dynamic,rates,mels,pn}_{date}_sp{sp}.csv`, `submissions_{dataset}_{YYYY-MM}.csv` | ~0.5 MB a date; submissions since Sep 2016: MDV and MDP 0.3 MB each, MZT, MNZT, NDZ, SEL, RURE, RDRE 4-25 MB each |
| `lccc_pull` (+ `--levy`) | LCCC CfD portal (CKAN): register status, CfD↔BMU map, actual generation and payments, strike prices, levy rates, the hourly IMRP, the Capacity Market's obligations and payments by auction and month | free | `raw/lccc/` | 20 MB |
| `ons_pull` | ONS time series: the CPI index (D7BT, 2015=100), for the Capacity Market's indexation | free | `raw/ons/cpi_index_d7bt.csv` | 20 kB |
| `cost_data_pull [names] [--force]` | DESNZ Electricity Generation Costs 2020, 2023 and 2025 (key data and assumptions, Annex A) the Danish Energy Agency's Technology Data for Energy Storage datasheet, and NREL's ATB 2021-2025 (streamed, cut to utility-scale batteries) | free | `raw/cost_data/{egc2020_key_data_and_assumptions,egc2023_annex_a,egc2025_annex_a}.xlsx`, `dea_technology_data_energy_storage_v{version}.xlsx`, `atb_{edition}[_v{version}]_utility_battery.csv` | 4 MB (0.6 GB streamed) |
| `neso_pull [demand]` | NESO data portal: BSUoS, AAHEDC, TNUoS; `demand`: the historic demand data, one file per year from 2016 (national and transmission demand, embedded wind and solar, pumping, every interconnector's flow, non-BM STOR, per settlement period) | free | `raw/neso/`, `raw/neso/historic_demand_{year}.csv` | 18 MB; demand 1.3-1.8 MB a year |
| `cm_register_pull` | NESO Capacity Market register: every CM unit and its components (applicant, parent company, technology, capacities, agreements, traded obligations), and the auction results (clearing price, base period, capacity awarded) and de-rating factors; the trading contacts' columns are dropped | free | `raw/neso/cm_register/{cmu,components,auction_static,auction_capacity_cost,derating_factors}_{date}.csv` | 16 MB |
| `ancillary_pull [--list]` | NESO data portal: unit-level results of the monthly FFR tenders (post-tender reports TR108-TR166, for January 2019 to November 2023), the weekly FFR auctions (Dec 2019–Nov 2021), Dynamic Containment (tenders 2020–21, auctions 2021–23), the Enduring Auction Capability (response, quick, slow and balancing reserve, from Nov 2023), Balancing Reserve (2024–25), Static FFR (from Apr 2023) and STOR's daily auctions with their committed windows (from Apr 2021): MW, price and the company that bid, per unit and period; and gov.uk's bank holidays | free | `raw/neso/ancillary/{stem}.csv` (an archive once; a resource NESO still updates under the pull date; the FFR reports as published, `ffr_post_tender_tr{nnn}[_amended].{xlsx,xlsm,csv}`), `raw/govuk/bank_holidays.json` | 0.7 GB |
| `ebocf_pull [--dataset volumes] [--start YYYY-MM --end YYYY-MM]` | Elexon: indicative BM cashflows (EBOCF) of the battery and pumped storage units, per settlement period: the register's T_ and E_ units and `storage_fleet`'s supplier and virtual lead party batteries; a month on disk is pulled again only for the units its `.units` list lacks; `--dataset volumes`: their accepted volumes (DISPTAV, the "Original" data type) | free, ~1 min a month | `raw/ebocf/ebocf_{YYYY-MM}.csv`, `raw/bm_volumes/bm_volumes_{YYYY-MM}.csv`, each with its `.units` list | 0.2 GB; volumes 0.16 GB |
| `dukes_pull` | DESNZ DUKES 5.11, power stations in the UK (one sheet per edition), found through the gov.uk content API | free | `raw/dukes/DUKES_5.11_{edition}.xlsx` | 1 MB |
| `crown_estate_pull` (+ `--archived`) | The Crown Estate's offshore wind farm ownership tables (operator or lead developer, holders and shares; earlier years from the Internet Archive's captures), one file per as-at date | free; The Crown Estate's terms: own use only, never packed | `raw/crown_estate/wind_farm_ownership_{YYYYMMDD}.html` | 0.1 MB a page |
| `companies_house_pull [--follow 2]` | Companies House: profile and persons with significant control (ceased ones included) of the companies in `reference/companies_house_numbers.csv`, and with `--follow` their UK-registered corporate controllers; an individual is kept only as its kind, natures of control and dates | free key | `raw/companies_house/{YYYYMMDD}/{number}.json` | <5 MB |
| `ofgem_pull` | Ofgem price-cap annexes (scraped from the levels page) | free | `raw/ofgem/` | ~0.4 GB |
| `octopus_pull` | Octopus Agile and standard variable tariffs | free | `raw/octopus/` | 0.4 GB |
| `entsoe_pull`, `entsoe_capacity_pull` | ENTSO-E Transparency: neighbour day-ahead prices, interconnector NTC | free token | `raw/entsoe/` | 0.6 GB |
| `gas_pull` | ONS System Average Price of gas (daily) | free | `raw/gas_sap_daily.csv` | <1 MB |
| `carbon_pull` | EEX EUA (2018–20) and gov.uk UKA auctions (2021+) | free | `raw/carbon_monthly.csv` | <1 MB |
| `coal_pull` | World Bank Pink Sheet coal | free | `raw/coal_monthly.csv` | <1 MB |
| `fx_pull` | ECB EUR→GBP daily | free | `raw/ecb_fx/` | <1 MB |
| `renninja_pull` | renewables.ninja reanalysis CF per site | free token, ~50 requests/h | `raw/ninja/` | 0.1 GB, ~8 h |
| `pecd_pull` | Copernicus CDS PECD v4.2 (ERA5 and CMIP6 CF, temperature) | free CDS key + licence acceptance | `raw/pecd/` | up to 10 GB |
| `nuts_boundaries_pull` | Eurostat GISCO NUTS-2 boundaries | free | `raw/gis/nuts2_boundaries_2021.geojson` | <5 MB |
| `ppm_pull` | powerplantmatching plant roster, pinned release v0.8.1, checksum-verified | free (GitHub) | `raw/powerplants.csv` | 22 MB |
| `nordpool_pull` | Nord Pool N2EX prices, aggregated curves, blocks, flows | **paid API** | `raw/nordpool/` | 13 GB |
| `epex_pull` | EPEX SPOT GB day-ahead and intraday prices, curves, blocks, trades | **paid sFTP** | `raw/epex/` | 3.4 GB |

Two hand-downloaded Ofgem reports feed the ownership tables: `raw/ofgem/RO_Accredited_Stations_*.csv` and
`raw/ofgem/RO_Certificates_*.csv` (Renewables and CHP Register; see `raw/manual/README.md`).

Three sources behind the ownership tables publish only their current state: Elexon's BM unit register
(`elexon_pull bmunits`), NESO's Capacity Market register (`cm_register_pull`) and The Crown Estate's
ownership page (`crown_estate_pull`). `python scripts/snapshot_registers.py [--only bmunits cm crown_estate]`
pulls Elexon's and NESO's registers when today's snapshot is missing (never overwriting one) and The Crown
Estate's page when its as-at date is new; run it once a month (its docstring has the Task Scheduler and cron
lines, and says where the snapshots go) so the ownership tables get a history from now on: `bm_units` gives
each year the register snapshot of its as-of date. About 17 MB a month, nearly all of it the CM register.

Credentials are read from an environment variable first, then from a gitignored file in
`data/reference/`:

| Source | Environment variable(s) | File |
| --- | --- | --- |
| ENTSO-E | `ENTSOE_TOKEN` | `entsoe_token.txt` |
| renewables.ninja | `RENNINJA_TOKEN` | `renewables_ninja_token.txt` |
| Copernicus CDS | `CDSAPI_KEY` | `cds_api_token.txt` |
| Nord Pool | `NORDPOOL_USER`, `NORDPOOL_PASS` | `nordpool_credentials.txt` (user, password) |
| EPEX SPOT | `EPEX_USER`, `EPEX_PASS` | `epex_credentials.txt` (user, password) |
| Companies House | `CH_API_KEY` | `companies_house_token.txt` |

## 2. Reference tables: one-off builders

These write small tables to `reference/`. The derived ones are also tracked in git, so a fresh
clone only needs them rebuilt when their inputs change (see `data/reference/README.md`).

| Command | Reads | Writes |
| --- | --- | --- |
| `python scripts/build_bmu_crosswalk.py` | `raw/psd/ids.csv`, `raw/bm_units_*.csv`, `reference/bmu_crosswalk_overrides.yaml` | `reference/bmu_crosswalk.csv`, `reference/cfd_bmu_map.csv` |
| `python scripts/build_wind_farm_map.py` | `raw/fpn/`, `raw/bm_units_*.csv`, `raw/psd/ids.csv`, `raw/repd_*.csv`, `reference/cfd_bmu_map.csv`, `reference/wind_farm_map_overrides.csv` | `reference/wind_farm_map.csv` |
| `python -m gbpowerdata.pull.build_zone_sites` | `processed/powerplants_located_{y}.csv`, CfD register, REPD, GIS | `reference/ninja_sites_by_zone.csv` |
| `python -m gbpowerdata.build.analyze_flexibility` | `raw/fuelhh_*.csv` | `reference/tech_flexibility_empirical.csv` |
| `python -m gbpowerdata.build.nuclear_availability` | `raw/fuelhh_*.csv`, `processed/powerplants_located_{y}.csv` | `reference/nuclear_availability_by_year.csv` |
| `python -m gbpowerdata.common.pecd_regions --build-nuts2-gsp` / `--build-wind-zones` | GIS boundaries, `raw/pecd/masks/*.nc` | `reference/nuts2_to_gsp_group_area_weights.csv`, `reference/pecd_{onshore,offshore}_zone_to_nuts2.csv` |

## 3. Build: the per-year panel (`python scripts/run_pipeline.py [years]`)

Runs each stage as a subprocess with `PIPELINE_YEAR` set, for 2018–2025 by default. A failing
stage stops the run, except the two marked *soft*, which are skipped when their inputs are absent.

| Stage (`gbpowerdata.build.<x>`) | Reads | Writes (`processed/`) |
| --- | --- | --- |
| `build_cfd_status` (once) | CfD register xlsx, `reference/cfd_round_params.csv`, REPD | `cfd_status.csv` |
| `nuclear_availability` (once, soft) | see section 2 | `reference/nuclear_availability_by_year.csv` |
| `stage1_tag_plants` | `raw/powerplants.csv`, CfD register, `reference/{plant,cfd}_overrides.yaml`, `reference/benchmarks_{y}.csv` | `powerplants_tagged_{y}.csv`, `regime_summary_{y}.csv`, `cfd_ppm_matches_{y}.csv` |
| `stage1_spatial_join` | tagged plants, CfD register, `raw/gis/`, `reference/gsp_overrides.csv` | `powerplants_located_{y}.csv` |
| `stage2_build_timeseries` | ESPENI, ITSDO, MID, BM units, REPD, gas, carbon, coal (N2EX fills MID gaps only if `raw/nordpool/` exists and `timeseries.mid_gap_fill_n2ex` is true) | `demand_{y}.csv`, `capacity_factors_{y}.csv`, `fuel_prices_{y}.csv`, `mid_target_{y}.csv` |
| `build_cfd_fleet` | `raw/lccc/`, `capacity_factors_{y}.csv` | `cfd_fleet_{y}.csv` |
| `stage2c_zone_demand` | `demand_{y}.csv`, `reference/gsp_group_demand_weights.csv` | `demand_by_zone_{y}.csv` |
| `stage3_build_agents` | fleet, CfD status, located plants, REPD, GIS, `reference/tech_parameters.yaml`, flexibility, nuclear availability | `agents_{y}.csv` |
| `stage2b_zone_cf` (soft) | `raw/ninja/`, `reference/ninja_sites_by_zone.csv`, agents, national CF | `capacity_factors_by_zone_{y}.csv` |
| `stage2d_wind_farms` (soft) | `raw/fpn/`, `reference/wind_farm_map.csv` | `wind_farms_{y}.csv`, `wind_farm_fpn_{y}.csv`, `wind_farm_fpn_gaps_{y}.csv` |

## 4. Build: tables outside the per-year runner

| Command (`python -m gbpowerdata.build.<x>`) | Reads | Writes (`processed/`) |
| --- | --- | --- |
| `build_system_prices [--years 2016 2025]` | `raw/system_prices/` | `system_prices_{y}.csv` |
| `build_lolp [--years 2018 2025]` | `raw/forecasts/LOLPDRM_*` | `lolp_drm_{y}.csv` |
| `build_forecast_state --start 2016 --end 2025` | `raw/forecasts/` | `forecast_state_{y}.csv` |
| `build_consumer_levy` | `raw/lccc/` (levy set), `raw/octopus/svt_unit_rates.csv` | `consumer_levy_daily.csv`, `consumer_levy_annual.csv` |
| `build_duos_tariffs` | `raw/manual/dno_duos/`, `raw/ofgem/duos_per_customer.csv` | `duos_domestic_tariffs.csv` |
| `build_cap_tariff` | Ofgem cap tariff model xlsx in `raw/ofgem/` | `cap_tariff_by_region.csv` |
| `build_subnational_domestic` | `raw/manual/desnz_subnational/` | `domestic_supply_by_year.csv` |
| `bm_units [--years 2018 2026]` (default to the current year) | `raw/bm_units_*.csv` (every kept snapshot), `reference/bmu_left_register.csv` (the units that left the register before it, after `fpn_left_register_pull`), `raw/{fpn,b1610,bod}/` | `bm_unit_register_{y}.csv` |
| `bm_dynamic [--pull]` | `raw/bm_dynamic/` (`--pull` fetches the missing snapshots first), `bm_unit_register_{y}.csv` | `bm_dynamic_units.csv` (one row per snapshot and active thermal or pumped-storage unit: declared values and the derived minimum stable share, ramp rates, run-up time) and `reference/bm_dynamic_by_tech.csv` (by technology, each year and 2018–2025; [thermal_parameters.md](thermal_parameters.md)) |
| `build_company_control [--stamp YYYYMMDD]` | `raw/companies_house/` (the newest snapshot of each company; with `--stamp`, those up to that pull date) | `company_control.csv` (`company_control_{stamp}.csv` with `--stamp`) |
| `build_ownership [--years 2018 2026]` (after `capacity_market`) | `raw/dukes/`, `raw/ofgem/RO_*` (optional), CfD register and `raw/lccc/`, `raw/neso/cm_register/`, `raw/neso/ancillary/eac_by_unit_*.csv` (battery postcodes), `bm_unit_register_{y}.csv`, `capacity_market_links.csv` and `capacity_market_agreements.csv` (storage units' CM owners; without them a warning), `company_control.csv` (optional, basis `ch_psc`), `reference/{company_groups,company_owners,bmu_lead_parties,companies_house_numbers,dukes_bmu_map,wind_farm_map}.csv` | `ownership_{y}.csv`, `ownership_bmu_{y}.csv` ([ownership.md](ownership.md)) |
| `ancillary_services [--years 2019 2026]` | `raw/neso/ancillary/`, `raw/govuk/bank_holidays.json` (the FFR tenders' frames), `raw/bm_units_*.csv` (every kept snapshot, to map NESO's unit ids), `reference/company_groups.csv` and the other company tables (the bidder's group) | `ancillary_by_unit_{y}.csv` ([storage_revenues.md](storage_revenues.md)) |
| `capacity_market [--years 2018 2026]` | `raw/neso/cm_register/` (the newest register and auction files), `raw/lccc/cm_capacity_obligation_by_auction.csv`, `raw/ons/cpi_index_d7bt.csv`, `raw/bm_units_*.csv` (the storage units for the links) | `capacity_market_{y}.csv` (every agreement's obligation and payment by month), `capacity_market_auctions.csv`, `capacity_market_weights.csv`, `capacity_market_derating.csv`, `capacity_market_agreements.csv`, `capacity_market_links.csv` |
| `investment_inputs` (after `cost_data_pull`) | `raw/cost_data/` | `investment_inputs.csv`: every technology's costs, lifetimes, efficiencies, load factors and hurdle rates by source edition and year, in the source's price base, units per kW and kWh; `processed.read_investment_inputs()` adds `reference/investment_parameters.csv` |
| `storage_revenues [--years 2018 2025]` (after `storage_fleet`, and `capacity_market` for `cm_gbp`) | `raw/fpn/`, `raw/mid_apx_*.csv`, `raw/system_prices/`, `raw/ebocf/`, `bm_unit_register_{y}.csv`, `ownership_bmu_{y}.csv`, `ancillary_by_unit_{y}.csv`, `storage_fleet.csv` (the supplier and virtual lead party batteries), `capacity_market_{y}.csv` and `capacity_market_links.csv` (optional); builds a year only when the notifications, the MID and the BM cashflows cover all of it | `storage_revenue_{y}.csv` ([storage_revenues.md](storage_revenues.md)) |
| `storage_fleet` (after `ancillary_services` and `capacity_market`; `bm_dynamic_pull [dates]` and `--submissions` first for declared MWh; again after `ebocf_pull` and `fpn_pull --storage-fleet`, which take its supplier and virtual lead party batteries) | `raw/bm_units_*.csv`, `raw/fpn/`, `raw/ebocf/`, `ancillary_by_unit_{y}.csv`, `raw/bm_dynamic/{dynamic,submissions}_*.csv` (optional), `raw/neso/cm_register/components_*.csv` (optional), `raw/neso/ancillary/eac_by_unit_*.csv` (postcodes), `capacity_market_links.csv` and `capacity_market_agreements.csv` (optional) | `storage_fleet.csv`: every storage unit with MW, MWh where stated, registration bound, entry and exit dates ([storage_revenues.md](storage_revenues.md)) |
| `unit_runs` (after `b1610_pull`, `fpn_pull` and `bm_dynamic_pull --submissions MNZT MZT NDZ`; about five minutes) | `raw/b1610/` (the units it measures), `raw/fpn/`, `raw/bm_dynamic/submissions_{MNZT,MZT,NDZ}_*.csv`, `raw/bm_units_*.csv` | `unit_run_times.csv` (per unit, year and source, metered or notified: hours on, starts, the run and down spells' percentiles in hours, the share under 6 h, the two-shift share, and the declared MNZT, MZT and NDZ in force) and `unit_spells_{y}.csv` (every spell, censored where it meets a gap or an end of the data) |
| `build_crown_estate [--strict]` | `raw/crown_estate/`, `reference/crown_estate_farms.csv`, `reference/crown_estate_ownership_reports.csv` (local only, optional), `reference/{company_owners,company_groups}.csv` | `crown_estate_ownership.csv` (local only, not packed); prints the differences between `company_owners.csv` and The Crown Estate's tables; `--strict` exits 1 on an unexplained difference, an unmapped farm, a changed not-compared farm or an unused known difference |
| `pecd_build`, then `pecd_national_cf` | `raw/pecd/historical/`, PECD region weights, agents | `pecd/cf_historical.csv`, `pecd/temperature_popweighted_historical.csv`, `capacity_factors_pecd_{y}.csv` |
| `pecd_build --stream future` | `raw/pecd/projection/{gcm}/{ssp}/` (from `pecd_pull --stream projection`) | `pecd/cf_future_{gcm}_{ssp}.csv` (~0.7 GB each) |

`python scripts/build_fuel_prices.py [first last]` (default 2018 2021) runs `gas_pull`,
`carbon_pull` and `coal_pull`, then `stage2_build_timeseries --fuel-only` for each year, so it
rebuilds `fuel_prices_{y}.csv` alone, with no ESPENI or Elexon input. It exists for the years
the data pack leaves out because their carbon price comes from EEX.

**Licensed venues** (need `raw/nordpool/` and/or `raw/epex/`; every output is licensed data):

| Command | Writes (`processed/`) |
| --- | --- |
| `dayahead_curves {n2ex,epex_hourly,epex_hh,all} [years]` (before `build_dayahead_prices`) | `{venue}_curve_checks_{y}.csv`: per delivery period, whether the aggregated curves are monotone and clear at the published price (N2EX's with its accepted blocks and flows from 2021, EPEX's read as steps), the curves' price range, and the volume traded (N2EX's weights the blend); `failing_dates()` lists the dates that fail |
| `build_dayahead_prices [years]` | `dayahead_price_{n2ex,epex_hourly,epex_hh,blend,gb}_{y}.csv` |
| `parse_n2ex_curves [years]` | `n2ex_curve_features_{y}.csv` |
| `parse_epex_curves --modality hourly\|hh [years]` | `epex_{hourly,hh}_curve_features_{y}.csv` |
| `parse_blocks epex\|n2ex [years]` | `{epex,n2ex}_blocks_{y}.csv`, `{epex,n2ex}_block_hours_{y}.csv` |
| `parse_epex_trades [years]` | `epex_trades_halfhourly_{y}.csv` |
| `storage_revenues_dayahead [--years 2018 2025]` (after `storage_revenues` and `build_dayahead_prices`) | `storage_revenue_dayahead_{y}.csv`: each storage unit's notified position valued at each day-ahead auction's price (N2EX, EPEX hourly, EPEX half-hourly, the blend), next to its MID value ([storage_revenues.md](storage_revenues.md)) |

`build_dayahead_prices` weights its N2EX/EPEX blend by the volume each auction traded: N2EX's
measured from its curves and accepted blocks by `dayahead_curves` (else the research code's
`n2ex_bid_panel_{y}.csv`, if present), EPEX's as published; `blend_basis` marks the half-hours
where a volume was missing and the plain mean stands in. LCCC's IMRP (`lccc_pull imrp-actuals`,
open) is the same weighted average, and `tests/realdata/test_licensed.py` checks the blend
against it.

## 5. Reading the outputs

Use `gbpowerdata.processed` instead of globbing file names:

```python
from gbpowerdata import processed, venue
d = processed.load_year(2023)            # {"demand", "cf", "fuel", "mid", "agents", ...}
own = processed.read_ownership_bmu(2023, role="owner")   # owners of every active BM unit
rev = processed.read_storage_revenue(2025, annual=True)  # each storage unit's estimated margin, by stream
runs = processed.read_unit_run_times(source="fpn")       # thermal units' notified run and down times by year
hh = processed.merge_drivers(2023)       # half-hourly demand + CF + fuel + MID on one index
p = venue.get("epex").load_da_price(2023)   # day-ahead price of one auction (licensed data)
```

Every time series is UTC, half-hourly, keyed on `startTime`.

## 6. Data packs

`gbpowerdata.datapack` moves data between machines without putting it in git:

| Command | Does |
| --- | --- |
| `export processed [--years 2018 2025] [--out dist]` | zips the open processed tables (`PROCESSED_YEARLY`, `PROCESSED_SINGLE`) with a sha256 manifest |
| `export inputs [--out dist]` | zips the hand-downloaded raw inputs (`INPUTS`) |
| `verify <zip>` | checks every member against the manifest |
| `unpack <zip> [--force]` | verifies, then writes into the configured data folders |

Export refuses licensed N2EX/EPEX tables and any `mid_target` holding N2EX rows, and leaves out
every file with a source marked `ship=False` in `datapack.SOURCES` (today EEX, so
`fuel_prices_2018` to `fuel_prices_2021`); the manifest lists those under `withheld` with the
command that builds them, and `unpack` prints it. A release is built with
`timeseries.mid_gap_fill_n2ex: false`, committed and tagged; then both packs are exported and
attached to the GitHub Release of that tag (`gh release create <tag> dist/*.zip`), so the
manifest's commit names the code that built the data.
