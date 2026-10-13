"""Stage 2 — build the half-hourly time-series spine the ABM reads each period.

Outputs (data/processed/, UTC half-hourly, year-suffixed, aligned on startTime):
  demand_{year}.csv          transmission demand (ITSDO), embedded wind and solar, and national demand (their
                             sum), with transmission_demand_source (ITSDO, interpolated, missing). ITSDO is
                             Elexon's transmission system demand: it INCLUDES interconnector exports, pumped
                             storage pumping and station load (measured on 2018-2025: ITSDO - INDO = 0.56 GW +
                             1.00 x exports + 1.00 x pumping), so national_demand_mw is not the demand a model
                             with its own interconnectors and storage should serve (README, data caveats).
  capacity_factors_{year}.csv  wind_offshore / wind_onshore / solar capacity factors
  fuel_prices_{year}.csv     gas (p/therm), coal (GBP/MWh-th), carbon ETS + total
                             (ETS+CPS, GBP/tonne), filled to half-hourly
  mid_target_{year}.csv      Elexon's market index price (MID: the volume-weighted price of the half-hour's
                             short-term trades on EPEX SPOT GB, not a day-ahead auction price; validation
                             target, NOT an input), with mid_source. A half-hour without traded volume is
                             published at price 0 and is a gap here, not a price of GBP 0/MWh.
Gaps: a gap of at most MAX_GAP_HH half-hours is interpolated (fill_short_gaps); a longer one stays empty. Elexon
published neither ITSDO nor INDO for whole days in 2018, 2020 and 2021 (500 half-hours), and those days keep an
empty transmission and national demand.

Capacity-factor split (onshore vs offshore):
  - offshore proxied by transmission-connected wind (espeni ELEX_WIND); offshore
    farms are essentially all transmission-connected.
  - onshore proxied by embedded wind (espeni EMBEDDED_WIND), all distribution-connected.
  CF denominators come from the Stage 1 tagged plants + the raw BM-unit snapshot
  (transmission vs embedded wind split via the T_ prefix). A peak-floor correction
  keeps observed CF below ~0.95/0.98, compensating PPM's understatement of embedded
  capacity. mid_target is held out — only Stage 4 reads it.

Parameters (year, interpolation, file names) come from config.yaml. All inputs
live in data/raw/; Elexon series are sliced from whatever pull covers the year.
`--fuel-only` writes fuel_prices_{year}.csv alone (a year whose demand inputs are not
complete); a year the gas series has not finished stops at its last observed day.
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from gbpowerdata import config as cfg
from gbpowerdata.common import elexon, repd

CFG = cfg.load_config()
YEAR = int(CFG["year"])
RES = int(CFG["resolution_minutes"])
RAW = cfg.raw_dir()
PROC = cfg.processed_dir()

START = pd.Timestamp(f"{YEAR}-01-01 00:00", tz="UTC")
END = pd.Timestamp(f"{YEAR + 1}-01-01 00:00", tz="UTC")

# espeni column names (long, with embedded unit annotations).
ESP_TIME = "ELEC_elex_startTime[utc](datetime)"
ESP_TRANS_WIND = "ELEC_POWER_ELEX_WIND[MW](float32)"
ESP_EMB_WIND = "ELEC_POWER_NGEM_EMBEDDED_WIND_GENERATION[MW](float32)"
ESP_EMB_SOLAR = "ELEC_POWER_NGEM_EMBEDDED_SOLAR_GENERATION[MW](float32)"


def master_index() -> pd.DatetimeIndex:
    return pd.date_range(START, END, freq=f"{RES}min", inclusive="left", tz="UTC")


def _load_elexon_series(glob_pat: str, value_col: str) -> pd.Series:
    """Concat every raw Elexon CSV matching glob_pat, slice to the year, return a
    startTime-indexed series. Handles both long-range pulls and year slices."""
    files = sorted(RAW.glob(glob_pat))
    if not files:
        raise FileNotFoundError(f"No raw files match {glob_pat} in {RAW}")
    frames = [pd.read_csv(f, usecols=lambda c: c in ("startTime", value_col))
              for f in files]
    df = pd.concat(frames, ignore_index=True)
    df["startTime"] = pd.to_datetime(df["startTime"], utc=True)
    df = df[(df["startTime"] >= START) & (df["startTime"] < END)]
    return (df.drop_duplicates("startTime").set_index("startTime")[value_col]
            .sort_index())


def _load_n2ex_price(idx: pd.DatetimeIndex) -> pd.Series:
    """Nord Pool N2EX day-ahead price (hourly) as a half-hourly series, used to
    backfill gaps in the APXMIDP MID. An hourly price applies to both half-hours.

    N2EX prices are licensed data, so a mid_target built with them cannot be shared.
    config.yaml `timeseries.mid_gap_fill_n2ex: false` builds it from Elexon's MID alone
    (gaps then interpolated or left missing), which is what the shareable data pack holds."""
    files = sorted(RAW.glob("nordpool/n2ex_prices_*.csv"))
    if not files or not CFG.get("timeseries", {}).get("mid_gap_fill_n2ex", True):
        return pd.Series(index=idx, dtype=float)
    df = pd.concat([pd.read_csv(f, usecols=lambda c: c in ("deliveryStart", "price")) for f in files],
                   ignore_index=True)
    df["deliveryStart"] = pd.to_datetime(df["deliveryStart"], utc=True)
    s = df.drop_duplicates("deliveryStart").set_index("deliveryStart")["price"].sort_index()
    return s.reindex(idx, method="ffill", limit=1)


MAX_GAP_HH = 6        # a gap of at most this many half-hours is interpolated; a longer one stays empty


def fill_short_gaps(s: pd.Series, max_gap: int = MAX_GAP_HH) -> pd.Series:
    """Linear interpolation across interior gaps of at most `max_gap` values; longer gaps stay NaN whole. (pandas'
    interpolate(limit=n) also fills the first n values of a LONGER gap, from the values on either side of it.)"""
    na = s.isna()
    run = (na != na.shift()).cumsum()
    length = na.groupby(run).transform("sum")
    short = na & (length <= max_gap)
    filled = s.interpolate(limit_area="inside")
    return s.where(~short, filled)


def mid_target(mid_apx: pd.Series, n2ex: pd.Series) -> pd.DataFrame:
    """The MID validation target on the spine of `mid_apx`: Elexon's APX market index where the half-hour had traded
    volume (gbpowerdata.common.elexon.mid_prices), else N2EX (only where config allows it: licensed), else
    interpolated across a gap of at most MAX_GAP_HH half-hours, else missing; mid_source says which."""
    mid = mid_apx.fillna(n2ex.reindex(mid_apx.index))
    n2ex_filled = mid_apx.isna() & mid.notna()
    before = mid.isna()
    mid = fill_short_gaps(mid)
    source = pd.Series("APXMIDP", index=mid_apx.index)
    source[n2ex_filled] = "N2EX"
    source[before & mid.notna()] = "interpolated"
    source[mid.isna()] = "missing"
    return pd.DataFrame({"price_gbp_per_mwh": mid, "mid_source": source})


def demand_table(itsdo: pd.Series, esp: pd.DataFrame) -> pd.DataFrame:
    """Demand on the spine of `itsdo` (ITSDO, MW, NaN where Elexon published none) and `esp` (ESPENI's embedded wind
    and solar). transmission_demand_mw is ITSDO, interpolated across a gap of at most MAX_GAP_HH half-hours;
    national_demand_mw adds the embedded generation and is empty wherever ITSDO is (500 half-hours of 2018, 2020 and
    2021 in whole days, when Elexon published neither ITSDO nor INDO): read as zero they put national demand at
    0.7-11 GW. transmission_demand_source is ITSDO, interpolated or missing."""
    filled = fill_short_gaps(itsdo)
    source = pd.Series("ITSDO", index=itsdo.index)
    source[itsdo.isna() & filled.notna()] = "interpolated"
    source[filled.isna()] = "missing"
    d = pd.DataFrame({"startTime": itsdo.index, "transmission_demand_mw": filled.values,
                      "embedded_wind_mw": esp["embedded_wind_mw"].values,
                      "embedded_solar_mw": esp["embedded_solar_mw"].values})
    d["national_demand_mw"] = d["transmission_demand_mw"] + d["embedded_wind_mw"] + d["embedded_solar_mw"]
    d["transmission_demand_source"] = source.values
    return d


def capacities() -> dict:
    """CF denominators (MW): REPD OPERATIONAL capacity by technology in YEAR (time-
    masked, so unbuilt future phases don't dilute CF), split transmission vs
    embedded wind via the BM-unit snapshot."""
    offshore = repd.operational_capacity(YEAR, "offshore")
    onshore_total = repd.operational_capacity(YEAR, "onshore")
    solar = repd.operational_capacity(YEAR, "solar")

    bm_file = sorted(RAW.glob("bm_units_*.csv"))[-1]
    bm = pd.read_csv(bm_file, keep_default_na=False, na_values=[""])
    bm["generationCapacity"] = pd.to_numeric(bm["generationCapacity"], errors="coerce")
    bm_wind = bm[bm["fuelType"] == "WIND"]
    trans_wind = bm_wind[bm_wind["elexonBmUnit"].str.startswith("T_", na=False)]["generationCapacity"].sum()

    transmission_onshore = max(trans_wind - offshore, 0.0)
    embedded_onshore = max(onshore_total - transmission_onshore, 1.0)
    return {
        "offshore": float(offshore),
        "onshore_embedded": float(embedded_onshore),
        "solar": float(solar),
        "_bm_file": bm_file.name,
    }


def load_espeni(idx: pd.DatetimeIndex) -> pd.DataFrame:
    cols = [ESP_TIME, ESP_TRANS_WIND, ESP_EMB_WIND, ESP_EMB_SOLAR]
    df = pd.read_csv(RAW / "espeni.csv", usecols=cols).rename(columns={
        ESP_TIME: "startTime",
        ESP_TRANS_WIND: "transmission_wind_mw",
        ESP_EMB_WIND: "embedded_wind_mw",
        ESP_EMB_SOLAR: "embedded_solar_mw",
    })
    df["startTime"] = pd.to_datetime(df["startTime"], utc=True)
    df = df[(df["startTime"] >= START) & (df["startTime"] < END)]
    return df.sort_values("startTime").set_index("startTime").reindex(idx).interpolate(limit=6)


def daily_to_halfhourly(daily: pd.Series, idx: pd.DatetimeIndex) -> pd.Series:
    by_date = daily.copy()
    by_date.index = pd.to_datetime(by_date.index).date
    return pd.Series(idx, index=idx).map(lambda t: by_date.get(t.date(), np.nan))


# UK Carbon Price Support — a fossil-fuel carbon tax for electricity generation, ON TOP
# of the ETS, frozen at GBP 18/tCO2 since 2015/16. GB generators receive NO free ETS
# allowances (full auctioning since 2013), so they pay the full ETS price + CPS per tonne.
CPS_GBP_PER_TONNE = 18.0


def build_fuel_prices(idx: pd.DatetimeIndex) -> pd.DataFrame:
    method = CFG["timeseries"]["fuel_carbon_interpolation"]  # linear | ffill
    days = pd.date_range(f"{YEAR - 1}-12-01", f"{YEAR + 1}-01-31", freq="D")

    def _monthly_to_daily(path: str, col: str) -> pd.Series:
        s = pd.read_csv(RAW / path)
        s = s.set_index(pd.to_datetime(s["month"] + "-15"))[col].sort_index()
        d = (s.reindex(s.index.union(days)).ffill().reindex(days) if method == "ffill"
             else s.reindex(s.index.union(days)).interpolate("time").reindex(days))
        return d.ffill().bfill()

    # Gas: daily SAP (p/therm) -> half-hourly by calendar date.
    gas = pd.read_csv(RAW / "gas_sap_daily.csv", parse_dates=["date"])
    gas = gas.set_index("date")["gas_price_pence_per_therm"].sort_index()
    gas_daily = (gas.reindex(gas.index.union(days)).interpolate("time")
                 .reindex(days).ffill().bfill())

    # Carbon: monthly ETS (EU-ETS EUA pre-2021 / UK-ETS UKA from 2021), GBP/t.
    carbon_daily = _monthly_to_daily("carbon_monthly.csv", "carbon_price_gbp_per_tonne")
    # Coal: monthly GB coal price (GBP/MWh-thermal) -> half-hourly by calendar month.
    coal_daily = _monthly_to_daily("coal_monthly.csv", "coal_gbp_per_mwh_thermal")

    out = pd.DataFrame({"startTime": idx})
    out["gas_price_pence_per_therm"] = daily_to_halfhourly(gas_daily, idx).round(3).values
    out["coal_price_gbp_per_mwh_thermal"] = daily_to_halfhourly(coal_daily, idx).round(3).values
    out["carbon_price_gbp_per_tonne"] = daily_to_halfhourly(carbon_daily, idx).round(3).values
    # Total fossil carbon = ETS + CPS. The ETS-only column is kept for transparency.
    out["carbon_total_gbp_per_tonne"] = (out["carbon_price_gbp_per_tonne"] + CPS_GBP_PER_TONNE).round(3)
    # A year the gas series has not finished (the current one) stops at its last observed day
    # instead of carrying that day's price to 31 December. Completed years are unaffected.
    after = out["startTime"] >= pd.Timestamp(gas.index.max().date() + pd.Timedelta(days=1), tz="UTC")
    out.loc[after, out.columns.drop("startTime")] = np.nan
    return out


def main() -> None:
    if "--fuel-only" in sys.argv[1:]:
        # Fuel prices alone, for a year whose demand and weather inputs are not yet complete
        # (2026 for the peak slides: ESPENI stops in February, the gas and carbon series do not).
        fuel = build_fuel_prices(master_index())
        path = PROC / f"fuel_prices_{YEAR}.csv"
        fuel.to_csv(path, index=False)
        print(f"Saved {len(fuel):,} rows -> {path.name}; gas to "
              f"{fuel.loc[fuel['gas_price_pence_per_therm'].notna(), 'startTime'].max()}")
        return
    print(f"Year {YEAR}  ({START.date()} -> {END.date()})")
    idx = master_index()
    caps = capacities()
    print(f"BM-unit snapshot: {caps.pop('_bm_file')}")
    print("CF denominators (MW):", {k: round(v) for k, v in caps.items()})

    esp = load_espeni(idx)
    itsdo = _load_elexon_series("itsdo_*.csv", "demand").reindex(idx)
    # MID validation target: APXMIDP where it had traded volume; its gaps backfilled from Nord Pool N2EX (if
    # allowed), then short gaps interpolated. mid_source tags provenance.
    target = mid_target(elexon.mid_prices().reindex(idx), _load_n2ex_price(idx))
    mid_source = target["mid_source"]

    # Peak-floor each CF denominator so observed peaks stay below ~0.95/0.98.
    caps["offshore"] = max(caps["offshore"], esp["transmission_wind_mw"].max() / 0.95)
    caps["onshore_embedded"] = max(caps["onshore_embedded"], esp["embedded_wind_mw"].max() / 0.95)
    caps["solar"] = max(caps["solar"], esp["embedded_solar_mw"].max() / 0.98)
    print("CF denominators after peak-floor (MW):", {k: round(v) for k, v in caps.items()})

    # --- demand ---
    demand = demand_table(itsdo, esp)

    # --- capacity factors ---
    cf = pd.DataFrame({"startTime": idx})
    cf["wind_offshore_cf"] = (esp["transmission_wind_mw"] / caps["offshore"]).clip(0, 1).round(4).values
    cf["wind_onshore_cf"] = (esp["embedded_wind_mw"] / caps["onshore_embedded"]).clip(0, 1).round(4).values
    cf["solar_cf"] = (esp["embedded_solar_mw"] / caps["solar"]).clip(0, 1).round(4).values

    # --- fuel prices + MID target ---
    fuel = build_fuel_prices(idx)
    target = target.rename_axis("startTime").reset_index()

    for name, df in [(f"demand_{YEAR}", demand), (f"capacity_factors_{YEAR}", cf),
                     (f"fuel_prices_{YEAR}", fuel), (f"mid_target_{YEAR}", target)]:
        path = PROC / f"{name}.csv"
        df.to_csv(path, index=False)
        print(f"Saved {len(df):,} rows -> {path.name}")

    print("\n--- CF validation (mean / max) ---")
    for col, ref in [("wind_offshore_cf", "GB offshore ~0.40"),
                     ("wind_onshore_cf", "GB onshore ~0.27"),
                     ("solar_cf", "GB solar ~0.11")]:
        print(f"  {col:18s}: mean {cf[col].mean():.3f}, max {cf[col].max():.2f}   ({ref})")
    print("\n--- demand (GW) ---")
    print(f"  transmission: mean {demand['transmission_demand_mw'].mean()/1000:.1f}, "
          f"peak {demand['transmission_demand_mw'].max()/1000:.1f}")
    print(f"  national    : mean {demand['national_demand_mw'].mean()/1000:.1f}, "
          f"peak {demand['national_demand_mw'].max()/1000:.1f}")
    print("\n--- fuel prices ---")
    print(f"  gas p/therm : mean {fuel['gas_price_pence_per_therm'].mean():.1f}")
    print(f"  coal GBP/MWh-th: mean {fuel['coal_price_gbp_per_mwh_thermal'].mean():.1f}")
    print(f"  carbon GBP/t: ETS mean {fuel['carbon_price_gbp_per_tonne'].mean():.1f} "
          f"| +CPS total {fuel['carbon_total_gbp_per_tonne'].mean():.1f}")
    print(f"\nMID target sources: {mid_source.value_counts().to_dict()}")


if __name__ == "__main__":
    sys.exit(main())
