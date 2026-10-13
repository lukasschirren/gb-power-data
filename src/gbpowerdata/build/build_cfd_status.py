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

THE END OF A CONTRACT (cfd_end_date, the first day without it; contract_end). The CfD Agreement sets the Specified
Expiry Date as the 15th anniversary of the EARLIER of the Start Date and the last day of the Target Commissioning
Window (TCW), the 20th for offshore wind (floating and other deepwater included), onshore and remote island wind and
solar PV from AR7 (generic CfD Agreement for AR8, May 2026, clause 3 and drafting notes 4-5; cfd_round_params.csv's
key-technology term), so a contract that starts after its window loses the years between. Biomass conversions end on
31 March 2027 (the model CfD Agreement's date for them; Drax unit 1 and Lynemouth, whose low-carbon dispatchable
CfDs from 1 April 2027 are separate contracts). Hinkley Point C's bespoke contract runs 35 years from its start.
The register gives the window's first day and a target commissioning date; where that date is later it is the
window's last day (AR2's offshore phases 364 days on, AR4 and AR6 solar three months on), else the register gives no
window length and the first day stands in, which can end a contract up to a window's length early. Until 13 Oct
2026 the end was the start plus the term, which ran late starters too long (Neart na Gaoithe to 2040 rather than
2034, Moray East to 2039 rather than 2037) and kept the two biomass conversions to 2031 and 2033.
"""

from __future__ import annotations

import sys

import pandas as pd

from gbpowerdata import config as cfg
from gbpowerdata.common import repd

# Map register technology_type -> (model tech, is_offshore, REPD tech hint).
TECH_MAP = {
    "Offshore Wind": ("Wind", True, "offshore"),
    "Floating Offshore Wind": ("Wind", True, "offshore"),
    "Onshore Wind": ("Wind", False, "onshore"),
    "Remote Island Wind": ("Wind", False, "onshore"),
    "Solar PV": ("Solar", False, "solar"),
    "Biomass Conversion": ("Biomass", False, None),
    "Dedicated Biomass": ("Biomass", False, None),
    "Energy from Waste with CHP": ("Waste", False, None),
    "Advanced Conversion Technologies": ("Waste", False, None),
    "Hydro": ("Hydro", False, None),
    "Tidal Stream": ("Tidal", False, None),
}
# the register's technologies that take the key-technology term (20 years from AR7; drafting note 5)
KEY_TERM = {"Offshore Wind", "Floating Offshore Wind", "Onshore Wind", "Remote Island Wind", "Solar PV"}
CONVERSION_END = pd.Timestamp("2027-04-01")       # the first day after 31 March 2027


def contract_end(start, tcw_start, target_commissioning, term_years: int, technology: str,
                 allocation_round: str) -> pd.Timestamp:
    """The first day without the contract (module docstring, THE END OF A CONTRACT); NaT before it starts."""
    if technology == "Biomass Conversion":
        return CONVERSION_END
    if pd.isna(start):
        return pd.NaT
    counts_from = pd.Timestamp(start)
    if allocation_round != "Bespoke":
        window_end = max((d for d in (tcw_start, target_commissioning) if pd.notna(d)), default=pd.NaT)
        if pd.notna(window_end):
            counts_from = min(counts_from, pd.Timestamp(window_end))
    return counts_from + pd.DateOffset(years=int(term_years))


def main() -> None:
    s1 = cfg.load_config()["stage1"]
    reg = pd.read_excel(cfg.raw_dir() / s1["cfd_register"])
    params = pd.read_csv(cfg.reference_dir() / "cfd_round_params.csv")

    for c in ("start_date", "termination_date", "target_commissioning_date", "target_commissioning_window_start_date"):
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
        term = int(pr["contract_term_years_key_tech"] if tech_raw in KEY_TERM
                   else pr["contract_term_years_other"])
        start = r["start_date"]
        end = contract_end(start, r["target_commissioning_window_start_date"], r["target_commissioning_date"],
                           term, tech_raw, ar)
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
            "cfd_end_date": end.date() if pd.notna(end) else None,
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
