"""GB generation by fuel and technology, and the flows on every interconnector, per half-hour, with yearly and monthly
energy and shares -> data/processed/generation_mix_{year}.csv and data/processed/generation_mix_summary.csv.

Why: the panel held demand, prices and capacity factors but not what generated the electricity: the fuel mix behind
each half-hour's price, each technology's share of a year, and how much the interconnectors brought in or took out.

SOURCES
  data/raw/fuelhh_*.csv   Elexon FUELHH (gbpowerdata.pull.elexon_pull, BMRS data licence): the half-hourly average
      output of BM-metered generation by fuel type, each interconnector's flow and pumped storage, MW. It covers the
      transmission system and the distribution-connected stations with BM units; read with
      gbpowerdata.checks.balance.fuelhh(), as the balance check reads it.
  data/raw/neso/historic_demand_{year}.csv   NESO's historic demand data (gbpowerdata.pull.neso_pull demand, NESO
      Open Data Licence): its estimates of embedded wind and solar generation, the output FUELHH does not meter.
      Settlement date and period are local time (46 or 50 periods on clock-change days); the date is ISO in some
      years and 01-Jan-23 in others; the current year mixes forecast rows (FORECAST_ACTUAL_INDICATOR "F"), which
      are left out.
  data/raw/b1610/{unit}.csv   Elexon B1610, each wind unit's metered output (gbpowerdata.pull.b1610_pull --fuel WIND:
      every T_ and E_ wind unit of the newest register snapshot), MWh per settlement period, from 1 February 2019
      (Elexon's archive starts then); for the split of metered wind into offshore and onshore.
  data/reference/wind_farm_map.csv   is_offshore of the wind units with a notification record; a unit it lacks, or
      leaves blank (no REPD site matched: North Kyle, Kennoxhead, Moy, Hywind ...), is offshore when its register
      name says so ("Offshore", "Hywind", "OWF": Burbo, Hywind, Kincardine, Dogger Bank B), else onshore. Before
      30 Oct 2026 a blank was read as offshore, which put about 0.5 GW of onshore farms in the offshore split.

THE HALF-HOURLY TABLE (MW, mean over the half-hour, UTC startTime on the year's spine)
  gas_ccgt_mw, gas_ocgt_mw, coal_mw, oil_mw, nuclear_mw, biomass_mw, hydro_mw (non-pumped hydro), other_mw,
  wind_metered_mw   FUELHH: CCGT, OCGT, COAL, OIL, NUCLEAR, BIOMASS, NPSHYD, OTHER, WIND. wind_metered is the
      BM-metered wind (transmission-connected farms and the embedded ones with BM units), offshore and onshore
      together: FUELHH does not split them.
  wind_offshore_metered_mw, wind_onshore_metered_mw   wind_metered split by the offshore share of the wind units'
      B1610 output in the half-hour (where the units sum to at least MIN_SPLIT_MW), so the two add up to
      wind_metered; empty before February 2019 and where B1610 is not yet published (wind_split_source "missing").
      They are parts of wind_metered and are not added again to generation.
  pumped_storage_generation_mw, pumped_storage_pumping_mw   FUELHH reports pumped storage net, negative while
      pumping: its positive part is generation and its negative part, as a positive number, pumping (as
      gbpowerdata.checks.balance does).
  wind_embedded_mw, solar_embedded_mw   NESO's estimates of the wind and solar generation without BM metering.
  interconnector_<link>_mw   each link's flow, imports positive, exports negative (FUELHH INT*): ifa (INTFR), ifa2,
      eleclink (INTELEC, with the 9 zero rows of INTELE in 2021), britned (INTNED), nemo (INTNEM), nsl (North Sea
      Link), viking (INTVKL), moyle (INTIRL), east_west (INTEW), greenlink (INTGRNL); 0 before a link's first flow.
  generation_mw   the sum of the generating columns above (embedded wind and solar and pumped storage generation
      included, pumping not subtracted); imports_mw, exports_mw (both positive) and net_imports_mw.
  metered_source ("FUELHH" or "missing"), embedded_source ("NESO" or "missing") and wind_split_source ("B1610" or
      "missing"): a half-hour a source did not publish stays empty in its columns, and nothing is interpolated.

THE SUMMARY (generation_mix_summary.csv, long): one row per resolution ("year" or "month"), period (YYYY or YYYY-MM)
  and technology (every column above without _mw, plus generation, imports, exports, net_imports): energy_gwh over
  the half-hours with both sources (MW x 0.5 h), half_hours and coverage (the half-hours with a value in the column,
  and their share of the period's: biomass from November 2017, the wind split from February 2019),
  share_of_generation (a generating technology's energy over generation's) and share_of_supply (a generating
  technology's or net imports' energy over generation plus net imports). Energy is not scaled up for missing
  half-hours: coverage says how much is missing.

GOTCHAS
  - Elexon reported biomass under OTHER until 1 Nov 2017 (FUELHH's BIOMASS starts then), so before that biomass_mw
    is empty and other_mw holds it.
  - Generation here is what the transmission system metered plus NESO's two estimates: embedded output from other
    fuels (small hydro, CHP, landfill and anaerobic digestion, diesel) is in no half-hourly source, so the shares
    are of this generation, not of DUKES's. FUELHH's figures are output at the meter (sent out), net of the
    stations' own use.
  - The interconnector flows are metered at the GB end; FUELHH and NESO's flows agree (correlation 0.9995 on 2023,
    the same yearly mean within 1 MW), so the table uses FUELHH's.
  - Against DUKES (official_statistics.csv; UK, so with Northern Ireland, where the table is GB), 2018-2025: wind
    (metered plus embedded) is 0.95-0.99 of DUKES's, solar 0.90-0.97; pumped storage generation and pumping (GB in
    both) 0.91-0.96, FUELHH netting the two within each half-hour (tests/realdata/test_generation_mix.py). Total
    generation, 237-279 TWh a year in 2018-2025, is below DUKES's because of the unmetered embedded output above.
  - The wind split, 2020-2025: offshore 1.00-1.02 of DUKES's offshore wind (Northern Ireland has none), onshore
    (metered plus embedded) 0.88-0.95 of DUKES's UK onshore, Northern Ireland's in it; 2019 starts in February. The
    wind units' B1610 output is 0.93-0.96 of FUELHH's wind (units the register lists without an Elexon id, and
    farms renamed or closed), which is why the split takes their offshore share rather than their sum.
  - Offshore and onshore come from B1610 and not from Elexon's AGWS (B1630, "Wind Offshore", "Wind Onshore"), which
    is not a split of FUELHH's wind: over 1-7 January and 1-7 July 2023 its wind summed to 0.78 of FUELHH's.

Output: data/processed/generation_mix_{year}.csv (half-hourly), data/processed/generation_mix_summary.csv (every year
built so far, rebuilt from the half-hourly files). Read them with gbpowerdata.processed.read_generation_mix(year) and
read_generation_mix(summary=True).

Usage: python -m gbpowerdata.build.generation_mix [--years 2018 2025]
       (after elexon_pull fuelhh, neso_pull demand and b1610_pull --fuel WIND)
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from gbpowerdata import config as cfg
from gbpowerdata.checks import balance

FUELS = {  # FUELHH fuel type -> column
    "CCGT": "gas_ccgt_mw", "OCGT": "gas_ocgt_mw", "COAL": "coal_mw", "OIL": "oil_mw", "NUCLEAR": "nuclear_mw",
    "BIOMASS": "biomass_mw", "NPSHYD": "hydro_mw", "WIND": "wind_metered_mw", "OTHER": "other_mw",
}
LINKS = {  # FUELHH interconnector fuel type -> link name
    "INTFR": "ifa", "INTIFA2": "ifa2", "INTELEC": "eleclink", "INTELE": "eleclink", "INTNED": "britned",
    "INTNEM": "nemo", "INTNSL": "nsl", "INTVKL": "viking", "INTIRL": "moyle", "INTEW": "east_west",
    "INTGRNL": "greenlink",
}
EMBEDDED = {"EMBEDDED_WIND_GENERATION": "wind_embedded_mw", "EMBEDDED_SOLAR_GENERATION": "solar_embedded_mw"}
BIOMASS_FROM = pd.Timestamp("2017-11-01", tz="UTC")   # FUELHH's BIOMASS starts here; before, biomass is in OTHER
GENERATING = list(FUELS.values()) + ["pumped_storage_generation_mw", "wind_embedded_mw", "solar_embedded_mw"]
WIND_SPLIT = ["wind_offshore_metered_mw", "wind_onshore_metered_mw"]   # parts of wind_metered_mw, not added to it
OFFSHORE_NAME = re.compile(r"offshore|hywind|\bOWF\b", re.I)     # a wind unit the farm map does not flag
MIN_SPLIT_MW = 50.0           # metered wind units' total below which a half-hour's offshore share is not taken
LOCAL = "Europe/London"


def spine(year: int) -> pd.DatetimeIndex:
    return pd.date_range(f"{year}-01-01", f"{year + 1}-01-01", freq="30min", tz="UTC", inclusive="left", name="startTime")


def settlement_start(date: pd.Series, period: pd.Series) -> pd.Series:
    """UTC start of a settlement period: local midnight of its date plus 30 minutes per period before it."""
    day = pd.to_datetime(date, format="mixed", dayfirst=True).dt.tz_localize(LOCAL).dt.tz_convert("UTC")
    return day + pd.to_timedelta((period.astype(int) - 1) * 30, unit="min")


def neso_embedded(raw: Path, year: int) -> pd.DataFrame:
    """NESO's embedded wind and solar estimates of `year` (MW) on their UTC startTime; actuals only."""
    path = Path(raw) / "neso" / f"historic_demand_{year}.csv"
    if not path.exists():
        return pd.DataFrame(columns=list(EMBEDDED.values()), index=pd.DatetimeIndex([], tz="UTC", name="startTime"))
    d = pd.read_csv(path)
    if "FORECAST_ACTUAL_INDICATOR" in d:
        d = d[d["FORECAST_ACTUAL_INDICATOR"].astype(str).str.upper() != "F"]
    d["startTime"] = settlement_start(d["SETTLEMENT_DATE"], d["SETTLEMENT_PERIOD"])
    return d.drop_duplicates("startTime", keep="last").set_index("startTime")[list(EMBEDDED)].rename(columns=EMBEDDED)


def wind_offshore_flags(register: pd.DataFrame, farm_map: pd.DataFrame) -> pd.Series:
    """Every T_ and E_ wind unit of a register snapshot -> offshore (bool): the farm map's is_offshore where it has the
    unit and states it, else whether the unit's name says offshore (OFFSHORE_NAME)."""
    w = register[register["fuelType"].eq("WIND") & register["elexonBmUnit"].astype(str).str.match(r"[TE]_")]
    names = w.drop_duplicates("elexonBmUnit").set_index("elexonBmUnit")["bmUnitName"].astype(str)  # some listed twice
    # is_offshore is blank where no REPD site matched (North Kyle, Kennoxhead, Moy ...); a blank read as bool is True
    mapped = (farm_map.drop_duplicates("elexon_bmu_id").set_index("elexon_bmu_id")["is_offshore"].dropna()
              .map(lambda v: str(v).strip().lower() == "true"))
    flags = names.str.contains(OFFSHORE_NAME).rename("offshore")
    known = names.index.intersection(mapped.index)
    flags[known] = mapped[known]
    return flags


def wind_units_metered(folder: Path, flags: pd.Series) -> pd.DataFrame:
    """The units' B1610 metered output (MW, from MWh per half-hour) summed into offshore_mw and all_mw by UTC startTime;
    units without a file are left out."""
    parts = []
    for unit, offshore in flags.items():
        path = Path(folder) / f"{unit.replace('/', '_')}.csv"
        if not path.exists():
            continue
        d = pd.read_csv(path, usecols=["settlementDate", "settlementPeriod", "quantity"])
        d["startTime"] = settlement_start(d["settlementDate"], d["settlementPeriod"])
        parts.append(pd.DataFrame({"mw": d["quantity"].to_numpy() * 2.0, "offshore": offshore}, index=d["startTime"]))
    if not parts:
        return pd.DataFrame(columns=["offshore_mw", "all_mw"], index=pd.DatetimeIndex([], tz="UTC", name="startTime"))
    d = pd.concat(parts)
    return pd.DataFrame({"offshore_mw": d.loc[d["offshore"], "mw"].groupby(level=0).sum(),
                         "all_mw": d["mw"].groupby(level=0).sum()}).fillna({"offshore_mw": 0.0})


def metered(w: pd.DataFrame) -> pd.DataFrame:
    """FUELHH wide (fuel types as columns) -> the metered columns, a half-hour without any FUELHH row left empty."""
    present = w.notna().any(axis=1)
    out = pd.DataFrame(index=w.index)
    for fuel, col in FUELS.items():
        out[col] = w[fuel] if fuel in w else np.nan
    ps = w["PS"] if "PS" in w else pd.Series(np.nan, index=w.index)
    out["pumped_storage_generation_mw"] = ps.clip(lower=0)
    out["pumped_storage_pumping_mw"] = -ps.clip(upper=0)
    for link in dict.fromkeys(LINKS.values()):
        cols = [f for f, name in LINKS.items() if name == link and f in w]
        out[f"interconnector_{link}_mw"] = w[cols].sum(axis=1, min_count=1) if cols else np.nan
    # a fuel or link with no row in a published half-hour is 0 (a link before its first flow), not missing,
    # except biomass before FUELHH reported it separately
    out.loc[present] = out.loc[present].fillna(0.0)
    out.loc[out.index < BIOMASS_FROM, "biomass_mw"] = np.nan
    out["metered_source"] = np.where(present, "FUELHH", "missing")
    return out


def split_wind(metered_wind: pd.Series, units: pd.DataFrame) -> pd.DataFrame:
    """Metered wind into offshore and onshore by the offshore share of the wind units' metered output in the half-hour
    (taken where the units sum to at least MIN_SPLIT_MW), so the two add up to FUELHH's wind."""
    u = units.reindex(metered_wind.index)
    share = (u["offshore_mw"] / u["all_mw"]).where(u["all_mw"] >= MIN_SPLIT_MW).clip(0, 1)
    off = metered_wind * share
    return pd.DataFrame({"wind_offshore_metered_mw": off, "wind_onshore_metered_mw": metered_wind - off,
                         "wind_split_source": np.where(share.notna(), "B1610", "missing")}, index=metered_wind.index)


def assemble(w: pd.DataFrame, emb: pd.DataFrame, year: int, wind_units: pd.DataFrame | None = None) -> pd.DataFrame:
    """The half-hourly table of `year` on its UTC spine."""
    idx = spine(year)
    m = metered(w.reindex(w.index.intersection(idx))).reindex(idx)
    m["metered_source"] = m["metered_source"].fillna("missing")
    e = emb.reindex(idx)
    if wind_units is None:
        wind_units = pd.DataFrame(columns=["offshore_mw", "all_mw"], dtype=float)
    out = pd.concat([m, e, split_wind(m["wind_metered_mw"], wind_units)], axis=1)
    out["embedded_source"] = np.where(e.notna().all(axis=1), "NESO", "missing")
    links = [c for c in out if c.startswith("interconnector_")]
    both = (out["metered_source"] == "FUELHH") & (out["embedded_source"] == "NESO")
    out["generation_mw"] = out[GENERATING].sum(axis=1).where(both)       # biomass empty before 2017-11 counts 0
    out["imports_mw"] = out[links].clip(lower=0).sum(axis=1, min_count=1)
    out["exports_mw"] = -out[links].clip(upper=0).sum(axis=1, min_count=1)
    out["net_imports_mw"] = out["imports_mw"] - out["exports_mw"]
    order = (GENERATING[:-2] + WIND_SPLIT + ["wind_embedded_mw", "solar_embedded_mw", "pumped_storage_pumping_mw"]
             + links + ["generation_mw", "imports_mw", "exports_mw", "net_imports_mw", "metered_source",
                        "embedded_source", "wind_split_source"])
    return out[order]


def summarise(t: pd.DataFrame) -> pd.DataFrame:
    """Energy (GWh), shares and coverage by year and by month (long), from half-hourly tables of whole years."""
    t = t.copy()
    both = (t["metered_source"] == "FUELHH") & (t["embedded_source"] == "NESO")
    mw = [c for c in t.columns if c.endswith("_mw")]
    gwh = t.loc[both, mw] * 0.5 / 1000
    rows = []
    for resolution, key, all_key in (("year", gwh.index.year.astype(str), t.index.year.astype(str)),
                                     ("month", gwh.index.strftime("%Y-%m"), t.index.strftime("%Y-%m"))):
        e = gwh.groupby(key).sum(min_count=1)
        n = gwh.notna().groupby(key).sum()                      # per column: biomass from Nov 2017, the split from 2019
        total = pd.Series(1, index=t.index).groupby(all_key).sum()
        for period, r in e.iterrows():
            gen, net = r["generation_mw"], r["net_imports_mw"]
            for col in mw:
                tech = col[:-3]
                share_gen = r[col] / gen if col in GENERATING + WIND_SPLIT else np.nan
                share_sup = r[col] / (gen + net) if col in GENERATING + WIND_SPLIT + ["net_imports_mw"] else np.nan
                rows.append(dict(resolution=resolution, period=period, technology=tech, energy_gwh=round(r[col], 3),
                                 share_of_generation=round(share_gen, 5), share_of_supply=round(share_sup, 5),
                                 half_hours=int(n.at[period, col]),
                                 coverage=round(n.at[period, col] / total[period], 5)))
    return pd.DataFrame(rows)


def build(years: list[int]) -> None:
    raw, proc = cfg.raw_dir(), cfg.processed_dir()
    w = balance.fuelhh(raw)
    register = pd.read_csv(sorted(raw.glob("bm_units_*.csv"))[-1])
    farm_map = pd.read_csv(cfg.reference_dir() / "wind_farm_map.csv")
    flags = wind_offshore_flags(register, farm_map)
    by_name = flags.index.difference(farm_map["elexon_bmu_id"])
    print(f"  wind units: {len(flags)} ({int(flags.sum())} offshore); not in the farm map, flagged by name: "
          f"{', '.join(u for u in by_name if flags[u]) or 'none'} offshore, {len(by_name) - int(flags[by_name].sum())} "
          f"onshore", flush=True)
    units = wind_units_metered(raw / "b1610", flags)
    for y in years:
        t = assemble(w, neso_embedded(raw, y), y, units)
        if (t["metered_source"] == "missing").all():
            print(f"[{y}] no FUELHH: not written")
            continue
        t.to_csv(proc / f"generation_mix_{y}.csv", float_format="%.6g")
        cov = {s: round(float((t[f"{s}_source"] != "missing").mean()), 4) for s in ("metered", "embedded", "wind_split")}
        print(f"[{y}] -> generation_mix_{y}.csv  coverage {cov}  generation {t['generation_mw'].mean() / 1000:.1f} GW "
              f"mean, net imports {t['net_imports_mw'].mean() / 1000:.2f} GW", flush=True)
    files = sorted(proc.glob("generation_mix_[0-9][0-9][0-9][0-9].csv"))
    t = pd.concat([pd.read_csv(f, index_col="startTime", parse_dates=["startTime"]) for f in files])
    s = summarise(t)
    s.to_csv(proc / "generation_mix_summary.csv", index=False)
    print(f"  generation_mix_summary.csv: {len(s)} rows, years {sorted(set(s.loc[s.resolution == 'year', 'period']))}")


def main(argv: list[str]) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--years", nargs=2, type=int, default=[2018, 2025])
    a = p.parse_args(argv)
    build(list(range(a.years[0], a.years[1] + 1)))


if __name__ == "__main__":
    main(sys.argv[1:])
