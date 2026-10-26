"""Annual electricity generation by fuel for the UK, Great Britain and each country, from DESNZ's official statistics,
and how much of Great Britain's the half-hourly generation mix captures -> data/processed/generation_by_fuel_annual.csv
and data/processed/generation_reconciliation_annual.csv.

Why: the half-hourly generation mix (gbpowerdata.build.generation_mix) holds what Elexon meters and NESO's embedded
wind and solar estimates. Generation outside both (gas CHP at industrial sites and hospitals, small hydro, engines,
landfill gas and anaerobic digestion, waste) is in no half-hourly source, so the mix's gas share is a share of the
metered output. DESNZ surveys every generator for its annual statistics: they give the official share of each fuel,
the gas share above all, and, set against the half-hourly table, how much of each fuel it misses.

SOURCES (gbpowerdata.pull.dukes_pull; Open Government Licence v3.0)
  data/raw/dukes/DUKES_5.6_{edition}.xlsx   DUKES 5.6, "Electricity fuel use, generation and supply", UK, 1996 to the
      year before the July edition: Table 5.6.B electricity generated and 5.6.E electricity supplied (gross:
      generated less used on works) by fuel, for the major power producers, the other generators (autogenerators and
      small, mostly embedded plant) and all generating companies. The UK series here.
  data/raw/dukes/regional_generation_{year}.xlsx   Energy Trends' article on generation in Scotland, Wales, Northern
      Ireland and England, Table 2a (sheet "Electricity generation by fuel"): generation by fuel and generator type per
      country, 2004 to the year before the December edition. Its all-companies total equals the major power producers'
      plus the other generators' in the panel's years; in some early years (Wales 2004: 33,100 against 35,422 GWh) it
      does not, and the published total is kept.

THE ANNUAL TABLE (generation_by_fuel_annual.csv, long): year, area (UK, England, Scotland, Wales, Northern Ireland,
  GB), generator_type (major_power_producers, other_generators, all), fuel, measure (generated, supplied_gross), gwh,
  share (of the total of the same year, area, type and measure), source.
  - UK from DUKES 5.6, both measures; the regional workbook's UK column is not used (it matches DUKES's generation to
    the revisions; the check prints the largest difference).
  - The four countries from the regional workbook (generated); GB = England + Scotland + Wales (source "derived").
  - The latest year DUKES has and the regional workbook not yet (2025 until December 2026): GB = the UK less Northern
    Ireland at its latest year (source "estimate"), for the fuels both tables name.
  - Fuels: coal, oil, gas, nuclear, hydro (natural flow), wind (with DUKES's wind_onshore and wind_offshore), solar,
    wave_tidal, bioenergy (DUKES's "thermal renewables"), other (other fuels: non-biodegradable waste, coke oven and
    blast furnace gas...), storage (DUKES: pumped storage and batteries) or pumped_storage and battery_storage
    (regional), total, and the aggregates renewables, low_carbon and fossil_fuels.

THE RECONCILIATION (generation_reconciliation_annual.csv): per year and fuel for GB, all generating companies:
  official_generated_gwh, supplied_ratio (the UK's supplied (gross) over generated for the fuel and year, DUKES),
  official_supplied_gwh (their product: GB's output net of works use, the basis FUELHH meters, an estimate),
  half_hourly_gwh (generation_mix_summary.csv's year: gas = gas_ccgt + gas_ocgt, wind = wind_metered + wind_embedded,
  solar = solar_embedded, bioenergy = biomass, pumped_storage = pumped_storage_generation, total = generation),
  missing_gwh (official_supplied - half_hourly) and half_hourly_share (half_hourly / official_supplied), with the
  half-hourly table's coverage. For gas, missing_gwh is the gas generation outside the half-hourly table, and
  half_hourly_share is the factor by which the metered gas share understates the full one.

WHAT IT SHOWS (DUKES 2026, regional Dec 2025; built 26 Oct 2026)
  Gas generated 35.9, 39.8, 38.3, 34.3 and 29.6% of GB's electricity in 2020-2024 (all generating companies), and an
  estimated 31.0% in 2025; the UK's shares are 0.2-1.0 points higher (Northern Ireland's gas). The half-hourly table
  holds 90-94% of GB's gas output (sent out) in 2016-2025: 6.5-12 TWh a year of gas, mostly CHP of the other
  generators, is outside it, so its half-hourly gas share is a lower bound. On 2023: wind 1.00, coal 0.98, nuclear
  1.03, solar 0.94, pumped storage 0.91, hydro 0.61 (small hydro), bioenergy 0.43 and other 0.45 (landfill gas,
  anaerobic digestion, waste and small CHP), oil 0.00 (engines and back-up plant); all fuels 0.88-0.90 a year. The
  four countries add up to DUKES's UK total within 0.2% in 2009-2022 and 0.4% after (DUKES's later revisions); in
  2004-2008 they fall 1.4-1.8% short.

Gotchas: DUKES revises its last few years each July and the regional workbook each December, so a year's figures
move between editions (the source column names the file). FUELHH's OTHER holds some units DESNZ counts as gas,
bioenergy or storage (and biomass before November 2017), so per-fuel shares are approximate where 'other' is large.

Output: data/processed/generation_by_fuel_annual.csv, data/processed/generation_reconciliation_annual.csv (the second
only where generation_mix_summary.csv exists). Read them with gbpowerdata.processed.read_generation_by_fuel().

Usage: python -m gbpowerdata.build.generation_by_fuel     (after dukes_pull 5.6 regional, and generation_mix)
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from gbpowerdata import config as cfg

TYPES = {"major power producers": "major_power_producers", "other generators": "other_generators",
         "all generating companies": "all"}
FUELS = {  # label, lower case without notes -> fuel
    "coal": "coal", "oil": "oil", "gas": "gas", "nuclear": "nuclear",
    "hydro (natural flow)": "hydro", "hydro natural flow": "hydro",
    "total wind": "wind", "wind": "wind", "onshore wind": "wind_onshore", "offshore wind": "wind_offshore",
    "shoreline wave / tidal": "wave_tidal", "shoreline wave and tidal": "wave_tidal", "solar": "solar",
    "thermal renewables": "bioenergy", "bioenergy": "bioenergy", "other fuels": "other",
    "energy storage": "storage", "hydro pumped storage": "pumped_storage", "pumped storage": "pumped_storage",
    "battery storage": "battery_storage",
    "total major power producers": "total", "total other generators": "total", "total all generating companies": "total",
    "total renewable generation": "renewables", "renewables": "renewables",
    "total low carbon generation": "low_carbon", "low carbon": "low_carbon",
    "total fossil fuel generation": "fossil_fuels", "fossil fuels": "fossil_fuels",
}
AGGREGATES = ("total", "renewables", "low_carbon", "fossil_fuels")
COUNTRIES = ("England", "Scotland", "Wales", "Northern Ireland")
GB = ("England", "Scotland", "Wales")
HALF_HOURLY = {  # fuel -> generation_mix_summary technologies
    "coal": ["coal"], "oil": ["oil"], "gas": ["gas_ccgt", "gas_ocgt"], "nuclear": ["nuclear"], "hydro": ["hydro"],
    "wind": ["wind_metered", "wind_embedded"], "solar": ["solar_embedded"], "bioenergy": ["biomass"],
    "other": ["other"], "pumped_storage": ["pumped_storage_generation"], "total": ["generation"],
}


def _label(s) -> str:
    return re.sub(r"\s*\[note[^\]]*\]", "", str(s), flags=re.I).strip().lower()


def _block(sheet: pd.DataFrame, title: str) -> tuple[pd.DataFrame, int]:
    """The rows of the table whose title cell starts with `title`, up to the next title or blank: (rows, header row)."""
    col0 = sheet.iloc[:, 0].astype(str)
    start = col0[col0.str.startswith(title)].index[0] + 1           # the header row
    end = start + 1
    while end < len(sheet) and col0.iloc[end] not in ("nan", "") and not col0.iloc[end].startswith("Table"):
        end += 1
    return sheet.iloc[start + 1:end], start


def _long(rows: pd.DataFrame, columns) -> pd.DataFrame:
    """Rows of (generator type, fuel, one value per column) -> long, with the fuel and type normalised."""
    out = []
    for _, r in rows.iterrows():
        typ, fuel = TYPES.get(_label(r.iloc[0])), FUELS.get(_label(r.iloc[1]))
        if typ is None or fuel is None:
            raise ValueError(f"unknown row: {r.iloc[0]!r} / {r.iloc[1]!r}")
        for j, key in columns:
            v = pd.to_numeric(r.iloc[j], errors="coerce")       # '[x]': not available
            out.append(dict(**key, generator_type=typ, fuel=fuel, gwh=v))
    return pd.DataFrame(out).dropna(subset=["gwh"])


def read_dukes(path: Path) -> pd.DataFrame:
    """DUKES 5.6.B (generated) and 5.6.E (supplied, gross), UK, long."""
    sheet = pd.read_excel(path, sheet_name="5.6", header=None)
    frames = []
    for title, measure in (("Table 5.6.B", "generated"), ("Table 5.6.E", "supplied_gross")):
        rows, h = _block(sheet, title)
        cols = [(j, dict(year=int(float(y)), measure=measure)) for j, y in enumerate(sheet.iloc[h])
                if j >= 2 and pd.notna(y)]
        frames.append(_long(rows, cols))
    d = pd.concat(frames, ignore_index=True).assign(area="UK", source=f"dukes:{path.name}")
    return d


def read_regional(path: Path) -> pd.DataFrame:
    """Table 2a: generation by fuel, generator type and country (the UK column left out), long."""
    sheet = pd.read_excel(path, sheet_name="Electricity generation by fuel", header=None)
    rows, h = _block(sheet, "Table 2a")
    cols = []
    for j, head in enumerate(sheet.iloc[h]):
        m = re.match(r"(\d{4}) (.+)$", str(head).strip())
        if m and m.group(2) in COUNTRIES:
            cols.append((j, dict(year=int(m.group(1)), area=m.group(2))))
    return _long(rows, cols).assign(measure="generated", source=f"regional:{path.name}")


def great_britain(regional: pd.DataFrame, uk: pd.DataFrame) -> pd.DataFrame:
    """GB = England + Scotland + Wales; for a year only DUKES has, the UK less Northern Ireland's latest year."""
    key = ["year", "generator_type", "fuel", "measure"]
    gb = regional[regional["area"].isin(GB)].groupby(key, as_index=False)["gwh"].sum().assign(
        area="GB", source="derived: England + Scotland + Wales")
    last = regional["year"].max()
    later = uk[(uk["year"] > last) & (uk["measure"] == "generated")]
    ni = regional[(regional["area"] == "Northern Ireland") & (regional["year"] == last)].set_index(
        ["generator_type", "fuel"])["gwh"]
    est = later.join(ni.rename("ni"), on=["generator_type", "fuel"], how="inner")
    est = est.assign(gwh=est["gwh"] - est["ni"], area="GB",
                     source=f"estimate: UK (DUKES) less Northern Ireland at {last}").drop(columns="ni")
    return pd.concat([gb, est], ignore_index=True)


def with_shares(d: pd.DataFrame) -> pd.DataFrame:
    key = ["year", "area", "generator_type", "measure"]
    total = d[d["fuel"] == "total"].set_index(key)["gwh"].rename("total")
    d = d.join(total, on=key)
    d["share"] = (d["gwh"] / d["total"]).round(5)
    d["gwh"] = d["gwh"].round(3)
    cols = ["year", "area", "generator_type", "fuel", "measure", "gwh", "share", "source"]
    return d[cols].sort_values(["area", "measure", "generator_type", "fuel", "year"]).reset_index(drop=True)


def countries_vs_uk(annual: pd.DataFrame, first_year: int = 2009) -> float:
    """The largest relative difference between the four countries' total generation and DUKES's UK total, from
    `first_year` (2004-2008 differ by 1.4-1.8%)."""
    annual = annual[annual["year"] >= first_year]
    t = annual[(annual["generator_type"] == "all") & (annual["fuel"] == "total") & (annual["measure"] == "generated")]
    countries = t[t["area"].isin(COUNTRIES)].groupby("year")["gwh"].sum()
    uk = t[t["area"] == "UK"].set_index("year")["gwh"]
    return float((countries / uk - 1).dropna().abs().max())


def reconcile(annual: pd.DataFrame, summary: pd.DataFrame) -> pd.DataFrame:
    """GB's official output by fuel (all generating companies) against the half-hourly table's year."""
    a = annual[(annual["generator_type"] == "all")]
    gb = a[(a["area"] == "GB") & (a["measure"] == "generated")].set_index(["year", "fuel"])["gwh"]
    uk = a[a["area"] == "UK"].pivot_table(index=["year", "fuel"], columns="measure", values="gwh")
    ratio = (uk["supplied_gross"] / uk["generated"]).rename("supplied_ratio")
    if "storage" in ratio.index.get_level_values("fuel"):   # pumped storage takes DUKES's 'storage' ratio
        ratio = ratio.combine_first(ratio.xs("storage", level="fuel").to_frame().assign(fuel="pumped_storage")
                                    .set_index("fuel", append=True)["supplied_ratio"])
    s = summary[summary["resolution"] == "year"].assign(year=lambda x: x["period"].astype(int))
    hh = s.pivot_table(index="year", columns="technology", values="energy_gwh")
    cov = s.groupby("year")["coverage"].min()
    rows = []
    for (year, fuel), off in gb.items():
        if fuel not in HALF_HOURLY:
            continue
        r = ratio.get((year, fuel), np.nan)
        sup = off * r
        h = hh.loc[year, HALF_HOURLY[fuel]].sum(min_count=1) if year in hh.index else np.nan
        rows.append(dict(year=year, fuel=fuel, official_generated_gwh=round(off, 3), supplied_ratio=round(r, 5),
                         official_supplied_gwh=round(sup, 3), half_hourly_gwh=round(h, 3),
                         missing_gwh=round(sup - h, 3), half_hourly_share=round(h / sup, 5) if sup else np.nan,
                         half_hourly_coverage=cov.get(year, np.nan)))
    return pd.DataFrame(rows).sort_values(["fuel", "year"]).reset_index(drop=True)


def _newest(folder: Path, pattern: str) -> Path:
    files = sorted(folder.glob(pattern))
    if not files:
        sys.exit(f"no {pattern} in {folder}: run python -m gbpowerdata.pull.dukes_pull 5.6 regional")
    return files[-1]


def build() -> tuple[pd.DataFrame, pd.DataFrame | None]:
    raw, proc = cfg.raw_dir() / "dukes", cfg.processed_dir()
    uk = read_dukes(_newest(raw, "DUKES_5.6_*.xlsx"))
    regional = read_regional(_newest(raw, "regional_generation_*.xlsx"))
    annual = with_shares(pd.concat([uk, regional, great_britain(regional, uk)], ignore_index=True))
    annual.to_csv(proc / "generation_by_fuel_annual.csv", index=False)
    print(f"  the countries' total against DUKES's UK from 2009, largest difference: {countries_vs_uk(annual):.2%}")
    gas = annual[(annual["generator_type"] == "all") & (annual["fuel"] == "gas") & (annual["measure"] == "generated")
                 & annual["area"].isin(["UK", "GB"])].pivot(index="year", columns="area", values="share")
    print(f"  generation_by_fuel_annual.csv: {len(annual)} rows; gas share of generation, last years:\n"
          f"{gas.tail(6).round(3).to_string()}")
    path = proc / "generation_mix_summary.csv"
    if not path.exists():
        print("  no generation_mix_summary.csv: the reconciliation needs python -m gbpowerdata.build.generation_mix")
        return annual, None
    rec = reconcile(annual, pd.read_csv(path, dtype={"period": str}))
    rec.to_csv(proc / "generation_reconciliation_annual.csv", index=False)
    g = rec[rec["fuel"] == "gas"].set_index("year")[["official_supplied_gwh", "half_hourly_gwh", "half_hourly_share"]]
    print(f"  generation_reconciliation_annual.csv: {len(rec)} rows; gas:\n{g.dropna().round(3).to_string()}")
    return annual, rec


def main(argv: list[str]) -> None:
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args(argv)
    build()


if __name__ == "__main__":
    main(sys.argv[1:])
