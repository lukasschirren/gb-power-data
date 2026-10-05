# gb-power-data

A reproducible data pipeline for the GB electricity market. It pulls public sources (Elexon,
NESO, LCCC, Ofgem, ENTSO-E, ONS, Octopus, renewables.ninja, Copernicus PECD) into immutable raw
snapshots, then builds per-year, half-hourly UTC panels for **2018–2025**:

| Theme | Processed tables (`data/processed/`) |
| --- | --- |
| Demand and weather | `demand_{y}`, `demand_by_zone_{y}` (14 GSP groups), `capacity_factors_{y}`, `capacity_factors_by_zone_{y}`, PECD capacity factors (`pecd/`) |
| Prices | `fuel_prices_{y}` (gas, coal, carbon incl. CPS), `mid_target_{y}` (Elexon MID), `system_prices_{y}` (cash-out, NIV) |
| Fleet and support | `powerplants_tagged_{y}` / `powerplants_located_{y}` (support regime, GSP), `cfd_status`, `cfd_fleet_{y}` (LCCC actual CfD payments), `agents_{y}` (fleet aggregated for models), `wind_farms_{y}` + `wind_farm_fpn_{y}` (per-farm output) |
| System state | `forecast_state_{y}` (D-1 forecasts), `lolp_drm_{y}` (loss-of-load probability, de-rated margin) |
| Consumer side | `consumer_levy_{daily,annual}` (CfD levy, £/household), `duos_domestic_tariffs`, `cap_tariff_by_region`, `domestic_supply_by_year` |
| Day-ahead auctions *(licensed)* | `dayahead_price_*`, N2EX/EPEX curve features, block orders, intraday trades |

The full stage-by-stage map (every input and output) is in [docs/pipeline.md](docs/pipeline.md).

## Install

```bash
conda env create -f environment.yml      # Python 3.12 + all dependencies, installs this package
conda activate gb-power-data
```

or, with an existing Python ≥ 3.12: `pip install -e ".[all]"` (extras: `epex` for the EPEX
sFTP puller, `pecd` for Copernicus PECD, `dev` for pytest).

## Configure

`config.yaml` holds every path and parameter; code never hardcodes a path. To keep the data tree
somewhere else (a shared drive, an external disk), copy the file, set absolute `paths`, and point
the pipeline at the copy instead of editing the tracked file:

```bash
cp config.yaml config.local.yaml          # config.local.yaml is gitignored
export GBPOWERDATA_CONFIG=config.local.yaml   # PowerShell: $env:GBPOWERDATA_CONFIG="config.local.yaml"
```

A relative `GBPOWERDATA_CONFIG`, like every relative entry under `paths:`, is resolved against the
repo root, so it means the same from a notebook, a script or a subprocess.

Most sources need no account. The rest read an environment variable, else a file in
`data/reference/` (gitignored):

| Source | Needed for | Variable(s) | File |
| --- | --- | --- | --- |
| ENTSO-E Transparency (free token) | neighbour prices, interconnector capacity | `ENTSOE_TOKEN` | `entsoe_token.txt` |
| renewables.ninja (free token) | per-zone wind/solar CF | `RENNINJA_TOKEN` | `renewables_ninja_token.txt` |
| Copernicus CDS (free account, accept the PECD licence) | PECD capacity factors | `CDSAPI_KEY` | `cds_api_token.txt` |
| Nord Pool (paid) | N2EX prices, curves, blocks | `NORDPOOL_USER`, `NORDPOOL_PASS` | `nordpool_credentials.txt` |
| EPEX SPOT (paid) | EPEX GB prices, curves, blocks, trades | `EPEX_USER`, `EPEX_PASS` | `epex_credentials.txt` |

## Get the data

Git holds the code, configuration and the small reference tables (`data/reference/`). The data
itself ships as two **data packs**, zip archives attached to each GitHub Release (not committed,
so the repository stays small however often the data is rebuilt):

| Pack | Contents | Needed for |
| --- | --- | --- |
| `gb-power-data_processed_<date>.zip` | the processed 2018–2025 tables built from open sources (everything in the table at the top except the licensed day-ahead data), plus PECD historical capacity factors | using the data |
| `gb-power-data_inputs_<date>.zip` | the hand-downloaded raw files no puller can fetch (plant roster, CfD register, REPD, ESPENI, GSP/DNO boundaries, Ofgem cap model, DNO charging statements, DESNZ consumption) | re-running stages 1–3 or the consumer-side stages |

```bash
gh release download <tag> --pattern "gb-power-data_*.zip"        # or download from the Releases page
python -m gbpowerdata.datapack unpack gb-power-data_processed_<date>.zip   # checksums verified
```

Each pack is a byte-exact copy of the CSVs plus a `MANIFEST.json` (sha256 per file, build date,
git commit). `unpack` writes into the folders `config.yaml` points at and never overwrites a file
that differs unless given `--force`. Maintainers build packs with
`python -m gbpowerdata.datapack export processed --years 2018 2025` and `... export inputs`.

Not in any pack:
- **API data** that the pullers fetch for free (Elexon, NESO, LCCC, Ofgem, ENTSO-E, ONS, …):
  section 1 of [docs/pipeline.md](docs/pipeline.md). The per-unit Elexon pulls (FPN, BOD) take
  hours and several GB; renewables.ninja is rate-limited (~8 h).
- **PECD climate projections** (CMIP6, ~4 GB processed): rebuild them with
  `python -m gbpowerdata.pull.pecd_pull --stream projection ...` and
  `python -m gbpowerdata.build.pecd_build --stream future` (free Copernicus key).
- **Licensed N2EX/EPEX data** (below).

To rebuild from source, unpack the inputs pack (or download the files listed in
[data/raw/manual/README.md](data/raw/manual/README.md)), run the pullers you need, then:

```bash
python scripts/run_pipeline.py              # core per-year panel, 2018-2025
python scripts/run_pipeline.py 2023         # one year
python -m gbpowerdata.build.build_system_prices --years 2018 2025
python -m gbpowerdata.build.build_lolp --years 2018 2025
python -m gbpowerdata.build.build_forecast_state --start 2018 --end 2025
python -m gbpowerdata.build.build_consumer_levy
```

Read the outputs through the loaders rather than by file name:

```python
from gbpowerdata import processed
tables = processed.load_year(2023)          # {"demand", "cf", "fuel", "mid", "agents", ...}
hh = processed.merge_drivers(2023)          # demand + CF + fuel + MID on one half-hourly index
```

## Licensed market data (N2EX, EPEX SPOT)

Nord Pool N2EX and EPEX SPOT data are commercial. The pullers and parsers are here, but using
them needs your own (or your institution's) subscription, and **neither the raw files nor anything
derived from them may be committed or redistributed**. That includes `dayahead_price_*`, curve
features, and block and trade panels. Where `data/raw/nordpool/` exists, stage 2 also fills gaps in
Elexon's MID with N2EX prices (up to 6% of half-hours in 2020); set
`timeseries.mid_gap_fill_n2ex: false` in `config.yaml` to build a `mid_target` that may be shared
(the data pack's is built that way, so its gaps are interpolated or left missing). `.gitignore`
blocks all of these paths, `tests/test_repo_hygiene.py` fails if one is ever tracked, and
`datapack export` refuses to pack them. Without the licensed data every other stage still runs.

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
scripts/              run_pipeline.py and the two reference-map builders
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

Synthetic-data tests of the stage logic (LoLP vintage, PECD calendar and region weights, system
prices, wind-farm FPN gaps), the data-pack round trip and its guards, an import test of every
module, and the licensed-data guard above. None needs data beyond `data/reference/`.

## Data caveats

- **CfD levy**: the billed Interim Levy Rate is set a quarter ahead and floors at zero, so the
  2022 payback never reached bills that year. Use `reconciled_levy_gbp_mwh` for economic
  incidence and `interim_levy_gbp_mwh` for what was billed.
- **Octopus Agile** is capped at 33.33 p/kWh (exc. VAT); the cap binds on 25.6% of half-hours in
  2021 and 57.6% in 2022. Filter on `at_price_cap` before using it as a price signal.
- **DUoS** charging statements are missing for some areas in 2018–2021 (table in
  `data/raw/manual/README.md`).
- **Day-ahead blend**: `dayahead_price_blend_{y}` weights N2EX and EPEX by traded volume only when
  `processed/n2ex_bid_panel_{y}.csv` exists, which this package does not build; otherwise it is a
  plain mean of the two.

## Data terms

The code licence does not cover data. Every file keeps the terms of its sources, and each data
pack's `MANIFEST.json` lists, per file, its `sources`, a `non_commercial` flag and a `check_terms`
flag, plus each source's licence and attribution. In summary (terms checked 5 Oct 2026):

| Source | Terms | Attribution | Files in the packs |
| --- | --- | --- | --- |
| Elexon BMRS | [BMRS open data licence](https://www.elexon.co.uk/bsc/data/balancing-mechanism-reporting-agent/copyright-licence-bmrs-data/) (commercial use allowed) | "Contains BMRS data © Elexon Limited copyright and database right [year]" | `demand`, `mid_target`, `system_prices`, `lolp_drm`, `forecast_state`, `wind_farm*`, `capacity_factors`, `capacity_factors_by_zone`, `agents` |
| NESO Data Portal | [NESO Open Licence](https://www.neso.energy/data-portal/neso-open-licence) (OGL-based, set per dataset) | source + licence link | `forecast_state`, GSP/DNO boundaries, `powerplants_located`, `agents` |
| LCCC | Open Government Licence v3.0 | source + licence link | `cfd_fleet`, `cfd_status`, `consumer_levy_*`, CfD register |
| DESNZ, ONS, gov.uk | Open Government Licence v3.0 | source + licence link | REPD, `domestic_supply_by_year`, gas and UK ETS prices in `fuel_prices` |
| Ofgem | Open Government Licence v3.0 | source + licence link | `cap_tariff_by_region`, `duos_domestic_tariffs` |
| powerplantmatching | CC BY 4.0 | source | `powerplants_*`, `regime_summary`, `cfd_ppm_matches`, `agents` |
| Copernicus PECD v4.2 | CC BY 4.0 | "Generated using Copernicus Climate Change Service information [year]" | `pecd/*`, `capacity_factors_pecd` |
| World Bank Pink Sheet | CC BY 4.0 | source | coal price in `fuel_prices` |
| ECB | reuse with source acknowledged | source | EUR→GBP in `fuel_prices` |
| **ESPENI** | **CC BY-NC 4.0: non-commercial only** | Wilson et al. (2021), *Energy Strategy Reviews*; [Zenodo](https://doi.org/10.5281/zenodo.4739408) | `demand`, `demand_by_zone`, `capacity_factors`, `capacity_factors_by_zone`; `espeni.csv` |
| **renewables.ninja** | **CC BY-NC 4.0: non-commercial only** | Pfenninger & Staffell (2016), *Energy* 114:1251–65; Staffell & Pfenninger (2016), *Energy* 114:1224–39 | `capacity_factors_by_zone` |
| EEX | **check**: substantial redistribution needs EEX's permission | — | EU carbon price 2018–20 in `fuel_prices` |
| Octopus Energy API | **check**: no published data licence | — | `consumer_levy_*` (tariff comparison) |
| DNO charging statements | **check**: no stated licence | — | the workbooks in the inputs pack |

What this means in practice:
- Sharing the packs for **academic, non-commercial** work is fine with attribution.
- A **commercial** user needs the ESPENI and renewables.ninja owners' permission for the four
  files that carry their values. We treat files that only use them as a weight (`cfd_fleet`'s
  CF-weighted delivery share) as LCCC data; a commercial user unsure about that should ask.
- Before a **public** release, clear the three **check** rows: EEX (or switch the 2018–20 carbon
  price to an openly licensed series), Octopus, and the DNO workbooks.

## Licence and citation

Code: [BSD 3-Clause](LICENSE), Imperial College London's preferred open-source licence.
Copyright © 2026, Imperial College, London. Data: see [Data terms](#data-terms).
Maintainer: Lukas Schirren, Imperial College London.
