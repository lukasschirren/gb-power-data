"""Build the authoritative per-unit CfD fleet for `config.year` from LCCC data.

Unlike the keyword-matched register tagging (Stage 1), this uses the LCCC
actual-generation dataset, which records which CfD units actually drew CfD
difference payments in the year — the correct fleet for a settlement-cost model.
Notably it excludes commissioned units that ran merchant (e.g. Hornsea 2 deferred
its CfD start through 2023), which the nameplate/register approach mis-tags.

Output (data/processed/): cfd_fleet_{year}.csv — one row per operational CfD unit:
  CfD_ID, name, technology, allocation_round, contract_capacity_mw, delivery_weight,
  effective_capacity_mw, bmu_id, generation_mwh, mean_strike_gbp_mwh,
  mean_market_ref_gbp_mwh, cfd_payments_gbp

Headline: total CfD generation and net settlement cost (the consumer-cost figure
the ABM exists to reproduce). Feeds Stage 3 (CfD agents) and Stage 4 (validation).

MID-YEAR DELIVERY
    A contract that starts part-way through a year used to enter the stack at full
    contract capacity for all twelve months of it. The fleet is annual and the model
    is half-hourly, so Lynemouth (407 MW from 23 Jun 2018), Walney Extension (330 MW
    from 13 Apr) and Beatrice (252 MW from 6 Nov) were each present for months in
    which they did not exist: the 2018 CfD fleet was 24% larger than its
    delivery-weighted size, 2019 13%, later years 4-6%.

    `delivery_weight` is the share of the year the contract was actually in delivery,
    and `effective_capacity_mw` is the contract capacity scaled by it. For WIND AND
    SOLAR the weight is the share of the year's CAPACITY FACTOR falling inside the
    delivery window, not the share of days — a farm commissioned in April misses the
    windiest quarter, and a days-based weight would hand it back that energy. For
    baseload technologies the CF is flat and the two coincide, so days are used.

    The window is read from the unit's own settlement rows in the LCCC file rather
    than from a register start date: same source as everything else here, and it is
    the period the unit was actually paid for.

    DIAGNOSTIC ONLY - DO NOT FEED `effective_capacity_mw` TO STAGE 3 ON ITS OWN.
    Tried and reverted (tag v24). The overstatement is real but it is not free-standing:
    stage2 builds the capacity-factor series as metered output over REPD's END-OF-YEAR
    operational capacity, so the CF denominator already carries the same part-year effect
    and the series is depressed by it. Multiplying a delivery-weighted capacity by an
    already-depressed CF derates twice. Measured against LCCC's published intermittent-CfD
    generation:

        TWh          2018   2019   2020   2021   2023   2025
        published    4.76   9.47  14.59  15.07  18.64  27.18
        nameplate    5.01   9.26  13.74  14.69  16.34  26.88   <- what the model ships
        weighted     3.70   7.57  12.41  13.72  15.93  26.18   <- double-derated

    and the settlement panel total moves from -0.4% of the published outturn to -6.0%.
    The pipeline is internally consistent on nameplate; correcting the fleet alone breaks
    a pair of matched conventions. Doing this properly means fixing BOTH ends - a
    delivery-weighted fleet AND a CF denominator built on delivery-weighted capacity -
    which is a stage-2 change, not a stage-3 one.

    The columns are kept because the size of the effect is worth knowing (2018 24%,
    2019 13%, later years 4-6%) and because the correct fix needs them.
"""

from __future__ import annotations

import sys

import pandas as pd

from gbpowerdata import config as cfg

CFG = cfg.load_config()
YEAR = int(CFG["year"])
LCCC = cfg.raw_dir() / "lccc"

# LCCC technology -> the capacity-factor column whose seasonality the delivery weight
# must respect. Anything absent here is treated as flat (baseload), where the CF-weighted
# and day-weighted shares coincide.
CF_COL = {"Offshore Wind": "wind_offshore_cf", "Onshore Wind": "wind_onshore_cf",
          "Solar PV": "solar_cf", "Solar Photovoltaic": "solar_cf"}
_CF: pd.DataFrame | None = None


def _cf_table() -> pd.DataFrame | None:
    """Half-hourly capacity factors for the year, or None if the stage has not run."""
    global _CF
    if _CF is None:
        f = cfg.processed_dir() / f"capacity_factors_{YEAR}.csv"
        if not f.exists():
            return None
        d = pd.read_csv(f, parse_dates=["startTime"])
        d["startTime"] = pd.to_datetime(d["startTime"], utc=True)
        _CF = d.set_index("startTime")
    return _CF


def _weight(first_day, last_day, technology: str | None) -> float:
    """Share of the year the contract was in delivery, CF-weighted for wind and solar."""
    if pd.isna(first_day) or pd.isna(last_day):
        return 1.0
    lo = pd.Timestamp(first_day).tz_localize("UTC")
    hi = pd.Timestamp(last_day).tz_localize("UTC") + pd.Timedelta(days=1)
    cf, col = _cf_table(), CF_COL.get(str(technology))
    if cf is not None and col in (cf.columns if cf is not None else []):
        tot = float(cf[col].sum())
        if tot > 0:
            inside = float(cf.loc[(cf.index >= lo) & (cf.index < hi), col].sum())
            return min(1.0, inside / tot)
    days = pd.Timestamp(f"{YEAR}-12-31") - pd.Timestamp(f"{YEAR}-01-01")
    return min(1.0, ((hi - lo).days) / (days.days + 1))


def main() -> None:
    gen = pd.read_csv(LCCC / "cfd_actual_generation.csv")
    gen["Settlement_Date"] = pd.to_datetime(gen["Settlement_Date"], errors="coerce")
    for c in ("CFD_Generation_MWh", "Strike_Price_GBP_Per_MWh", "CFD_Payments_GBP",
              "Market_Reference_Price_GBP_Per_MWh"):
        gen[c] = pd.to_numeric(gen[c], errors="coerce")
    yr = gen[gen["Settlement_Date"].dt.year == YEAR]
    if yr.empty:
        sys.exit(f"No LCCC CfD generation records for {YEAR} — check the pull.")

    fleet = (yr.groupby(["CfD_ID", "Name_of_CfD_Unit", "Technology", "Allocation_round"])
             .agg(generation_mwh=("CFD_Generation_MWh", "sum"),
                  mean_strike_gbp_mwh=("Strike_Price_GBP_Per_MWh", "mean"),
                  mean_market_ref_gbp_mwh=("Market_Reference_Price_GBP_Per_MWh", "mean"),
                  cfd_payments_gbp=("CFD_Payments_GBP", "sum"))
             .reset_index())
    fleet = fleet[fleet["generation_mwh"] > 0].copy()

    # Contract capacity from the portfolio status.
    ps = pd.read_csv(LCCC / "cfd_contract_portfolio_status.csv")
    cap = ps.set_index("CFD_ID")["Maximum_Contract_Capacity_MW"]
    fleet["contract_capacity_mw"] = fleet["CfD_ID"].map(cap)

    # Delivery window per unit, from its own settlement rows (see MID-YEAR DELIVERY).
    win = yr[yr["CFD_Generation_MWh"].notna()].groupby("CfD_ID")["Settlement_Date"].agg(
        ["min", "max"]).rename(columns={"min": "first_day", "max": "last_day"})
    fleet = fleet.merge(win, left_on="CfD_ID", right_index=True, how="left")
    fleet["delivery_weight"] = [_weight(r.first_day, r.last_day, r.Technology)
                                for r in fleet.itertuples()]
    fleet["effective_capacity_mw"] = (fleet["contract_capacity_mw"]
                                      * fleet["delivery_weight"]).round(2)

    # BM-unit id(s) from the mapping (first active mapping per CfD unit).
    mp = pd.read_csv(LCCC / "cfd_to_bm_unit_mapping.csv")
    bmu = mp.groupby("CFD_Id")["BMU_Id"].first()
    fleet["bmu_id"] = fleet["CfD_ID"].map(bmu)

    fleet = fleet.rename(columns={"Name_of_CfD_Unit": "name", "Technology": "technology",
                                  "Allocation_round": "allocation_round"})
    fleet = fleet[["CfD_ID", "name", "technology", "allocation_round",
                   "contract_capacity_mw", "delivery_weight", "effective_capacity_mw",
                   "bmu_id", "generation_mwh",
                   "mean_strike_gbp_mwh", "mean_market_ref_gbp_mwh", "cfd_payments_gbp"]]
    fleet = fleet.sort_values("contract_capacity_mw", ascending=False, ignore_index=True)

    out = cfg.processed_dir() / f"cfd_fleet_{YEAR}.csv"
    fleet.to_csv(out, index=False)

    cap_gw = fleet["contract_capacity_mw"].sum() / 1e3
    gen_twh = fleet["generation_mwh"].sum() / 1e6
    pay_m = fleet["cfd_payments_gbp"].sum() / 1e6
    print(f"Authoritative CfD fleet {YEAR}: {len(fleet)} operational units")
    print(f"  contract capacity : {cap_gw:,.2f} GW")
    print(f"  CfD generation    : {gen_twh:,.2f} TWh")
    print(f"  net settlement    : GBP {pay_m:,.0f} m  (CfD top-up; negative = generators paid back)")
    print("\n  by technology:")
    print(fleet.groupby("technology").agg(
        units=("CfD_ID", "count"),
        capacity_mw=("contract_capacity_mw", "sum"),
        payments_m=("cfd_payments_gbp", lambda s: round(s.sum() / 1e6, 1)),
    ).round(0).to_string())
    print(f"\nSaved -> {out.name}")


if __name__ == "__main__":
    sys.exit(main())
