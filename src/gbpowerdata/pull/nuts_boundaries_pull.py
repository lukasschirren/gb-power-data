"""Pull Eurostat NUTS-2 region boundaries (GISCO distribution service).

The PECD reader (`gbpowerdata.pull.pecd_pull`) delivers onshore wind/solar/temperature already
aggregated to NUTS-2 by the CDS server, but re-expressing that at the ABM's own `gsp_group`
zones (`gbpowerdata.common.gsp`) needs NUTS-2 polygons to overlay against the existing GSP-group
polygons (`gbpowerdata.common.pecd_regions.build_nuts2_gsp_group_weights`). This is the one-off,
free, no-auth GIS-boundary download that supports that overlay — same role as the NESO GSP/DNO
boundary downloads `gsp.py`'s docstring describes, just a different publisher.

Source: Eurostat GISCO statistical-unit distribution service, NUTS 2021 edition, 1:20 million
generalisation (fine enough for an area-weight overlay; GISCO also serves 1:1/1:3/1:10 million
if a sharper boundary is ever needed), EPSG:4326, NUTS level 2:
  https://gisco-services.ec.europa.eu/distribution/v2/nuts/geojson/NUTS_RG_20M_2021_4326_LEVL_2.geojson

No API key. If GISCO's URL layout has changed since this was written, the fetch fails loudly
(HTTP error, not a silent empty file) with the manual fallback: download the same product from
the GISCO NUTS viewer (https://ec.europa.eu/eurostat/web/gisco/geodata/statistical-units/territorial-units-statistics)
and place it at the OUT path below by hand.

Usage:
  python -m gbpowerdata.pull.nuts_boundaries_pull
Output:
  data/raw/gis/nuts2_boundaries_2021.geojson
"""

from __future__ import annotations

import sys

import requests

from gbpowerdata import config as cfg

GISCO_URL = ("https://gisco-services.ec.europa.eu/distribution/v2/nuts/geojson/"
             "NUTS_RG_20M_2021_4326_LEVL_2.geojson")
NUTS_YEAR = 2021
OUT = cfg.raw_dir() / "gis" / f"nuts2_boundaries_{NUTS_YEAR}.geojson"


def main() -> None:
    if OUT.exists():
        print(f"  skip {OUT.name} (exists)")
        return
    OUT.parent.mkdir(parents=True, exist_ok=True)
    try:
        r = requests.get(GISCO_URL, timeout=120)
        r.raise_for_status()
    except requests.exceptions.RequestException as e:
        sys.exit(f"GISCO fetch failed ({type(e).__name__}: {e}). Manual fallback: download the "
                  f"NUTS {NUTS_YEAR} level-2 GeoJSON from the GISCO statistical-units viewer and "
                  f"save it to {OUT}")
    OUT.write_bytes(r.content)
    print(f"Saved {OUT} ({len(r.content):,} bytes)")


if __name__ == "__main__":
    sys.exit(main())
