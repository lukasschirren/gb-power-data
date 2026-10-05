"""Pull PECD v4.2 (Copernicus CDS `sis-energy-pecd`) capacity factors + temperature, GB only.

This is a second, independent weather-derived CF source alongside `renewables.ninja`
(`gbpowerdata.pull.renninja_pull`): ECMWF/ENTSO-E's Pan-European Climate Database, ERA5-reanalysis
based, aggregated by the CDS server straight to NUTS-2 for onshore wind / solar PV /
temperature (no client-side spatial weighting needed for those three -- see
`gbpowerdata.common.pecd_regions` for what IS weighted: offshore wind, which PECD publishes at its own
offshore zones, and the NUTS-2 -> gsp_group re-expression). `gbpowerdata.build.pecd_build` turns the raw
cache this module writes into the wide hourly CSV; `gbpowerdata.build.pecd_national_cf` collapses that
to the same national `wind_offshore_cf, wind_onshore_cf, solar_cf` shape as the ninja-derived
`capacity_factors_{year}.csv`, so `meritorder` can run a PECD-driven sensitivity.

Scope of this module (see the plan this was built from, `pecd v4.2 reader`, for the full
rationale): started as historical (ERA5) only, GB, 2020-2025 -- the years needed to validate
against ninja before using PECD going forward. `--stream projection` (CMIP6, 2015-2100, six GCMs x
four SSPs) is now wired up too, for extreme-wind-year screening across the future ensemble.

Requires a free CDS account + API key (same per-account-token pattern as `renninja_pull`):
  - set env var  CDSAPI_KEY=<key>, or
  - put it in    data/reference/cds_api_token.txt   (gitignored, matches the *token*.txt rule)
Register / find your key at https://cds.climate.copernicus.eu (Beta CDS, not the legacy climate.copernicus.eu/cdsapp).

All enum strings below are CONFIRMED against the dataset's own constraints endpoint
(`https://cds.climate.copernicus.eu/api/catalogue/v1/collections/sis-energy-pecd/constraints.json`,
queried with a live key on 2026-09-29 after the FIRST real pull attempt failed with
`MultiAdaptorNoDataError` -- the fix, and the reason every wind entry below looks the way it does:

  - There is no `country`/`area` field for aggregated (non-gridded) products at all -- GB is
    selected downstream by keeping zone codes that start with "UK"
    (`gbpowerdata.build.pecd_build`/`gbpowerdata.common.pecd_regions`), not by an API-side filter.
  - **NUTS-2 does NOT exist for either wind variable in pecd4_2** -- only solar PV and temperature
    get server-side NUTS-2/SZON aggregation. Wind (onshore AND offshore) is only published at
    PECD's own energy zones (`peon`/`p2on` onshore, `peof`/`p2of` offshore), so BOTH wind techs
    need the same hand-curated zone->NUTS-2 weighting `gbpowerdata.common.pecd_regions` provides --
    not just offshore, as originally assumed before this was confirmed against the live API.
  - `technology="30"`/`"20"` ("Existing technologies", today's actual fleet, not a future
    specific-power/hub-height typology) for onshore/offshore wind is ONLY a valid combination with
    `energy_scenario="resource_grade_b"` -- `resource_grade_a` exists only alongside the FUTURE
    turbine typology codes (31-39 / 21-22). Getting this pairing wrong doesn't error cleanly; it's
    exactly the kind of combination the constraints endpoint exists to catch, so `--list-request`
    is checked against it, not just printed.
  - Solar PV has no "existing" option; `"62"` (SPV utility-scale fixed) is used as the closest
    match to ninja's fixed, south-facing site convention (`data/reference/ninja_sites.csv`) --
    a documented approximation, not a confirmed equivalence.

Projection quirk, found the same way as everything above -- by a live request failing and the
constraints endpoint explaining why: `bcc_csm2_mr`'s `peon`/`peof` (v1 zone) data is versioned
`fv2`, not `fv1` like every other GCM, but ONLY under `emission_scenario=ssp2_4_5` -- the other
three scenarios (`ssp1_2_6`, `ssp3_7_0`, `ssp5_8_5`) have `bcc_csm2_mr` at `fv1` like everyone
else. `_file_version()` encodes this exactly; get it wrong and the request fails loudly (CDS 4xx
naming the valid file_version) rather than silently returning nothing.

Usage:
  python -m gbpowerdata.pull.pecd_pull --list-request                    # print requests, don't send
  python -m gbpowerdata.pull.pecd_pull                                   # historical, all techs, 2020-2025
  python -m gbpowerdata.pull.pecd_pull --tech onshore_wind --start-year 2023 --end-year 2024
  python -m gbpowerdata.pull.pecd_pull --stream projection --tech onshore_wind offshore_wind \
      --gcm ec_earth3 --scenario ssp2_4_5 --start-year 2015 --end-year 2100
Output:
  data/raw/pecd/historical/<technology_key>_<y0>-<y1>.<ext>
  data/raw/pecd/projection/<gcm>/<scenario>/<technology_key>_<y0>-<y1>.<ext>
"""

from __future__ import annotations

import argparse
import os
import sys
import zipfile
from pathlib import Path

from gbpowerdata import config as cfg

CDS_URL = "https://cds.climate.copernicus.eu/api"   # current (Beta) CDS endpoint
DATASET = "sis-energy-pecd"
PECD_VERSION = "pecd4_2"
HIST_ORIGIN = "era5_reanalysis"
PECD_RAW_DIR = cfg.raw_dir() / "pecd"
OUT_DIR = PECD_RAW_DIR / "historical"          # kept for backwards compat (build_cf imports it)
CHUNK_YEARS = 2      # CDS cost-limit guidance (ECMWF ENTSO-E training): request in short year windows
PROJ_CHUNK_YEARS = 10  # projections span 2015-2100 (86y); confirmed the API accepts a full-range
                       # request in one go (unlike historical, no 2y guidance applies), but a
                       # single ~370 MB all-Europe file per request risks timing out -- 10y keeps
                       # request COUNT tractable across 6 GCMs while keeping file size reasonable.

# technology_key -> CDS request fields, all confirmed against the live constraints endpoint (see
# the module docstring). Solar and temperature get server-side NUTS-2/SZON aggregation -- no
# client weighting needed. Onshore AND offshore wind do NOT (no NUTS-2/SZOF option exists for
# either), so both go through gbpowerdata.common.pecd_regions's hand-curated zone->NUTS-2 tables.
GCMS = ["cmcc_cm2_sr5", "ec_earth3", "mpi_esm1_2_hr", "awi_cm_1_1_mr", "bcc_csm2_mr", "mri_esm2_0"]
SCENARIOS = ["ssp1_2_6", "ssp2_4_5", "ssp3_7_0", "ssp5_8_5"]

VARIABLES = {
    "onshore_wind": {
        "variable": "wind_power_onshore_capacity_factor",
        "technology": "30",              # "Existing technologies" (today's actual fleet)
        "energy_scenario": "resource_grade_b",  # the ONLY grade valid alongside technology="30"
        "spatial_resolution": "peon",     # Pan-European Onshore Zone -- no NUTS-2 exists for wind
    },
    "offshore_wind": {
        "variable": "wind_power_offshore_capacity_factor",
        "technology": "20",              # "Existing technologies"
        "energy_scenario": "resource_grade_b",  # the ONLY grade valid alongside technology="20"
        "spatial_resolution": "peof",     # Pan-European Offshore Zone
    },
    "solar_pv": {
        "variable": "solar_photovoltaic_generation_capacity_factor",
        "technology": "62",               # SPV utility-scale fixed -- closest match to ninja's
                                           # fixed south-facing site convention; no "existing" option
        "spatial_resolution": "nuts_2",
    },
    "temperature_popweighted": {
        "variable": "population_weighted_temperature",
        "spatial_resolution": "szon",     # confirmed SZON-only (TAW is national-for-GB)
    },
}


def get_cds_key() -> str:
    key = os.environ.get("CDSAPI_KEY")
    if key:
        return key.strip()
    f = cfg.reference_dir() / "cds_api_token.txt"
    if f.exists():
        return f.read_text(encoding="utf-8").strip()
    sys.exit("No CDS API key. Set CDSAPI_KEY or create data/reference/cds_api_token.txt "
             "(https://cds.climate.copernicus.eu -> your profile -> API key).")


def _year_chunks(start: int, end: int, size: int = CHUNK_YEARS) -> list[tuple[int, int]]:
    return [(y, min(y + size - 1, end)) for y in range(start, end + 1, size)]


def _file_version(tech: str, y0: int, y1: int, gcm: str | None, scenario: str | None) -> str:
    """`population_weighted_temperature` (and its Climate-group siblings) were reprocessed
    partway through the HISTORICAL stream: the live constraints endpoint shows `fv2` covering
    1950-2021 and `fv1` covering 2022-2025 -- discovered only by a real pull attempt failing on
    2020-2021 with `fv1`. A single request can't straddle the 2021/2022 boundary either way --
    `CHUNK_YEARS=2` already keeps every default historical chunk on one side of it.

    PROJECTION quirk, found the same way: `bcc_csm2_mr`'s `peon`/`peof` (v1 zone) wind data is
    versioned `fv2`, not `fv1` like every other GCM AND every other scenario for `bcc_csm2_mr`
    itself -- it's specific to `emission_scenario=ssp2_4_5`. Every other (GCM, scenario, tech)
    combination in the projection stream is `fv1`."""
    if tech == "temperature_popweighted" and gcm is None:  # historical only
        if y0 <= 2021 < y1:
            raise ValueError("temperature request straddles the fv1/fv2 boundary at 2021/2022; "
                             "split it into two requests, one per side.")
        return "fv2" if y1 <= 2021 else "fv1"
    if gcm == "bcc_csm2_mr" and scenario == "ssp2_4_5" and tech in ("onshore_wind", "offshore_wind"):
        return "fv2"
    return "fv1"


def build_request(tech: str, y0: int, y1: int, *, stream: str = "historical",
                  gcm: str | None = None, scenario: str | None = None) -> dict:
    """No `country`/`area` field exists for this dataset's aggregated (non-gridded) products
    (confirmed against the catalogue's constraints endpoint -- passing one was the cause of the
    first live request's `MultiAdaptorNoDataError`); GB is selected downstream by keeping
    NUTS-2/zone codes that start with "UK" (`gbpowerdata.build.pecd_build`), the same way the CDS web
    form's own "Geographical area" widget only applies to gridded (ORIG) requests. `month` is
    likewise omitted: the constraints endpoint only pairs a `month` field with `year=["2026"]`
    (the current, still-partial historical year) -- every full historical year (1950-2025) and
    every projection year (2015-2100) has no `month` key at all."""
    if stream == "historical" and (y1 >= 2026 or y0 >= 2026):
        raise NotImplementedError("2026 is PECD's current partial historical year and needs "
                                  "`month`, which this module doesn't build -- request 2025 or earlier.")
    if stream == "projection" and (gcm is None or scenario is None):
        raise ValueError("--stream projection needs --gcm and --scenario.")
    spec = VARIABLES[tech]
    req = {
        "pecd_version": [PECD_VERSION],
        "temporal_period": ["historical" if stream == "historical" else "future_projections"],
        "origin": [HIST_ORIGIN if stream == "historical" else gcm],
        "variable": [spec["variable"]],
        "spatial_resolution": [spec["spatial_resolution"]],
        "year": [str(y) for y in range(y0, y1 + 1)],
    }
    if stream == "projection":
        req["emission_scenario"] = [scenario]
    if "technology" in spec:
        req["technology"] = [spec["technology"]]
    if "energy_scenario" in spec:
        req["energy_scenario"] = [spec["energy_scenario"]]
    req["file_version"] = [_file_version(tech, y0, y1, gcm, scenario)]
    return req


def _place_response(tmp_path: Path, out_dir: Path, stem: str) -> list[Path]:
    """CDS returns csv/nc for an aggregated request, sometimes zipped. Sniff the payload and
    cache it byte-for-byte under its real extension(s) -- never silently coerce the format.

    Named `{stem}` (+ an index if the zip holds more than one member), NOT the original CDS
    filename embedded in the zip -- that name is ~120 characters of its own
    (`H_ERA5_ECMW_T639_WON_..._PECD4.2_fv1.csv`), and appending it here pushed the full path past
    Windows' 260-character MAX_PATH on the first live pull (silently truncated by whatever wrote
    it, or rejected outright -- either way, `_place_response` is the one place a path is built, so
    it's the one place that needs to keep it short)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    if zipfile.is_zipfile(tmp_path):
        placed = []
        with zipfile.ZipFile(tmp_path) as z:
            members = z.namelist()
            for i, name in enumerate(members):
                suffix = f"_{i}" if len(members) > 1 else ""
                dest = out_dir / f"{stem}{suffix}{Path(name).suffix}"
                dest.write_bytes(z.read(name))
                placed.append(dest)
        tmp_path.unlink()
        return placed
    head = tmp_path.read_bytes()[:8]
    ext = ".nc" if head[:3] == b"CDF" or head[:4] == b"\x89HDF" else ".csv"
    dest = out_dir / f"{stem}{ext}"
    tmp_path.rename(dest)
    return [dest]


def out_dir_for(stream: str, gcm: str | None = None, scenario: str | None = None) -> Path:
    if stream == "historical":
        return OUT_DIR
    return PECD_RAW_DIR / "projection" / gcm / scenario


def fetch(client, tech: str, y0: int, y1: int, *, stream: str = "historical",
         gcm: str | None = None, scenario: str | None = None) -> list[Path]:
    req = build_request(tech, y0, y1, stream=stream, gcm=gcm, scenario=scenario)
    out_dir = out_dir_for(stream, gcm, scenario)
    stem = f"{tech}_{y0}-{y1}"
    existing = sorted(out_dir.glob(f"{stem}*"))
    if existing:
        print(f"  skip {stem} ({len(existing)} file(s) exist)", flush=True)
        return existing
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = out_dir / f".{stem}.tmp"
    client.retrieve(DATASET, req).download(str(tmp))
    placed = _place_response(tmp, out_dir, stem)
    print(f"  {stem}: saved {[p.name for p in placed]}", flush=True)
    return placed


def main(argv: list[str]) -> None:
    p = argparse.ArgumentParser(description="Pull PECD v4.2 CF/temperature, GB only "
                                            "(historical ERA5 or CMIP6 projection stream).")
    p.add_argument("--tech", nargs="*", choices=list(VARIABLES), default=list(VARIABLES))
    p.add_argument("--start-year", type=int, default=None)
    p.add_argument("--end-year", type=int, default=None)
    p.add_argument("--stream", choices=["historical", "projection"], default="historical")
    p.add_argument("--gcm", nargs="*", default=None, choices=GCMS,
                    help="projection only; default: all six GCMs.")
    p.add_argument("--scenario", nargs="*", default=None, choices=SCENARIOS,
                    help="projection only; default: all four SSPs.")
    p.add_argument("--chunk-years", type=int, default=None,
                    help="override CHUNK_YEARS/PROJ_CHUNK_YEARS -- request COUNT (queueing "
                         "overhead) dominated wall-clock time more than per-request data volume "
                         "in testing, so fewer/larger chunks (up to the full 86y projection range "
                         "in one request, confirmed allowed) can be much faster overall.")
    p.add_argument("--list-request", action="store_true",
                    help="print the request dict(s) that would be sent and exit -- no download, no key needed.")
    args = p.parse_args(argv[1:])

    if args.stream == "historical":
        start, end = args.start_year or 2020, args.end_year or 2025
        chunk_size = args.chunk_years or CHUNK_YEARS
        gcms, scenarios = [None], [None]
    else:
        start, end = args.start_year or 2015, args.end_year or 2100
        chunk_size = args.chunk_years or PROJ_CHUNK_YEARS
        gcms = args.gcm or GCMS
        scenarios = args.scenario or SCENARIOS

    chunks = _year_chunks(start, end, chunk_size)
    jobs = [(tech, y0, y1, gcm, scenario)
           for tech in args.tech for gcm in gcms for scenario in scenarios for y0, y1 in chunks]

    if args.list_request:
        for tech, y0, y1, gcm, scenario in jobs:
            print(f"{tech} {gcm or ''} {scenario or ''} {y0}-{y1}:",
                 build_request(tech, y0, y1, stream=args.stream, gcm=gcm, scenario=scenario))
        return

    key = get_cds_key()   # fail on a missing key before ever touching cdsapi/network
    try:
        import cdsapi
    except ImportError:
        sys.exit("cdsapi is not installed. `pip install -e \".[climate]\"` (see pyproject.toml's "
                 "climate extra) and try again.")
    client = cdsapi.Client(url=CDS_URL, key=key)

    print(f"{len(jobs)} requests ({args.stream}). out={PECD_RAW_DIR}", flush=True)
    for tech, y0, y1, gcm, scenario in jobs:
        try:
            fetch(client, tech, y0, y1, stream=args.stream, gcm=gcm, scenario=scenario)
        except Exception as e:
            # CDS 4xx bodies name the valid enum for whatever field was wrong -- surface it
            # verbatim rather than swallowing it, per the module docstring's fail-loud policy.
            sys.exit(f"CDS request failed for {tech} {gcm or ''} {scenario or ''} {y0}-{y1}: {e}")


if __name__ == "__main__":
    sys.exit(main(sys.argv))
