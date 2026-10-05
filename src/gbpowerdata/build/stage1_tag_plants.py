"""Stage 1 — tag every GB power plant with a support regime.

Reads the powerplantmatching roster + the LCCC CfD register and assigns each
plant operational in `config.year` one regime via a first-match-wins waterfall
(per the modelling doc, "capacity coverage"):

    nuclear          : Fueltype == Nuclear (separate must-run class)
    storage          : batteries, pumped storage (opportunity-cost bidders)
    merchant_thermal : any non-renewable (CCGT, coal, oil, gas turbines, ...)
    CfD              : renewable, substring-matched to a CfD contract active in `year`
    FiT              : renewable, not CfD, Capacity < fit_threshold_mw
    RO               : renewable, not CfD, DateIn <= ro_closure_year
    None             : renewable, not CfD, >= threshold, DateIn > ro_closure_year
                       (post-RO-closure merchant renewables)

Outputs (data/processed/, year-suffixed so years never overwrite each other):
    powerplants_tagged_{year}.csv  — every plant with its support_regime + CfD strike
    regime_summary_{year}.csv      — capacity by regime vs the {year} benchmark
    cfd_ppm_matches_{year}.csv      — audit of every CfD <-> plant name match

The regime benchmark is reported here but NOT enforced; the hard fail-on-breach
gate is Stage 4. Parameters come from config.yaml; data-quality overrides from
data/reference/plant_overrides.yaml.
"""

from __future__ import annotations

import sys

import pandas as pd

from gbpowerdata import config as cfg
from gbpowerdata.common.naming import keyword as _keyword, normalise as _normalise

CFG = cfg.load_config()
YEAR = int(CFG["year"])
S1 = CFG["stage1"]
FIT_THRESHOLD_MW = float(S1["fit_threshold_mw"])
RO_CLOSURE_YEAR = int(S1["ro_closure_year"])

RENEWABLE_FUELS = {"Wind", "Solar", "Solid Biomass", "Biogas", "Waste"}
STORAGE_TECHS = {"Pumped Storage"}

# CfD allocation rounds whose strike top-up makes a plant a "CfD" bidder.
# AR5+ contracts sign years before they generate; restrict to rounds whose
# plants could plausibly be operational in the modelled year.
CFD_ACTIVE_ROUNDS = {
    "Allocation Round 1", "Allocation Round 2",
    "Allocation Round 3", "Allocation Round 4",
    "Investment Contract", "Bespoke",
}

# Data-quality overrides (editable, not hardcoded) — see plant_overrides.yaml.
OV = cfg.load_reference_yaml("plant_overrides.yaml")
PUMPED_STORAGE_NAMES = set(OV["pumped_storage_names"])
DATEOUT_PATCHES = OV["dateout_patches"]
NI_LAT_RANGE = tuple(OV["ni_bbox"]["lat"])
NI_LON_RANGE = tuple(OV["ni_bbox"]["lon"])


# --------------------------------------------------------------------------- #
# Loaders
# --------------------------------------------------------------------------- #
def load_ppm_operational() -> pd.DataFrame:
    """GB plants operational in `YEAR`, with NI dropped and DateOut patched."""
    df = pd.read_csv(cfg.raw_dir() / S1["powerplants"])
    uk = df[df["Country"] == "United Kingdom"].copy()
    uk["DateIn"] = pd.to_numeric(uk["DateIn"], errors="coerce")
    uk["DateOut"] = pd.to_numeric(uk["DateOut"], errors="coerce")

    for name, dateout in DATEOUT_PATCHES.items():
        uk.loc[uk["Name"] == name, "DateOut"] = dateout

    # Drop Northern Ireland (separate SEM grid).
    ni_mask = uk["lat"].between(*NI_LAT_RANGE) & uk["lon"].between(*NI_LON_RANGE)
    gb = uk[~ni_mask].copy()

    op = gb[(gb["DateIn"] <= YEAR) & (gb["DateOut"].isna() | (gb["DateOut"] >= YEAR))].copy()
    op["name_norm"] = op["Name"].apply(_normalise)
    op["keyword"] = op["Name"].apply(_keyword)
    return op.reset_index(drop=True)


def load_active_cfd() -> pd.DataFrame:
    """CfD contracts whose strike top-up was actually in effect during `YEAR`.

    Strict definition: require a present `start_date` on/before the year end.
    Plants generating in `YEAR` but with a CfD start in a later year bid as
    merchant for `YEAR` because the strike top-up was not yet being paid.
    """
    cfd = pd.read_excel(cfg.raw_dir() / S1["cfd_register"])
    for col in ("start_date", "termination_date"):
        cfd[col] = pd.to_datetime(cfd[col], errors="coerce", utc=True)

    year_end = pd.Timestamp(f"{YEAR + 1}-01-01", tz="UTC")
    year_start = pd.Timestamp(f"{YEAR}-01-01", tz="UTC")
    not_terminated = cfd["termination_date"].isna() | (cfd["termination_date"] > year_start)
    started_by_year = cfd["start_date"].notna() & (cfd["start_date"] < year_end)
    rounds_ok = cfd["allocation_round"].isin(CFD_ACTIVE_ROUNDS)

    active = cfd[not_terminated & started_by_year & rounds_ok].copy()
    active["project_keyword"] = active["project_name"].apply(_keyword)
    return active


def match_cfd_to_ppm(ppm: pd.DataFrame, cfd: pd.DataFrame) -> pd.DataFrame:
    """Substring-match each CfD project keyword against PPM plant names."""
    matches = []
    for _, c in cfd.iterrows():
        kw = c["project_keyword"]
        if len(kw) < 5:
            continue
        hits = ppm[ppm["name_norm"].str.contains(kw, na=False, regex=False)]
        for _, p in hits.iterrows():
            matches.append({
                "ppm_id": p["id"],
                "ppm_name": p["Name"],
                "ppm_capacity_mw": p["Capacity"],
                "ppm_fueltype": p["Fueltype"],
                "ppm_date_in": p["DateIn"],
                "cfd_contract_id": c["contract_id"],
                "cfd_project_name": c["project_name"],
                "cfd_allocation_round": c["allocation_round"],
                "cfd_strike_price": c["current_strike_price"],
                "cfd_capacity_mw": c["current_installed_capacity"],
                "match_keyword": kw,
            })
    return pd.DataFrame(matches)


# --------------------------------------------------------------------------- #
# Classification
# --------------------------------------------------------------------------- #
def is_storage(row: pd.Series) -> bool:
    if row["Fueltype"] == "Battery":
        return True
    if row["Fueltype"] == "Hydro" and row.get("Technology") in STORAGE_TECHS:
        return True
    if isinstance(row.get("Name"), str) and row["Name"] in PUMPED_STORAGE_NAMES:
        return True
    return False


def is_renewable(row: pd.Series) -> bool:
    if row["Fueltype"] in RENEWABLE_FUELS:
        return True
    # All hydro is renewable except pumped storage (handled as storage above).
    if row["Fueltype"] == "Hydro" and not is_storage(row):
        return True
    return False


def classify_support(row: pd.Series) -> str:
    if row["Fueltype"] == "Nuclear":
        return "nuclear"
    if is_storage(row):
        return "storage"
    if not is_renewable(row):
        return "merchant_thermal"
    if pd.notna(row.get("cfd_contract_id")):
        return "CfD"
    if row["Capacity"] < FIT_THRESHOLD_MW:
        return "FiT"
    if pd.notna(row["DateIn"]) and row["DateIn"] <= RO_CLOSURE_YEAR:
        return "RO"
    return "None"


def tag_all(ppm: pd.DataFrame, cfd_matches: pd.DataFrame) -> pd.DataFrame:
    if cfd_matches.empty:
        keep = pd.DataFrame(columns=["id", "cfd_contract_id", "cfd_project_name",
                                     "cfd_allocation_round", "cfd_strike_price",
                                     "cfd_capacity_mw"])
    else:
        keep = (
            cfd_matches.sort_values("cfd_capacity_mw", ascending=False)
            .drop_duplicates(subset=["ppm_id"], keep="first")
            .rename(columns={"ppm_id": "id"})
            [["id", "cfd_contract_id", "cfd_project_name", "cfd_allocation_round",
              "cfd_strike_price", "cfd_capacity_mw"]]
        )
    tagged = ppm.merge(keep, on="id", how="left")
    tagged["support_regime"] = tagged.apply(classify_support, axis=1)
    return tagged


def apply_cfd_overrides(tagged: pd.DataFrame) -> pd.DataFrame:
    """Pin specific MW of named PPM plants to CfD contracts (capacity-aware).

    Handles the keyword matcher's material misses and PPM rows that bundle
    multiple regimes / unbuilt phases into one entry. Each override moves
    `cfd_capacity_mw` to CfD and sends the remainder to `remainder_regime`
    (or drops it if not operational in the year). See cfd_overrides.yaml.
    """
    path = cfg.reference_dir() / "cfd_overrides.yaml"
    if not path.exists():
        return tagged
    overrides = cfg.load_reference_yaml("cfd_overrides.yaml") or []
    tagged = tagged.copy()
    drop_idx, extra_rows = [], []
    for ov in overrides:
        mask = tagged["Name"] == ov["ppm_name"]
        if "ppm_fueltype" in ov:
            mask &= tagged["Fueltype"] == ov["ppm_fueltype"]
        idxs = tagged.index[mask].tolist()
        if not idxs:
            print(f"  [cfd override] no PPM match for {ov['ppm_name']!r} -> skipped")
            continue
        for i in idxs:
            row = tagged.loc[i]
            total = float(pd.to_numeric(row["Capacity"], errors="coerce"))
            cfd_cap = min(float(ov["cfd_capacity_mw"]), total)

            cfd_row = row.copy()
            cfd_row["Capacity"] = round(cfd_cap, 3)
            cfd_row["support_regime"] = "CfD"
            cfd_row["cfd_contract_id"] = "MANUAL_OVERRIDE"
            cfd_row["cfd_project_name"] = ov.get("cfd_project")
            cfd_row["cfd_allocation_round"] = ov.get("cfd_allocation_round")
            cfd_row["cfd_strike_price"] = ov.get("strike_gbp_mwh")
            cfd_row["cfd_capacity_mw"] = round(cfd_cap, 3)
            extra_rows.append(cfd_row)

            remainder = total - cfd_cap
            rem_regime = ov.get("remainder_regime", "drop")
            if remainder > 1.0 and rem_regime != "drop":
                rem_row = row.copy()
                rem_row["Capacity"] = round(remainder, 3)
                rem_row["support_regime"] = rem_regime
                for c in ("cfd_contract_id", "cfd_project_name", "cfd_allocation_round",
                          "cfd_strike_price", "cfd_capacity_mw"):
                    rem_row[c] = pd.NA
                extra_rows.append(rem_row)
            drop_idx.append(i)
            tail = f", {remainder:.0f} MW -> {rem_regime}" if remainder > 1.0 else ""
            print(f"  [cfd override] {ov['ppm_name']}: {cfd_cap:.0f} MW -> CfD{tail}")
    tagged = tagged.drop(index=drop_idx)
    if extra_rows:
        tagged = pd.concat([tagged, pd.DataFrame(extra_rows)], ignore_index=True)
    return tagged.reset_index(drop=True)


# --------------------------------------------------------------------------- #
# Benchmark (reported, not enforced — Stage 4 is the gate)
# --------------------------------------------------------------------------- #
def benchmark_check(tagged: pd.DataFrame) -> pd.DataFrame:
    by_regime = tagged.groupby("support_regime")["Capacity"].agg(["count", "sum"]).round(0)
    by_regime.columns = ["n_plants", "capacity_mw"]
    by_regime = by_regime.sort_values("capacity_mw", ascending=False)

    bench_path = cfg.reference_dir() / f"benchmarks_{YEAR}.csv"
    if bench_path.exists():
        # keep_default_na=False so the literal regime name "None" stays a string
        # (pandas would otherwise parse it as NaN and drop the comparison).
        bench = (pd.read_csv(bench_path, keep_default_na=False)
                 .set_index("support_regime")["benchmark_mw"].astype(int))
        by_regime["benchmark_mw"] = by_regime.index.map(bench).astype("Int64")
        by_regime["delta_mw"] = (by_regime["capacity_mw"] - by_regime["benchmark_mw"]).astype("Int64")
        by_regime["delta_pct"] = (
            100 * (by_regime["capacity_mw"] - by_regime["benchmark_mw"]) / by_regime["benchmark_mw"]
        ).round(1)
    else:
        print(f"  (no benchmark file {bench_path.name}; skipping comparison)")
    return by_regime


def main() -> None:
    print(f"Year            : {YEAR}")
    print(f"PPM roster      : {S1['powerplants']}")
    print(f"CfD register    : {S1['cfd_register']}\n")

    ppm = load_ppm_operational()
    cfd = load_active_cfd()
    print(f"GB plants operational in {YEAR}  : {len(ppm):,}")
    print(f"CfD contracts active in {YEAR}    : {len(cfd):,}")

    cfd_matches = match_cfd_to_ppm(ppm, cfd)
    print(f"\nCfD x PPM candidate matches     : {len(cfd_matches):,}")
    if not cfd_matches.empty:
        print(f"Distinct PPM plants matched      : {cfd_matches['ppm_id'].nunique():,}")
        print(f"Distinct CfD projects matched    : {cfd_matches['cfd_contract_id'].nunique():,} / {len(cfd):,}")

    tagged = tag_all(ppm, cfd_matches)
    print("\nApplying CfD overrides (capacity-aware):")
    tagged = apply_cfd_overrides(tagged)
    summary = benchmark_check(tagged)

    print("\n--- Capacity by support regime (PPM tagged) vs benchmark ---")
    print(summary.to_string())

    renew = ["CfD", "RO", "None", "FiT"]
    modelled = summary.loc[summary.index.isin(renew), "capacity_mw"].sum()
    bench_path = cfg.reference_dir() / f"benchmarks_{YEAR}.csv"
    if bench_path.exists():
        bench_total = pd.read_csv(bench_path)["benchmark_mw"].sum()
        print(f"\nTotal renewable (modelled)  : {modelled:,.0f} MW")
        print(f"Total renewable (benchmark) : {bench_total:,.0f} MW")
        print(f"Delta                       : {modelled - bench_total:+,.0f} MW")

    out = cfg.processed_dir()
    tagged_path = out / f"powerplants_tagged_{YEAR}.csv"
    summary_path = out / f"regime_summary_{YEAR}.csv"
    matches_path = out / f"cfd_ppm_matches_{YEAR}.csv"
    tagged.to_csv(tagged_path, index=False)
    summary.to_csv(summary_path)
    cfd_matches.to_csv(matches_path, index=False)
    print(f"\nSaved {len(tagged):,} tagged plants -> {tagged_path.name}")
    print(f"Saved regime summary            -> {summary_path.name}")
    print(f"Saved {len(cfd_matches):,} CfD-PPM matches    -> {matches_path.name}")


if __name__ == "__main__":
    sys.exit(main())
