"""Pull DESNZ's list of power stations in the United Kingdom (DUKES table 5.11) into data/raw/dukes/.

Why: the ownership tables (gbpowerdata.build.build_ownership) need who owned each major power station in each
year. DUKES 5.11 lists every station of the major power producers with its company, technology, fuel, installed
capacity and location; the workbook keeps one sheet per past edition ("DUKES 2004" ... "DUKES 2025", each the
fleet at the end of the year before), so one download gives the owners of 2003-2024 and the newest edition
("5.11 Full list") those of the latest year.

What "company" means (the workbook's notes): the company that returned DESNZ's survey of major power producers
for the station, mostly the owning group; joint ventures are named as such ("Co-owned by SSE Group and Cheung
Kong Infrastructure Ltd"). Only major power producers are listed (note 1), so small and most embedded stations
and every battery are missing (the edition of May 2026 counts 28.8 GW of other generators that it does not list).

Source: gov.uk, "Digest of UK Energy Statistics (DUKES): electricity" (chapter 5), found through the gov.uk
content API, which lists the page's attachments with their current URLs; the attachment whose title ends
"(DUKES 5.11)" is downloaded. Open Government Licence v3.0.

Output (one file per edition, never overwritten): data/raw/dukes/DUKES_5.11_{edition}.xlsx, the edition being
the year in the attachment's title ("Power stations in the United Kingdom, May 2026").

Usage:
  python -m gbpowerdata.pull.dukes_pull
  python -m gbpowerdata.pull.dukes_pull --list       # the chapter's attachments
"""
from __future__ import annotations

import argparse
import re
import sys

import requests

from gbpowerdata import config as cfg

PAGE = "https://www.gov.uk/api/content/government/statistics/electricity-chapter-5-digest-of-united-kingdom-energy-statistics-dukes"
TABLE = "(DUKES 5.11)"


def out_dir():
    return cfg.raw_dir() / "dukes"


def attachments() -> tuple[list[dict], str]:
    """The chapter page's attachments and the page's last update (ISO date)."""
    r = requests.get(PAGE, timeout=60)
    r.raise_for_status()
    page = r.json()
    return page.get("details", {}).get("attachments", []), str(page.get("public_updated_at", ""))


def edition_of(title: str, updated: str) -> str:
    """The edition's year: the year in the attachment's title, else the year the page was last updated."""
    m = re.search(r"\b(20\d\d)\b", title)
    return m.group(1) if m else updated[:4]


def pull() -> str:
    files, updated = attachments()
    hits = [a for a in files if TABLE in str(a.get("title", "")) and str(a.get("url", "")).endswith(".xlsx")]
    if len(hits) != 1:
        raise RuntimeError(f"dukes_pull: expected one {TABLE} workbook on {PAGE}, found {len(hits)}")
    title, url = hits[0]["title"], hits[0]["url"]
    out = out_dir()
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"DUKES_5.11_{edition_of(title, updated)}.xlsx"
    if path.exists():
        print(f"  {path.name} exists (raw snapshots are immutable), skipped")
        return str(path)
    r = requests.get(url, timeout=300)
    r.raise_for_status()
    path.write_bytes(r.content)
    print(f"  {title}: {len(r.content) / 1e6:.1f} MB -> {path}")
    return str(path)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--list", action="store_true", help="list the chapter's attachments and exit")
    a = ap.parse_args(argv)
    if a.list:
        files, updated = attachments()
        print(f"page updated {updated}")
        for f in files:
            print(f"  {f.get('title')}\n    {f.get('url')}")
        return 0
    pull()
    return 0


if __name__ == "__main__":
    sys.exit(main())
