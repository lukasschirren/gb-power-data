# Storage revenues: what batteries and pumped storage earned, from public data

Two tables, built from public data only (Elexon, NESO), one per year:

| Table | One row per | Use it for |
| --- | --- | --- |
| `storage_revenue_{y}` | storage unit in the Balancing Mechanism (BM) x month | what each battery and pumped storage unit earned, by market; a check on a model's storage revenues; which traders and optimisers earn the most per MW |
| `ancillary_by_unit_{y}` | unit x service x delivery period | the MW each unit held for frequency response and reserve, the price, the payment and the company that bid it (an input to a model: capacity held for these services is not offered in the energy markets) |

They are built by `python -m gbpowerdata.build.ancillary_services` and `python -m gbpowerdata.build.storage_revenues`
after the pulls `ancillary_pull` and `ebocf_pull` (and `fpn_pull`, `elexon_pull mid`, `system_price_pull`,
`bm_units`, `build_ownership`), and read with `processed.read_storage_revenue(year, annual=False)` and
`processed.read_ancillary_by_unit(year)`. The method is in the docstrings of `build/storage_revenues.py` and
`build/ancillary_services.py`; this note is the overview. `storage_revenue_{y}` is in the processed data pack;
`ancillary_by_unit_{y}` is not (0.7 GB for 2020-2026): the two commands above rebuild it from public data in about
ten minutes.

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
| `anc_dc_gbp`, `anc_dm_gbp`, `anc_dr_gbp` | Dynamic Containment, Moderation, Regulation: MW x clearing price x hours | NESO DC tenders (2020-21), DC/DM/DR auctions (2021-23), Enduring Auction Capability (from Nov 2023) |
| `anc_sffr_gbp` | Static Firm Frequency Response | NESO SFFR auctions (from Apr 2023) |
| `anc_qr_gbp`, `anc_sr_gbp`, `anc_br_gbp` | Quick, Slow and Balancing Reserve availability | NESO EAC (QR from 2024, SR from 2026), Balancing Reserve (from Mar 2024) |
| `total_gbp` | the sum: a gross margin before network charges, optimisers' fees, Capacity Market payments and imbalance | |
| `gbp_per_kw_yr` | `total_gbp` per kW of registered capacity at an annual rate (x 365 / days active) | |
| `trading` | whether the unit did anything in these markets in the month: a notified position, a BM cashflow or an ancillary payment | |

A clearing price below zero makes a payment negative: Dynamic Regulation (high) cleared below zero in many blocks of
winter 2023/24 and 2024 (down to GBP -15/MW/h), when providers paid to hold the service, and the table keeps NESO's
prices as published (GBP -11.6m for the batteries' DR in 2024).

A battery's energy is in two columns: what it traded before gate closure (its notified position, `wholesale_gbp`)
and what the system operator moved it by after (`bm_offer_gbp`, `bm_bid_gbp`). In 2025 the BM was a fifth of the
batteries' revenue here (offers GBP 69.5m, bids GBP -37.7m).

The MID is Elexon's market index (the volume-weighted price of the half-hour's short-term trades on EPEX GB),
published by Elexon on its terms. Nothing from the licensed day-ahead auctions (N2EX, EPEX SPOT) is read, so the
tables may be shared on the terms of Elexon's and NESO's data; `tests/test_storage_revenues.py` checks that the
build code names none of the licensed tables.

## Units, traders and optimisers

The units are the battery and pumped storage units active in the year in `bm_unit_register_{y}` (T_ and E_ units),
with their registered capacity, lead party and `trader` (the lead party's group in `ownership_bmu_{y}`). `optimiser`
is the group of the company that bid the unit into NESO's auctions, with the largest payments in the month: the
lead party of a battery is often its owner's project company, while the company that trades it is an optimiser
(Tesla, Habitat Energy, EDF, Statkraft). Both are grouped by the ownership tables' rules and spellings.

## What it leaves out

| Gap | Direction |
| --- | --- |
| Trading skill and re-trading: the whole notified position is valued at one index price, so a trader that bought low and sold high within the day is credited with the index only; tolls, floors and fees between owner and optimiser are not seen | either |
| Imbalance: metered output that differs from the notified and accepted position is settled at the system price; batteries' metered output per unit is not published | either, small for a unit that follows its instructions |
| Capacity Market payments (a fixed GBP/kW of de-rated capacity, not trading income; NESO's register links few batteries to BM units) | total too low |
| Ancillary services before 2 Oct 2020 (monthly FFR tenders, EFR contracts: no unit-level tables); the columns are empty, not zero, before then (`ancillary_published`) | total too low before 2021 |
| Batteries outside the T_ and E_ units: those traded through supplier (2__) and virtual lead party (V__) units, such as BP's 2__FBPGM001 and Habitat's V__NHABI005, and batteries outside the BM. They are in `ancillary_by_unit_{y}` (with their Elexon id where they have one) but not in `storage_revenue_{y}` | fleet too small |

Battery payments for frequency response and reserve by kind of unit (`ancillary_by_unit_{y}`, technology
"Batteries"):

| Year | GBP m | T_ and E_ units (in `storage_revenue`) | supplier and VLP units (2__, V__) | non-BM units |
| --- | --- | --- | --- | --- |
| 2020 (from 2 Oct) | 10 | 15% | 40% | 45% |
| 2021 | 69 | 15% | 45% | 39% |
| 2022 | 136 | 28% | 44% | 28% |
| 2023 | 70 | 38% | 37% | 24% |
| 2024 | 61 | 28% | 37% | 35% |
| 2025 | 157 | 39% | 37% | 24% |

So `storage_revenue_{y}` describes the BM-registered T_ and E_ storage fleet, not every battery in Great Britain.

A pumped storage station registers its units separately, and some register their pumping as a unit of its own
(Cruachan's T_CRUAD-1, 1 MW of generation capacity): a unit under 2 MW gets no `gbp_per_kw_yr`, and a station's
units should be added up before comparing it.

## Results

Batteries (T_ and E_ units of at least 2 MW), from `storage_revenue_{y}`; GBP/kW/yr is capacity- and
day-weighted over the months a unit traded (`trading`), as an index of operating assets would count them:

| Year | Units | GW | GBP m | GBP/kW/yr | Wholesale | BM | Ancillary | Capacity-days not trading |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2018 | 2 | 0.07 | 1.0 | 48 | 34% | 66% | not published | 0% |
| 2019 | 5 | 0.17 | 2.3 | 30 | 35% | 65% | not published | 51% |
| 2020 | 6 | 0.18 | 3.7 | 48 | 13% | 45% | 41% (Oct-Dec) | 56% |
| 2021 | 10 | 0.36 | 18.7 | 99 | 15% | 8% | 76% | 24% |
| 2022 | 24 | 0.87 | 47.4 | 103 | 17% | 3% | 80% | 13% |
| 2023 | 44 | 1.79 | 48.6 | 41 | 31% | 14% | 56% | 1% |
| 2024 | 63 | 2.85 | 73.0 | 38 | 51% | 27% | 21% | 7% |
| 2025 | 101 | 5.20 | 153.6 | 54 | 41% | 21% | 39% | 20% |

Before 2021 the batteries were paid mostly by the FFR tenders and EFR contracts, which are not in the data, so those
years' margins are too low and some of their "not trading" months may be months paid only through those contracts.
In 2025, 24 batteries (1.38 GW) were registered and notified only zeros without a BM cashflow or an ancillary payment:
Coalburn's five units (from October), Uskmouth's four (from September), Thornton Battery, KXP Immingham, Whitegate,
Neilston, Indian Queens and others. Seven of them first appear in the BM cashflows during 2026 (KXP Immingham from
February, Whitebirk from March, Broxburn from May, Cathkin from June, Coalburn from July, Torquay and Whitegate from
September); the others not by 6 October 2026. Pumped storage (Dinorwig, Ffestiniog, Cruachan, Foyers) earned
GBP 160.7m in 2025 by the same streams, GBP 288.5m in 2022.

Against Modo's GB BESS index (GBP thousand per MW per year, the months Modo published, from its research notes):

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

## Using it to check a model

- Compare like with like: a model of the day-ahead market alone is compared with `wholesale_gbp` (and the BM
  columns if the model has a balancing stage), not with `total_gbp`; the ancillary columns say how much of the
  fleet's income came from markets the model does not have.
- `annual=True` gives one row per unit, with `gbp_per_kw_yr` over all its days and `gbp_per_kw_yr_trading` over
  the months it traded; add units up by `trader` or `optimiser` for company-level margins, and weight by capacity
  x days (or trading days). A fleet average over trading months is the one to set against commercial indices.
- `ancillary_by_unit_{y}` gives, per unit and EFA block (4 hours) or half-hour, the MW committed to each service:
  the capacity a battery agent should hold out of the energy markets in those hours.
