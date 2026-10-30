"""Export the tables a market model reads as one self-contained folder with a sha256 manifest.

WHY. A model that reads this repository's tables straight from its data folders is tied to that checkout: its
results cannot say which snapshot of the data they were cleared on, and a rebuilt table changes them unasked. This
module writes a folder the model reads instead: the per-year panel, the single tables and the reference tables it
needs, copied byte for byte under fixed names, with MANIFEST.json naming each file's size, sha256 and sources and
the commit of this repository that built the data. The model's own loader reads the folder and never this package;
a model run records the manifest's commit beside its results.

WHAT GOES IN. YEARLY tables for each year of the range, SINGLE tables, REFERENCE tables of data/reference/ and the
RAW files of RAW (copied under a flat name; a pattern takes the newest file). Tables ENTSO-E, Elexon, NESO, LCCC
and the other open sources allow passing on are always exported. Licensed tables (the day-ahead auction prices of
N2EX and EPEX, a mid_target gap-filled with N2EX, and the interconnector table, whose NSL capacity comes from
Nord Pool) are exported only with `licensed=True`, for the licence holder's own machine, and the manifest flags
them; without it they are left out and listed under left_out_licensed. Every file is checked before anything is
written: a missing table stops the export with its name. A folder that already holds a manifest is refused unless
`overwrite=True`, so a model run cannot mix two snapshots.

MANIFEST. {"kind": "model-inputs", "created": ISO time, "gbpowerdata_version", "commit" (this repository's, with
-dirty when src/ has uncommitted changes), "years": [first, last], "licensed": bool, "tables": [{"name", "size",
"sha256", "sources", "licensed"}] sorted by name, "left_out_licensed": [names]}. `check(folder)` reads it back and
reports the files missing or changed since the export.

RUN    python -m gbpowerdata.modelinputs --out DIR [--years 2018 2025] [--licensed] [--overwrite]
       python -m gbpowerdata.modelinputs --out DIR --check
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from gbpowerdata import __version__
from gbpowerdata import config as cfg
from gbpowerdata import datapack

KIND = "model-inputs"
MANIFEST = "MANIFEST.json"

# processed/{name}_{year}.csv for every year of the range
YEARLY = ("demand", "capacity_factors", "capacity_factors_by_zone", "fuel_prices", "agents", "cfd_fleet",
          "powerplants_located", "wind_farms", "wind_farm_fpn", "wind_farm_fpn_gaps", "bm_unit_register",
          "generation_mix", "lolp_drm", "capacity_market")
# per year too; mid_target is required (licensed only when gap-filled with N2EX), the day-ahead prices are copied
# when present
YEARLY_LICENSED = ("mid_target", "dayahead_price_n2ex", "dayahead_price_epex_hourly", "dayahead_price_epex_hh",
                   "dayahead_price_blend")
# processed/ tables without a year (.csv unless an extension is given; a folder keeps its folder)
SINGLE = ("cfd_status", "cfd_contracts", "rego_vintages", "rego_price_monthly", "vre_cf_corrected", "ic_hourly.parquet",
          "bmrp_halfhourly", "foreign_supply_slope", "ro_stations", "tyndp_nt2030_cy2009_hourly",
          "pecd/gsp_cf_era5.parquet", "pecd/national_cf_historical.parquet",
          "capacity_market_agreements", "capacity_market_auctions", "capacity_market_derating",
          "capacity_market_weights", "capacity_market_links", "consumer_levy_annual", "consumer_levy_daily",
          "domestic_supply_by_year", "cap_components_by_period", "generation_by_fuel_annual", "storage_fleet",
          "generation_battery_summary", "generation_battery_units")
# data/reference/ tables
REFERENCE = ("thermal_parameters", "thermal_parameter_sources", "thermal_station_bmu", "thermal_unit_efficiency",
             "cfd_round_params", "wind_farm_map", "wind_farm_map_overrides", "tech_parameters.yaml",
             "gsp_overrides", "nuclear_availability_by_year", "bm_dynamic_by_tech", "ic_rated_capacity",
             "rego_prices", "rego_price_sources", "rego_statistics")
# raw files, pattern under raw/ -> name in the folder (a pattern with * takes the newest match), and their sources
RAW = {"ecb_fx/eur_gbp_daily.csv": "fx_eur_gbp_daily.csv",
       "lccc/cfd_actual_generation.csv": "cfd_actual_generation.csv",
       "coal_monthly.csv": "coal_monthly.csv",
       "repd_*.csv": "repd.csv",
       "gis/gsp_regions_*.geojson": "gis/gsp_regions.geojson"}
RAW_SOURCES = {"fx_eur_gbp_daily.csv": ("ecb",), "cfd_actual_generation.csv": ("lccc",),
               "coal_monthly.csv": ("worldbank", "hmrc", "ecb"), "repd.csv": ("govuk",),
               "gis/gsp_regions.geojson": ("neso",)}
# processed tables whose sources datapack.sources_for cannot resolve from the name (no year, a parquet, a folder)
EXTRA_SOURCES = {"ic_hourly.parquet": ("entsoe", "nordpool", "ecb"),
                 "pecd/gsp_cf_era5.parquet": ("pecd", "ppm"),
                 "pecd/national_cf_historical.parquet": ("pecd", "ppm")}
REFERENCE_SOURCE = ("reference",)        # see data/reference/README.md for each table's sources
UNREGISTERED = ("unregistered",)         # a table with no entry in datapack.FILE_SOURCES (built locally)


def file_name(name: str) -> str:
    """The file a table name stands for: .csv unless an extension is given."""
    return name if Path(name).suffix else f"{name}.csv"


def table_sources(name: str) -> tuple[str, ...]:
    """The datapack.SOURCES keys behind a table of the folder, by its file name."""
    if name in EXTRA_SOURCES:
        return EXTRA_SOURCES[name]
    if name.startswith("dayahead_price"):
        return ("nordpool",) if "n2ex" in name else ("epex",) if "epex" in name else ("nordpool", "epex")
    try:
        return datapack.sources_for(f"processed/{name}")
    except ValueError:
        return UNREGISTERED


def _newest(folder: Path, pattern: str) -> Path | None:
    files = sorted(f for f in folder.glob(pattern) if f.is_file())
    return files[-1] if files else None


def files(years: tuple[int, int]) -> list[tuple[Path, str, tuple[str, ...]]]:
    """Every (source path, name in the folder, sources) the export considers, the licensed ones included; raises
    SystemExit naming each required file that is missing before anything is written."""
    proc, ref, raw = cfg.processed_dir(), cfg.reference_dir(), cfg.raw_dir()
    out: list[tuple[Path, str, tuple[str, ...]]] = []
    missing: list[str] = []

    def take(path: Path, name: str, sources: tuple[str, ...], required: bool = True) -> None:
        if path.exists():
            out.append((path, name, sources))
        elif required:
            missing.append(f"{name} ({path})")

    for y in range(years[0], years[1] + 1):
        for t in YEARLY:
            take(proc / f"{t}_{y}.csv", f"{t}_{y}.csv", table_sources(f"{t}_{y}.csv"))
        take(proc / f"mid_target_{y}.csv", f"mid_target_{y}.csv", table_sources(f"mid_target_{y}.csv"))
        for t in YEARLY_LICENSED[1:]:       # present or not; export leaves them out unless licensed
            take(proc / f"{t}_{y}.csv", f"{t}_{y}.csv", table_sources(f"{t}_{y}.csv"), required=False)
    for s in SINGLE:
        name = file_name(s)
        take(proc / name, name, table_sources(name))
    for r in REFERENCE:
        name = file_name(r)
        take(ref / name, name, REFERENCE_SOURCE)
    for pattern, name in RAW.items():
        p = _newest(raw, pattern) if "*" in pattern else raw / pattern
        if p is None:
            missing.append(f"{name} (raw/{pattern})")
        else:
            take(p, name, RAW_SOURCES.get(name, UNREGISTERED))
    if missing:
        raise SystemExit("modelinputs: missing files, nothing written:\n  " + "\n  ".join(missing))
    return out


def is_licensed(path: Path, name: str, sources: tuple[str, ...]) -> bool:
    """Whether a file is, or derives from, licensed market data: by its name's markers, by a source whose terms do
    not allow passing it on (Nord Pool, EPEX), or, for mid_target, by N2EX rows in it."""
    if datapack.LICENSED.search(name):
        return True
    if any(k in ("nordpool", "epex") or not datapack.SOURCES.get(k, {}).get("ship", True) for k in sources):
        return True
    try:
        datapack.check_shareable(path, f"processed/{name}")
    except ValueError:
        return True
    return False


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def export(out_dir: Path, years: tuple[int, int] = (2018, 2025), licensed: bool = False,
           overwrite: bool = False) -> dict:
    """Copy the tables into `out_dir` and write its manifest (docstring); returns the manifest."""
    out_dir = Path(out_dir)
    if (out_dir / MANIFEST).exists() and not overwrite:
        raise SystemExit(f"modelinputs: {out_dir} already holds a {MANIFEST}; pass --overwrite to replace it")
    items = files(years)
    kept, left_out = [], []
    for path, name, sources in items:
        lic = is_licensed(path, name, sources)
        if lic and not licensed:
            left_out.append(name)
            continue
        kept.append((path, name, sources, lic))

    out_dir.mkdir(parents=True, exist_ok=True)
    entries = []
    for path, name, sources, lic in kept:
        target = out_dir / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())
        entries.append({"name": name, "size": target.stat().st_size, "sha256": _sha256(target),
                        "sources": list(sources), "licensed": lic})
    manifest = {
        "kind": KIND,
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "gbpowerdata_version": __version__,
        "commit": datapack._git_commit(),
        "years": [years[0], years[1]],
        "licensed": licensed,
        "tables": sorted(entries, key=lambda e: e["name"]),
        "left_out_licensed": sorted(left_out),
    }
    (out_dir / MANIFEST).write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return manifest


def check(out_dir: Path) -> dict:
    """Every table of the manifest present with its sha256: {"ok", "missing", "changed", "n"}."""
    out_dir = Path(out_dir)
    man = json.loads((out_dir / MANIFEST).read_text(encoding="utf-8"))
    missing, changed = [], []
    for t in man["tables"]:
        p = out_dir / t["name"]
        if not p.exists():
            missing.append(t["name"])
        elif _sha256(p) != t["sha256"]:
            changed.append(t["name"])
    return {"ok": not missing and not changed, "missing": missing, "changed": changed, "n": len(man["tables"]),
            "commit": man.get("commit"), "created": man.get("created")}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", required=True, help="the folder to write (or to check)")
    ap.add_argument("--years", nargs=2, type=int, default=[2018, 2025], metavar=("FROM", "TO"))
    ap.add_argument("--licensed", action="store_true", help="include the licensed tables (own machine only)")
    ap.add_argument("--overwrite", action="store_true", help="replace a folder that already holds a manifest")
    ap.add_argument("--check", action="store_true", help="verify an exported folder against its manifest")
    a = ap.parse_args(argv)
    if a.check:
        c = check(Path(a.out))
        print(f"{a.out}: {c['n']} tables of commit {c['commit']} ({c['created']}); "
              + ("ok" if c["ok"] else f"missing {c['missing']}, changed {c['changed']}"))
        return 0 if c["ok"] else 1
    man = export(Path(a.out), (a.years[0], a.years[1]), a.licensed, a.overwrite)
    size = sum(t["size"] for t in man["tables"]) / 1e6
    print(f"wrote {len(man['tables'])} tables ({size:,.0f} MB) to {a.out}, commit {man['commit']}")
    if man["left_out_licensed"]:
        print(f"left out (licensed; pass --licensed on the licence holder's machine): "
              + ", ".join(man["left_out_licensed"]))
    unregistered = sorted(t["name"] for t in man["tables"] if t["sources"] == list(UNREGISTERED))
    if unregistered:
        print(f"no source entry in datapack.FILE_SOURCES (built locally): {', '.join(unregistered)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
