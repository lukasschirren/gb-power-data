"""Pull the powerplantmatching plant roster (the stage-1 input `data/raw/powerplants.csv`).

powerplantmatching (PyPSA, https://github.com/PyPSA/powerplantmatching) merges the European plant
databases (ENTSO-E, OPSD, GEM, JRC, GPD, ...) into one roster with capacity, fuel, technology,
commissioning and retirement dates and coordinates; `gbpowerdata.build.stage1_tag_plants` keeps
its GB rows. Each release publishes its merged output as `powerplants.csv` at the release tag, under
CC BY 4.0.

PINNED. The roster changes between releases (v0.8.1 is 21.9 MB, v0.9.0 23.5 MB), and stage 1
and everything downstream (powerplants_tagged/located, agents) follow it, so the default pull is
the exact release the published tables were built from, checked against its sha256. The file in
use since May 2026 is byte-identical to the v0.8.1 release file (verified 5 Oct 2026).
`--version vX.Y.Z` pulls another release for a deliberate update; its checksum is then reported,
not enforced, and the processed tables will change.

Usage:
  python -m gbpowerdata.pull.ppm_pull                     # pinned v0.8.1, checksum-verified
  python -m gbpowerdata.pull.ppm_pull --version v0.9.0    # a deliberate update
Output:
  data/raw/<stage1.powerplants in config.yaml>  (powerplants.csv)
"""

from __future__ import annotations

import argparse
import hashlib
import sys

import requests

from gbpowerdata import config as cfg

PINNED_VERSION = "v0.8.1"
PINNED_SHA256 = "0bb395b298bdcbcb29526df20f2a97f3c3dde0768af6f754ff66ed26ad8ed703"
URL = "https://raw.githubusercontent.com/PyPSA/powerplantmatching/{version}/powerplants.csv"


def pull(version: str = PINNED_VERSION) -> None:
    out = cfg.raw_dir() / cfg.load_config()["stage1"]["powerplants"]
    r = requests.get(URL.format(version=version), timeout=300)
    r.raise_for_status()
    digest = hashlib.sha256(r.content).hexdigest()
    if version == PINNED_VERSION and digest != PINNED_SHA256:
        sys.exit(f"{version}: checksum {digest[:12]}... differs from the pinned {PINNED_SHA256[:12]}...; "
                 "the release file has changed upstream, nothing written")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(r.content)
    note = "checksum verified" if version == PINNED_VERSION else f"sha256 {digest} (not the pinned release)"
    print(f"powerplantmatching {version}: {len(r.content)/1e6:.1f} MB -> {out} ({note})")


def main(argv: list[str]) -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--version", default=PINNED_VERSION, help=f"release tag (default {PINNED_VERSION})")
    pull(p.parse_args(argv).version)


if __name__ == "__main__":
    main(sys.argv[1:])
