"""Build the consumer-side CfD cost: settlement GBP -> levy GBP/MWh -> GBP/household.

The model computes CfD settlement cost on the *generator* side (what LCCC pays
out, `build_cfd_fleet.py`). This stage closes the loop to the *consumer* side, via
the actual statutory mechanism:

  LCCC pays generators  ->  recovers it from electricity suppliers as the
  Supplier Obligation    ->  suppliers pass it into retail tariffs.

Two published rates matter and they are not the same thing:
  Interim Levy Rate (ILR)   forward-looking, fixed quarterly, what suppliers were
                            actually billed at the time.
  Reconciled Daily Levy     the settled, after-the-fact true-up. This is the
                            defensible "what CfDs cost consumers per MWh" number.
Add the Operational Cost Levy (LCCC's own running costs, ~£0.03-0.08/MWh).

Year-independent — writes the whole panel in one pass, like `cfd_status.csv`.

Output (data/processed/):
  consumer_levy_daily.csv   date, reconciled + interim levy GBP/MWh, eligible
                            demand, CfD payments from the settlement side, and the
                            implied levy (payments / demand) as a cross-check; and
                            the electricity exempted for energy-intensive
                            industries in the same settlement run as the reconciled
                            rate (eii_demand_mwh, from Nov 2017, 85% of their
                            supply until Apr 2024 and 100% since; outside eligible
                            demand), for the cost the exemption moves onto other
                            consumers. Use runs after the initial one (settlement_run
                            != 'II'): the initial run misses certificates processed
                            late, most in July when they renew (July 2024: 3.2% of
                            demand at first, 4.9% reconciled)
  consumer_levy_annual.csv  per year: total levy GBP bn, mean GBP/MWh, and the
                            household bill impact at Ofgem's TDCV

Usage:
  python -m gbpowerdata.build.build_consumer_levy
  python -m gbpowerdata.build.build_consumer_levy --tdcv-kwh 3100
"""

from __future__ import annotations

import argparse
import sys

import pandas as pd

from gbpowerdata import config as cfg

LCCC = cfg.raw_dir() / "lccc"
OCTOPUS = cfg.raw_dir() / "octopus"

# Ofgem Typical Domestic Consumption Value, single-rate electricity. Ofgem cut the
# medium TDCV from 3,100 to 2,700 kWh/yr in Oct 2023; 2,700 is the current basis.
TDCV_KWH = 2700.0
VAT_DOMESTIC = 0.05  # domestic electricity VAT; the levy itself is charged VAT-exclusive


def _dates(df: pd.DataFrame, col: str) -> pd.DataFrame:
    df[col] = pd.to_datetime(df[col], errors="coerce").dt.normalize()
    return df.dropna(subset=[col])


def load_reconciled() -> pd.DataFrame:
    """Settled daily levy rate — one row per day, latest settlement run only."""
    df = pd.read_csv(LCCC / "levy_reconciled_daily.csv")
    df = df[df["Latest_Flag"] == "Latest Settlement Run"].copy()
    df = _dates(df, "Settlement_Date")
    df = df.rename(columns={
        "Settlement_Date": "date",
        "Reconciled_Daily_Levy_Rate_GBP_Per_MWh": "reconciled_levy_gbp_mwh",
        "Reconciled_Eligible_Demand_MWh": "reconciled_eligible_demand_mwh",
        "Reconciled_Energy_Intensive_Industries_Demand_MWh": "eii_demand_mwh",
        "Settlement_Run_Type": "settlement_run"})
    keep = ["date", "reconciled_levy_gbp_mwh", "reconciled_eligible_demand_mwh", "eii_demand_mwh",
            "settlement_run"]
    for c in keep[1:4]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    dup = df["date"].duplicated().sum()
    if dup:
        print(f"  ! {dup} duplicate dates in the latest settlement run — keeping first")
        df = df.drop_duplicates("date")
    return df[keep].sort_values("date")


def load_interim() -> pd.DataFrame:
    """What suppliers were billed at the time (forward-looking ILR)."""
    df = _dates(pd.read_csv(LCCC / "levy_actual_ilr_income.csv"), "Settlement_Date")
    df = df.rename(columns={"Settlement_Date": "date",
                            "Actual_ILR_GBP_Per_MWh": "interim_levy_gbp_mwh",
                            "Actual_Eligible_Demand_MWh": "eligible_demand_mwh",
                            "Actual_Income_GBP": "levy_income_gbp"})
    keep = ["date", "interim_levy_gbp_mwh", "eligible_demand_mwh", "levy_income_gbp"]
    for c in keep[1:]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df[keep].sort_values("date")


def load_operational() -> pd.DataFrame:
    """Operational Cost Levy periods -> a per-period GBP/MWh rate to interval-join."""
    df = pd.read_csv(LCCC / "levy_operational_costs.csv")
    for c in ("Period_Start", "Period_End"):
        df[c] = pd.to_datetime(df[c], errors="coerce").dt.normalize()
    for c in ("OCL_Rate_GBP_Per_MWh", "Effective_OCL_Rate_GBP_Per_MWh"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    # Effective = charged rate net of the excess-cost refund; fall back to charged
    # for periods not yet trued up.
    df["ocl_gbp_mwh"] = df["Effective_OCL_Rate_GBP_Per_MWh"].fillna(df["OCL_Rate_GBP_Per_MWh"])
    return df[["Period_Start", "Period_End", "ocl_gbp_mwh"]].dropna(subset=["Period_Start"])


def load_settlement() -> pd.DataFrame:
    """Generator-side CfD payments per day — the thing the levy has to recover."""
    df = pd.read_csv(LCCC / "cfd_actual_generation.csv", low_memory=False)
    df = _dates(df, "Settlement_Date")
    for c in ("CFD_Payments_GBP", "CFD_Generation_MWh"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    out = (df.groupby("Settlement_Date")
           .agg(cfd_payments_gbp=("CFD_Payments_GBP", "sum"),
                cfd_generation_mwh=("CFD_Generation_MWh", "sum"))
           .reset_index().rename(columns={"Settlement_Date": "date"}))
    return out


def attach_ocl(daily: pd.DataFrame, ocl: pd.DataFrame) -> pd.DataFrame:
    daily["ocl_gbp_mwh"] = pd.NA
    for _, r in ocl.iterrows():
        end = r["Period_End"] if pd.notna(r["Period_End"]) else daily["date"].max()
        m = daily["date"].between(r["Period_Start"], end)
        daily.loc[m, "ocl_gbp_mwh"] = r["ocl_gbp_mwh"]
    daily["ocl_gbp_mwh"] = pd.to_numeric(daily["ocl_gbp_mwh"], errors="coerce")
    return daily


def svt_unit_rate_by_year() -> pd.Series | None:
    """Mean GB standard-variable unit rate GBP/MWh per year, for a share-of-bill column."""
    path = OCTOPUS / "svt_unit_rates.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path, parse_dates=["valid_from", "valid_to"])
    df = df[df["payment_method"].isna() | (df["payment_method"] == "DIRECT_DEBIT")]
    # Expand each (region, price) validity window to days, then average across regions.
    rows = []
    hi = pd.Timestamp.utcnow().normalize()
    for _, r in df.iterrows():
        end = r["valid_to"] if pd.notna(r["valid_to"]) else hi
        if pd.isna(r["valid_from"]) or end <= r["valid_from"]:
            continue
        days = pd.date_range(r["valid_from"].normalize(), end.normalize(), freq="D", tz="UTC")
        rows.append(pd.DataFrame({"date": days, "rate": r["price_gbp_mwh_inc_vat"]}))
    if not rows:
        return None
    d = pd.concat(rows, ignore_index=True)
    d["year"] = d["date"].dt.year
    return d.groupby("year")["rate"].mean()


def main(argv: list[str]) -> None:
    p = argparse.ArgumentParser(description="Build consumer-side CfD levy series.")
    p.add_argument("--tdcv-kwh", type=float, default=TDCV_KWH,
                   help=f"annual household consumption for the bill impact (default {TDCV_KWH:.0f}).")
    args = p.parse_args(argv[1:])

    missing = [f for f in ("levy_reconciled_daily.csv", "levy_actual_ilr_income.csv",
                           "levy_operational_costs.csv", "cfd_actual_generation.csv")
               if not (LCCC / f).exists()]
    if missing:
        sys.exit(f"Missing LCCC inputs {missing} — run "
                 "`python -m gbpowerdata.pull.lccc_pull --all` first.")

    daily = load_reconciled().merge(load_interim(), on="date", how="outer")
    daily = daily.merge(load_settlement(), on="date", how="left").sort_values("date")
    daily = attach_ocl(daily, load_operational())

    # Cross-check: settlement paid out / eligible demand should track the settled
    # levy rate. Divergence is timing (the levy lags payments) plus the reserve.
    demand = daily["reconciled_eligible_demand_mwh"].fillna(daily["eligible_demand_mwh"])
    daily["implied_levy_gbp_mwh"] = daily["cfd_payments_gbp"] / demand
    daily["total_levy_gbp_mwh"] = (daily["reconciled_levy_gbp_mwh"].fillna(0)
                                   + daily["ocl_gbp_mwh"].fillna(0))
    daily["eligible_demand_mwh"] = demand

    out_daily = cfg.processed_dir() / "consumer_levy_daily.csv"
    cols = ["date", "reconciled_levy_gbp_mwh", "interim_levy_gbp_mwh", "ocl_gbp_mwh",
            "total_levy_gbp_mwh", "implied_levy_gbp_mwh", "eligible_demand_mwh",
            "cfd_payments_gbp", "cfd_generation_mwh", "levy_income_gbp", "settlement_run", "eii_demand_mwh"]
    daily[cols].to_csv(out_daily, index=False)
    print(f"Saved {len(daily):,} daily rows -> {out_daily}")

    # ---- annual roll-up -------------------------------------------------------
    d = daily.copy()
    d["year"] = d["date"].dt.year
    # Demand-weighted mean levy: the levy is charged per MWh, so weight by MWh.
    d["levy_cost_gbp"] = d["total_levy_gbp_mwh"] * d["eligible_demand_mwh"]
    ann = (d.groupby("year")
           .agg(days=("date", "size"),
                eligible_demand_twh=("eligible_demand_mwh", lambda s: s.sum() / 1e6),
                levy_cost_gbp_bn=("levy_cost_gbp", lambda s: s.sum() / 1e9),
                cfd_payments_gbp_bn=("cfd_payments_gbp", lambda s: s.sum() / 1e9),
                mean_reconciled_gbp_mwh=("reconciled_levy_gbp_mwh", "mean"),
                mean_interim_gbp_mwh=("interim_levy_gbp_mwh", "mean"))
           .reset_index())
    ann = ann[ann["days"] >= 350]  # drop part-years at the panel edges
    ann["levy_weighted_gbp_mwh"] = ann["levy_cost_gbp_bn"] * 1e9 / (ann["eligible_demand_twh"] * 1e6)
    ann["household_gbp_yr_exc_vat"] = ann["levy_weighted_gbp_mwh"] * args.tdcv_kwh / 1000.0
    ann["household_gbp_yr_inc_vat"] = ann["household_gbp_yr_exc_vat"] * (1 + VAT_DOMESTIC)

    svt = svt_unit_rate_by_year()
    if svt is not None:
        ann["svt_unit_rate_gbp_mwh"] = ann["year"].map(svt)
        ann["levy_share_of_unit_rate_pct"] = (
            100 * ann["levy_weighted_gbp_mwh"] * (1 + VAT_DOMESTIC) / ann["svt_unit_rate_gbp_mwh"])
    else:
        print("  (no Octopus SVT data — run `python -m gbpowerdata.pull.octopus_pull svt` "
              "for the share-of-tariff columns)")

    out_ann = cfg.processed_dir() / "consumer_levy_annual.csv"
    ann.to_csv(out_ann, index=False)
    print(f"Saved {len(ann)} annual rows -> {out_ann}\n")

    show = ["year", "eligible_demand_twh", "cfd_payments_gbp_bn", "levy_cost_gbp_bn",
            "levy_weighted_gbp_mwh", "household_gbp_yr_inc_vat"]
    if "levy_share_of_unit_rate_pct" in ann:
        show += ["svt_unit_rate_gbp_mwh", "levy_share_of_unit_rate_pct"]
    print(f"CfD cost to consumers (TDCV {args.tdcv_kwh:.0f} kWh/yr)")
    print(ann[show].to_string(index=False, float_format=lambda v: f"{v:,.2f}"))


if __name__ == "__main__":
    sys.exit(main(sys.argv))
