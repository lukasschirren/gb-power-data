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
| `fpn_pull` | Elexon per-unit physical notifications | free, slow (per unit) | `raw/fpn/{bmu}.csv` | 3.6 GB |
| `elexon_bod_pull` | Elexon per-unit bid-offer data and acceptances | free, slow | `raw/bod/`, `raw/boalf/` | 4.5 GB |
| `b1610_pull` | Elexon per-unit metered generation (thermal) | free, slow | `raw/b1610/` | 0.6 GB |
| `mels_pull` | Elexon MEL/PN/BOD for chosen days | free | `raw/mels/` | 0.2 GB |
| `lccc_pull` (+ `--levy`) | LCCC CfD portal (CKAN): register status, CfD↔BMU map, actual generation and payments, strike prices, levy rates | free | `raw/lccc/` | 20 MB |
| `neso_pull` | NESO data portal: BSUoS, AAHEDC, TNUoS | free | `raw/neso/` | 18 MB |
| `cm_register_pull` | NESO Capacity Market register: every CM unit and its components (applicant, parent company, technology, capacities, agreements); the trading contacts' columns are dropped | free | `raw/neso/cm_register/{cmu,components}_{date}.csv` | 16 MB |
| `ancillary_pull [--list]` | NESO data portal: unit-level results of Dynamic Containment (tenders 2020–21, auctions 2021–23), the Enduring Auction Capability (response, quick, slow and balancing reserve, from Nov 2023), Balancing Reserve (2024–25) and Static FFR (from Apr 2023): MW, price and the company that bid, per unit and period | free | `raw/neso/ancillary/{stem}.csv` (an archive once; a resource NESO still updates under the pull date) | 0.7 GB |
| `ebocf_pull [--start YYYY-MM --end YYYY-MM]` | Elexon: indicative BM cashflows (EBOCF) of the battery and pumped storage units, per settlement period | free, ~1 min a month | `raw/ebocf/ebocf_{YYYY-MM}.csv` | 0.13 GB |
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
| `bm_units [--years 2018 2026]` (default to the current year) | `raw/bm_units_*.csv` (every kept snapshot), `raw/{fpn,b1610,bod}/` | `bm_unit_register_{y}.csv` |
| `build_company_control [--stamp YYYYMMDD]` | `raw/companies_house/` (the newest snapshot of each company; with `--stamp`, those up to that pull date) | `company_control.csv` (`company_control_{stamp}.csv` with `--stamp`) |
| `build_ownership [--years 2018 2026]` | `raw/dukes/`, `raw/ofgem/RO_*` (optional), CfD register and `raw/lccc/`, `raw/neso/cm_register/`, `bm_unit_register_{y}.csv`, `company_control.csv` (optional, basis `ch_psc`), `reference/{company_groups,company_owners,bmu_lead_parties,companies_house_numbers,dukes_bmu_map,wind_farm_map}.csv` | `ownership_{y}.csv`, `ownership_bmu_{y}.csv` ([ownership.md](ownership.md)) |
| `ancillary_services [--years 2020 2026]` | `raw/neso/ancillary/`, `raw/bm_units_*.csv` (every kept snapshot, to map NESO's unit ids), `reference/company_groups.csv` and the other company tables (the bidder's group) | `ancillary_by_unit_{y}.csv` ([storage_revenues.md](storage_revenues.md)) |
| `storage_revenues [--years 2018 2025]` | `raw/fpn/`, `raw/mid_apx_*.csv`, `raw/system_prices/`, `raw/ebocf/`, `bm_unit_register_{y}.csv`, `ownership_bmu_{y}.csv`, `ancillary_by_unit_{y}.csv`; builds a year only when the notifications, the MID and the BM cashflows cover all of it | `storage_revenue_{y}.csv` ([storage_revenues.md](storage_revenues.md)) |
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
| `build_dayahead_prices [years]` | `dayahead_price_{n2ex,epex_hourly,epex_hh,blend,gb}_{y}.csv` |
| `parse_n2ex_curves [years]` | `n2ex_curve_features_{y}.csv` |
| `parse_epex_curves --modality hourly\|hh [years]` | `epex_{hourly,hh}_curve_features_{y}.csv` |
| `parse_blocks epex\|n2ex [years]` | `{epex,n2ex}_blocks_{y}.csv`, `{epex,n2ex}_block_hours_{y}.csv` |
| `parse_epex_trades [years]` | `epex_trades_halfhourly_{y}.csv` |

`build_dayahead_prices` weights its N2EX/EPEX blend by traded volume when
`processed/n2ex_bid_panel_{y}.csv` exists. That panel is built by research code outside this
package, so without it the blend is a plain mean of the two venues.

## 5. Reading the outputs

Use `gbpowerdata.processed` instead of globbing file names:

```python
from gbpowerdata import processed, venue
d = processed.load_year(2023)            # {"demand", "cf", "fuel", "mid", "agents", ...}
own = processed.read_ownership_bmu(2023, role="owner")   # owners of every active BM unit
rev = processed.read_storage_revenue(2025, annual=True)  # each storage unit's estimated margin, by stream
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
