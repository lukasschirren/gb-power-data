# Ownership: who owns, runs and trades GB generation

Two tables per year, 2018 to the current year, built from five public registers and a small curated table of
joint ventures and sales, each share with its sources:

| Table | One row per | Use it for |
| --- | --- | --- |
| `ownership_{y}` | register record x role x group | concentration within one register (DUKES, RO, CfD, Capacity Market, Balancing Mechanism) |
| `ownership_bmu_{y}` | BM unit active in the year x role x group | joining owners to anything keyed by BM unit (FPN, BOD, BOALF, B1610), and owner versus trader |

They are built by `python -m gbpowerdata.build.build_ownership` after `python -m gbpowerdata.build.bm_units`, and read
with `processed.read_ownership(year, register=..., role=...)` and `processed.read_ownership_bmu(year, role=...)`.
The method, every rule and its source are in the docstrings of `build/build_ownership.py`, `build/bm_units.py` and
`common/companies.py`; this note is the overview. Every curated share is listed with its evidence in
[ownership_references.md](ownership_references.md).

## Three roles

- **owner**: who holds the equity, with its share where a source gives one. A joint venture has several owners;
  a share no source gives is left blank, and the part the known shares do not cover is `unresolved`.
- **operator**: the company that runs the unit and bids for its owners. A single owner is its own operator; a
  joint venture's operator is the owner `company_owners.csv` marks.
- **trader**: the BSC party registered to trade the unit in the Balancing Mechanism in the year (Elexon's lead
  party). For a gas station that is the owner's own company; for a battery it is often an optimiser trading for
  the owner.

## Years

A year describes its last day, the current year the build date (`as_of` in every row). Each source is read at that
date where it can be:

- DUKES: the edition of the following year (the stations operating at the end of May) stands for the end of the
  year; the latest edition also for the current year. A station that closed between January and May is missing
  from the year before's records; the links to BM units read the edition before for it, and a station whose BM
  units produced in the year but that the year's lists leave out (Sutton Bridge's CCGT in the lists for 2022-2024)
  takes the latest earlier list that has it.
- The dated rows of `company_owners.csv` (joint ventures, sales, companies that changed group) are read at the
  as-of date, so owners and operators change over the years (the battery companies of Harmony Energy Income Trust
  are HEIT's until 16 June 2025 and Foresight's after, when Foresight took the trust private). For the offshore wind
  farms they follow The Crown
  Estate's ownership tables at the ends of 2018, 2019, 2020, 2023 and 2024 and its lists of transactions, and
  `build.build_crown_estate` checks them against those tables (see "Checked against The Crown Estate").
- CfD contracts count once their round has reported and until terminated; CM agreements in their delivery years;
  RO stations in the years they were issued ROCs for; BM units in the years they produced (dated by their output).
  A year the activity files do not reach (the current year, before its files are pulled) takes the last year's
  activity (`activity_year` in the register table): a unit in an outage at the end of the pull still counts, one
  first producing after it does not.
- The BM register: Elexon publishes only the register of the day, so every pulled snapshot
  (`data/raw/bm_units_YYYYMMDD.csv`) is kept, and a year takes the latest snapshot on or before its as-of date.
  Where none is that old, the earliest after it stands in (`party_basis` "proxy" in the register table).
  `scripts/snapshot_registers.py`, run once a month, keeps a snapshot of the register each month, with dated copies
  of the CM register and The Crown Estate's page.

**Traders by year.** A unit's trader is, in this order: its lead party in `bmu_lead_parties.csv` where a documented
change covers the date (register `curated`); its lead party in the year's register snapshot (`bm`); or, before the
first snapshot, today's lead party as a proxy (`bm_proxy`), checked against the unit's ownership: where a dated
source (a curated row or the year's DESNZ list) gives the unit a different operator in the year than at the
snapshot's date, the unit changed hands since and its trader in the year is taken to be its operator then
(`operator_at_date`, a judgement). Damhead Creek and Rye House were Drax's to trade until January 2021 (VPI's today), West
Burton B EDF's until August 2021 (EIG's today), Severn Calon's until 2025 (Centrica bought it in May 2026). A joint
venture's own company trading for the venture resolves to the venture's operator (`jv_operator`). The `bm` records
of `ownership_{y}` carry the same traders as the BM-unit table, whose `register` column says which of these
applies.

## What each register names

| Register | Source (puller) | Company it names | Counts in year y |
| --- | --- | --- | --- |
| `dukes` | DESNZ, DUKES 5.11 (`pull.dukes_pull`) | the survey returner, mostly the owning group; joint ventures named as such | GB stations listed in the edition of May y+1 (one sheet per edition) |
| `ro` | Ofgem, RO register and certificates (hand-downloaded) | the accreditation holder, mostly a project company, today's | GB stations of 1 MW or more issued ROCs for output in y |
| `cfd` | LCCC, CfD register and status (`pull.lccc_pull`) | the counterparty (a project company) with its Companies House number | operating (started by the end of y) or contracted (its round had reported), not terminated |
| `cm` | NESO, Capacity Market register (`pull.cm_register_pull`) | the applicant and its declared parent (today's); the class from its Primary Fuel Type, else from its CMU Technology | agreements in force in the delivery year from October y |
| `bm` | Elexon, BM unit register (`pull.elexon_pull bmunits`, `build.bm_units`) | the trader, as in the BM-unit table (see "Traders by year") | units that produced in y |

Capacity is each register's own: installed (DUKES), declared net (RO), contracted (CfD), connection and de-rated
(CM), generation capacity (BM). Compare groups within a register, not totals across registers.

## How a company becomes a group

First match wins, and the basis is in every row: a dated row of `company_owners.csv` (`curated`), an alias in
`company_groups.csv` (`alias`), the group named in the company's name (`name`), in its address (`address`) or one of
a group's own single-occupier sites (`site`; RO and CfD only, which carry addresses), its majority controller on the
date in Companies House's register of persons with significant control, followed up the chain to a controller known
by alias or name (`ch_psc`; for a company with a number: the CfD register's, or `companies_house_numbers.csv`'s for
its name; needs a pull, `pull.companies_house_pull --follow 2` and `build.build_company_control`; a trustee, nominee
or custodian holding the shares for someone else, or a lender holding them as security, is never taken as the
controller), its parent in the
Capacity Market register (`cm_parent`; today's, so after the dated controller), the last controller's name where the
chain reaches no known group (`ch_psc`), else the company itself (`self`). In the BM-unit table, a unit no register links to
takes its lead party as owner (`lead_party`, a proxy), except a battery, which stays `unresolved`. A group no rule,
alias or curated row names keeps a register's spelling, and the registers spell one company differently (LCCC's
"CLEVE HILL SOLAR PARK", Elexon's "Cleve Hill Solar Park"), so each name takes one spelling in every table and year:
mixed case before capitals only, then the most capital letters, then the shortest.

## How BM units are linked

| Link | Through | Covers |
| --- | --- | --- |
| CfD | LCCC's CfD-to-BM-unit mapping (T_/E_ units mapped in the year) | CfD units of contracts that count in the year |
| DUKES | `data/reference/dukes_bmu_map.csv`: a DUKES site pattern, a technology class, the station's units | the main gas, coal, nuclear, pumped-storage and biomass stations |
| RO | `data/reference/wind_farm_map.csv`, matched to the RO register by the farm's name | transmission-connected RO wind farms |
| CM | the components' Component ID (Elexon's or National Grid's unit id) | 220 of the register's 655 units; few batteries |

The first link in that order gives the unit's owners and operator. Where that register names a company without
dated rows and the unit's lead party is a joint venture's own company with dated rows, the venture's rows give the
owners (register `bm`, basis `curated`): Gunfleet Sands I and II, whose RO holder (Orsted Burbo (UK) Limited) also
holds Burbo Bank, are Orsted's, DBJ's and Marubeni's (JERA's from 2019), not Orsted's alone.

## The curated tables (`data/reference/`, edit by hand)

- `company_groups.csv`: a name a register uses, its group, and `same_as`, the name of the same legal entity under
  which `company_owners.csv` keys it (Elexon's "Doggerbank OWF Project 1" is the CfD register's "Doggerbank
  Offshore Wind Farm Project 1 Projco Limited").
- `company_owners.csv`: joint ventures and sales, keyed `company:<name>` or `station:<station>`: owner, share,
  operator, validity dates, `sources` (ids into `ownership_sources.csv`, ";"-separated), `evidence` (what the
  sources say), `status` (`verified`, `partly verified`, `to verify`, `judgement`) and the date `checked`. Shares on
  any date add up to at most 100, with at most one operator (checked by `tests/test_ownership.py`).
- `ownership_sources.csv`: every source cited: id, publisher, title, date published, kind, URL, date accessed.
- `bmu_lead_parties.csv`: documented lead parties of a BM unit over a period, for changes the register snapshots do
  not cover (same columns of evidence as `company_owners.csv`; empty so far).
- `dukes_bmu_map.csv`: the stations linked to their BM units.
- `crown_estate_farms.csv`: The Crown Estate's farm names (one row per spelling) -> the company under which
  `company_owners.csv` keys the farm, for the check against The Crown Estate.
- `companies_house_numbers.csv`: the companies whose persons with significant control are pulled (number as
  eight-character text, the register's name, why it is listed): the CfD counterparties that resolve to themselves,
  and since 7 Oct 2026 the BM lead parties that do, under Elexon's spelling (cut at 30 characters and abbreviated:
  "Mobius Renewables Gen. (GB2", "HYWINDSC"), each number found by Companies House's company search on that name
  and, where the names differ, chosen by hand (`why` says how). Left out: the Nuclear Decommissioning Authority (a
  public body), Erova Energy (an overseas company, without a PSC register) and ESBIG Trading (no company found).

Local only, never committed: `crown_estate_ownership_reports.csv`, the hand transcription of The Crown Estate's
tables for the ends of 2018-2020 (its terms allow own use only; `data/reference/README.md` describes it).

A new joint venture or sale is a row in `company_owners.csv` with its sources; the tables need no code change.
After editing them, regenerate the reference document (the tests fail until it is):

```bash
python -m gbpowerdata.common.companies --references    # writes docs/ownership_references.md
```

## Checked against The Crown Estate

`python -m gbpowerdata.pull.crown_estate_pull --archived` keeps The Crown Estate's offshore wind ownership tables
(the live page, as at the end of 2024, and the Internet Archive's capture of the end-2023 table; one file per as-at
date), and the local transcription adds the tables of its reports for the ends of 2018-2020. `python -m
gbpowerdata.build.build_crown_estate [--strict]` compares, for every table date and every farm that
`crown_estate_farms.csv` maps to a company of `company_owners.csv`, the groups, shares (to 0.5 percentage points)
and operator that `company_owners.csv` gives on that date with The Crown Estate's; holders are grouped by its
`HOLDER_GROUPS`, and a vehicle named on one side only (Ocean Winds, Diamond Green) is compared with its owners
summed. Farms with no rows in `company_owners.csv` are listed in `NOT_COMPARED` with the holdings expected of them,
and a change in those holdings fails `--strict` like an unexplained difference, an unmapped farm or a known
difference that no longer occurs. On 6 Oct 2026: 171 farm-dates, 13 differences, all known (`KNOWN_DIFFERENCES`,
each matching one difference exactly): the 5% of Moray West that the end-2023 table gives Inpex (Ignitis's from the
financial close; the end-2024 table says Ignitis); two groupings in the reports (Race Bank at the end of 2018, a
vehicle against its look-through; Sheringham Shoal at the end of 2020, inconsistent with the reports before and the
tables after); and The Crown Estate naming the project company as the operator of Moray East, Moray West and Neart
na Gaoithe. The Crown Estate's pages are for own use under its terms, so the snapshots, the transcription and
`crown_estate_ownership.csv` stay local and are not packed.

## Known limits

- Lead parties before the first kept register snapshot (5 Jun 2026) are a proxy, corrected only where a dated
  source shows a change of hands; an offtake that moved without a sale is not seen. Ofgem's holders and the CM
  parents are as of the pull: a company sold since takes its buyer's group in every year (Flexitricity resolves to
  Drax through its parent in the CM register), unless a dated row says otherwise.
- DUKES lists 382-390 GB stations a year in the editions to 2021 and 1,263-1,317 from 2022 (more renewables): a
  break in coverage.
- BM units that left Elexon's register before its first kept snapshot (5 Jun 2026) are in no year's BM tables:
  Eggborough (closed September 2018), Cottam (September 2019) and Aberthaw B (March 2020) among the coal stations.
  Their DUKES records are there, without BM units and without a trader.
- A BM unit with no activity file that submits no notifications but has a fuel type counts as active in every year
  (3 units, 55 MW). The other units without files had their notifications pulled on 7 Oct 2026; the 25 that
  notified nothing before 2026, Dogger Bank B's 1.2 GW among them, count in no year.
- The current year's activity is the last pulled year's (see "Years"): a unit that closed in that year still counts,
  one commissioned since does not.
- A CM unit without a Primary Fuel Type (most agreements of the earlier auctions) is classed by its CMU Technology:
  "OCGT and Reciprocating Engines" without a stated fuel as gas, "Coal/biomass" as coal except the energy-from-waste
  plants and Drax's biomass units, which their names identify.
- Battery owners come from the Capacity Market register, whose components are mostly sites rather than BM units,
  so most battery units have a trader but no owner; the CM records (`register == "cm"`, `tech_class ==
  "battery"`) give the battery fleet's owners in aggregate.
- RO stations under 1 MW are left out; many are held by individuals.
- A joint venture whose own company appears in no register (Rhyl Flats: RWE 50.1%, Greencoat UK Wind 24.95%, UK
  GIG 24.95% in every Crown Estate table; DESNZ and Ofgem name RWE companies that hold other farms too, and it has
  no BM unit) is counted as the named company's group alone; dated rows would need a key by register record.
- `lead_party` owners are a proxy; filter them out for a strict view (`basis != "lead_party"`).
- Companies House places a company by its majority controller on the date. A holding company that kept a former
  owner's name after a sale is placed by that name unless an alias says otherwise (the Infinis wind holdings,
  Ventient's since May 2017 and renamed Mobius, have aliases); a company whose only holder of record is a lender has
  no controller while the lender holds (Kilbraur and Millennium Wind Energy, Renantis' farms, from Dec 2022), and
  one whose filings give the parent no majority stays itself (OnPath Energy in 2023-2024, when Brookfield's entry
  shows 25-50% of the votes).

## Personal data

Ofgem's RO reports give organisation and station addresses, and small stations are often held by individuals:
addresses are used only to group holders and are never written, stations under 1 MW are left out, and the raw
reports are not in the inputs pack. The CM register's trading contacts (telephone, e-mail) are dropped by its
puller and never read. Companies House lists individuals with significant control by name, address and birth date:
its puller keeps an individual (or any entry carrying a person's details) only as its kind, natures of control and
dates, and `company_control.csv` names corporate controllers only.

## What could be added

- Companies House for the RO holders that resolve to themselves: the RO register gives no company numbers, so they
  would be found by name as the BM lead parties were (the CfD counterparties and the lead parties were pulled on
  7 Oct 2026).
- The CM parent by date: the kept monthly CM registers could date parents as the BM snapshots date lead parties
  (the build reads only the newest CM register so far).
- Dated rows keyed by register record, for joint ventures without a company of their own in the registers (Rhyl
  Flats).
- Balancing Mechanism volumes and payments by group (BOALF acceptances priced with BOD), and the ancillary-service
  auctions (NESO's results name the registered participant per unit).
- Output-weighted concentration (FPN, B1610, ROC volumes) next to capacity.
