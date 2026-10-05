"""Build the per-CfD-unit status table — the single source of truth for the panel.

One row per CfD contract (phases are separate contracts in the register). Joins:
  - LCCC CfD register  -> capacity, start_date, strike (base-year), base_year, round
  - cfd_round_params   -> vintage, term, negative-price rule (by allocation_round)
  - REPD               -> commissioned_date (actual first power; captures the
                          merchant period a farm may run before its CfD starts)

Output (data/processed/): cfd_status.csv. Downstream, two masks are evaluated per
year t:
  operational_mw(t) = cfd_capacity_mw if commissioned_date <= t            (physical)
  cfd_active_mw(t)  = cfd_capacity_mw if cfd_start_date <= t < cfd_end_date (settlement)

Baseline strike-by-year comes from the LCCC actual-generation data (already
CPI-uprated); CPI indexation of strike_base is deferred to counterfactual reruns.
"""

from __future__ import annotations

import sys

import pandas as pd

from gbpowerdata import config as cfg
from gbpowerdata.common import repd

# Map register technology_type -> (model tech, is_offshore, REPD tech hint).
TECH_MAP = {
    "Offshore Wind": ("Wind", True, "offshore"),
    "Onshore Wind": ("Wind", False, "onshore"),
    "Solar PV": ("Solar", False, "solar"),
    "Biomass Conversion": ("Biomass", False, None),
    "Dedicated Biomass": ("Biomass", False, None),
    "Energy from Waste with CHP": ("Waste", False, None),
    "Advanced Conversion Technologies": ("Waste", False, None),
    "Hydro": ("Hydro", False, None),
    "Tidal Stream": ("Tidal", False, None),
}


def main() -> None:
    s1 = cfg.load_config()["stage1"]
    reg = pd.read_excel(cfg.raw_dir() / s1["cfd_register"])
    params = pd.read_csv(cfg.reference_dir() / "cfd_round_params.csv")

    for c in ("start_date", "termination_date", "target_commissioning_date"):
        reg[c] = pd.to_datetime(reg[c], errors="coerce", utc=True).dt.tz_localize(None)

    p = params.set_index("allocation_round")
    rows = []
    for _, r in reg.iterrows():
        ar = r["allocation_round"]
        if ar not in p.index:
            continue
        pr = p.loc[ar]
        tech_raw = str(r["technology_type"])
        tech, is_off, hint = TECH_MAP.get(tech_raw, (tech_raw, False, None))
        term = int(pr["contract_term_years_key_tech"] if tech in ("Wind", "Solar")
                   else pr["contract_term_years_other"])
        start = r["start_date"]
        comm = repd.commissioned_date(r["project_name"], hint) if pd.notna(r["project_name"]) else None
        if comm is None and pd.notna(r["target_commissioning_date"]):
            comm = r["target_commissioning_date"]
        rows.append({
            "cfd_id": r["contract_id"],
            "name": r["project_name"],
            "technology": tech,
            "is_offshore": is_off,
            "allocation_round": ar,
            "vintage": pr["vintage"],
            "neg_price_rule": pr["neg_price_rule"],
            "neg_price_min_hours": int(pr["neg_price_min_consecutive_hours"]),
            "term_years": term,
            "cfd_capacity_mw": pd.to_numeric(r["current_installed_capacity"], errors="coerce"),
            "cfd_start_date": start.date() if pd.notna(start) else None,
            "cfd_end_date": (start + pd.DateOffset(years=term)).date() if pd.notna(start) else None,
            "strike_base_gbp_mwh": pd.to_numeric(r["initial_strike_price"], errors="coerce"),
            "base_year": r["base_year"],
            "commissioned_date": pd.Timestamp(comm).date() if comm is not None and pd.notna(comm) else None,
        })

    status = pd.DataFrame(rows)
    out = cfg.processed_dir() / "cfd_status.csv"
    status.to_csv(out, index=False)

    # Diagnostics: how the operational fleet evolves vs the CfD-paying fleet.
    print(f"CfD status table: {len(status)} contracts -> {out.name}\n")
    st = status.copy()
    st["commissioned_date"] = pd.to_datetime(st["commissioned_date"])
    st["cfd_start_date"] = pd.to_datetime(st["cfd_start_date"])
    st["cfd_end_date"] = pd.to_datetime(st["cfd_end_date"])
    print("Year | operational GW | CfD-active GW | merchant-but-built GW (deferred)")
    for y in range(2018, 2026):
        end = pd.Timestamp(f"{y}-12-31")
        opera = st[st["commissioned_date"] <= end]
        active = opera[(opera["cfd_start_date"] <= end) & (opera["cfd_end_date"] > end)]
        op_gw = opera["cfd_capacity_mw"].sum() / 1e3
        ac_gw = active["cfd_capacity_mw"].sum() / 1e3
        print(f"{y} |   {op_gw:6.2f}       |   {ac_gw:6.2f}      |   {op_gw - ac_gw:5.2f}")
    print("\nby vintage (contracts):")
    print(status["vintage"].value_counts().to_string())


if __name__ == "__main__":
    sys.exit(main())
