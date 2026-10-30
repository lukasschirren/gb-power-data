"""Pull ENTSO-E / ENTSOG TYNDP 2024 scenario files -> raw/tyndp/.

WHY. A projection of GB's market into the 2030s needs its neighbours' own future systems, not their observed
prices moved by gas: with far more wind and solar, continental surplus hours take their prices to zero and GB can
no longer export its own surplus at a positive price. The TYNDP 2024 market model (ENTSO-E's PLEXOS runs of the
National Trends+ scenario) publishes the hourly marginal cost of every market node in 2030
(`build.tyndp_hourly` keeps GB's neighbours).

FILES (https://2024.entsos-tyndp-scenarios.eu/download/, licence CC BY 4.0 as Open-TYNDP records it):
  MMStandardOutputFile_NT2030_Plexos_CY2009_2.5_v40.xlsx   NT+ 2030 market model results, climate year 2009 (the one
                                                          climate year published for 2030): sheet "Hourly Market
                                                          Data", 55 columns per node (generation by technology,
                                                          demand, balance, dumped energy, energy not served, marginal
                                                          cost in EUR/MWh), 8,736 hours
  MMStandardOutputFile_Readme.docx                        what the columns are
  Prices.zip                                              the commodity prices the runs assume ("2023 06 22 TYNDP 2024
                                                          Commodity prices Final.xlsx"; 2021 EUR: NT+ 2030 gas blend
                                                          7.5 EUR/GJ, CO2 113.4 EUR/t)
Each is saved as downloaded, the zips beside the extracted workbooks; a file on disk is not pulled again.
Ported on 30 Oct 2026 from the research repository's gbabm.pull.tyndp_pull.

RUN    python -m gbpowerdata.pull.tyndp_pull
"""
from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

import requests

from gbpowerdata import config as cfg

BASE = "https://2024-data.entsos-tyndp-scenarios.eu/files"
FILES = {
    "MMStandardOutputFile_NT2030_Plexos_CY2009_2.5_v40.xlsx.zip":
        f"{BASE}/scenarios-outputs/MMStandardOutputFile_NT2030_Plexos_CY2009_2.5_v40.xlsx.zip",
    "MMStandardOutputFile_Readme.docx": f"{BASE}/scenarios-outputs/MMStandardOutputFile_Readme.docx",
    "Prices.zip": f"{BASE}/scenarios-inputs/Prices.zip",
}


def out_dir() -> Path:
    return cfg.raw_dir() / "tyndp"


def pull() -> None:
    """Download each file that is not on disk and extract the zips beside themselves."""
    d = out_dir()
    d.mkdir(parents=True, exist_ok=True)
    for name, url in FILES.items():
        p = d / name
        if not p.exists():
            r = requests.get(url, timeout=600)
            r.raise_for_status()
            part = p.with_suffix(p.suffix + "_part")
            part.write_bytes(r.content)
            part.replace(p)
            print(f"  {name}: {len(r.content) / 1e6:.1f} MB")
        if p.suffix == ".zip":
            with zipfile.ZipFile(p) as z:
                for m in z.namelist():
                    if m.startswith("__MACOSX") or m.endswith("/"):
                        continue
                    target = d / m.split("/")[-1]
                    if not target.exists():
                        target.write_bytes(z.read(m))
                        print(f"  extracted {target.name}")


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args(argv)
    pull()
    return 0


if __name__ == "__main__":
    sys.exit(main())
