# Storage revenues: what batteries and pumped storage earned, from public data

Two tables, built from public data only (Elexon, NESO), one per year:

| Table | One row per | Use it for |
| --- | --- | --- |
| `storage_revenue_{y}` | storage unit in the Balancing Mechanism (BM) x month: the T_ and E_ units, and the batteries traded through supplier (2__) and virtual lead party (V__) units (`kind`) | what each battery and pumped storage unit earned, by market; a check on a model's storage revenues; which traders and optimisers earn the most per MW |
| `ancillary_by_unit_{y}` | unit x service x delivery period | the MW each unit held for frequency response and reserve, the price, the payment and the company that bid it (an input to a model: capacity held for these services is not offered in the energy markets) |

They are built by `python -m gbpowerdata.build.ancillary_services` and `python -m gbpowerdata.build.storage_revenues`
after the pulls `ancillary_pull` and `ebocf_pull` (and `fpn_pull`, `elexon_pull mid`, `system_price_pull`,
`bm_units`, `build_ownership`), with `storage_fleet` built before `ebocf_pull` and `fpn_pull --storage-fleet` (for the
supplier and virtual lead party batteries) and again after them, and read with
`processed.read_storage_revenue(year, annual=False)` and `processed.read_ancillary_by_unit(year)`. The method is in
the docstrings of `build/storage_revenues.py` and `build/ancillary_services.py`; this note is the overview.
`storage_revenue_{y}` is in the processed data pack; `ancillary_by_unit_{y}` is not (0.7 GB for 2019-2026): the two
commands above rebuild it from public data in about ten minutes.

## Why

A battery earns in three places: the wholesale market, the Balancing Mechanism and the services NESO buys to hold
frequency and reserve. Which of them pays most has changed fast (Dynamic Containment paid most of a GB battery's
revenue in 2021 and 2022, the wholesale market and the BM after its prices fell), and a model of storage should
earn about what the fleet earned, in about the same shares. Commercial services estimate this per asset (Aurora's
Flexplorer, Modo's index) for their subscribers. This layer does the same from public data, every stream in its own
column, so a model can be compared on the markets it has.

## Streams

| Column | What | Source |
| --- | --- | --- |
| `wholesale_gbp` | the unit's position as notified before gate closure (its final physical notification: the net of what it traded day-ahead and intraday), valued at Elexon's market index price; discharging earns, charging costs | Elexon PN (`fpn_pull`), MID APX (`elexon_pull mid`); where the MID has no volume, the system price (`price_fallback_share`) |
| `bm_offer_gbp`, `bm_bid_gbp` | the cashflow of accepted BM offers and bids: positive paid to the unit, negative paid by it | Elexon EBOCF, indicative period BM unit cashflows (`ebocf_pull`) |
| `bm_offer_mwh`, `bm_bid_mwh` | the accepted volumes behind them (offers positive, bids negative): the notified energy plus these is the unit's position after the BM; empty without the volume files | Elexon DISPTAV, indicative period BM unit volumes, "Original" data type (`ebocf_pull --dataset volumes`) |
| `anc_dc_gbp`, `anc_dm_gbp`, `anc_dr_gbp` | Dynamic Containment, Moderation, Regulation: MW x clearing price x hours | NESO DC tenders (2020-21), DC/DM/DR auctions (2021-23), Enduring Auction Capability (from Nov 2023) |
| `anc_sffr_gbp`, `anc_dffr_gbp` | static and dynamic Firm Frequency Response: the monthly tenders' accepted fees (GBP/h) x the hours of their frames, the weekly and day-ahead auctions' MW x clearing price x hours | NESO FFR post-tender reports (January 2019 to November 2023), the weekly FFR auctions (Dec 2019 to Nov 2021), SFFR auctions (from Apr 2023) |
| `anc_qr_gbp`, `anc_sr_gbp`, `anc_br_gbp` | Quick, Slow and Balancing Reserve availability | NESO EAC (QR from 2024, SR from 2026), Balancing Reserve (from Mar 2024) |
| `anc_stor_gbp` | Short-Term Operating Reserve availability: contracted MW x clearing price x the hours of the service day's committed windows | NESO's daily STOR auctions and STOR windows (from Apr 2021); storage units held little of it (GBP 0.4m in 2022) |
| `total_gbp` | the sum: a gross margin before network charges, optimisers' fees, Capacity Market payments and imbalance | |
| `wholesale_imrp_gbp` | the same notified position valued at LCCC's Intermittent Market Reference Price instead of the MID: the GB day-ahead hourly price, since 2021 the N2EX and EPEX SPOT auction prices weighted by their traded volumes; not in `total_gbp` | LCCC data portal "imrp-actuals", Open Government Licence (`lccc_pull imrp-actuals`) |
| `cm_gbp`, `cm_obligation_mw` | the Capacity Market payments of the agreements linked to the unit, and the de-rated obligation behind them, from the month the unit entered the market (outages included); an entitlement before suspensions and penalties; not in `total_gbp` | `capacity_market_{y}` and `capacity_market_links` (`build.capacity_market`: NESO's register, the Capacity Regulations' formula, LCCC's payments, ONS's CPI) |
| `gbp_per_kw_yr` | `total_gbp` per kW of registered capacity at an annual rate (x 365 / days active); none for a supplier or virtual lead party unit, whose capacity is the largest MW NESO accepted it for (`capacity_source` `ancillary_max_mw`, a lower bound) | |
| `trading` | whether the unit did anything in these markets in the month: a notified position, a BM cashflow or an ancillary payment | |
| `has_fpn`, `fpn_coverage` | whether the unit's notifications reach the end of the month (else its MWh and `wholesale_gbp` are empty), and the share of the month's half-hours inside its activity that hold a notification (below 1 in the months Elexon's archive misses whole days) | Elexon PN |

A clearing price below zero makes a payment negative: Dynamic Regulation (high) cleared below zero in many blocks of
winter 2023/24 and 2024 (down to GBP -15/MW/h), when providers paid to hold the service, and the table keeps NESO's
prices as published (GBP -11.6m for the batteries' DR in 2024).

A battery's energy is in two columns: what it traded before gate closure (its notified position, `wholesale_gbp`)
and what the system operator moved it by after (`bm_offer_gbp`, `bm_bid_gbp`). In 2025 the BM was a fifth of the
T_ and E_ batteries' revenue here (offers GBP 69.5m, bids GBP -37.7m) and a quarter of the supplier and virtual lead
party batteries' (GBP 31.3m, -10.6m).

The notified and accepted positions are not the whole physical one. Over the batteries with notified energy, MWh
discharged per MWh charged by the notifications (and with the accepted BM volumes, `bm_offer_mwh` and `bm_bid_mwh`):

| Year | T_ and E_ batteries | supplier units (2__) | virtual lead party units (V__) |
| --- | --- | --- | --- |
| 2021 | 1.14 (1.31) | 1.41 (1.39) | 0.85 (0.61) |
| 2022 | 1.13 (1.14) | 1.46 (1.54) | 0.86 (0.92) |
| 2023 | 0.96 (0.97) | 1.02 (1.07) | 0.70 (0.73) |
| 2024 | 1.24 (1.34) | 1.02 (1.09) | 0.25 (0.31) |
| 2025 | 1.22 (1.23) | 0.91 (1.04) | 0.23 (0.28) |

A battery returns less than it takes in, so in most years the T_ and E_ batteries charged, and since 2024 the
virtual lead party batteries discharged, outside their notified and accepted positions: an inference, at the system
price (imbalance) or through another unit's position, which no public data give per unit. In 2025, 15 of the 21
virtual lead party batteries discharged less than half as much as they charged by their positions, and their
`wholesale_gbp` is GBP -12.8m (the supplier units' +11.9m); `total_gbp` misses what they sold outside the positions
([AUDIT.md](AUDIT.md) A9-11). With the accepted volumes, the median battery's daily state-of-charge swing stays within
1.25 times its stated MWh on 95% of days, against 87% from its notifications alone (71 units, 2022-2025; A9-8).

The MID is Elexon's market index (the volume-weighted price of the half-hour's short-term trades on EPEX GB),
published by Elexon on its terms. Nothing from the licensed day-ahead auctions (N2EX, EPEX SPOT) is read, so the
tables may be shared on the terms of Elexon's and NESO's data; `tests/test_storage_revenues.py` checks that the
build code names none of the licensed tables.

How much the choice of price matters can be read from open data: LCCC publishes the day-ahead reference price it
settles intermittent CfDs against (the IMRP, hourly from June 2016, under the OGL), and `wholesale_imrp_gbp` values
the positions at it. Notified positions, GBP m (built 10 Oct 2026):

| Year | T_/E_ batteries at the MID | at the IMRP | supplier and VLP batteries at the MID | at the IMRP | Pumped storage at the MID | at the IMRP |
| --- | --- | --- | --- | --- | --- | --- |
| 2018 | 0.33 | 0.33 | | | -7.28 | -6.69 |
| 2019 | 0.81 | 0.83 | 0.04 | 0.04 | 17.22 | 18.80 |
| 2020 | 0.48 | 0.47 | 0.03 | 0.05 | 37.52 | 37.70 |
| 2021 | 2.88 | 4.50 | 5.06 | 8.03 | 88.97 | 124.88 |
| 2022 | 8.28 | 9.69 | 14.56 | 16.79 | 140.21 | 157.14 |
| 2023 | 14.99 | 14.98 | 7.62 | 7.30 | 119.83 | 116.38 |
| 2024 | 37.37 | 39.75 | 5.68 | 6.39 | 126.38 | 124.94 |
| 2025 | 62.59 | 66.11 | -0.83 | 0.67 | 124.20 | 124.05 |

The day-ahead price values the T_ and E_ batteries' positions 6% higher in 2024 and 2025, 17% higher in 2022 and 56%
higher in 2021; in 2020 and 2023 the two agree to 2%. Which is nearer what a battery earned depends on when it traded,
which the public data do not show.

With a Nord Pool or EPEX SPOT subscription, `python -m gbpowerdata.build.storage_revenues_dayahead` values the same
notified positions at each day-ahead auction's price instead (N2EX, EPEX hourly, EPEX half-hourly and their
volume-weighted blend, one column each, never mixed in one series) and writes `storage_revenue_dayahead_{y}`, which
stays local: its name carries "dayahead", which `.gitignore`, `tests/test_repo_hygiene.py` and the data pack's
licensed-data guard refuse. The two valuations answer different questions: the MID prices the position at the
short-term trades of the half-hour, the auctions at the price of trading all of it the day before; a battery that
moves its position after the auction earns neither exactly.

## Capacity Market payments

A Capacity Market payment is an entitlement, not trading income: a de-rated obligation (MW) paid at its auction's
clearing price, indexed to CPI for T-4 and T-3 auctions, and spread over the delivery year by monthly weighting factors
(The Electricity Capacity Regulations 2014, Schedule 1). `python -m gbpowerdata.build.capacity_market` computes it
for every agreement in NESO's register (`capacity_market_{y}`). Summed by auction and delivery year, it comes 0.4-5.5%
above what LCCC reports as paid in the 15 auction years where new build takes under 15% of the payments: suspended
agreements are paid nothing, and new build only once built, which the register does not date. `cm_gbp` gives each BM unit the
payments of the agreements linked to it, from the month it entered the market. GBP m, built 10 Oct 2026:

| Year | Batteries: BM units (`cm_gbp`) | all battery agreements | Pumped storage: BM units | all pumped storage agreements |
| --- | --- | --- | --- | --- |
| 2018 | 0.01 | 0.26 | 28.85 | 28.85 |
| 2019 | 0.08 | 0.61 | 54.79 | 54.79 |
| 2020 | 0.64 | 3.44 | 53.11 | 53.11 |
| 2021 | 2.59 | 13.84 | 50.55 | 50.55 |
| 2022 | 5.04 | 24.63 | 27.28 | 27.28 |
| 2023 | 13.17 | 43.44 | 34.50 | 34.81 |
| 2024 | 18.30 | 52.05 | 52.98 | 54.16 |
| 2025 | 14.39 | 53.59 | 56.07 | 69.45 |

Most battery agreements belong to distribution-connected batteries outside the BM (Non CMRS), which no unit here
stands for, and their total includes new build, which is paid only once built: an upper bound. In 2025, pumped
storage's gap is Ffestiniog unit 3, refurbishing and not in the BM units of the year. For a battery agent, a new
battery's payment per kW is its duration class's de-rating factor (`capacity_market_derating`) times the auction's
price (`capacity_market_auctions`): the T-4 auction for 2029/30 cleared at GBP 27.10/kW/yr with 2-hour storage
de-rated at 0.2198, GBP 5.96 per kW of a 2-hour battery a year before indexation.

## Units, traders and optimisers

The units are the battery and pumped storage units active in the year in `bm_unit_register_{y}` (T_ and E_ units,
`kind` "bm"), with their registered capacity, lead party and `trader` (the lead party's group in
`ownership_bmu_{y}`), and the supplier (2__) and virtual lead party (V__) batteries of `storage_fleet` from their
first result in NESO's services (the evidence that the unit is a battery) to the last date they were seen, with the
name and lead party Elexon's register gives them, no trader (the ownership tables cover T_ and E_ units) and as
capacity the largest MW NESO accepted them for, a lower bound (`capacity_source`). A supplier or virtual lead party
unit can hold several sites (EDF's "Aggregate Eastern 02"). `optimiser`
is the group of the company that bid the unit into NESO's auctions, with the largest payments in the month: the
lead party of a battery is often its owner's project company, while the company that trades it is an optimiser
(Tesla, Habitat Energy, EDF, Statkraft). Both are grouped by the ownership tables' rules and spellings.

## What it leaves out

| Gap | Direction |
| --- | --- |
| Trading skill and re-trading: the whole notified position is valued at one index price, so a trader that bought low and sold high within the day is credited with the index only; tolls, floors and fees between owner and optimiser are not seen | either |
| Days missing from Elexon's archive of physical notifications, for every unit at once (Elexon's PN stream returns them empty today too): 2 Oct and 9-10 Nov 2018, 9-18 Jan and 9-10 Aug 2019, 10 Jan, 7 and 20 Jul 2020, 18 days of November 2020, eight days of February and two of March 2021. The MWh and `wholesale_gbp` count the notified half-hours only; `fpn_coverage` is the notified share of the month (0.40 in November 2020, 0.71 in February 2021, 1.00 from April 2021), so divide by it for an estimate of the whole month | wholesale too low in those months (batteries: at most GBP 0.03m a year; pumped storage more) |
| Imbalance: metered output that differs from the notified and accepted position is settled at the system price; Elexon publishes each battery unit's metered output (B1610: `b1610_pull --storage-fleet`, `generation_battery_{y}`), not yet valued here | either, small for a unit that follows its instructions |
| Capacity Market payments in `total_gbp`: they are in `cm_gbp`, for the units an agreement is linked to (by component id, or by name for CMRS units: an inference, `capacity_market_links`); a unit whose CMU names it otherwise has none | `cm_gbp` too low for unlinked units |
| What a battery charges or discharges outside its notified and accepted positions, at the system price (imbalance) or through another unit: by their positions the T_ and E_ batteries discharged 1.23 MWh per MWh charged in 2025, the virtual lead party batteries 0.28 (A9-11) | either |
| Ancillary services before 2019 (the columns are empty, not zero, before then: `ancillary_published`), FFR contracts accepted before December 2018 that ran into 2019 (the tender reports on NESO's portal begin with round TR108), and the Enhanced Frequency Response contracts of the 2016 tender (eight batteries, 201 MW, GBP 9.44/MW/h on average; no unit-level table, and their actual start and end dates are not published) | total too low before 2021 |
| FFR tenders valued as accepted: within 6% of what NESO paid for Dynamic FFR in every month of 2023/24, 70% above its FFR spend in 2022/23 ([AUDIT.md](AUDIT.md) A10-5) | FFR too high in 2022/23 |
| Batteries outside the BM (non-BM units sell only to NESO): they are in `ancillary_by_unit_{y}` but not in `storage_revenue_{y}` | fleet too small |
| A supplier or virtual lead party unit's activity before its first result in NESO's services (13 such units traded in the BM more than 90 days before it, GBP 4.4m of BM cashflows in 2019-2026, most of it units that held other sites first, such as UK Power Reserve's East Midlands unit) | either |

Payments for frequency response and reserve to the units `storage_fleet` classes as batteries, by kind of unit
(`ancillary_by_unit_{y}`; FFR from 2019, the other services from October 2020):

| Year | GBP m | of which FFR | T_ and E_ units | supplier and VLP units (2__, V__) | non-BM units (not in `storage_revenue`) |
| --- | --- | --- | --- | --- | --- |
| 2019 | 6 | 6 | 43% | 22% | 35% |
| 2020 | 30 | 20 | 18% | 35% | 47% |
| 2021 | 106 | 17 | 16% | 45% | 40% |
| 2022 | 190 | 54 | 25% | 49% | 27% |
| 2023 | 87 | 16 | 37% | 40% | 23% |
| 2024 | 63 | 0 | 29% | 36% | 35% |
| 2025 | 158 | 0 | 39% | 37% | 24% |

So `storage_revenue_{y}` describes the storage fleet in the BM, T_ and E_ units and the batteries traded through
supplier and virtual lead party units, not every battery in Great Britain: the non-BM batteries' payments are in
`ancillary_by_unit_{y}` alone.

A pumped storage station registers its units separately, and some register their pumping as a unit of its own
(Cruachan's T_CRUAD-1, 1 MW of generation capacity): a unit under 2 MW gets no `gbp_per_kw_yr`, and a station's
units should be added up before comparing it.

## Results

Batteries (T_ and E_ units of at least 2 MW), from `storage_revenue_{y}`; GBP/kW/yr is capacity- and
day-weighted over the months a unit traded (`trading`), as an index of operating assets would count them:

| Year | Units | GW | GBP m | GBP/kW/yr | Wholesale | BM | Ancillary | Capacity-days not trading |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2018 | 2 | 0.07 | 1.0 | 48 | 34% | 66% | not published | 0% |
| 2019 | 5 | 0.17 | 4.4 | 40 | 18% | 34% | 47% (FFR) | 30% |
| 2020 | 6 | 0.18 | 6.7 | 56 | 7% | 25% | 68% | 33% |
| 2021 | 10 | 0.36 | 20.5 | 106 | 14% | 8% | 78% | 23% |
| 2022 | 24 | 0.87 | 56.4 | 118 | 15% | 2% | 83% | 9% |
| 2023 | 44 | 1.79 | 52.8 | 44 | 28% | 13% | 59% | 1% |
| 2024 | 63 | 2.85 | 73.0 | 38 | 51% | 27% | 21% | 7% |
| 2025 | 101 | 5.20 | 153.6 | 54 | 41% | 21% | 39% | 20% |

The supplier and virtual lead party batteries (their capacity a lower bound, so no GBP/kW/yr):

| Year | Units | GW (at least) | GBP m | Wholesale | BM | Ancillary | Capacity-days not trading |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2019 | 6 | 0.10 | 1.4 | 3% | 7% | 90% | 0% |
| 2020 | 13 | 0.31 | 10.4 | 0% | 1% | 99% | 0% |
| 2021 | 22 | 0.61 | 53.7 | 9% | 2% | 88% | 7% |
| 2022 | 34 | 0.95 | 110.3 | 13% | 3% | 84% | 5% |
| 2023 | 40 | 1.13 | 46.2 | 16% | 9% | 75% | 6% |
| 2024 | 59 | 1.74 | 37.6 | 15% | 24% | 60% | 7% |
| 2025 | 69 | 1.99 | 78.4 | -1% | 26% | 75% | 3% |

Before 2021 the batteries were paid mostly by FFR (in the data from January 2019) and the EFR contracts (not in the
data), so those years' margins are too low by the EFR income; the FFR tenders are valued as accepted, which in
2022/23 is well above what NESO paid ([AUDIT.md](AUDIT.md) A10-5).
In 2025, 24 batteries (1.38 GW) were registered and notified only zeros without a BM cashflow or an ancillary payment:
Coalburn's five units (from October), Uskmouth's four (from September), Thornton Battery, KXP Immingham, Whitegate,
Neilston, Indian Queens and others. Seven of them first appear in the BM cashflows during 2026 (KXP Immingham from
February, Whitebirk from March, Broxburn from May, Cathkin from June, Coalburn from July, Torquay and Whitegate from
September); the others not by 6 October 2026. Pumped storage (Dinorwig, Ffestiniog, Cruachan, Foyers) earned
GBP 160.7m in 2025 by the same streams, GBP 288.5m in 2022.

The benchmarks the tests use are free and official: NESO's annual spend on each response and reserve service
(`data/reference/official_statistics.csv`; the ancillary columns are awards, 7-38% above what NESO paid by service,
[AUDIT.md](AUDIT.md) A10-2) and DESNZ's battery capacity (DUKES 5.16). Nothing in the pipeline reads commercial
indices. As an optional, anecdotal cross-check only, against the figures Modo quotes for its GB BESS index in its
free research notes (GBP thousand per MW per year):

| Month | This table, trading units | Modo |
| --- | --- | --- |
| Jan 2024 | 20 | 36 |
| Dec 2024 | 76 | 84 (76 without the Capacity Market) |
| Jan 2025 | 78 | 88 |
| Oct 2025 | 56 | 77 |
| Nov 2025 | 43 | 59 |

Modo gives December 2024 without the Capacity Market too, GBP 76,000 (its January 2025 research roundup), the same
as this table's. The months move together, and the shares agree: the wholesale market and the BM are 62% of the
batteries' 2025 total here and "around 60%" of Modo's stack over the twelve months to April 2026. In the other
months the level is GBP 10,000-21,000 per MW per year lower here. Modo includes Capacity Market payments and
imbalance, counts virtual lead party units, and values the notified position at the average of the N2EX and EPEX
day-ahead auctions and EPEX's continuous index (its methodology page, https://modoenergy.com/methodology/gb), where
this table uses Elexon's market index; how much of the gap each of these makes is not known here.

By trader and by optimiser, 2025 (trading months, at least 150 MW):

| Trader (lead party's group) | GW | GBP/kW/yr | | Optimiser (bidder's group) | GW | GBP/kW/yr |
| --- | --- | --- | --- | --- | --- | --- |
| Tesla | 0.54 | 79 | | Tesla | 0.64 | 79 |
| Zenobe | 0.68 | 61 | | Habitat Energy | 0.22 | 60 |
| EDF | 0.71 | 51 | | EDF | 1.24 | 56 |
| Octopus | 0.16 | 48 | | Octopus | 0.16 | 46 |
| Arenko Cleantech | 0.28 | 39 | | Arenko Cleantech | 0.47 | 46 |
| Statera | 0.40 | 37 | | Statkraft | 0.40 | 39 |

The optimiser column counts a battery under the company that bid it into NESO's auctions, the trader column under
the company registered to trade it in the BM. They differ for half
the 2025 capacity that has an optimiser (1.76 of 3.53 GW): Zenobe's sites are bid into NESO's auctions by EDF
(0.63 GW) and Statera's by Statkraft (0.40 GW). 1.67 GW held no ancillary contract in 2025 and has no optimiser.

## The fleet: `storage_fleet`

`python -m gbpowerdata.build.storage_fleet` lists every battery and pumped storage unit the open data name, for a
model of entry and exit: the BM units (T_, E_) and the supplier (2__), virtual lead party (V__) and non-BM units that
sold to NESO, with capacity (MW), energy (MWh) where an open source states it, and dates. `entry_date` is the first
evidence of trading: the first non-zero notification, BM cashflow or accepted ancillary MW, whichever comes first;
`registered_from` (the first record of the unit's notifications, zeros included) bounds its registration, since Elexon
publishes no registration date. A unit known only from NESO's results gets no exit date (one that stops appearing
there may have moved to a BM unit or to the energy markets), and `operating(fleet, date)` counts it only while seen.

Energy comes from the maximum delivery volume (MDV) a unit declares in its BM dynamic data
(`bm_dynamic_pull [dates]` and every submission, `--submissions`; 0, 1 and 99,999 are placeholders), else from the
Capacity Market register's storage duration class: of a component that carries the unit's id, of the agreement
`capacity_market` links to the BM unit by name, or, for a battery outside the BM units, of the storage components at
the postcode NESO's EAC results give it (`cm_duration_basis`). On 10 Oct 2026, 238 of the 395 batteries had one, 72% of
their capacity (129 from MDV; 109 from the CM class: 75 by postcode, 31 by link, 3 by component id), median 1.5 hours;
where a unit has both, MDV divided by capacity matches the CM class within half a class for 59 of 65 units (all 15
linked by component id).
DESNZ states it has no reliable source for battery energy capacity (Grid-scale battery storage statistics, 30 Jun
2026); NESO's FES 2025 puts the 2024 GB fleet at 6.8 GW and 8.8 GWh.

Battery capacity trading at the end of each year (`operating`) against DESNZ's UK grid-scale battery capacity
(DUKES 2026, Table 5.16.C):

| Year | This table, GW | of which BM (T_, E_) | DUKES 5.16, GW | Share |
| --- | --- | --- | --- | --- |
| 2018 | 0.07 | 0.07 | 0.63 | 11% |
| 2019 | 0.54 | 0.19 | 0.88 | 61% |
| 2020 | 0.93 | 0.20 | 1.10 | 85% |
| 2021 | 1.34 | 0.38 | 1.54 | 87% |
| 2022 | 2.31 | 0.89 | 2.32 | 100% |
| 2023 | 3.79 | 1.90 | 3.82 | 99% |
| 2024 | 4.87 | 2.33 | 5.21 | 93% |
| 2025 | 6.64 | 3.81 | 7.51 | 88% |

Before 2019 only BM units are visible (NESO's unit-level results begin with the FFR tenders for January 2019), so
2018 is short by the batteries that sold only frequency response (and those on the EFR contracts); DUKES counts the
UK and includes sites that trade only energy behind a supplier, which no open source here lists.

## Using it to check a model

- Compare like with like: a model of the day-ahead market alone is compared with `wholesale_gbp` (and the BM
  columns if the model has a balancing stage), not with `total_gbp`; the ancillary columns say how much of the
  fleet's income came from markets the model does not have.
- `annual=True` gives one row per unit, with `gbp_per_kw_yr` over all its days and `gbp_per_kw_yr_trading` over
  the months it traded; add units up by `trader` or `optimiser` for company-level margins, and weight by capacity
  x days (or trading days). A fleet average over trading months is the one to set against commercial indices.
- `ancillary_by_unit_{y}` gives, per unit and EFA block (4 hours) or half-hour, the MW committed to each service:
  the capacity a battery agent should hold out of the energy markets in those hours.
