"""Pull the JRC Open Power Plants Database (JRC-PPDB-OPEN v1.00), the source of each GB thermal unit's efficiency.

The European Commission's Joint Research Centre publishes, for every generating unit of the ENTSO-E area, its EIC
codes, type, capacity and commissioning year (JRC_OPEN_UNITS.csv) and its operating parameters (JRC_OPEN_PERFORMANCE.csv),
among them the net electrical efficiency `eff` with `best_source`: OEM_derived (the manufacturer's rating of the
unit's model), emissions_*_derived (verified emissions and output) or Class_derived (a typical value of its class).
Version 1.00, 13 Dec 2019, Zenodo record 3574566 (https://zenodo.org/records/3574566), CC BY 4.0 ("JRC Open Power
Plants Database (JRC-PPDB-OPEN)", European Commission, Joint Research Centre). gbpowerdata.build.thermal_unit_efficiency
turns its GB rows into data/reference/thermal_unit_efficiency.csv, which stage 3 joins to the BM units by EIC.

PINNED. The archive is checked against the md5 Zenodo publishes for it; a changed upstream file writes nothing.

Usage:  python -m gbpowerdata.pull.jrc_ppdb_pull
Output: data/raw/jrc_ppdb/JRC-PPDB-OPEN.ver1.0.zip
"""

from __future__ import annotations

import argparse
import hashlib
import sys

import requests

from gbpowerdata import config as cfg

RECORD = 3574566
FILE = "JRC-PPDB-OPEN.ver1.0.zip"
PINNED_MD5 = "a89c15290a6e1f76273e33f302666a84"
URL = f"https://zenodo.org/api/records/{RECORD}/files/{FILE}/content"


def out_path():
    return cfg.raw_dir() / "jrc_ppdb" / FILE


def pull() -> None:
    r = requests.get(URL, timeout=300)
    r.raise_for_status()
    digest = hashlib.md5(r.content).hexdigest()
    if digest != PINNED_MD5:
        sys.exit(f"{FILE}: md5 {digest} differs from Zenodo's {PINNED_MD5}; nothing written")
    out = out_path()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(r.content)
    print(f"JRC-PPDB-OPEN v1.00: {len(r.content) / 1e6:.1f} MB -> {out} (md5 verified)")


def main(argv: list[str]) -> None:
    argparse.ArgumentParser(description=__doc__.split("\n")[0]).parse_args(argv)
    pull()


if __name__ == "__main__":
    main(sys.argv[1:])
