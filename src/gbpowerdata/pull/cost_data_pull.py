"""Pull the published cost and technical assumptions of generation and storage technologies into data/raw/cost_data/.

Why: a model of entry needs what an investor would have assumed when deciding: capital and operating costs,
lifetimes, efficiencies and hurdle rates, as published at the time (a vintage per edition), by commissioning year.
gbpowerdata.build.investment_inputs reads these files; values published only in PDF reports (CEPA's hurdle rates,
Mott MacDonald's 2018 storage costs) are transcribed in data/reference/investment_parameters.csv instead.

Sources (FILES; their terms in data/reference/investment_parameter_sources.csv):
  egc2020      BEIS, Electricity Generation Costs (2020), key data and assumptions (real 2018 GBP), Open Government
               Licence v3.0: https://www.gov.uk/government/publications/beis-electricity-generation-costs-2020
  egc2023      DESNZ, Electricity generation costs 2023, Annex A (2021 prices; updated 16 November 2023), OGL:
               https://www.gov.uk/government/publications/electricity-generation-costs-2023
  egc2025      DESNZ, Electricity generation costs 2025, Annex A (2024 prices; published 14 January 2026), OGL:
               https://www.gov.uk/government/publications/electricity-generation-costs-2025
  dea_storage  Danish Energy Agency, Technology Data for Energy Storage, datasheet (2020 EUR; lithium-ion and flow
               batteries updated May 2025), Creative Commons Attribution 4.0 International (its Index sheet):
               https://ens.dk/en/analyses-and-statistics/technology-data-energy-storage
  atb          NREL (now the National Laboratory of the Rockies), Annual Technology Baseline, electricity, editions
               2021-2025 (ATB_EDITIONS), the newest version of each in the OEDI data lake
               (https://oedi-data-lake.s3.amazonaws.com/ATB/electricity/csv/{edition}/[vX.Y.Z/]ATBe.csv, 40-320 MB),
               streamed and cut to the utility-scale battery rows of the market case ("Market" to 2024, "Exp" in
               2025) with a 20-year cost recovery period (ATB_KEEP); Creative Commons Attribution 4.0 (the editions' OEDI records); in 2019, 2020, 2021,
               2022 and 2023 USD for the editions 2021-2025 (each edition's "Definitions" page, "Dollar Year").
               Editions 2019 and 2020 are left out: their definitions pages, with the dollar year, are gone.
None of the generation costs editions covers batteries; the Danish Energy Agency's datasheet and the ATB do.

Gotchas: the Danish Energy Agency replaces the file behind the same URL when it updates it, so the file is kept
under its version (the "Version:" cell of its Index sheet): dea_technology_data_energy_storage_v{version}.xlsx. A
file already there is not pulled again (the editions do not change; pass --force to refresh).

Output: data/raw/cost_data/egc2020_key_data_and_assumptions.xlsx, egc2023_annex_a.xlsx, egc2025_annex_a.xlsx,
dea_technology_data_energy_storage_v{version}.xlsx, atb_{edition}[_v{version}]_utility_battery.csv.

Usage: python -m gbpowerdata.pull.cost_data_pull [names] [--force]      (names: egc2020 ... dea_storage atb)
"""
from __future__ import annotations

import argparse
import csv
import io
import re
import sys

import openpyxl
import requests

from gbpowerdata import config as cfg

FILES = {
    "egc2020": ("https://assets.publishing.service.gov.uk/media/5f450d378fa8f55de885e1b8/GC20_Key_Data_and_Assumptions.xlsx",
                "egc2020_key_data_and_assumptions.xlsx"),
    "egc2023": ("https://assets.publishing.service.gov.uk/media/6555cb6d046ed4000d8b99bb/"
                "annex-a-additional-estimates-and-key-assumptions.xlsx", "egc2023_annex_a.xlsx"),
    "egc2025": ("https://assets.publishing.service.gov.uk/media/69d8efec96c86b7513170229/"
                "annex-a-additional-estimates-and-key-assumptions-2025.xlsx", "egc2025_annex_a.xlsx"),
    "dea_storage": ("https://ens.dk/media/6589/download", "dea_technology_data_energy_storage_v{version}.xlsx"),
}
UA = {"User-Agent": "Mozilla/5.0 (research data pull)"}
ATB_BUCKET = "https://oedi-data-lake.s3.amazonaws.com"
ATB_EDITIONS = (2021, 2022, 2023, 2024, 2025)
# the market case is "Market" to 2024 and "Exp" (expected) in 2025; capital and O&M costs do not depend on it
ATB_KEEP = {"technology": ("Utility-Scale Battery Storage",), "core_metric_case": ("Market", "Exp"), "crpyears": ("20",),
            "core_metric_parameter": ("CAPEX", "OCC", "GCC", "Fixed O&M", "Variable O&M", "Round-Trip Efficiency")}


def out_dir():
    return cfg.raw_dir() / "cost_data"


def atb_key(edition: int, keys: list[str]) -> tuple[str, str]:
    """(object key, version) of an edition's ATBe.csv among the bucket's keys: the highest vX.Y.Z, else the plain one."""
    found = []
    for k in keys:
        m = re.fullmatch(rf"ATB/electricity/csv/{edition}/(?:v(\d+)\.(\d+)\.(\d+)/)?ATBe\.csv", k)
        if m:
            found.append((tuple(int(x) for x in m.groups()) if m.group(1) else (-1,), k))
    if not found:
        raise RuntimeError(f"cost_data_pull: no ATBe.csv for the {edition} ATB")
    ver, key = max(found)
    return key, ("" if ver == (-1,) else "v" + ".".join(map(str, ver)))


def atb_keys(edition: int) -> list[str]:
    r = requests.get(ATB_BUCKET, params={"list-type": "2", "prefix": f"ATB/electricity/csv/{edition}/"}, timeout=120)
    r.raise_for_status()
    return re.findall(r"<Key>([^<]+)</Key>", r.text)


def keep(header: list[str], rows) -> list[list[str]]:
    """The rows of an ATBe.csv that ATB_KEEP selects."""
    ix = {h: i for i, h in enumerate(header)}
    return [r for r in rows if len(r) == len(header) and all(r[ix[c]] in v for c, v in ATB_KEEP.items())]


def pull_atb(edition: int, force: bool = False) -> str:
    key, version = atb_key(edition, atb_keys(edition))
    path = out_dir() / f"atb_{edition}{'_' + version if version else ''}_utility_battery.csv"
    if path.exists() and not force:
        print(f"  {path.name} exists, skipped")
        return str(path)
    r = requests.get(f"{ATB_BUCKET}/{key}", stream=True, timeout=900)
    r.raise_for_status()
    rd = csv.reader(line.decode("utf-8-sig") for line in r.iter_lines())
    header = [h.lstrip("﻿") for h in next(rd)]
    rows = keep(header, rd)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    print(f"  ATB {edition} {version or ''}: {len(rows):,} rows -> {path}")
    return str(path)


def dea_version(content: bytes) -> str:
    """The version on the datasheet's Index sheet (the cell after "Version:")."""
    wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    for row in wb["Index"].iter_rows(values_only=True):
        cells = [c for c in row if c not in (None, "")]
        for i, c in enumerate(cells[:-1]):
            if str(c).strip().lower().startswith("version"):
                return str(cells[i + 1]).strip()
    raise RuntimeError("cost_data_pull: no 'Version:' cell on the datasheet's Index sheet")


def pull(name: str, force: bool = False) -> str:
    url, stem = FILES[name]
    out = out_dir()
    out.mkdir(parents=True, exist_ok=True)
    if "{version}" not in stem and (out / stem).exists() and not force:
        print(f"  {stem} exists, skipped")
        return str(out / stem)
    r = requests.get(url, headers=UA, timeout=300)
    r.raise_for_status()
    if "{version}" in stem:
        stem = stem.format(version=dea_version(r.content))
        if (out / stem).exists() and not force:
            print(f"  {stem} exists, skipped")
            return str(out / stem)
    (out / stem).write_bytes(r.content)
    print(f"  {name}: {len(r.content) / 1e6:.1f} MB -> {out / stem}")
    return str(out / stem)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("names", nargs="*", default=[*FILES, "atb"], help=f"files to pull (default: {', '.join(FILES)}, atb)")
    ap.add_argument("--force", action="store_true", help="pull again even if the file exists")
    a = ap.parse_args(argv)
    for n in a.names:
        if n == "atb":
            for edition in ATB_EDITIONS:
                pull_atb(edition, a.force)
        else:
            pull(n, a.force)
    return 0


if __name__ == "__main__":
    sys.exit(main())
