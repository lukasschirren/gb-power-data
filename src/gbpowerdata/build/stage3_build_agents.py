"""Stage 3 — collapse the fleet into representative ABM agents (LOCATIONAL panel).

Three sources, each authoritative for its part:
  - CfD agents          <- cfd_fleet_{year}.csv (LCCC actual-paying fleet) enriched
                           with vintage / negative-price rule from cfd_status.csv
                           and the CfD register's authoritative `gsp_group`.
  - Offshore wind (non-CfD) <- REPD operational capacity (time-masked, no phantom)
                           minus the CfD-paying offshore, split RO (commissioned
                           <= RO closure) vs None (post-closure merchant, which
                           absorbs deferred-CfD farms such as Hornsea 2), and
                           distributed across zones by REPD per-zone offshore share.
  - Everything else (onshore wind, solar, biomass, hydro, thermal, nuclear,
    storage) <- the Stage 1b LOCATED PPM tagging (powerplants_located_{year}.csv).

Locational extension (additive — national totals are unchanged, a gsp_group
groupby reproduces the copperplate fleet): every agent carries `gsp_id` (~330 GSP
regions, best-effort) and `gsp_group` (14 zones, _A.._P). CfD `gsp_group` comes
straight from the LCCC register (authoritative for the grid-connection group —
this is what correctly puts Hornsea in _M, not the nearest-land snap). Sub-500MW
PPM plants now bucket per (tech, regime, is_offshore, gsp_group), so embedded
solar / onshore wind become located per-zone agents.

Each CfD agent carries `vintage` and `neg_price_rule` so the ABM can apply the
AR1-3 six-hour vs AR4+ any-hour behaviour.  Output: data/processed/agents_{year}.csv
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from gbpowerdata import config as cfg
from gbpowerdata.common import gsp
from gbpowerdata.common import repd

CFG = cfg.load_config()
YEAR = int(CFG["year"])
THRESH = float(CFG["agents"]["individual_threshold_mw"])
RO_CLOSURE = int(CFG["stage1"]["ro_closure_year"])
TP = cfg.load_reference_yaml("tech_parameters.yaml")
EFF, EMIT, ROC, CFD_TECH = TP["efficiency_defaults"], TP["emissions_factor"], TP["roc_value"], TP["cfd_tech_map"]
VINTAGE_EFF = TP.get("efficiency_vintage", {})  # gas efficiency by commissioning year (DateIn)
# A measured PPM efficiency is net LHV; this factor (NCV/GCV) puts it on the basis of the fuel's price
# (gas per therm = GCV). See the heating-value note at the top of tech_parameters.yaml.
PPM_EFF_FACTOR = TP.get("ppm_efficiency_basis_factor", {})

AGENT_COLS = ["agent_id", "name", "tech", "support_regime", "capacity_mw", "n_plants",
              "efficiency", "emissions_factor", "support_value_gbp_mwh", "is_offshore",
              "vintage", "neg_price_rule", "gsp_id", "gsp_group", "source"]

# --- per-tech flexibility / cost-shape parameters (ABM v1, build-step 1) ------
#   availability   : fraction of nameplate offerable in a period (outage/maintenance).
#                    VRE = 1.0 (the CF series already sets output, no double-derate);
#                    nuclear = empirical fleet CF (it runs whenever available, so realized
#                    CF is its availability); dispatchable thermal = technical availability
#                    (the merit order decides actual running); hydro = energy-limited proxy.
#   srmc_base      : non-fuel marginal cost (GBP/MWh_e) for techs NOT priced off a
#                    time-varying fuel series — nuclear ~8 (uranium + O&M), supported
#                    renewables ~0. NaN => fuel-priced (gas/coal/oil): the ABM computes
#                    SRMC from fuel_prices (+ coal_monthly) at clearing time.
#   min_stable_pct, ramp_pct_per_h : OVERRIDDEN from tech_flexibility_empirical.csv where
#                    present (Nuclear/Hard Coal/CCGT/OCGT); documented defaults elsewhere.
#                    Carried now so agents are complete for the Stage-2 stateful engine.
TECH_FLEX = {
    "Nuclear":       {"availability": 0.65, "srmc_base": 8.0,    "min_stable_pct": 91, "ramp_pct_per_h": 3.3},
    "CCGT":          {"availability": 0.90, "srmc_base": np.nan, "min_stable_pct": 20, "ramp_pct_per_h": 20.5},
    "OCGT":          {"availability": 0.90, "srmc_base": np.nan, "min_stable_pct": 10, "ramp_pct_per_h": 53.9},
    "Hard Coal":     {"availability": 0.85, "srmc_base": np.nan, "min_stable_pct": 18, "ramp_pct_per_h": 13.7},
    "Oil":           {"availability": 0.85, "srmc_base": np.nan, "min_stable_pct": 10, "ramp_pct_per_h": 50.0},
    "Biomass":       {"availability": 0.80, "srmc_base": 0.0,    "min_stable_pct": 40, "ramp_pct_per_h": 10.0},
    "Solid Biomass": {"availability": 0.80, "srmc_base": 0.0,    "min_stable_pct": 40, "ramp_pct_per_h": 10.0},
    "Waste":         {"availability": 0.85, "srmc_base": 0.0,    "min_stable_pct": 50, "ramp_pct_per_h": 5.0},
    "Hydro":         {"availability": 0.40, "srmc_base": 0.0,    "min_stable_pct": 0,  "ramp_pct_per_h": 80.0},
    "Wind":          {"availability": 1.00, "srmc_base": 0.0,    "min_stable_pct": 0,  "ramp_pct_per_h": 100.0},
    "Solar":         {"availability": 1.00, "srmc_base": 0.0,    "min_stable_pct": 0,  "ramp_pct_per_h": 100.0},
    "Battery":       {"availability": 0.90, "srmc_base": np.nan, "min_stable_pct": 0,  "ramp_pct_per_h": 100.0},
    "Geothermal":    {"availability": 0.85, "srmc_base": 0.0,    "min_stable_pct": 50, "ramp_pct_per_h": 5.0},
    "Other":         {"availability": 0.85, "srmc_base": 0.0,    "min_stable_pct": 0,  "ramp_pct_per_h": 50.0},
}
FLEX_COLS = ["availability", "srmc_base_gbp_mwh", "min_stable_pct", "ramp_pct_per_h"]
OUT_COLS = AGENT_COLS + FLEX_COLS


def flexibility_table() -> pd.DataFrame:
    """Per-tech flexibility/cost-shape params. min_stable + ramp come from the
    empirical FUELHH analysis (tech_flexibility_empirical.csv) where available;
    availability + srmc_base from the documented TECH_FLEX defaults."""
    flex = (pd.DataFrame(TECH_FLEX).T.rename_axis("tech").reset_index()
            .rename(columns={"srmc_base": "srmc_base_gbp_mwh"}))
    for c in ["availability", "srmc_base_gbp_mwh", "min_stable_pct", "ramp_pct_per_h"]:
        flex[c] = pd.to_numeric(flex[c], errors="coerce")
    emp_path = cfg.reference_dir() / "tech_flexibility_empirical.csv"
    if emp_path.exists():
        emp = pd.read_csv(emp_path).set_index("technology")
        for tech in emp.index.intersection(flex["tech"]):
            flex.loc[flex["tech"] == tech, "min_stable_pct"] = emp.loc[tech, "min_stable_pct_committed"]
            flex.loc[flex["tech"] == tech, "ramp_pct_per_h"] = emp.loc[tech, "ramp_p99_pct_per_h"]
    return flex[["tech"] + FLEX_COLS]


def nuclear_availability() -> float | None:
    """Empirical per-year nuclear availability (FUELHH-derived, src/nuclear_availability.py)
    for YEAR — the ageing/declining AGR fleet ran well below nameplate and the troubled
    units sat offline for years before official closure, so a flat factor carries phantom
    nuclear. Falls back to the flat TECH_FLEX value if the reference file is absent."""
    path = cfg.reference_dir() / "nuclear_availability_by_year.csv"
    if not path.exists():
        return None
    t = pd.read_csv(path).set_index("year")["availability"]
    return float(t.loc[YEAR]) if YEAR in t.index else None


def _cfd_register() -> pd.DataFrame:
    """contract_id -> authoritative gsp_group + coordinates (for gsp_id)."""
    reg = pd.read_excel(cfg.raw_dir() / CFG["stage1"]["cfd_register"])
    return reg.set_index("contract_id")[["gsp_group", "latitude", "longitude"]]


def cfd_agents() -> pd.DataFrame:
    fleet = pd.read_csv(cfg.processed_dir() / f"cfd_fleet_{YEAR}.csv")
    status = pd.read_csv(cfg.processed_dir() / "cfd_status.csv")
    vint = status[["cfd_id", "vintage", "neg_price_rule"]].drop_duplicates("cfd_id")
    f = fleet.merge(vint, left_on="CfD_ID", right_on="cfd_id", how="left")

    reg = _cfd_register()
    f = f.merge(reg, left_on="CfD_ID", right_index=True, how="left")
    # gsp_id from the register coordinates (best-effort); gsp_group stays the
    # register's own authoritative value where present (offshore connection group).
    loc = gsp.tag_latlon(f, "latitude", "longitude")
    f["gsp_id"] = loc["gsp_id"].values
    f["gsp_group"] = f["gsp_group"].where(f["gsp_group"].notna(), loc["gsp_group"].values)

    rows = []
    for _, u in f.iterrows():
        m = CFD_TECH.get(u["technology"], {"tech": u["technology"], "fuel": u["technology"], "offshore": False})
        rows.append({
            "agent_id": u["CfD_ID"], "name": u["name"], "tech": m["tech"],
            # NAMEPLATE, deliberately - see the MID-YEAR DELIVERY note in build_cfd_fleet.
            # cfd_fleet also carries a delivery-weighted `effective_capacity_mw`, and using
            # it HERE makes the model worse, because the capacity-factor series it is
            # multiplied by already carries the same part-year effect in its denominator.
            "support_regime": "CfD", "capacity_mw": round(float(u["contract_capacity_mw"]), 1),
            "n_plants": 1, "efficiency": EFF.get(m["fuel"], np.nan),
            "emissions_factor": EMIT.get(m["fuel"], 0.0),
            "support_value_gbp_mwh": round(float(u["mean_strike_gbp_mwh"]), 2),
            "is_offshore": bool(m["offshore"]), "vintage": u.get("vintage"),
            "neg_price_rule": u.get("neg_price_rule"),
            "gsp_id": u.get("gsp_id"), "gsp_group": u.get("gsp_group"), "source": "LCCC",
        })
    return pd.DataFrame(rows, columns=AGENT_COLS)


def offshore_noncfd_agents() -> pd.DataFrame:
    """Non-CfD offshore wind from REPD operational capacity, RO/None split, then
    distributed across zones by REPD per-zone offshore capacity share."""
    fleet = pd.read_csv(cfg.processed_dir() / f"cfd_fleet_{YEAR}.csv")
    cfd_off = fleet.loc[fleet["technology"] == "Offshore Wind", "contract_capacity_mw"].sum()
    total = repd.operational_capacity(YEAR, "offshore")
    ro_all = repd.operational_capacity(YEAR, "offshore", commissioned_by=RO_CLOSURE)
    non_cfd = max(total - cfd_off, 0.0)
    ro = min(ro_all, non_cfd)
    none = non_cfd - ro

    # Per-zone weights: RO-era offshore vs post-closure offshore distributions.
    ro_zones = repd.operational_by_zone(YEAR, "offshore", commissioned_by=RO_CLOSURE)
    all_zones = repd.operational_by_zone(YEAR, "offshore")
    post_zones = (all_zones.sub(ro_zones, fill_value=0.0)).clip(lower=0.0)

    def _share(s: pd.Series) -> pd.Series:
        return s / s.sum() if s.sum() > 0 else s

    rows = []
    for regime, cap, weights in (("RO", ro, _share(ro_zones)), ("None", none, _share(post_zones))):
        if cap <= 1:
            continue
        for zone, w in weights.items():
            zcap = cap * w
            if zcap <= 1:
                continue
            rows.append({
                "agent_id": f"agg_Wind_{regime}_offshore_{zone}",
                "name": f"Aggregate Wind offshore ({regime}, {zone})",
                "tech": "Wind", "support_regime": regime, "capacity_mw": round(zcap, 1), "n_plants": 0,
                "efficiency": np.nan, "emissions_factor": 0.0,
                "support_value_gbp_mwh": ROC["Wind"] if regime == "RO" else 0.0,
                "is_offshore": True, "vintage": np.nan, "neg_price_rule": np.nan,
                "gsp_id": pd.NA, "gsp_group": zone, "source": "REPD",
            })
    return pd.DataFrame(rows, columns=AGENT_COLS)


def _gas_tech(row):
    tech = str(row.get("Technology", "") or "")
    if "CCGT" in tech or "Combined Cycle" in tech:
        return "CCGT"
    if "OCGT" in tech or "Turbine" in tech:
        return "OCGT"
    return "CCGT" if row["Capacity"] >= 200 else "OCGT"


def _vintage_eff(gas_tech: str, year: float) -> float:
    """Gas efficiency interpolated from the (year, eff) anchors in tech_parameters.yaml,
    clamped outside the anchor range — slopes the gas stack so the marginal unit moves
    with demand through the day (instead of a flat plateau at one default efficiency)."""
    anchors = VINTAGE_EFF[gas_tech]
    return float(np.interp(year, [a[0] for a in anchors], [a[1] for a in anchors]))


def _eff(row):
    e = pd.to_numeric(row.get("Efficiency"), errors="coerce")
    if pd.notna(e) and 0.2 < e < 0.65:          # measured PPM efficiency, if physically sane
        return float(e) * float(PPM_EFF_FACTOR.get(row["Fueltype"], 1.0))
    if row["Fueltype"] == "Natural Gas":
        gt = _gas_tech(row)
        yr = pd.to_numeric(row.get("DateIn"), errors="coerce")
        if pd.notna(yr) and gt in VINTAGE_EFF:  # vintage-sloped by commissioning year
            return _vintage_eff(gt, float(yr))
        return EFF[gt]                            # no commissioning year -> flat default
    return EFF.get(row["Fueltype"], np.nan)


def other_agents() -> pd.DataFrame:
    """LOCATED PPM (Stage 1b) minus CfD and minus offshore wind (REPD handles those).

    Individuals (>=THRESH) keep their own gsp_id + gsp_group; sub-threshold plants
    bucket per (tech, regime, is_offshore, gsp_group) so embedded solar / onshore
    wind become per-zone located agents."""
    df = pd.read_csv(cfg.processed_dir() / f"powerplants_located_{YEAR}.csv",
                     keep_default_na=False, na_values=[""])
    df["Capacity"] = pd.to_numeric(df["Capacity"], errors="coerce")
    df = df[df["Capacity"].notna() & (df["Capacity"] > 0)].copy()
    df["support_regime"] = df["support_regime"].fillna("None").replace("", "None")
    df = df[df["support_regime"] != "CfD"]
    df = df[~((df["Fueltype"] == "Wind") & (df["Technology"] == "Offshore"))]

    df["tech"] = np.where(df["Fueltype"] == "Natural Gas", df.apply(_gas_tech, axis=1), df["Fueltype"])
    df["eff"] = df.apply(_eff, axis=1)
    df["emissions_factor"] = df["Fueltype"].map(EMIT).fillna(0.0)
    df["support_value"] = np.where(df["support_regime"] == "RO",
                                   df["Fueltype"].map(ROC).fillna(ROC["default"]), 0.0)
    df["is_offshore"] = df["Technology"] == "Offshore"

    big, small = df[df["Capacity"] >= THRESH], df[df["Capacity"] < THRESH]
    individual = pd.DataFrame({
        "agent_id": big["Name"].str.replace(r"[^A-Za-z0-9]+", "_", regex=True), "name": big["Name"],
        "tech": big["tech"], "support_regime": big["support_regime"],
        "capacity_mw": big["Capacity"].round(1), "n_plants": 1, "efficiency": big["eff"].round(3),
        "emissions_factor": big["emissions_factor"], "support_value_gbp_mwh": big["support_value"].round(2),
        "is_offshore": big["is_offshore"], "vintage": np.nan, "neg_price_rule": np.nan,
        "gsp_id": big["gsp_id"], "gsp_group": big["gsp_group"], "source": "PPM",
    })

    def wavg(s, w):
        m = s.notna() & w.notna()
        return np.average(s[m], weights=w[m]) if m.any() and w[m].sum() > 0 else np.nan

    rows = []
    for (tech, regime, off, zone), g in small.groupby(
            ["tech", "support_regime", "is_offshore", "gsp_group"]):
        loc = "_offshore" if off else ("_onshore" if tech == "Wind" else "")
        rows.append({
            "agent_id": f"agg_{tech}_{regime}{loc}_{zone}".replace(" ", "_"),
            "name": f"Aggregate {tech}{' onshore' if tech == 'Wind' and not off else ''} "
                    f"({regime}, {zone}, <{THRESH:.0f}MW)",
            "tech": tech, "support_regime": regime, "capacity_mw": round(g["Capacity"].sum(), 1),
            "n_plants": len(g), "efficiency": round(wavg(g["eff"], g["Capacity"]), 3),
            "emissions_factor": g["emissions_factor"].iloc[0],
            "support_value_gbp_mwh": round(wavg(g["support_value"], g["Capacity"]), 2),
            "is_offshore": off, "vintage": np.nan, "neg_price_rule": np.nan,
            "gsp_id": pd.NA, "gsp_group": zone, "source": "PPM",
        })
    return pd.concat([individual, pd.DataFrame(rows, columns=AGENT_COLS)], ignore_index=True)[AGENT_COLS]


def main() -> None:
    cfd = cfd_agents()
    agents = pd.concat([cfd, offshore_noncfd_agents(), other_agents()], ignore_index=True)
    agents = agents.sort_values(["support_regime", "capacity_mw"], ascending=[True, False]).reset_index(drop=True)

    # build-step 1: enrich with per-tech flexibility / SRMC-base params
    agents = agents.merge(flexibility_table(), on="tech", how="left")
    unmapped = sorted(agents.loc[agents["availability"].isna(), "tech"].dropna().unique())
    if unmapped:
        print(f"  WARNING: no flexibility params for {unmapped} -> defaults (avail 0.85)")
        agents["availability"] = agents["availability"].fillna(0.85)
        agents["min_stable_pct"] = agents["min_stable_pct"].fillna(0.0)
        agents["ramp_pct_per_h"] = agents["ramp_pct_per_h"].fillna(50.0)
    nuke_av = nuclear_availability()  # empirical per-year override (declining AGR fleet)
    if nuke_av is not None:
        agents.loc[agents["tech"] == "Nuclear", "availability"] = round(nuke_av, 3)
    agents = agents[OUT_COLS]

    out = cfg.processed_dir() / f"agents_{YEAR}.csv"
    agents.to_csv(out, index=False)

    print(f"Year {YEAR}: {len(agents)} agents "
          f"(CfD {len(cfd)} from LCCC; offshore-noncfd from REPD; rest from PPM)")
    print(f"Total capacity: {agents['capacity_mw'].sum()/1000:.1f} GW\n")
    print(agents.groupby("support_regime").agg(
        n=("agent_id", "count"), gw=("capacity_mw", lambda s: round(s.sum()/1000, 2))).to_string())
    off = agents[(agents["tech"] == "Wind") & agents["is_offshore"]]
    print(f"\noffshore wind by regime (GW): "
          f"{off.groupby('support_regime')['capacity_mw'].sum().div(1000).round(2).to_dict()}")

    # --- locational summary ---
    miss = agents["gsp_group"].isna().sum()
    names = gsp.group_names()
    print(f"\n--- capacity by GSP group (GW)  [{agents['gsp_group'].nunique()} zones; "
          f"{miss} agents unlocated] ---")
    byz = (agents.groupby("gsp_group")["capacity_mw"].sum().div(1000).round(2)
           .sort_values(ascending=False))
    for z, gw in byz.items():
        print(f"  {z}  {names.get(z, '?'):36s} {gw:6.2f}")
    assert miss == 0, f"{miss} agents have no gsp_group"
    fleet = pd.read_csv(cfg.processed_dir() / f"cfd_fleet_{YEAR}.csv")
    print(f"CfD net settlement {YEAR}: GBP {fleet['cfd_payments_gbp'].sum()/1e6:,.0f} m  "
          f"| vintages: {cfd['vintage'].value_counts().to_dict()}")

    flexsum = (agents.groupby("tech").agg(
        gw=("capacity_mw", lambda s: round(s.sum() / 1000, 2)),
        avail=("availability", "first"), srmc_base=("srmc_base_gbp_mwh", "first"),
        min_stab=("min_stable_pct", "first"), ramp=("ramp_pct_per_h", "first"))
        .sort_values("gw", ascending=False))
    print("\n--- flexibility params by tech (build-step 1) ---")
    print(flexsum.to_string())
    print(f"\nSaved -> {out.name}")


if __name__ == "__main__":
    sys.exit(main())
