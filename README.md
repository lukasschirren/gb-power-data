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

The last command is there because the 2018–2020 carbon price comes from EEX, whose terms do not
allow passing it on. The pack therefore leaves out `fuel_prices_2018` to `fuel_prices_2021`
(early January 2021 is interpolated from December 2020), and the script fetches the prices from the
public sources and builds those four files locally, with no account needed.

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
| Demand | `demand_{y}` | national and transmission demand, embedded wind and solar (MW) |
| | `demand_by_zone_{y}` | the same split across the 14 GSP groups (the regional distribution areas) |
| Wind and solar | `capacity_factors_{y}` | offshore wind, onshore wind and solar capacity factors |
| | `capacity_factors_by_zone_{y}` | the same per GSP group, shaped by renewables.ninja reanalysis |
| | `capacity_factors_pecd_{y}` | the same three capacity factors from a second weather source, the Copernicus Pan-European Climate Database (PECD) |
| Prices | `fuel_prices_{y}` | gas, coal and carbon (EU or UK ETS plus the carbon price support); 2018–2021 built locally |
| | `mid_target_{y}` | Elexon's Market Index Data price, a day-ahead price indicator |
| | `system_prices_{y}` | the imbalance (cash-out) price and net imbalance volume |
| Plants and support | `powerplants_tagged_{y}`, `powerplants_located_{y}` | every GB plant with its support scheme (CfD, RO, FiT, none) and grid region |
| | `cfd_status`, `cfd_fleet_{y}` | each CfD contract, and the actual payments LCCC settled |
| | `agents_{y}` | the fleet grouped into units ready for a market model |
| | `wind_farms_{y}`, `wind_farm_fpn_{y}` | output of each transmission-connected wind farm |
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
   several GB, and renewables.ninja allows about 50 requests an hour (about 8 h in all).

3. Build.

   ```bash
   python scripts/run_pipeline.py              # the per-year tables, 2018-2025 (or name years: 2023)
   python -m gbpowerdata.build.build_system_prices --years 2018 2025
   python -m gbpowerdata.build.build_lolp --years 2018 2025
   python -m gbpowerdata.build.build_forecast_state --start 2018 --end 2025
   python -m gbpowerdata.build.build_consumer_levy
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
features, and the block and trade panels.

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
checked on 5 Oct 2026.

| Source | Terms | Attribution | Files in the packs |
| --- | --- | --- | --- |
| Elexon BMRS | [BMRS open data licence](https://www.elexon.co.uk/bsc/data/balancing-mechanism-reporting-agent/copyright-licence-bmrs-data/), commercial use allowed | "Contains BMRS data © Elexon Limited copyright and database right [year]" | `demand`, `mid_target`, `system_prices`, `lolp_drm`, `forecast_state`, `wind_farm*`, `capacity_factors`, `capacity_factors_by_zone`, `agents` |
| NESO Data Portal | [NESO Open Licence](https://www.neso.energy/data-portal/neso-open-licence), OGL-based and set per dataset | source and licence link | `forecast_state`, GSP and DNO boundaries, `powerplants_located`, `agents` |
| LCCC | Open Government Licence v3.0 | source and licence link | `cfd_fleet`, `cfd_status`, `consumer_levy_*`, CfD register |
| DESNZ, ONS, gov.uk | Open Government Licence v3.0 | source and licence link | REPD, `domestic_supply_by_year`, gas and UK ETS prices in `fuel_prices` |
| Ofgem | Open Government Licence v3.0 | source and licence link | `cap_tariff_by_region`, `duos_domestic_tariffs` |
| powerplantmatching (v0.8.1) | CC BY 4.0 | source | `powerplants_*`, `regime_summary`, `cfd_ppm_matches`, `agents` (the roster itself is pulled, not packed) |
| Copernicus PECD v4.2 | CC BY 4.0 | "Generated using Copernicus Climate Change Service information [year]" | `capacity_factors_pecd` |
| World Bank Pink Sheet | CC BY 4.0 | source | coal price in `fuel_prices` |
| ECB | [ECB statistics reuse policy](https://www.ecb.europa.eu/stats/ecb_statistics/governance_and_quality_framework/html/usage_policy.en.html), commercial use allowed | "Source: ECB statistics" | EUR→GBP and USD→GBP conversions in `fuel_prices` |
| ESPENI | **CC BY-NC 4.0, non-commercial only** | Wilson et al. (2021), *Energy Strategy Reviews*; [Zenodo](https://doi.org/10.5281/zenodo.4739408) | `demand`, `demand_by_zone`, `capacity_factors`, `capacity_factors_by_zone`; `espeni.csv` |
| renewables.ninja | **CC BY-NC 4.0, non-commercial only** | Pfenninger & Staffell (2016), *Energy* 114, 1251–65; Staffell & Pfenninger (2016), *Energy* 114, 1224–39 | `capacity_factors_by_zone` |
| EEX | passing the data on to third parties is a licensed EEX service, so it is **never packed**; `scripts/build_fuel_prices.py` fetches it for each user | — | none; `fuel_prices_2018` to `fuel_prices_2021` are built locally |
| Octopus Energy API | publicly published, no stated licence | source | two columns of `consumer_levy_annual` (`svt_unit_rate_gbp_mwh`, `levy_share_of_unit_rate_pct`) |
| DNO charging statements | publicly published regulatory statements, no stated licence | source | `duos_domestic_tariffs`; the workbooks in the inputs pack |

Sharing the packs for academic, non-commercial work is fine with attribution. A commercial user
needs permission from ESPENI and renewables.ninja for the four tables that carry their values. We
treat tables that use those values only as a weight (the CF-weighted delivery share in
`cfd_fleet`) as LCCC data, and a commercial user unsure about that should ask. Every packed file
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
- **Day-ahead blend.** `dayahead_price_blend_{y}` weights N2EX and EPEX by traded volume only when
  `processed/n2ex_bid_panel_{y}.csv` exists, which this package does not build, so otherwise it is
  a plain mean of the two.
- **MID gaps.** The shared `mid_target` has no N2EX gap-fill, so about 5% of half-hours in 2020
  (and fewer in 2018, 2019 and 2021) are missing; none are missing from 2022 on.

## Repository layout

```text
config.yaml           paths and parameters (override with GBPOWERDATA_CONFIG)
environment.yml       conda environment; pyproject.toml is the pip equivalent
src/gbpowerdata/
  pull/               one module per source -> data/raw/
  build/              processing stages     -> data/processed/
  common/             GSP geolocation, REPD, name matching, PECD regions
  config.py           config loader and path helpers
  processed.py        loaders for the processed tables
  venue.py            which day-ahead auction a consumer reads (N2EX / EPEX hourly / EPEX half-hourly)
  datapack.py         export / verify / unpack the data packs
scripts/              run_pipeline.py, build_fuel_prices.py and the two reference-map builders
data/raw/             source snapshots (not in git; manual/README.md lists hand-downloaded files)
data/reference/       small tables the pipeline needs (in git; see its README)
data/processed/       stage outputs (not in git; shipped as the processed pack)
dist/                 packs built locally for a release (not in git)
docs/pipeline.md      every stage, its inputs and outputs
tests/                pytest
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
weights, system prices, wind-farm FPN gaps), the data-pack round trip and its guards, an import
test of every module, and the licensed-data guard. None of it needs data beyond `data/reference/`.

## Licence and citation

The code is released under the [BSD 3-Clause licence](LICENSE), the preferred open-source licence
of Imperial College London, © 2026 Imperial College, London. For the data, see
[data terms](#data-terms). The maintainer is Lukas Schirren, Imperial College London.
