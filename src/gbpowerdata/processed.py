"""Loaders for the pipeline's per-year processed tables (data/processed/*_{year}.csv).

They belong to the data layer: every model, figure script or notebook that consumes the
pipeline's outputs should read them through here, so the file naming and the UTC parsing live
in ONE place.

    load_year(2023)      -> {"demand": df, "cf": df, "fuel": df, "mid": df, "agents": df, ...}
    merge_drivers(2023)  -> half-hourly join of demand + capacity factors + fuel prices + MID,
                            plus the monthly coal price mapped onto the index

Nothing here carries model economics: the coal fallback price is a parameter, not a constant.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from gbpowerdata import config as cfg

# friendly file-kind -> processed/{prefix}_{year}.csv
KIND_FILE = {
    "demand": "demand", "cf": "capacity_factors", "fuel": "fuel_prices",
    "mid": "mid_target", "agents": "agents", "regime": "regime_summary",
    "fleet": "cfd_fleet", "plants": "powerplants_tagged",
}
TS_KINDS = ("demand", "cf", "fuel", "mid")  # parse startTime as UTC

COAL_FALLBACK_GBP_MWH_TH = 40.0  # used only when data/raw/coal_monthly.csv is absent


def years_available() -> list[int]:
    """Years for which the timeseries were built, sorted ascending."""
    # demand_{year}.csv only - NOT demand_by_zone_{year}.csv (the locational file).
    return sorted(int(p.stem.split("_")[-1])
                  for p in cfg.processed_dir().glob("demand_[0-9][0-9][0-9][0-9].csv"))


def processed_csv(kind: str, year: int | None = None) -> Path:
    """Path to a processed file. ``year=None`` only valid for panel files."""
    if kind == "cfd_status":
        return cfg.processed_dir() / "cfd_status.csv"
    return cfg.processed_dir() / f"{KIND_FILE[kind]}_{year}.csv"


def read_kind(kind: str, year: int) -> pd.DataFrame:
    df = pd.read_csv(processed_csv(kind, year))
    if kind in TS_KINDS:
        df["startTime"] = pd.to_datetime(df["startTime"], utc=True)
    return df


def read_lolp(year: int, hourly: bool = False) -> pd.DataFrame:
    """NESO's loss-of-load probability and de-rated margin (gbpowerdata.build.build_lolp), half-hourly
    and indexed by UTC `startTime`. `hourly=True` gives the hourly auction product: the highest
    LoLP and the lowest de-rated margin of its two settlement periods. Kept out of KIND_FILE so
    load_year() does not require it for years before the P305 series was pulled."""
    df = pd.read_csv(cfg.processed_dir() / f"lolp_drm_{year}.csv")
    df["startTime"] = pd.to_datetime(df["startTime"], utc=True)
    df = df.set_index("startTime").sort_index()
    if not hourly:
        return df
    r = df.resample("h")
    return pd.concat([r[[c for c in df.columns if c.startswith("lolp")]].max(),
                      r[[c for c in df.columns if c.startswith("drm")]].min()], axis=1)[df.columns]


def read_system_prices(year: int, hourly: bool = False) -> pd.DataFrame:
    """The cash-out price and net imbalance volume (gbpowerdata.build.build_system_prices), half-hourly
    and indexed by UTC `startTime`. `hourly=True` gives the hourly product: the mean of the two
    periods' prices and the sum of their volumes (an hour with one period missing keeps the other;
    the derivation code is dropped). Kept out of KIND_FILE, like read_lolp, so load_year() does
    not require it."""
    df = pd.read_csv(cfg.processed_dir() / f"system_prices_{year}.csv")
    df["startTime"] = pd.to_datetime(df["startTime"], utc=True)
    df = df.set_index("startTime").sort_index()
    if not hourly:
        return df
    prices = [c for c in df.columns if c.endswith("_gbp_per_mwh")]
    volumes = [c for c in df.columns if c.endswith("_mwh") and c not in prices]
    r = df.resample("h")
    return pd.concat([r[prices].mean(), r[volumes].sum(min_count=1)], axis=1)[prices + volumes]


def read_bm_unit_register(year: int, active_only: bool = False) -> pd.DataFrame:
    """Elexon's register of generating BM units for `year` (gbpowerdata.build.bm_units): lead party, technology,
    capacity and whether the unit produced in the year. `active_only` keeps the units that did. Kept out of
    KIND_FILE, like read_lolp, so load_year() does not require it."""
    df = pd.read_csv(cfg.processed_dir() / f"bm_unit_register_{year}.csv")
    return df[df["active"]].reset_index(drop=True) if active_only else df


def read_ownership(year: int, register: str | None = None, role: str | None = None) -> pd.DataFrame:
    """Owners, operators and traders by register record for `year` (gbpowerdata.build.build_ownership): one row
    per record, role and group. `register` (dukes, ro, cfd, cm, bm) and `role` (owner, operator, trader) filter.
    A group's capacity in a register is sum(capacity_mw * share) over its rows of one role."""
    df = pd.read_csv(cfg.processed_dir() / f"ownership_{year}.csv", dtype={"company_number": str, "record_id": str})
    if register is not None:
        df = df[df["register"] == register]
    if role is not None:
        df = df[df["role"] == role]
    return df.reset_index(drop=True)


def read_ownership_bmu(year: int, role: str | None = None) -> pd.DataFrame:
    """Owners, operators and traders of every BM unit active in `year` (gbpowerdata.build.build_ownership): one
    row per unit, role and group, with the register each came from. `role` filters."""
    df = pd.read_csv(cfg.processed_dir() / f"ownership_bmu_{year}.csv", dtype={"record_id": str})
    if role is not None:
        df = df[df["role"] == role]
    return df.reset_index(drop=True)


def read_ancillary_by_unit(year: int) -> pd.DataFrame:
    """NESO's frequency response and reserve results by unit and delivery period (gbpowerdata.build.
    ancillary_services): MW, GBP/MW/h and revenue, the company that bid the unit and its group, with UTC
    delivery_start and delivery_end. Kept out of KIND_FILE, like read_lolp."""
    df = pd.read_csv(cfg.processed_dir() / f"ancillary_by_unit_{year}.csv", low_memory=False)
    for c in ("delivery_start", "delivery_end"):
        df[c] = pd.to_datetime(df[c], utc=True)
    return df


def read_storage_revenue(year: int, annual: bool = False) -> pd.DataFrame:
    """What each storage unit in the BM earned by month, estimated from public data (gbpowerdata.build.
    storage_revenues): wholesale, BM and ancillary streams in GBP, with trader and optimiser. `annual=True` gives
    one row per unit and year (gbpowerdata.build.storage_revenues.annual). Kept out of KIND_FILE, like read_lolp."""
    df = pd.read_csv(cfg.processed_dir() / f"storage_revenue_{year}.csv")
    if not annual:
        return df
    from gbpowerdata.build.storage_revenues import annual as by_unit
    return by_unit(df)


def read_storage_fleet() -> pd.DataFrame:
    """Every battery and pumped storage unit the open data name, with power and (where stated) energy capacity and
    the dates it entered and left the market (gbpowerdata.build.storage_fleet; operating(fleet, date) there gives the
    units trading on a date). Kept out of KIND_FILE, like read_lolp."""
    df = pd.read_csv(cfg.processed_dir() / "storage_fleet.csv")
    for c in ("registered_from", "first_notified", "first_bm_action", "first_ancillary", "entry_date",
              "last_notified", "last_bm_action", "last_ancillary", "last_seen", "exit_date"):
        if c in df:
            df[c] = pd.to_datetime(df[c])
    return df


def read_unit_run_times(source: str | None = None) -> pd.DataFrame:
    """How long each thermal BM unit ran once started and stayed off once stopped, per year (gbpowerdata.build.
    unit_runs): counts and percentiles of the spells in hours, from the metered output (`source="b1610"`) or the unit's
    final physical notifications ("fpn"), beside the MNZT, MZT and NDZ it declared. Kept out of KIND_FILE, like
    read_lolp."""
    df = pd.read_csv(cfg.processed_dir() / "unit_run_times.csv")
    return df if source is None else df[df["source"] == source].reset_index(drop=True)


def read_unit_spells(year: int) -> pd.DataFrame:
    """Every run and down spell of the thermal BM units that started in `year` (gbpowerdata.build.unit_runs), with UTC
    start and end; a censored spell ran into a gap in the data or its end, so its length is a lower bound."""
    df = pd.read_csv(cfg.processed_dir() / f"unit_spells_{year}.csv")
    for c in ("start", "end"):
        df[c] = pd.to_datetime(df[c], utc=True)
    return df


CAPACITY_MARKET_TABLES = ("auctions", "weights", "derating", "agreements", "links")


def read_capacity_market(year: int) -> pd.DataFrame:
    """Every Capacity Market agreement's obligation and payment by month of `year` (gbpowerdata.build.capacity_market):
    the obligation (MW), the auction's indexed price, the weighting factor and the payment. Kept out of KIND_FILE,
    like read_lolp."""
    return pd.read_csv(cfg.processed_dir() / f"capacity_market_{year}.csv", parse_dates=["month"])


def read_capacity_market_table(name: str) -> pd.DataFrame:
    """One of the Capacity Market's tables (gbpowerdata.build.capacity_market): "auctions" (the price per auction and
    delivery year), "weights" (the monthly weighting factors), "derating" (the de-rating factors), "agreements" (every
    agreement and auction) or "links" (the storage BM units of the agreements)."""
    if name not in CAPACITY_MARKET_TABLES:
        raise ValueError(f"{name}: one of {CAPACITY_MARKET_TABLES}")
    parse = {"weights": ["month"], "agreements": ["terminated_on"]}.get(name, False)
    return pd.read_csv(cfg.processed_dir() / f"capacity_market_{name}.csv", parse_dates=parse)


def read_investment_inputs(reference: bool = True) -> pd.DataFrame:
    """Capital and operating costs, lifetimes, efficiencies and hurdle rates by source edition (a vintage),
    technology and year, each in its source's price base (gbpowerdata.build.investment_inputs: the generation costs
    studies and the Danish Energy Agency's storage datasheet). `reference=True` adds the values transcribed from PDF
    reports, cited with locators (data/reference/investment_parameters.csv: CEPA's 2025 hurdle rates, Mott
    MacDonald's 2018 storage costs), and every row gets its source's licence."""
    frames = []
    path = cfg.processed_dir() / "investment_inputs.csv"
    if path.exists():
        frames.append(pd.read_csv(path))
    if reference:
        frames.append(pd.read_csv(cfg.reference_dir() / "investment_parameters.csv"))
    if not frames:
        raise FileNotFoundError(f"{path} missing: run python -m gbpowerdata.build.investment_inputs")
    t = pd.concat(frames, ignore_index=True)
    src = pd.read_csv(cfg.reference_dir() / "investment_parameter_sources.csv")
    return t.merge(src[["source_id", "licence"]].rename(columns={"source_id": "source"}), on="source", how="left")


REGO_TABLES = ("vintages", "monthly", "observations", "statistics")


def read_rego(table: str = "vintages") -> pd.DataFrame:
    """Renewable Energy Guarantees of Origin (gbpowerdata.build.rego): "vintages" (one row per certificate vintage,
    April to March: the price the sources report and the fuel mix disclosure figures of the period), "monthly" (the
    price observations by month and vintage), "observations" (every cited price, data/reference/rego_prices.csv,
    with its source's publisher, URL and terms) or "statistics" (DESNZ's and Ofgem's figures,
    data/reference/rego_statistics.csv). The prices are cited from market commentary: no official price exists."""
    if table not in REGO_TABLES:
        raise ValueError(f"{table}: one of {REGO_TABLES}")
    ref = cfg.reference_dir()
    if table == "observations":
        src = pd.read_csv(ref / "rego_price_sources.csv")
        cols = ["source_id", "publisher", "title", "url", "licence"]
        return (pd.read_csv(ref / "rego_prices.csv", dtype=str)
                .astype({c: float for c in ("value", "low", "high")})
                .merge(src[cols].rename(columns={"source_id": "source"}), on="source", how="left"))
    if table == "statistics":
        return pd.read_csv(ref / "rego_statistics.csv")
    name = {"vintages": "rego_vintages.csv", "monthly": "rego_price_monthly.csv"}[table]
    path = cfg.processed_dir() / name
    if not path.exists():
        raise FileNotFoundError(f"{path} missing: run python -m gbpowerdata.build.rego")
    return pd.read_csv(path)


def read_generation_mix(year: int | None = None, summary: bool = False) -> pd.DataFrame:
    """GB generation by fuel and technology and every interconnector's flow (gbpowerdata.build.generation_mix): the
    half-hours of `year` in MW, indexed by UTC `startTime`, or with `summary=True` the energy (GWh), shares and coverage
    of every year and month built (long: resolution, period, technology)."""
    if summary:
        return pd.read_csv(cfg.processed_dir() / "generation_mix_summary.csv", dtype={"period": str})
    if year is None:
        raise ValueError("read_generation_mix: a year, or summary=True")
    df = pd.read_csv(cfg.processed_dir() / f"generation_mix_{year}.csv")
    df["startTime"] = pd.to_datetime(df["startTime"], utc=True)
    return df.set_index("startTime")


def read_generation_battery(year: int | None = None, summary: bool = False, units: bool = False) -> pd.DataFrame:
    """GB batteries' discharge and charge, metered (B1610) and notified, and the frequency response NESO held from
    them, by group of unit (gbpowerdata.build.generation_battery): the half-hours of `year` in MW, indexed by UTC
    `startTime`; with `summary=True` the energy (GWh), mean MW, share of generation, units, capacity and coverage of
    every year and month built (long: resolution, period, basis, group, gsp_group, flow); with `units=True` one row
    per unit and year with its GSP group, energy and response MW."""
    if summary:
        return pd.read_csv(cfg.processed_dir() / "generation_battery_summary.csv", dtype={"period": str})
    if units:
        return pd.read_csv(cfg.processed_dir() / "generation_battery_units.csv")
    if year is None:
        raise ValueError("read_generation_battery: a year, summary=True or units=True")
    df = pd.read_csv(cfg.processed_dir() / f"generation_battery_{year}.csv")
    df["startTime"] = pd.to_datetime(df["startTime"], utc=True)
    return df.set_index("startTime")


def read_generation_by_fuel(reconciliation: bool = False) -> pd.DataFrame:
    """DESNZ's annual generation by fuel for the UK, GB and each country (gbpowerdata.build.generation_by_fuel; long:
    year, area, generator_type, fuel, measure, gwh, share, source), or with `reconciliation=True` GB's official output
    by fuel against the half-hourly generation mix's year (the gas the half-hourly table misses, by year)."""
    name = "generation_reconciliation_annual.csv" if reconciliation else "generation_by_fuel_annual.csv"
    return pd.read_csv(cfg.processed_dir() / name)


def _timeseries(path: Path, time_col: str = "startTime") -> pd.DataFrame:
    df = pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_csv(path)
    if time_col in df.columns:
        df[time_col] = pd.to_datetime(df[time_col], utc=True)
        df = df.set_index(time_col)
    else:
        df.index = pd.to_datetime(df.index, utc=True)
    return df


def read_vre_split() -> pd.DataFrame:
    """Metered wind split offshore and onshore by the reanalysis shape, and embedded solar (gbpowerdata.build.vre_split):
    half-hourly capacity factors against the agents' capacities and MW, indexed by UTC startTime, 2018-2025."""
    return _timeseries(cfg.processed_dir() / "vre_cf_corrected.csv")


def read_interconnector() -> pd.DataFrame:
    """Each interconnector's hourly capacity per direction, published and rated, with the neighbour's price in
    GBP/MWh and the import bid and export willingness to pay (gbpowerdata.build.interconnector_capacity): long,
    one row per hour and link, indexed by UTC startTime; carries Nord Pool's NSL capacity, so licensed."""
    return _timeseries(cfg.processed_dir() / "ic_hourly.parquet")


def read_bmrp() -> pd.DataFrame:
    """The baseload CfDs' season-ahead reference price on the half-hourly spine (gbpowerdata.build.bmrp): season and
    bmrp_gbp_mwh, NaN before LCCC's first published season (Summer 2019), indexed by UTC startTime."""
    return _timeseries(cfg.processed_dir() / "bmrp_halfhourly.csv")


def read_foreign_supply() -> pd.DataFrame:
    """The neighbours' inverse-supply slope per zone (gbpowerdata.build.foreign_supply): zone, link, slope_gbp_per_mw,
    r2, n, usable."""
    return pd.read_csv(cfg.processed_dir() / "foreign_supply_slope.csv")


def read_ro_stations() -> pd.DataFrame:
    """Ofgem's RO accredited stations without their holders (gbpowerdata.build.ro_stations): accreditation number,
    station, technology, DNC in MW, commissioning and accreditation dates (parsed), country, station postcode."""
    df = pd.read_csv(cfg.processed_dir() / "ro_stations.csv", dtype={"station_postcode": str})
    for c in ("commissioning_date", "accreditation_date"):
        df[c] = pd.to_datetime(df[c], errors="coerce")
    return df


WEATHER_TABLES = ("national", "gsp")


def read_weather_years(kind: str = "national") -> pd.DataFrame:
    """The ERA5 weather record as capacity factors (gbpowerdata.build.weather_years), hourly 1950-2025 on PECD's stamps,
    indexed by UTC startTime: "national" (wind_offshore_cf, wind_onshore_cf, solar_cf on today's fleet) or "gsp"
    (one column per GSP group and technology, to be weighted by any fleet with weather_years.weighted_national)."""
    if kind not in WEATHER_TABLES:
        raise ValueError(f"{kind}: one of {WEATHER_TABLES}")
    name = "national_cf_historical.parquet" if kind == "national" else "gsp_cf_era5.parquet"
    return _timeseries(cfg.processed_dir() / "pecd" / name)


def read_tyndp_hourly() -> pd.DataFrame:
    """ENTSO-E's TYNDP 2024 market model for 2030, climate year 2009 (gbpowerdata.build.tyndp_hourly): the hourly
    marginal cost of GB's neighbours' nodes and GB's own demand, wind and solar potential and dumped energy."""
    return pd.read_csv(cfg.processed_dir() / "tyndp_nt2030_cy2009_hourly.csv")


def load_year(year: int) -> dict[str, pd.DataFrame]:
    """All per-year tables for one year, keyed by friendly name."""
    return {k: read_kind(k, year) for k in KIND_FILE}


def load_panel(kind: str, years: list[int] | None = None) -> pd.DataFrame:
    """One long DataFrame across years with an added ``year`` column."""
    years = years or years_available()
    frames = []
    for y in years:
        df = read_kind(kind, y)
        df.insert(0, "year", y)
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


def load_cfd_status() -> pd.DataFrame:
    df = pd.read_csv(processed_csv("cfd_status"))
    for c in ("cfd_start_date", "cfd_end_date", "commissioned_date"):
        df[c] = pd.to_datetime(df[c], errors="coerce")
    return df


def coal_price_thermal(times: pd.Series, fallback: float = COAL_FALLBACK_GBP_MWH_TH) -> pd.Series:
    """Monthly GB coal price (GBP/MWh-thermal, gbpowerdata.pull.coal_pull) mapped to the
    half-hourly index; falls back to a flat value if the series is absent."""
    path = cfg.raw_dir() / "coal_monthly.csv"
    if not path.exists():
        return pd.Series(fallback, index=times.index)
    cm = pd.read_csv(path).set_index("month")["coal_gbp_per_mwh_thermal"]
    return (times.dt.strftime("%Y-%m").map(cm)
            .astype(float).ffill().bfill()
            .fillna(fallback))


def merge_drivers(year: int, coal_fallback: float = COAL_FALLBACK_GBP_MWH_TH) -> pd.DataFrame:
    """Half-hourly join of demand + capacity factors + fuel prices + MID price, with the coal
    price as the monthly step from data/raw/coal_monthly.csv where that file exists.

    A processed-only install (the data pack, no raw/) keeps the coal series fuel_prices_{year}
    already carries instead: coal_price_thermal() would otherwise replace it with the flat
    fallback without a word."""
    d = load_year(year)
    m = (d["demand"]
         .merge(d["cf"], on="startTime")
         .merge(d["fuel"], on="startTime")
         .merge(d["mid"], on="startTime"))
    col = "coal_price_gbp_per_mwh_thermal"
    if (cfg.raw_dir() / "coal_monthly.csv").exists() or col not in m:
        m[col] = coal_price_thermal(m["startTime"], coal_fallback)
    else:
        m[col] = m[col].fillna(coal_fallback)
    return m
