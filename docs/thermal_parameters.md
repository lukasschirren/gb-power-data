# Thermal plant parameters for GB models

A unit-commitment or agent model of the GB market needs, for every thermal plant, a minimum stable level, ramp
rates, minimum up and down times, start-up costs and fuel by start type, an efficiency on the right heating-value
basis, outage rates and an emission factor. This repository collects them with their sources in two hand-curated
tables, and measures the dynamic ones for GB units from the Balancing Mechanism in a build stage.

| File | One row per | Made by |
| --- | --- | --- |
| `data/reference/thermal_parameters.csv` | technology x class x parameter x source (799 rows from 22 sources) | hand-curated, each value transcribed from a named sheet and cell or table and page |
| `data/reference/thermal_parameter_sources.csv` | source, with publisher, title, publication date, URL, date accessed and licence | hand-curated |
| `data/reference/bm_dynamic_by_tech.csv` | technology x metric x period (each year 2018-2025 and the pooled period) | `python -m gbpowerdata.build.bm_dynamic --pull` |
| `data/processed/bm_dynamic_units.csv` | snapshot x active thermal or pumped-storage BM unit (3,913 rows) | the same command |

## Reading the table

Each parameter is kept in one unit, so values compare across sources without conversion. Shares of capacity are
fractions, ramp rates are shares of capacity per minute, times are hours, start-up and shut-down fuel is MWh of fuel
per MW of capacity, and emission factors are tCO2 per MWh of fuel. Costs stay in the currency and price year the
source uses (`EUR/MW`, `USD2011/MW`, `GBP2021/MWh`), because converting them needs an exchange rate and a deflator
that belong to the model using them. The `status` column records how a value entered the table. `transcribed`
values are as printed, `converted` ones changed unit only (the source value is in `note`), and `derived` ones were
computed from data, such as the Elexon and JRC medians and the DUKES sent-out efficiency. The `basis` column carries
what a number means, such as the heating value of an efficiency, whether a start cost includes fuel, or which
statistic a median is.

`gb_default = yes` marks one recommended GB value per technology, parameter, year and commissioning period, and a test
keeps it unique. Year-specific defaults are the DUKES fleet efficiency by statistics year and the Capacity Market
de-rating by delivery year.

```python
import pandas as pd

t = pd.read_csv("data/reference/thermal_parameters.csv", dtype={"year": str})
gb = t[t["gb_default"] == "yes"]
ccgt = gb[(gb["technology"] == "ccgt") & gb["year"].isna() & gb["commissioned_from"].isna()]
```

## The GB defaults

| Parameter (unit) | CCGT | OCGT | Coal | Biomass | Nuclear |
| --- | --- | --- | --- | --- | --- |
| Minimum stable generation (share of capacity) | 0.47 | 0.87 | 0.46 | 0.47 | 0.82 |
| Ramp up / down (share of capacity per min) | 0.032 / 0.035 | 0.39 / 0.97 | 0.010 / 0.020 | 0.015 / 0.015 | 0.05 / 0.05 (E) |
| Start-up notice, NDZ (h) | 1.0 | 0.09 | 6.0 | 2.0 | - |
| Run-up from 0 MW to the minimum stable level (h) | 0.83 | 0.05 | 1.64 | 0.40 | - |
| Minimum up / down time (h) | 6 / 6 | 0.25 / 0.2 | 6 / 6 | 5 / 6 | 12 / 12 (E) |
| Start wear cost, hot / warm / cold (EUR/MW) | 21.9 / 25.1 / 36.0 (E) | 30.5 / 52.5 / 52.5 (E) | 49.3 / 69.7 / 94.0 (E) | - | warm 21 (E) |
| Start fuel, hot / warm / cold (MWh_th/MW) | 1.14 / 2.11 / 2.69 (E) | 0.56 any start (LF) | 2.92 / 5.00 / 5.83 (E) | - | warm 3.89 (E) |
| Hot start up to / warm start up to (h offline) | 8 / 48 (E) | 2 / 3 (E) | 12 / 72 (E) | - | - |
| Shut-down fuel (MWh_th/MW) | 0.74 (LF) | 0.42 (LF) | - | - | - |
| Efficiency | 0.469-0.482 GCV sent-out by year (DUKES); 0.41-0.49 GCV by commissioning period (JRC) | 0.26 GCV (JRC) | 0.34 NCV (PB) | 0.40 LHV (EGC 2016) | 0.33 NCV (E) |
| Availability, 2024/25 de-rating | 0.916 | 0.944 | 0.804 (2023/24) | 0.885 | 0.780 |
| Forced outage rate / planned outage (days a year) | 0.05 / 27 (E) | 0.08 / 13 (E) | 0.10 / 27 (E) | - | 0.05 / 54 (E) |
| VOM | 2 GBP2021/MWh (EGC 2023) | 1 GBP2021/MWh (EGC 2023) | - | - | - |

Unmarked dynamic values are medians of the GB BM units in 2018-2025 (Elexon), and the table holds their 10th and 90th
percentiles as `low` and `high`. (E) marks the ENTSO-E class that TYNDP 2026 assigns to GB plant (CCGT present 1, OCGT
old, hard coal old 1, nuclear). (LF) is Leigh Fisher and Jacobs (2016) and (PB) Parsons Brinckerhoff (2014), both for
DECC, and the availability row is the NESO Capacity Market de-rating factor of the T-1 auction. Emission factors are
fuel rows (`technology` = `fuel:natural_gas` and so on), with the DESNZ 2025 values 0.1846 tCO2/MWh GCV for gas
(the 100% mineral blend) and 0.3344 tCO2/MWh NCV for coal as defaults.

The choice follows four rules. Dynamic limits come from what GB units declare to NESO, since no other source
describes this fleet. Start costs, start fuel and the hot and warm thresholds come as one consistent set from
ENTSO-E, because their definitions differ between sources and mixing them would pair a cost with the wrong start
type. A UK source replaces ENTSO-E where it has no value (shut-down fuel) or where the two disagree tenfold (OCGT
start fuel, see Traps). Efficiencies and emission factors are on the basis of the fuel price they will be paired
with, which the next section explains.

## The heating-value basis

GB gas is bought per therm, a gross calorific value (GCV) unit, and DUKES reports plant efficiency on the same basis.
DESNZ's Electricity Generation Costs are HHV (the same as GCV) for non-renewables. ENTSO-E, the Danish Energy Agency,
Agora, JRC and the consultant reports behind the cost studies quote net calorific value (NCV, the same as LHV). The
API4 coal price the pipeline uses is net as received. DUKES gives the ratios of net to gross calorific value as
0.900 for natural gas, 0.950 for power-station coal, 0.940 for fuel and gas oil, and 0.924 for wood pellets
(`ncv_gcv_ratio` rows).

The short-run cost of a gas plant is (gas price per MWh GCV + carbon price x emission factor per MWh GCV) / efficiency
GCV, and every term must be on one basis. At 80 p/therm, or GBP 27.30 per MWh of gas, a CCGT at the DUKES 2023
sent-out efficiency of 0.479 burns GBP 57.0 of gas per MWh. The same plant described by its LHV efficiency of 0.532
appears to burn GBP 51.3, which is 10% too cheap. An NCV emission factor with GCV fuel overstates the carbon cost by
about 11% in the same way.

The fleet efficiency and the unit efficiencies agree once on one basis. JRC's OEM-derived efficiencies of 45 GB CCGT
units average 0.527 net LHV weighted by capacity, or 0.474 GCV, against the DUKES sent-out values of 0.474-0.482 for
2018-2024.

## Where the values come from

| Source | Region | What it gives | Licence |
| --- | --- | --- | --- |
| Elexon BM dynamic data (`elexon-bm-dynamic`) | GB units | declared SEL, run-up and run-down rates, NDZ, MZT and MNZT, summarised by `build.bm_dynamic` | BMRS data licence |
| DUKES 2026, Tables 5.10, 5.6, A.1 and A.2 | GB fleet | efficiency on GCV by year, sent-out ratio, calorific values | OGL v3.0 |
| DESNZ GHG conversion factors 2025 | UK | emission factors on GCV and NCV | OGL v3.0 |
| DESNZ and BEIS Electricity Generation Costs 2016, 2023 and 2025 | GB new build | efficiency (HHV), VOM | OGL v3.0 |
| CEPA and GHD (2025) for DESNZ | GB new build | efficiency (LHV) and availability of CCGT, OCGT and engines | values cited |
| Leigh Fisher and Jacobs (2016) for DECC | GB | CCGT start-up and shut-down fuel by start type, OCGT start and shut-down fuel | values cited |
| Parsons Brinckerhoff (2014) for DECC, two reports | GB | notice to synchronise and time to full load by start type, start-type definitions, coal minimum stable level, ramp and efficiency | values cited |
| NESO Capacity Market de-rating factors | GB | availability by technology class and delivery year | NESO Open Data Licence |
| JRC Open Power Plants Database v1.00 | GB units | net efficiency per unit (OEM, emissions or class derived) | CC BY 4.0 |
| ENTSO-E and ENTSOG, TYNDP 2026 Common Data | Europe | efficiency by class, minimum up and down times, start fuel and wear cost by start type, transition times, outages, minimum stable level, ramps | CC BY 4.0 |
| METIS Technical Note T6 (2017) | Europe | by build year (before 2000, 2000-2014, from 2015) minimum generation, ramps, start cost, minimum off time, efficiency at minimum and full load | reproduction allowed with acknowledgement |
| Kumar et al. (2012) for NREL | US | measured start costs (hot, warm, cold, with quartiles), start fuel, start-type windows | values cited |
| Schill, Pahle and Gambardella, DIW DP 1540 (2016) | Germany | minimum load, minimum off time, cold-start fuel, start depreciation | values cited |
| Agora Energiewende (2017) | Germany | minimum load, ramp rates and hot and cold start-up times, common and state-of-the-art plant | values cited |
| Danish Energy Agency technology data (2026) | Denmark | efficiency, minimum load, regulation rate, start-up times, outages, OCGT start cost | CC BY 4.0 |
| PyPSA-Eur `unit_commitment.csv`, PyPSA technology-data v0.15.0 | Europe | the values PyPSA uses, kept for comparison | CC BY 4.0; data under the input sources' terms |

The full citation, URL and access date of each are in `thermal_parameter_sources.csv`. Values from sources without an
open licence are cited facts with their locators, and no document is redistributed.

## Compared with PyPSA

PyPSA keeps cost and efficiency data in technology-data and the unit-commitment parameters in PyPSA-Eur's
`data/unit_commitment.csv`, revised in February 2026 (PR #2073) with DIW DP 1540, IRENA (2019) and Agora (2017) as
sources. Technology-data has no start, ramp or minimum-load values, and its efficiencies are single new-build values
without vintages.

| Parameter | PyPSA | GB default | Difference |
| --- | --- | --- | --- |
| CCGT minimum stable level | 0.45 | 0.47 | close |
| CCGT ramp | 1 per hour | 1.9 per hour up, 2.1 down | neither binds at hourly resolution |
| CCGT minimum up / down | 4 / 2 h | 6 / 6 h | GB units declare 6 h, a convention tied to their service agreements |
| CCGT start cost | 60 EUR/MW, one start type, no fuel | 21.9 / 25.1 / 36.0 EUR/MW wear plus 1.14 / 2.11 / 2.69 MWh_th/MW of fuel | PyPSA's 60 is DIW's start depreciation, close to Kumar's cold-start median x 0.75 (79 x 0.75 = 59) |
| OCGT minimum stable level | 0.20 | 0.87 | GB OCGT units are small turbines run at fixed output |
| Coal minimum stable level / up and down | 0.38 / 8 and 8 h | 0.46 / 6 and 6 h | |
| Coal ramp | 0.9 per hour | 0.6 per hour up | |
| Nuclear minimum stable level | 0.50 | 0.82 of capacity (0.91 of MEL) | GB AGRs barely turn down |
| Nuclear start cost | 250 EUR/MW including fuel | 21 EUR/MW wear plus 3.89 MWh_th/MW fuel | PyPSA's other start costs exclude fuel |
| CCGT efficiency | 0.57, new build, net LHV | 0.47-0.48 GCV fleet (about 0.53 LHV) | new build against a 1990s-2010s fleet, and a different basis |
| OCGT efficiency | 0.405, new build | 0.26 GCV, existing units | |
| Coal efficiency | 0.356 (from a Lazard heat rate) | 0.34 NCV | |
| Gas emission factor | 0.198 tCO2/MWh (stoichiometric, LHV) | 0.1846 GCV, 0.2045 NCV (DESNZ) | |
| CCGT VOM | 5.744 EUR2025/MWh | 2 GBP2021/MWh (EGC 2023); 5 GBP2024/MWh in EGC 2025 | |

## What changed in tech_parameters.yaml (7 Oct 2026)

Until 7 October 2026 `tech_parameters.yaml` gave gas plant an efficiency by commissioning year (CCGT 0.46 in 1990 to
0.55 in 2020) or a default of 0.50. Stage 3 averaged 0.504 over the 2023 CCGT fleet weighted by capacity. With the gas
price in p/therm that was 2.5 points above the DUKES 2023 sent-out value of 0.479, so the fuel and carbon cost of gas
plant came out about 5% low. The file now takes its values from this table, on the basis of each fuel's price.
The CCGT anchors are the JRC medians by commissioning period converted to GCV, plus a 2023 anchor for new-build H class
(EGC 2025, 0.54 HHV). The CCGT default is the DUKES 2018-2024 mean sent-out value of 0.479, and the OCGT anchors and
default are the former LHV-type values x 0.900. Coal is 0.34 NCV (PB 2014) with the DESNZ NCV emission factor of
0.334, matching the API4 net price. Stage 3 multiplies the three measured powerplantmatching efficiencies of GB gas
plants by 0.900 (`ppm_efficiency_basis_factor`) and now gives the CCGT fleet 0.473-0.474 weighted by capacity in
every year 2018-2025. The gas emission factor of 0.184 already was the DESNZ GCV value for the mineral
blend. The 20% CCGT minimum stable level in `tech_flexibility_empirical.csv` is the 10th percentile of daily minimum
over maximum CCGT output. It measures how far the fleet turns down by switching units off, whereas a unit's own minimum
is 0.47 of its capacity.

## Traps met while building the table

Several values that look independent probably trace to one study. Kumar et al. (2012) measured US start costs, and
every Kumar value in DIW Data Documentation 68 equals their median x 0.75 EUR per USD, printed under the heading of
fuel-related costs. Four of the six start depreciation values in DIW DP 1540, which PyPSA-Eur uses, equal Kumar
medians x 0.75 to within 1 EUR/MW, which is a numerical match and not a stated source. PyPSA-Eur's `start_up_cost`
mixes depreciation-only values (OCGT, CCGT, coal, lignite) with one total that includes fuel (nuclear). Its nuclear and
lignite start-up ramp limits (0.2 and 0.4) lie below their minimum stable levels (0.5). Under PyPSA's documented
committable constraints such a unit could neither start nor stop, which follows from the documentation and was not
tested here.

ENTSO-E's vintage classes are efficiency bins that each TSO picks, and its guidelines say commissioning dates are not
used. For OCGT start fuel, ENTSO-E and Kumar's large frame turbines give about 0.06 MWh_th/MW, while Leigh Fisher's
cold 20-minute start gives 0.56 and Kumar's aeroderivatives 0.45, so the GB default takes Leigh Fisher. The 2023
Electricity Generation Costs calculator labels an HHV efficiency "Net efficiency (LHV)", and the 2025 calculator holds
an LHV efficiency but converts it with the gross therm, which understates fuel burn by about 10%. JRC dates
Peterhead, Fellside and Cottam Development Centre to 1899, so the vintage medians leave out units without a plausible
commissioning year.

The BM dynamic parameters are declarations. Ofgem found SELs inflated to raise Balancing Mechanism payments (InterGen
2020, EDF West Burton B 2020, ESB Carrington 2021). SEL over MEL is higher for units at zero, so the minimum stable
level counts running units only. A value of 999, the top of the valid range, means a unit will not start at notice
and is left out of the summaries. A snapshot finds some units hot and some cold, so NDZ and the run-up time mix start
types, and nuclear units declare SEL and nothing else. The register behind the summaries was built from Elexon's 2026
unit list, which no longer carries Aberthaw B, Cottam or Eggborough. The coal rows therefore describe Drax 5-6,
Fiddler's Ferry, Ratcliffe-on-Soar and West Burton A, and the 2018 and 2019 registers held about 5.5 GW and 3.5 GW less
coal than operated. Since 14 Oct 2026 the register adds the three stations, and Deeside's CCGT, from
`data/reference/bmu_left_register.csv`, so the next build of `bm_dynamic` takes them into the coal and CCGT rows, and
the GB rows here are to be checked then.

## Using the values in a model

In PyPSA the defaults map to `p_min_pu` (minimum stable generation), `ramp_limit_up` and `ramp_limit_down` (the rate
per minute x 60, capped at 1 for hourly snapshots), `min_up_time` and `min_down_time` (in snapshots), and
`start_up_cost` per MW of `p_nom`. The start cost per MW of a start type is its wear cost plus its start fuel times the
fuel price and the carbon cost of that fuel. All terms are on the basis of the fuel price.

In ASSUME's `PowerPlant` the same arithmetic gives `hot_start_cost`, `warm_start_cost` and `cold_start_cost` per MW
(ASSUME multiplies them by `max_power`), with `downtime_hot_start` and `downtime_warm_start` from the hot and warm
thresholds. `min_power` is the minimum stable level times `max_power`, and `min_operating_time` and `min_down_time` are the
minimum up and down times. ASSUME limits the change in output between two market time steps to `ramp_up` and
`ramp_down` MW. That is the rate per minute x `max_power` x 60 for hourly products and x 30 for half-hourly ones. ENTSO-E's costs are in euros of an unstated year and Kumar's in 2011 US dollars, so convert them with the
model's own exchange rate and deflator.

## Rebuilding

`python -m gbpowerdata.build.bm_dynamic --pull` rebuilds the GB rows from the BM data. It fetches 32 snapshots into
`raw/bm_dynamic/` (about 0.5 MB each) and writes the unit table and the summary. The snapshots are settlement period
24 on the 15th of January, April, July and October of 2018-2025. `tests/test_thermal_parameters.py` then checks that
the GB defaults in `thermal_parameters.csv` still equal the summary, so a rebuild that moves a median shows up as a
failing test until the curated table is updated by hand.
