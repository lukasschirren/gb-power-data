"""Pull DESNZ's electricity tables into data/raw/dukes/: the list of power stations in the United Kingdom (DUKES table
5.11), electricity fuel use, generation and supply by fuel (DUKES 5.6), and generation by fuel in each country of
the UK (Energy Trends special feature article, data tables).

5.11 (ownership). The ownership tables (gbpowerdata.build.build_ownership) need who owned each major power station
in each year. DUKES 5.11 lists every station of the major power producers with its company, technology, fuel,
installed capacity and location; the workbook keeps one sheet per past edition ("DUKES 2004" ... "DUKES 2025", each
the fleet at the end of the year before), so one download gives the owners of 2003-2024 and the newest edition
("5.11 Full list") those of the latest year.
What "company" means (the workbook's notes): the company that returned DESNZ's survey of major power producers
for the station, mostly the owning group; joint ventures are named as such ("Co-owned by SSE Group and Cheung
Kong Infrastructure Ltd"). Only major power producers are listed (note 1), so small and most embedded stations
and every battery are missing (the edition of May 2026 counts 28.8 GW of other generators that it does not list).

5.6 (generation by fuel). The UK's fuel used, electricity generated, used on works and supplied, by fuel (coal, oil,
gas, nuclear, hydro, wind, solar, thermal renewables, other fuels, storage) for the major power producers, the other
generators (autogenerators and small, mostly embedded plant: the gas CHP Elexon does not meter is here) and all
generating companies, yearly from 1996 (sheet "5.6": tables 5.6.A to 5.6.G stacked; the July edition adds the year
before). gbpowerdata.build.generation_by_fuel reads it.

Regional (generation by country). "Electricity generation and supply in Scotland, Wales, Northern Ireland and
England", Energy Trends' December special feature article, whose data tables give generation by fuel and generator
type for the UK and each country, yearly from 2004 (sheet "Electricity generation by fuel", Table 2a), so Great
Britain is the UK less Northern Ireland. Its page moves each December: REGIONAL_PAGE names the edition to pull
(Dec 2025: 2004 to 2024).

Source: gov.uk, "Digest of UK Energy Statistics (DUKES): electricity" (chapter 5) and the Energy Trends article,
found through the gov.uk content API, which lists a page's attachments with their current URLs. Open Government
Licence v3.0.

Output (one file per edition, never overwritten): data/raw/dukes/DUKES_5.11_{edition}.xlsx and
DUKES_5.6_{edition}.xlsx, the edition being the year in the attachment's title ("Power stations in the United
Kingdom, May 2026"), else the year the chapter page was last updated; regional_generation_{last year}.xlsx.

Usage:
  python -m gbpowerdata.pull.dukes_pull                        # 5.11, 5.6 and the regional tables
  python -m gbpowerdata.pull.dukes_pull 5.6 regional           # some of them
  python -m gbpowerdata.pull.dukes_pull --list                 # the chapter's attachments
"""
from __future__ import annotations

import argparse
import re
import sys

import requests

from gbpowerdata import config as cfg

API = "https://www.gov.uk/api/content"
PAGE = f"{API}/government/statistics/electricity-chapter-5-digest-of-united-kingdom-energy-statistics-dukes"
TABLES = {"5.11": "(DUKES 5.11)", "5.6": "(DUKES 5.6)"}
TABLE = TABLES["5.11"]
REGIONAL_PAGE = (f"{API}/government/statistics/energy-trends-december-2025-special-feature-article-electricity-"
                 "generation-and-supply-in-scotland-wales-northern-ireland-and-england-2020-to-20")
REGIONAL_TITLE = "data tables"


def out_dir():
    return cfg.raw_dir() / "dukes"


def attachments(page: str = PAGE) -> tuple[list[dict], str]:
    """A page's attachments and the page's last update (ISO date)."""
    r = requests.get(page, timeout=60)
    r.raise_for_status()
    p = r.json()
    return p.get("details", {}).get("attachments", []), str(p.get("public_updated_at", ""))


def edition_of(title: str, updated: str) -> str:
    """The edition's year: the year in the attachment's title, else the year the page was last updated."""
    m = re.search(r"\b(20\d\d)\b", title)
    return m.group(1) if m else updated[:4]


def _save(url: str, path, title: str) -> str:
    if path.exists():
        print(f"  {path.name} exists (raw snapshots are immutable), skipped")
        return str(path)
    r = requests.get(url, timeout=300)
    r.raise_for_status()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(r.content)
    print(f"  {title}: {len(r.content) / 1e6:.1f} MB -> {path}")
    return str(path)


def pull(table: str = "5.11") -> str:
    """One DUKES chapter 5 table, by its number (TABLES)."""
    files, updated = attachments()
    tag = TABLES[table]
    hits = [a for a in files if tag in str(a.get("title", "")) and str(a.get("url", "")).endswith(".xlsx")]
    if len(hits) != 1:
        raise RuntimeError(f"dukes_pull: expected one {tag} workbook on {PAGE}, found {len(hits)}")
    title, url = hits[0]["title"], hits[0]["url"]
    return _save(url, out_dir() / f"DUKES_{table}_{edition_of(title, updated)}.xlsx", title)


def pull_regional() -> str:
    """The data tables of the Energy Trends article on generation by country (REGIONAL_PAGE)."""
    files, _ = attachments(REGIONAL_PAGE)
    hits = [a for a in files if str(a.get("title", "")).endswith(REGIONAL_TITLE)
            and str(a.get("url", "")).endswith(".xlsx")]
    if len(hits) != 1:
        raise RuntimeError(f"dukes_pull: expected one '{REGIONAL_TITLE}' workbook on {REGIONAL_PAGE}, found {len(hits)}")
    title, url = hits[0]["title"], hits[0]["url"]
    years = re.findall(r"\b(20\d\d)\b", title)               # "... 2004 to 2024 - data tables"
    return _save(url, out_dir() / f"regional_generation_{years[-1]}.xlsx", title)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("what", nargs="*", help=f"tables to pull, of {[*TABLES, 'regional']} (default: all)")
    ap.add_argument("--list", action="store_true", help="list the chapter's attachments and exit")
    a = ap.parse_args(argv)
    unknown = set(a.what) - {*TABLES, "regional"}
    if unknown:
        ap.error(f"unknown table(s) {sorted(unknown)}")
    if a.list:
        files, updated = attachments()
        print(f"page updated {updated}")
        for f in files:
            print(f"  {f.get('title')}\n    {f.get('url')}")
        return 0
    for what in a.what or [*TABLES, "regional"]:
        pull_regional() if what == "regional" else pull(what)
    return 0


if __name__ == "__main__":
    sys.exit(main())
