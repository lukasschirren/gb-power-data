# gb-power-data

Half-hourly data on the Great Britain electricity market for 2018–2025, and the code that builds
it from public sources.

The tables cover electricity demand, wind and solar output, fuel and carbon prices, every power
plant with its support scheme, Contracts for Difference (CfD) payments, imbalance prices,
day-before forecasts and the parts of a household bill. You can download the finished tables and
start working in a few minutes, or rebuild all of them from the original sources with the code here.

| | |
| --- | --- |
| Coverage | Great Britain, 2018–2025 |
| Time step | 30 minutes, in UTC |
| Format | CSV, one file per table and year (for example `demand_2023.csv`) |
| Size | about 0.5 GB, or 70 MB as a zip download |
| Sources | Elexon, NESO, LCCC, Ofgem, DESNZ, ONS, ENTSO-E, ESPENI, renewables.ninja, Copernicus and others |
| Licence | Code is BSD-3-Clause. Data keeps the terms of its sources, and four tables are for non-commercial use only ([data terms](#data-terms)) |

## Quick start

### 1. Install

You need [conda](https://docs.conda.io/en/latest/miniconda.html) (or any Python 3.12 with pip).

```bash
git clone <repository-url> gb-power-data
cd gb-power-data
conda env create -f environment.yml
conda activate gb-power-data
```

### 2. Download the data

The tables are attached to each [GitHub Release](../../releases) as a zip file, and one command
unpacks them into `data/processed/` after checking every file against its checksum.

```bash
gh release download --pattern "gb-power-data_processed_*.zip"    # or download it from the Releases page
python -m gbpowerdata.datapack unpack gb-power-data_processed_<date>.zip
python scripts/build_fuel_prices.py      # fuel prices for 2018-2021, built on your machine (about a minute)
```

The last command is there because the carbon price of 2018 to April 2021 comes from EEX, whose terms
do not allow passing it on (no UK allowance traded before May 2021, so January to April 2021 carry the
EU price of the month as the proxy). The pack therefore leaves out `fuel_prices_2018` to
`fuel_prices_2021`, and the script fetches the prices from the public sources and builds those four
files locally, with no account needed.

### 3. Load a table

```python
from gbpowerdata import processed

tables = processed.load_year(2023)       # the 2023 tables, keyed "demand", "cf", "fuel", "mid", "agents", ...
tables["demand"].head()

hh = processed.merge_drivers(2023)       # demand, capacity factors, fuel prices and MID on one half-hourly index
```

Plain pandas works too, with `pd.read_csv("data/processed/demand_2023.csv", parse_dates=["startTime"])`.

## What is in the data

Each table sits in `data/processed/`. A `{y}` in the name stands for the year, and every time
series has one row per half-hour with its UTC start time in the column `startTime`.

| Topic | Table | What it holds |
| --- | --- | --- |
| Demand | `demand_{y}` | transmission demand (Elexon's ITSDO, which includes interconnector exports, pumped storage pumping and station load), embedded wind and solar, and national demand, their sum (MW) ([data caveats](#data-caveats)) |
| | `demand_by_zone_{y}` | the same split across the 14 GSP groups (the regional distribution areas) |
| Wind and solar | `capacity_factors_{y}` | offshore wind, onshore wind and solar capacity factors |
| | `capacity_factors_by_zone_{y}` | the same per GSP group, shaped by renewables.ninja reanalysis |
| | `capacity_factors_pecd_{y}` | the same three capacity factors from a second weather source, the Copernicus Pan-European Climate Database (PECD) |
| Prices | `fuel_prices_{y}` | gas, coal and carbon (EU or UK ETS plus the carbon price support); coal both as the Richards Bay export price and as the price of the UK's landed imports; 2018–2021 built locally |
| | `mid_target_{y}` | Elexon's Market Index Data price: the volume-weighted price of the half-hour's short-term trades on EPEX SPOT GB (half-hour and 1-4 hour blocks; the day-ahead auction has weight 0), not a day-ahead auction price; its trading window moved closer to delivery on 18 Apr 2019 (BSC modification P377) |
| | `system_prices_{y}` | the imbalance (cash-out) price and net imbalance volume |
| Plants and support | `powerplants_tagged_{y}`, `powerplants_located_{y}` | every GB plant with its support scheme (CfD, RO, FiT, none) and grid region |
| | `cfd_status`, `cfd_fleet_{y}` | each CfD contract, and the actual payments LCCC settled |
| | `agents_{y}` | the fleet grouped into units ready for a market model |
| | `wind_farms_{y}`, `wind_farm_fpn_{y}` | output of each transmission-connected wind farm |
| Ownership | `bm_unit_register_{y}` | every BM unit of the kept register snapshots with its lead party (the company that trades it; the register snapshot for the year, today's as a proxy before the first kept snapshot), technology, capacity and whether it produced in the year (the current year: the last pulled year's activity); the units that left the register before the first snapshot (Cottam, Aberthaw B, Eggborough and Deeside) are added from a sourced table and dated by their notifications in Elexon's all-units stream |
| | `ownership_{y}`, `ownership_bmu_{y}` | owners (with joint-venture shares), operators and traders in the year, by register (DUKES, RO, CfD, Capacity Market, Balancing Mechanism) and by BM unit, 2018 to the current year ([docs/ownership.md](docs/ownership.md); every curated share with its sources in [docs/ownership_references.md](docs/ownership_references.md)) |
| | `company_control` | Companies House persons with significant control as a dated table: each pulled company's corporate controllers (names and numbers), ownership and voting bands, notified and ceased dates; individuals only as anonymous rows (not packed) |
| | `crown_estate_ownership` | The Crown Estate's offshore wind ownership tables by date, against which `build_crown_estate` checks `company_owners.csv` (local only: The Crown Estate's terms) |
| Storage and ancillary services | `storage_revenue_{y}` | what each battery and pumped storage unit in the Balancing Mechanism earned per month, estimated from public data: its notified position valued at Elexon's market index price, its Balancing Mechanism cashflows, its frequency response and reserve payments and, in its own column, its Capacity Market payments, with its trader and optimiser; the T_ and E_ units, and the batteries traded through supplier (2__) and virtual lead party (V__) units (`kind`) ([docs/storage_revenues.md](docs/storage_revenues.md)) |
| | `ancillary_by_unit_{y}` | NESO's frequency response and reserve results by unit and delivery period: MW, price, payment and the company that bid the unit, from January 2019 (the monthly FFR tenders and the weekly FFR auctions; Dynamic Containment and the later services from October 2020; STOR's daily auctions from April 2021) (built locally, 0.7 GB: not in the data pack) |
| | `storage_fleet` | every battery and pumped storage unit the open data name (BM units, and the supplier, virtual lead party and non-BM units that sell to NESO): MW, MWh where a source states it (declared MDV; else the Capacity Market duration class of a component named by the unit's id, of its linked agreement, or at its postcode), and the dates it entered and left the market ([docs/storage_revenues.md](docs/storage_revenues.md)) |
| Capacity Market | `capacity_market_{y}` | every capacity agreement's obligation (de-rated MW) and payment by month: the auction's clearing price, CPI-indexed for T-4 auctions, times the month's weighting factor, as the Capacity Regulations set it; entitlements before suspensions and penalties |
| | `capacity_market_auctions`, `capacity_market_derating`, `capacity_market_weights` | each auction's price per kW in every delivery year it pays for, as paid and in 2024 money (constant over a four-years-ahead agreement's years, so known for future years too), and its target; the de-rating factors by technology (storage by duration) and the monthly weighting factors |
| | `capacity_market_agreements`, `capacity_market_links` | every agreement with its technology, class, duration class, obligation, term, delivery years (to 2043/44) and termination, and the storage BM units each belongs to |
| Investment | `investment_inputs` | capital and operating costs, lifetimes, efficiencies, load factors and hurdle rates by technology and commissioning year, one vintage per source edition (DESNZ's Electricity Generation Costs 2020, 2023 and 2025; the Danish Energy Agency's storage datasheet; NREL's Annual Technology Baseline 2021-2025 for US battery costs), each in its own price base; `read_investment_inputs()` adds CEPA's 2025 hurdle rates (lithium batteries 8.90%) and Mott MacDonald's 2018 storage costs, transcribed with locators in `data/reference/investment_parameters.csv` |
| Thermal plant | `unit_run_times`, `unit_spells_{y}` | how long each thermal BM unit ran once started and stayed off once stopped, per year: the spells' counts and percentiles in its metered output (from February 2019) and in its own notifications (from 2018), the share under 6 h and how often it two-shifts, beside the minimum non-zero and zero times (MNZT, MZT) and the start notice (NDZ) it declared to NESO; every spell with its start and end |
| Forecasts and tightness | `forecast_state_{y}` | what was forecast the day before (wind, solar, demand, margin) |
| | `lolp_drm_{y}` | loss-of-load probability and de-rated margin |
| Household bills | `consumer_levy_daily`, `consumer_levy_annual` | the CfD levy in £/MWh and £ per household |
| | `duos_domestic_tariffs`, `cap_tariff_by_region`, `domestic_supply_by_year` | network charges, the price cap by region, the domestic share of demand |
| Day-ahead auctions (licensed) | `dayahead_price_*`, curve, block and trade tables | N2EX and EPEX SPOT data; needs a subscription and is never shared ([below](#licensed-market-data-n2ex-epex-spot)) |

How each table is built, with every input and output, is in [docs/pipeline.md](docs/pipeline.md).
Known quirks of the data are listed under [data caveats](#data-caveats).

## Rebuild the data yourself

You only need this section to update the data or change how it is built.

### Accounts and tokens

Most sources need no account. The others read an environment variable, or else a file in
`data/reference/` that git ignores.

| Source | Needed for | Variable(s) | File |
| --- | --- | --- | --- |
| ENTSO-E Transparency (free token) | neighbour prices, interconnector capacity | `ENTSOE_TOKEN` | `entsoe_token.txt` |
| renewables.ninja (free token) | regional wind and solar capacity factors | `RENNINJA_TOKEN` | `renewables_ninja_token.txt` |
| Copernicus CDS (free account, accept the PECD licence) | PECD capacity factors | `CDSAPI_KEY` | `cds_api_token.txt` |
| Nord Pool (paid) | N2EX prices, curves, blocks | `NORDPOOL_USER`, `NORDPOOL_PASS` | `nordpool_credentials.txt` |
| EPEX SPOT (paid) | EPEX GB prices, curves, blocks, trades | `EPEX_USER`, `EPEX_PASS` | `epex_credentials.txt` |

### Steps

1. Unpack the inputs pack, which holds the hand-downloaded files no script can fetch (CfD
   register, REPD, ESPENI, GSP and DNO boundaries, Ofgem cap model, DNO charging statements,
   DESNZ consumption), and pull the plant roster, which comes from a pinned powerplantmatching
   release. The inputs are listed with their origins in
   [data/raw/manual/README.md](data/raw/manual/README.md).

   ```bash
   gh release download --pattern "gb-power-data_inputs_*.zip"
   python -m gbpowerdata.datapack unpack gb-power-data_inputs_<date>.zip
   python -m gbpowerdata.pull.ppm_pull          # powerplantmatching v0.8.1, checksum-verified
   ```

2. Run the pullers you need, one module per source (section 1 of
   [docs/pipeline.md](docs/pipeline.md)). The per-unit Elexon pulls (FPN, BOD) take hours and
   several GB, and renewables.ninja allows about 50 requests an hour (about 8 h in all). Elexon's BM
   unit register, NESO's Capacity Market register and The Crown Estate's ownership page keep no
   history: schedule `python scripts/snapshot_registers.py` once a month (its docstring shows how) to
   keep a dated snapshot of each.

3. Build.

   ```bash
   python scripts/run_pipeline.py              # the per-year tables, 2018-2025 (or name years: 2023)
   python -m gbpowerdata.build.build_system_prices --years 2018 2025
   python -m gbpowerdata.build.build_lolp --years 2018 2025
   python -m gbpowerdata.build.build_forecast_state --start 2018 --end 2025
   python -m gbpowerdata.build.build_consumer_levy
   python -m gbpowerdata.pull.fpn_left_register_pull   # the units that left the register: Mar 2016-Mar 2020 (~30 min)
   python -m gbpowerdata.build.bm_units                # needs the per-unit FPN/B1610 pulls (~2 min)
   python -m gbpowerdata.build.build_company_control   # optional: after companies_house_pull --follow 2 (free key)
   python -m gbpowerdata.build.capacity_market         # after cm_register_pull, ons_pull, lccc_pull capacity-obligation-by-auction
   python -m gbpowerdata.build.build_ownership         # after capacity_market (battery owners), cm_register_pull, dukes_pull, the Ofgem RO reports
   python -m gbpowerdata.build.build_crown_estate --strict   # company_owners.csv against The Crown Estate's tables
   python -m gbpowerdata.build.ancillary_services      # after ancillary_pull
   python -m gbpowerdata.build.investment_inputs       # after cost_data_pull
   python -m gbpowerdata.build.storage_fleet           # after ancillary_services, capacity_market (bm_dynamic_pull, also --submissions, first for MWh)
   python -m gbpowerdata.pull.ebocf_pull               # then the BM cashflows of the fleet's supplier and VLP batteries,
   python -m gbpowerdata.pull.fpn_pull --storage-fleet # and their notifications,
   python -m gbpowerdata.build.storage_fleet           # and the fleet again, for their dates
   python -m gbpowerdata.build.storage_revenues        # after bm_units, build_ownership, ancillary_services, capacity_market, storage_fleet
   python -m gbpowerdata.build.unit_runs               # after b1610_pull, fpn_pull and bm_dynamic_pull --submissions MNZT MZT NDZ
   ```

The hourly regional PECD tables are in no pack because of their size, and a free Copernicus key
rebuilds them. They are `pecd/cf_historical.csv` (1950–2025, 0.75 GB), from
`python -m gbpowerdata.pull.pecd_pull` then `python -m gbpowerdata.build.pecd_build`, and the
CMIP6 climate projections (0.7 GB per climate model), from `pecd_pull --stream projection ...`
then `pecd_build --stream future`.

### Keep the data somewhere else

`config.yaml` holds every path and parameter, and no code hardcodes a path. To keep the data on a
shared drive or an external disk, copy the file, set absolute `paths`, and point the pipeline at
the copy, which leaves the tracked file untouched.

```bash
cp config.yaml config.local.yaml               # git ignores config.local.yaml
export GBPOWERDATA_CONFIG=config.local.yaml    # PowerShell: $env:GBPOWERDATA_CONFIG="config.local.yaml"
```

A relative `GBPOWERDATA_CONFIG`, like every relative entry under `paths`, is resolved against the
repository root, so it means the same from a notebook, a script or a subprocess.

### About the data packs

Git holds the code, the configuration and the small reference tables in `data/reference/`. The
data ships separately as zip files attached to each GitHub Release, so the repository stays small
however often the data is rebuilt.

| Pack | Contents | Needed for |
| --- | --- | --- |
| `gb-power-data_processed_<date>.zip` | the 2018–2025 tables above built from open sources | using the data |
| `gb-power-data_inputs_<date>.zip` | the hand-downloaded raw files | re-running the stages that read them |

Each pack holds the CSVs byte for byte, with a `MANIFEST.json` that records every file's sha256,
sources and terms, and the date and git commit of the build. `unpack` writes into the folders
`config.yaml` points at and never overwrites a file that differs unless given `--force`.
Maintainers build packs with `python -m gbpowerdata.datapack export processed --years 2018 2025`
and `... export inputs`.

## Licensed market data (N2EX, EPEX SPOT)

Nord Pool N2EX and EPEX SPOT data are commercial. The pullers and parsers are in this repository,
but they need your own (or your institution's) subscription, and neither the raw files nor
anything derived from them may be committed or shared. That covers `dayahead_price_*`, the curve
features and checks, the block and trade panels, and `storage_revenue_dayahead_*` (storage positions
priced at the auctions): every such file name carries `n2ex`, `epex` or `dayahead`.

Where `data/raw/nordpool/` exists, stage 2 also fills gaps in Elexon's MID with N2EX prices (up
to 6% of half-hours in 2020). Setting `timeseries.mid_gap_fill_n2ex: false` in `config.yaml`
builds a `mid_target` that may be shared, and the data pack's is built that way, so its gaps are
interpolated or left missing. `.gitignore` blocks all of these paths,
`tests/test_repo_hygiene.py` fails if one is ever tracked, and `datapack export` refuses to pack
them. Every other stage runs without the licensed data.

## Data terms

The code licence does not cover data. Every file keeps the terms of its sources, and the
`MANIFEST.json` of each data pack lists, per file, its `sources`, a `non_commercial` flag and a
`check_terms` flag, with each source's licence and required attribution. The terms below were
checked on 5 Oct 2026 (The Crown Estate and Companies House on 6 Oct 2026, the official statistics
on 10 Oct 2026).

| Source | Terms | Attribution | Files in the packs |
| --- | --- | --- | --- |
| Elexon BMRS | [BMRS open data licence](https://www.elexon.co.uk/bsc/data/balancing-mechanism-reporting-agent/copyright-licence-bmrs-data/), commercial use allowed | "Contains BMRS data © Elexon Limited copyright and database right [year]" | `demand`, `mid_target`, `system_prices`, `lolp_drm`, `forecast_state`, `wind_farm*`, `capacity_factors`, `capacity_factors_by_zone`, `agents`, `bm_unit_register`, `ownership*`, `bm_dynamic_units`, `storage_revenue`, `storage_fleet`, `unit_run_times`, `unit_spells`; tracked in `data/reference/`: `bm_dynamic_by_tech.csv` and the GB rows of `thermal_parameters.csv` |
| NESO Data Portal | [NESO Open Licence](https://www.neso.energy/data-portal/neso-open-licence), OGL-based and set per dataset | source and licence link | `forecast_state`, GSP and DNO boundaries, `powerplants_located`, `agents`, `ownership*` (Capacity Market register), `storage_revenue` (frequency response and reserve payments), `storage_fleet` (the units that sell to NESO, Capacity Market duration classes), `capacity_market*` (the Capacity Market register, auction results and de-rating factors) |
| LCCC | Open Government Licence v3.0 | source and licence link | `cfd_fleet`, `cfd_status`, `consumer_levy_*`, CfD register, `ownership*`, `storage_revenue` (`wholesale_imrp_gbp`, from the IMRP), `capacity_market_{y}` and `capacity_market_weights` (the weighting factors, from LCCC's capacity payments by auction) |
| DESNZ, ONS, gov.uk | Open Government Licence v3.0 | source and licence link | REPD, `domestic_supply_by_year`, gas and UK ETS prices in `fuel_prices`, `ownership*` (DUKES 5.11), `capacity_market*` (the CPI indexation of the T-4 prices, ONS series D7BT), `investment_inputs` (Electricity Generation Costs 2020, 2023, 2025), `storage_revenue` (gov.uk's bank holidays, for the FFR tenders' frames) |
| Ofgem | Open Government Licence v3.0 | source and licence link | `cap_tariff_by_region`, `duos_domestic_tariffs`, `ownership*` (RO register; the raw reports are not packed, see [data/raw/manual/README.md](data/raw/manual/README.md)) |
| The Crown Estate | [terms of use](https://www.thecrownestate.co.uk/about-us/terms-of-use): what is downloaded from its site is for the user's own use; digital copies are not to be passed to third parties | source | none: the pulled pages, the transcription of its 2018-2020 report tables and `crown_estate_ownership` stay local; `company_owners.csv` cites the shares it takes from them (`ce-2018` ... `ce-2024`) |
| Companies House | no licence stated: Companies House imposes no rules on how the public register's information is used, and requires credit where its guidance, website, publications or statistical tables are used ([public task statement](https://www.gov.uk/government/publications/companies-house-accreditation-to-information-fair-traders-scheme/public-task-copyright-and-crown-copyright)) | "Source: Companies House" | none so far (`company_control` is not packed); `ownership*` where basis `ch_psc` is used |
| OSUKED Power Station Dictionary | MIT | source and licence | `wind_farm*`, `ownership*` (the wind-farm map's links to BM units) |
| powerplantmatching (v0.8.1) | CC BY 4.0 | source | `powerplants_*`, `regime_summary`, `cfd_ppm_matches`, `agents` (the roster itself is pulled, not packed) |
| NREL (National Laboratory of the Rockies), Annual Technology Baseline | CC BY 4.0 | "NREL Annual Technology Baseline (ATB)" | `investment_inputs` (utility-scale batteries, editions 2021-2025) |
| Danish Energy Agency, Technology Data for Energy Storage | CC BY 4.0 | "Danish Energy Agency, Technology Data for Energy Storage" | `investment_inputs` (pumped hydro, lithium-ion and vanadium flow batteries) |
| Investment parameters from reports (CEPA for DESNZ 2025, Mott MacDonald for BEIS 2018) | published by DESNZ and BEIS on gov.uk, under the authors' copyright notices: values cited with a locator, never their documents | the source of each row (`source`, `locator`) in `investment_parameter_sources.csv` | `investment_parameters.csv`, tracked in `data/reference/`, not packed |
| Copernicus PECD v4.2 | CC BY 4.0 | "Generated using Copernicus Climate Change Service information [year]" | `capacity_factors_pecd` |
| World Bank Pink Sheet | CC BY 4.0 | source | coal price in `fuel_prices` |
| HMRC overseas trade statistics | Open Government Licence v3.0 | source and licence link | landed coal price in `fuel_prices` |
| ECB | [ECB statistics reuse policy](https://www.ecb.europa.eu/stats/ecb_statistics/governance_and_quality_framework/html/usage_policy.en.html), commercial use allowed | "Source: ECB statistics" | EUR→GBP and USD→GBP conversions in `fuel_prices` |
| Thermal plant parameters (22 sources, [docs/thermal_parameters.md](docs/thermal_parameters.md)) | per source, in `thermal_parameter_sources.csv`: CC BY 4.0 (ENTSO-E and ENTSOG TYNDP 2026 Scenarios, Danish Energy Agency, JRC, PyPSA-Eur), Open Government Licence v3.0 (DESNZ, BEIS, DUKES), NESO Open Licence, BMRS licence, reproduction with acknowledgement (METIS); the remaining sources (Kumar et al. 2012, DIW, Agora Energiewende, Leigh Fisher and Jacobs, Parsons Brinckerhoff, CEPA and GHD) state no open licence, and their values are cited, with a locator, never their documents | the source of each row (`source`, `locator`); "TYNDP 2026 Scenarios" for the ENTSO-E rows | `thermal_parameters.csv`, tracked in `data/reference/`, not packed |
| Official statistics (DESNZ, NESO, LCCC) | per row, in the `licence` column of `official_statistics.csv`: Open Government Licence v3.0 for DUKES; NESO's website terms for its balancing services spend reports and LCCC's terms of use for its annual reports, neither an open licence, so only single published totals are cited from them, with a locator, never their documents | the source of each row (`publisher`, `title`, `url`, `locator`) | `official_statistics.csv`, tracked in `data/reference/`, not packed |
| ESPENI | **CC BY-NC 4.0, non-commercial only** | Wilson et al. (2021), *Energy Strategy Reviews*; [Zenodo](https://doi.org/10.5281/zenodo.4739408) | `demand`, `demand_by_zone`, `capacity_factors`, `capacity_factors_by_zone`; `espeni.csv` |
| renewables.ninja | **CC BY-NC 4.0, non-commercial only** | Pfenninger & Staffell (2016), *Energy* 114, 1251–65; Staffell & Pfenninger (2016), *Energy* 114, 1224–39 | `capacity_factors_by_zone` |
| EEX | passing the data on to third parties is a licensed EEX service, so it is **never packed**; `scripts/build_fuel_prices.py` fetches it for each user | — | none; `fuel_prices_2018` to `fuel_prices_2021` are built locally |
| Octopus Energy API | publicly published, no stated licence | source | two columns of `consumer_levy_annual` (`svt_unit_rate_gbp_mwh`, `levy_share_of_unit_rate_pct`) |
| DNO charging statements | publicly published regulatory statements, no stated licence | source | `duos_domestic_tariffs`; the workbooks in the inputs pack |

Sharing the packs for academic, non-commercial work is fine with attribution. A commercial user
needs permission from ESPENI and renewables.ninja for the four tables that carry their values. We
treat tables that use those values only as a weight (the CF-weighted delivery share in
`cfd_fleet`) as LCCC data, and a commercial user unsure about that should ask. `storage_revenue`
carries the ownership tables' trader and optimiser, and so their sources too; each file's full list is
in the pack's `MANIFEST.json`. Every packed file
comes from a source that allows passing it on, so the packs may be published on a public release;
`datapack export` leaves out any file a source does not allow and names the command that
builds it locally.

## Data caveats

- **CfD levy.** The billed Interim Levy Rate is set a quarter ahead and floors at zero, so the
  2022 payback never reached bills that year. Use `reconciled_levy_gbp_mwh` for economic incidence
  and `interim_levy_gbp_mwh` for what was billed.
- **Octopus Agile** is capped at 33.33 p/kWh (excluding VAT), and the cap binds in 25.6% of
  half-hours in 2021 and 57.6% in 2022. Filter on `at_price_cap` before using it as a price signal.
- **DUoS** charging statements are missing for some areas in 2018–2021 (table in
  `data/raw/manual/README.md`).
- **Day-ahead blend.** `dayahead_price_blend_{y}` weights N2EX and EPEX by the volume each traded,
  N2EX's measured from its curves and accepted blocks (`python -m gbpowerdata.build.dayahead_curves
  n2ex` first); `blend_basis` marks where a volume is missing and the plain mean stands in. Without a
  subscription, LCCC's IMRP (`python -m gbpowerdata.pull.lccc_pull imrp-actuals`, open data) is the
  same volume-weighted day-ahead price.
- **MID gaps.** The shared `mid_target` has no N2EX gap-fill. A half-hour without traded volume is
  published by Elexon at a price of 0 and is a gap here, not a price of GBP 0/MWh (191 half-hours in
  2018-2025); a gap of up to 3 hours is interpolated and a longer one left empty (`mid_source`). Missing:
  164, 294, 1,032 and 709 half-hours in 2018-2021 (5.9% of 2020), 11 in 2022 and 7 in 2025.
- **Demand.** `transmission_demand_mw` is Elexon's ITSDO, which includes interconnector exports,
  pumped storage pumping and station load (on 2018-2025, ITSDO - INDO = 0.56 GW + 1.00 x exports +
  1.00 x pumping), so `national_demand_mw` is not the demand a model with its own interconnectors and
  storage should serve: it is 11-28 TWh a year above INDO plus embedded generation (28 TWh in 2022, a year
  of exports). Elexon published neither ITSDO nor INDO for whole days in 2018, 2020 and 2021; those
  554 half-hours have an empty `national_demand_mw` (`transmission_demand_source` "missing").

## Repository layout

```text
config.yaml           paths and parameters (override with GBPOWERDATA_CONFIG)
environment.yml       conda environment; pyproject.toml is the pip equivalent
src/gbpowerdata/
  pull/               one module per source -> data/raw/
  build/              processing stages     -> data/processed/
  common/             GSP geolocation, REPD, name matching, PECD regions, company groups, readers shared by
                      stages (Elexon's market index, LCCC's IMRP, ONS's CPI)
  checks/             checks of the built tables against the sources and official totals (tests/realdata)
  config.py           config loader and path helpers
  processed.py        loaders for the processed tables
  venue.py            which day-ahead auction a consumer reads (N2EX / EPEX hourly / EPEX half-hourly)
  datapack.py         export / verify / unpack the data packs
scripts/              run_pipeline.py, build_fuel_prices.py, snapshot_registers.py (monthly register
                      snapshots) and the two reference-map builders
data/raw/             source snapshots (not in git; manual/README.md lists hand-downloaded files)
data/reference/       small tables the pipeline needs (in git; see its README)
data/processed/       stage outputs (not in git; shipped as the processed pack)
dist/                 packs built locally for a release (not in git)
docs/pipeline.md      every stage, its inputs and outputs
docs/ownership.md     the ownership tables: roles, registers, links to BM units, limits
docs/AUDIT.md         the audit of October 2026: every finding with its evidence, severity and fix, and the plan
docs/DATA_GAPS.md     the open datasets still to add, with licence, access and the module that will own each
tests/                pytest; tests/realdata checks the built data where it exists
```

Module docstrings carry the method and the source quirks behind each stage. Some also name the
research code the data was first built for (a merit-order model, `meritorder`; a day-ahead curve
model, `spikeabm`; design notes under `reports/`). That code is not part of this repository and
nothing here imports it.

## Tests

```bash
pytest
```

The suite runs synthetic-data tests of the stage logic (LoLP vintage, PECD calendar and region
weights, system prices, wind-farm FPN gaps, the BM-unit register's activity dating, the ownership
rules, The Crown Estate's tables and their check, Companies House control, the monthly register
snapshot), checks that the curated ownership tables are sourced and add up, the data-pack round trip
and its guards, an import test of every module, and the licensed-data guard. None of it needs data
beyond `data/reference/`.

`tests/realdata` checks the built tables and the raw pulls wherever the configuration points: the UTC
spine and the clock changes, demand against metered generation, prices without false zeros, the storage
fleet against DESNZ's battery capacity, ancillary payments against NESO's published spend and CfD
payments against LCCC's (`data/reference/official_statistics.csv`, every figure with its source). Each
test is skipped where its data are absent; `-m "not licensed"` leaves out those reading local N2EX/EPEX
outputs. A known defect is a strict xfail naming its ID in [docs/AUDIT.md](docs/AUDIT.md).

## Licence and citation

The code is released under the [BSD 3-Clause licence](LICENSE), the preferred open-source licence
of Imperial College London, © 2026 Imperial College, London. For the data, see
[data terms](#data-terms). The maintainer is Lukas Schirren, Imperial College London.
