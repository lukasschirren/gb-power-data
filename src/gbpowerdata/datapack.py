"""Data packs: the processed tables and the hand-downloaded inputs as versioned, checksummed zips.

WHY. The pipeline works in CSV, and data does not belong in git: GitHub refuses files over
100 MB, and every rebuild of a committed table stays in every clone's history for good. A pack
is one archive per release, attached to a GitHub Release (up to 2 GB per file, outside the git
history, tied to the tag of the code that built it) or put on any shared drive.

PACKS
    processed   the data/processed/ tables built from open sources (PROCESSED_*): the 2018-2025
                panel, consumer-side tables and the national PECD capacity factors. Left out:
                licensed day-ahead data; fuel_prices_2018-2021, whose carbon price comes from EEX
                (whose terms do not allow passing it on), which `scripts/build_fuel_prices.py`
                rebuilds from the public sources; and the hourly NUTS-2 PECD tables
                (pecd/cf_historical spans 1950-2025 at 0.75 GB; pecd/cf_future_* is 0.7 GB per
                climate model), which `pecd_pull` + `pecd_build` rebuild with a free key.
    inputs      the hand-downloaded raw files no puller can fetch (INPUTS): CfD register, REPD,
                ESPENI, GSP/DNO boundaries, Ofgem cap model, DNO charging statements, DESNZ
                consumption. Only needed to re-run the stages that read them. The plant roster is
                not among them: `pull.ppm_pull` fetches the pinned powerplantmatching release.

FORMAT. A zip (deflate) holding the files byte for byte as the pipeline wrote them, under their
data/ layout (processed/demand_2023.csv, raw/espeni.csv, ...), plus MANIFEST.json with each file's
size and sha256 and the pack's provenance (created, package version, git commit). Byte-exact, so
unpacking restores exactly what was packed and the CSV readers need no change; it opens with any
unzip tool, Windows Explorer included. Measured on the 2018-2025 processed set (546 MB of CSV,
5 Oct 2026): zip-deflate 79 MB, Parquet-zstd 70 MB, zip-LZMA 48 MB. Parquet saves 11% for a
conversion step in both directions; LZMA saves 40% but writes 3x slower and Windows Explorer
cannot open it. Both stay well inside GitHub's 2 GB per release asset either way.

TERMS. A file is packed only if every one of its sources (SOURCES, FILE_SOURCES) allows
redistribution; a source marked `ship=False` (EEX) keeps its files out, and export says which
and how to rebuild them. Each manifest entry names the sources of its file and flags
`non_commercial` (it carries values from a CC BY-NC source: ESPENI, renewables.ninja); the
manifest lists every source's licence and required attribution.

GUARDS. Export refuses any file that is, or derives from, licensed N2EX/EPEX data, and any
mid_target whose mid_source column holds N2EX rows (build those with
`timeseries.mid_gap_fill_n2ex: false`). Unpack verifies every checksum, never writes outside the
configured data folders, and will not overwrite a file that differs unless told to.

Usage:
    python -m gbpowerdata.datapack export processed [--years 2018 2025] [--out dist]
    python -m gbpowerdata.datapack export inputs [--out dist]
    python -m gbpowerdata.datapack verify dist/gb-power-data_processed_2026-10-05.zip
    python -m gbpowerdata.datapack unpack dist/gb-power-data_processed_2026-10-05.zip [--force]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from gbpowerdata import __version__
from gbpowerdata import config as cfg

MANIFEST = "MANIFEST.json"

# Per-year processed tables built from open sources: {family}_{year}.csv
PROCESSED_YEARLY = (
    "agents", "bm_unit_register", "capacity_factors", "capacity_factors_by_zone", "capacity_factors_pecd",
    "cfd_fleet", "cfd_ppm_matches", "demand", "demand_by_zone", "forecast_state", "fuel_prices", "lolp_drm",
    "mid_target", "ownership", "ownership_bmu", "powerplants_located", "powerplants_tagged", "regime_summary",
    "storage_revenue", "system_prices", "wind_farm_fpn", "wind_farm_fpn_gaps", "wind_farms",
)
# Built from open sources but not packed for their size; each user rebuilds them (docs/storage_revenues.md):
# ancillary_by_unit_{y} (0.7 GB for 2020-2026; python -m gbpowerdata.pull.ancillary_pull, then
# python -m gbpowerdata.build.ancillary_services, about ten minutes)
PROCESSED_SINGLE = (
    "cfd_status.csv", "cap_tariff_by_region.csv", "consumer_levy_annual.csv",
    "consumer_levy_daily.csv", "domestic_supply_by_year.csv", "duos_domestic_tariffs.csv",
)
# Hand-downloaded raw inputs, as glob patterns under data/raw/ ({cfd_register} is the file name
# set in config.yaml).
INPUTS = (
    "{cfd_register}", "repd_*.csv", "espeni.csv",
    "gis/gsp_regions_*.geojson", "gis/dno_license_areas_*.geojson",
    "ofgem/cap_prelevelised_*.xlsx", "ofgem/cap_tariff_model_*.xlsx",
    "manual/dno_duos/**/*", "manual/desnz_subnational/*",
)
LICENSED = re.compile(r"nordpool|n2ex|epex|dayahead_price|curve_compare|demand_curves", re.I)

# Upstream sources and their terms (checked at the URLs, 5 Oct 2026). `nc`: non-commercial only;
# `ship=False`: the terms do not allow passing the data on, so files carrying it are never packed
# and each user pulls the source themselves (`rebuild` says how).
SOURCES = {
    "elexon": dict(name="Elexon BMRS", licence="BMRS open data licence", url="https://www.elexon.co.uk/bsc/data/balancing-mechanism-reporting-agent/copyright-licence-bmrs-data/",
                   attribution="Contains BMRS data © Elexon Limited copyright and database right {year}"),
    "neso": dict(name="NESO Data Portal", licence="NESO Open Licence (set per dataset)", url="https://www.neso.energy/data-portal/neso-open-licence"),
    "lccc": dict(name="Low Carbon Contracts Company", licence="Open Government Licence v3.0", url="https://dp.lowcarboncontracts.uk"),
    "govuk": dict(name="DESNZ / ONS / gov.uk (REPD, subnational consumption, gas SAP, UK ETS auctions)",
                  licence="Open Government Licence v3.0", url="https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/"),
    "ofgem": dict(name="Ofgem", licence="Open Government Licence v3.0", url="https://www.ofgem.gov.uk"),
    "ppm": dict(name="powerplantmatching", licence="CC BY 4.0", url="https://github.com/PyPSA/powerplantmatching"),
    "psd": dict(name="OSUKED Power Station Dictionary", licence="MIT", url="https://github.com/OSUKED/Power-Station-Dictionary"),
    "companies_house": dict(name="Companies House (persons with significant control)",
                            licence="no licence stated; credit required where its guidance, website, publications or statistical tables are used",
                            url="https://www.gov.uk/government/publications/companies-house-accreditation-to-information-fair-traders-scheme/public-task-copyright-and-crown-copyright",
                            attribution="Source: Companies House"),
    "espeni": dict(name="ESPENI (Wilson & Godfrey, Univ. of Birmingham)", licence="CC BY-NC 4.0", nc=True,
                   url="https://doi.org/10.5281/zenodo.4739408",
                   attribution="Wilson et al. (2021), Calculating Great Britain's half-hourly electrical demand from publicly available data, Energy Strategy Reviews"),
    "ninja": dict(name="renewables.ninja", licence="CC BY-NC 4.0", nc=True, url="https://www.renewables.ninja",
                  attribution="Pfenninger & Staffell (2016), Energy 114:1251-1265; Staffell & Pfenninger (2016), Energy 114:1224-1239"),
    "pecd": dict(name="Copernicus C3S Pan-European Climate Database v4.2", licence="CC BY 4.0",
                 url="https://cds.climate.copernicus.eu/datasets/sis-energy-pecd",
                 attribution="Generated using Copernicus Climate Change Service information {year}"),
    "worldbank": dict(name="World Bank Commodity Price Data (Pink Sheet)", licence="CC BY 4.0",
                      url="https://www.worldbank.org/en/research/commodity-markets"),
    "ecb": dict(name="ECB euro foreign exchange reference rates", licence="ECB statistics reuse policy (free reuse, commercial included)",
                url="https://www.ecb.europa.eu/stats/ecb_statistics/governance_and_quality_framework/html/usage_policy.en.html",
                attribution="Source: ECB statistics"),
    "eex": dict(name="EEX EU ETS primary auction clearing prices (carbon, 2018-2020)",
                licence="EEX market-data terms: redistribution to third parties is a licensed EEX service",
                ship=False, url="https://www.eex.com/en/market-data/licensing-policies",
                rebuild="python scripts/build_fuel_prices.py"),
    # The next two publish no data licence; treated as publicly published tariff information
    # (maintainer's decision, 5 Oct 2026).
    "octopus": dict(name="Octopus Energy public API (standard variable tariff)", licence="publicly published, no stated licence",
                    url="https://developer.octopus.energy"),
    "dno": dict(name="DNO charging statements", licence="publicly published regulatory statements, no stated licence"),
}
# Which sources feed which file: processed family (or single file) / raw input pattern -> keys.
FILE_SOURCES = {
    "agents": ("ppm", "lccc", "govuk", "neso", "elexon"),
    # NESO's results by unit, Elexon's register for the unit ids, and the bidders' groups by the ownership tables'
    # rules and spellings (the registers' names, Companies House's control register); not packed (see above)
    "ancillary_by_unit": ("neso", "elexon", "govuk", "ofgem", "lccc", "companies_house"),
    "bm_unit_register": ("elexon",),
    "capacity_factors": ("espeni", "elexon", "govuk"),
    "capacity_factors_by_zone": ("ninja", "espeni", "elexon", "govuk"),
    "capacity_factors_pecd": ("pecd", "ppm"),
    "cfd_fleet": ("lccc",),
    "cfd_ppm_matches": ("ppm", "lccc"),
    "demand": ("espeni", "elexon"),
    "demand_by_zone": ("espeni", "elexon", "govuk"),
    "forecast_state": ("elexon", "neso"),
    "fuel_prices": ("govuk", "worldbank", "ecb"),     # + "eex" for EEX_YEARS, see sources_for
    "lolp_drm": ("elexon",),
    "mid_target": ("elexon",),
    # DUKES 5.11 (govuk), Ofgem's RO register, LCCC's CfD register, NESO's CM register, Elexon's BM register, the
    # wind-farm map (REPD, the Power Station Dictionary), and Companies House's control register (basis ch_psc,
    # after a pull)
    "ownership": ("govuk", "ofgem", "lccc", "neso", "elexon", "psd", "companies_house"),
    "ownership_bmu": ("govuk", "ofgem", "lccc", "neso", "elexon", "psd", "companies_house"),
    "powerplants_located": ("ppm", "lccc", "neso"),
    "powerplants_tagged": ("ppm", "lccc"),
    "regime_summary": ("ppm", "lccc"),
    # Elexon's notifications, market index, cash-out and BM cashflows, NESO's ancillary results, and the traders and
    # optimisers of the ownership tables
    "storage_revenue": ("elexon", "neso", "govuk", "ofgem", "lccc", "psd", "companies_house"),
    "system_prices": ("elexon",),
    "wind_farm_fpn": ("elexon", "govuk", "lccc", "psd"),
    "wind_farm_fpn_gaps": ("elexon", "govuk", "lccc", "psd"),
    "wind_farms": ("elexon", "govuk", "lccc", "psd"),
    "cfd_status": ("lccc", "govuk"),
    "cap_tariff_by_region": ("ofgem",),
    "consumer_levy_annual": ("lccc", "octopus"),      # svt_unit_rate_gbp_mwh, levy_share_of_unit_rate_pct
    "consumer_levy_daily": ("lccc",),
    "domestic_supply_by_year": ("govuk",),
    "duos_domestic_tariffs": ("dno", "ofgem"),
    "raw/CfD_Register": ("lccc",), "raw/repd": ("govuk",),
    "raw/espeni": ("espeni",), "raw/gis": ("neso",), "raw/ofgem": ("ofgem",),
    "raw/manual/dno_duos": ("dno",), "raw/manual/desnz_subnational": ("govuk",),
}
# The carbon price is the EEX EUA auction price until the UK left the EU ETS (pull.carbon_pull
# EUA_YEARS 2018-2020), the gov.uk UK ETS price after. 2021 is included because stage 2 interpolates
# between mid-month prices, so 1-14 January 2021 still carries the December 2020 EEX price.
EEX_YEARS = (2018, 2019, 2020, 2021)


def sources_for(arcname: str) -> tuple[str, ...]:
    """The SOURCES keys behind a packed file. A file with no entry is an error, so the terms
    registry cannot silently fall behind the pack lists."""
    if arcname.startswith("processed/"):
        stem = arcname.removeprefix("processed/").removesuffix(".csv")
        key = re.sub(r"_\d{4}$", "", stem)
        if key in FILE_SOURCES:
            year = stem[len(key) + 1:]
            if key == "fuel_prices" and year.isdigit() and int(year) in EEX_YEARS:
                return FILE_SOURCES[key] + ("eex",)
            return FILE_SOURCES[key]
    else:
        for prefix in sorted((k for k in FILE_SOURCES if k.startswith("raw/")), key=len, reverse=True):
            if arcname.startswith(prefix):
                return FILE_SOURCES[prefix]
    raise ValueError(f"{arcname}: no entry in datapack.FILE_SOURCES - add its sources before packing")


def withheld_by(keys: tuple[str, ...]) -> list[str]:
    """The sources among `keys` whose terms do not allow passing their data on."""
    return [k for k in keys if not SOURCES[k].get("ship", True)]


def _roots() -> dict[str, Path]:
    """Archive prefix -> the configured data folder it unpacks into."""
    return {"processed": cfg.processed_dir(), "raw": cfg.raw_dir(), "reference": cfg.reference_dir()}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git_commit() -> str:
    """The commit that built the pack, with -dirty if src/ has uncommitted changes."""
    def git(*a):
        return subprocess.run(["git", *a], cwd=cfg.REPO_ROOT, capture_output=True, text=True)
    head = git("rev-parse", "--short", "HEAD")
    if head.returncode != 0:
        return "uncommitted"
    dirty = git("status", "--porcelain", "--", "src", "scripts", "config.yaml").stdout.strip()
    return head.stdout.strip() + ("-dirty" if dirty else "")


def processed_files(years: tuple[int, int] | None = None) -> list[Path]:
    """The open processed tables present on disk, optionally restricted to a year range."""
    proc = cfg.processed_dir()
    rx = re.compile(r"^(%s)_(\d{4})\.csv$" % "|".join(PROCESSED_YEARLY))
    out = []
    for f in sorted(proc.glob("*.csv")):
        m = rx.match(f.name)
        if m and (years is None or years[0] <= int(m.group(2)) <= years[1]):
            out.append(f)
    out += [proc / s for s in PROCESSED_SINGLE if (proc / s).exists()]
    return out


def input_files() -> list[Path]:
    """The hand-downloaded raw inputs present on disk."""
    raw, st1 = cfg.raw_dir(), cfg.load_config()["stage1"]
    out: list[Path] = []
    for pat in INPUTS:
        pat = pat.format(cfd_register=st1["cfd_register"])
        out += [f for f in sorted(raw.glob(pat)) if f.is_file() and f not in out]
    return out


def check_shareable(path: Path, arcname: str) -> None:
    """Raise if a file is (or derives from) licensed N2EX/EPEX data. Judged on its place in the
    data layout (`arcname`), not on where the data folder happens to sit on this machine."""
    if LICENSED.search(arcname):
        raise ValueError(f"{arcname}: licensed N2EX/EPEX data, never packed")
    if path.name.startswith("mid_target_"):
        src = pd.read_csv(path, usecols=["mid_source"])["mid_source"]
        n = int((src == "N2EX").sum())
        if n:
            raise ValueError(f"{path.name}: {n} half-hours filled from N2EX (licensed); rebuild stage 2 "
                             "with `timeseries.mid_gap_fill_n2ex: false` before packing")


def _arcname(path: Path) -> str:
    """processed/..., raw/... or reference/...: the file's place under the data layout."""
    for prefix, root in _roots().items():
        try:
            return f"{prefix}/{path.resolve().relative_to(root.resolve()).as_posix()}"
        except ValueError:
            continue
    raise ValueError(f"{path} is not under a configured data folder")


def export(pack: str, out_dir: Path, years: tuple[int, int] | None = None) -> Path:
    files = processed_files(years) if pack == "processed" else input_files()
    if not files:
        raise SystemExit(f"nothing to pack for '{pack}' - are the data folders in config.yaml populated?")
    names = {f: _arcname(f) for f in files}
    srcs, withheld = {}, []
    for f, name in list(names.items()):     # every check before anything is written
        check_shareable(f, name)
        srcs[name] = sources_for(name)
        if blocked := withheld_by(srcs[name]):
            withheld.append({"path": name, "sources": blocked,
                             "rebuild": sorted({SOURCES[k]["rebuild"] for k in blocked})})
            del names[f]
    out_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    target = out_dir / f"gb-power-data_{pack}_{now:%Y-%m-%d}.zip"
    entries = []
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f, name in names.items():
            data = f.read_bytes()
            z.writestr(name, data)
            keys = srcs[name]
            entries.append({"path": name, "bytes": len(data), "sha256": _sha256(data),
                            "sources": list(keys),
                            "non_commercial": any(SOURCES[k].get("nc", False) for k in keys)})
        used = sorted({k for e in entries for k in e["sources"]})
        manifest = {
            "pack": pack,
            "created_utc": now.isoformat(timespec="seconds"),
            "gbpowerdata_version": __version__,
            "git_commit": _git_commit(),
            "years": list(years) if years else None,
            "n_files": len(entries),
            "bytes_uncompressed": sum(e["bytes"] for e in entries),
            "terms": "The code's BSD licence does not cover this data. Each file keeps the terms of its "
                     "sources (listed below with their required attribution). non_commercial: CC BY-NC "
                     "material, non-commercial use only. withheld: files whose sources do not allow "
                     "passing them on; rebuild them locally with the command given.",
            "sources": {k: {f: (v.format(year=now.year) if isinstance(v, str) else v)
                            for f, v in SOURCES[k].items()} for k in used},
            "files": entries,
            "withheld": withheld,
        }
        z.writestr(MANIFEST, json.dumps(manifest, indent=1))
    return target


def _read_manifest(z: zipfile.ZipFile) -> dict:
    if MANIFEST not in z.namelist():
        raise ValueError(f"{z.filename}: no {MANIFEST}, not a gb-power-data pack")
    return json.loads(z.read(MANIFEST))


def _destination(name: str) -> Path:
    prefix, _, rest = name.partition("/")
    roots = _roots()
    if prefix not in roots or not rest or ".." in Path(rest).parts or Path(rest).is_absolute():
        raise ValueError(f"unsafe or unknown member path: {name}")
    return roots[prefix] / rest


def verify(archive: Path) -> dict:
    """Check every member against the manifest without extracting; return the manifest."""
    with zipfile.ZipFile(archive) as z:
        man = _read_manifest(z)
        for e in man["files"]:
            if _sha256(z.read(e["path"])) != e["sha256"]:
                raise ValueError(f"{e['path']}: checksum mismatch")
    return man


def unpack(archive: Path, force: bool = False) -> tuple[int, int]:
    """Extract into the configured data folders. Returns (written, already identical)."""
    same = 0
    with zipfile.ZipFile(archive) as z:
        man = _read_manifest(z)
        plan = []
        # Pass 1 checks every member and every destination, so a bad archive writes nothing.
        for e in man["files"]:
            if _sha256(z.read(e["path"])) != e["sha256"]:
                raise ValueError(f"{e['path']}: checksum mismatch, archive is damaged")
            dest = _destination(e["path"])
            if dest.exists():
                if _sha256(dest.read_bytes()) == e["sha256"]:
                    same += 1
                    continue
                if not force:
                    raise FileExistsError(f"{dest} exists and differs; use --force to overwrite")
            plan.append((e["path"], dest))
        # Pass 2 writes, one member in memory at a time (the zip's CRC guards the re-read).
        for name, dest in plan:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(z.read(name))
    return len(plan), same


def main(argv: list[str]) -> None:
    p = argparse.ArgumentParser(prog="python -m gbpowerdata.datapack", description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export", help="build a pack from the configured data folders")
    e.add_argument("pack", choices=["processed", "inputs"])
    e.add_argument("--years", nargs=2, type=int, metavar=("FIRST", "LAST"))
    e.add_argument("--out", type=Path, default=cfg.REPO_ROOT / "dist")
    v = sub.add_parser("verify", help="check a pack's checksums")
    v.add_argument("archive", type=Path)
    u = sub.add_parser("unpack", help="extract a pack into the configured data folders")
    u.add_argument("archive", type=Path)
    u.add_argument("--force", action="store_true", help="overwrite files that differ")
    a = p.parse_args(argv)

    if a.cmd == "export":
        path = export(a.pack, a.out, tuple(a.years) if a.years else None)
        man = verify(path)
        print(f"{path}  {man['n_files']} files, {man['bytes_uncompressed']/1e6:,.0f} MB -> "
              f"{path.stat().st_size/1e6:,.0f} MB, commit {man['git_commit']}")
        # one line per table family or per manual folder, not per file
        nc = sorted({re.sub(r"^(raw/manual/[^/]+/).*", r"\1", re.sub(r"_\d{4}\.csv$", "_{y}.csv", e["path"]))
                     for e in man["files"] if e["non_commercial"]})
        if nc:
            print(f"  non-commercial (CC BY-NC): {', '.join(nc)}")
        _print_withheld(man)
    elif a.cmd == "verify":
        man = verify(a.archive)
        print(f"OK  {man['pack']} pack, {man['n_files']} files, built {man['created_utc']} "
              f"from {man['git_commit']}")
        _print_withheld(man)
    else:
        written, same = unpack(a.archive, a.force)
        print(f"{written} files written, {same} already identical")
        with zipfile.ZipFile(a.archive) as z:
            _print_withheld(_read_manifest(z))


def _print_withheld(man: dict) -> None:
    """Tell the user which files the pack leaves out and the command that builds them."""
    for cmd in sorted({c for w in man.get("withheld", []) for c in w["rebuild"]}):
        paths = [w["path"] for w in man["withheld"] if cmd in w["rebuild"]]
        print(f"  not in this pack (source terms do not allow passing it on): {', '.join(paths)}\n"
              f"    build locally with: {cmd}")


if __name__ == "__main__":
    main(sys.argv[1:])
