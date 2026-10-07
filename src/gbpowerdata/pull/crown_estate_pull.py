"""Pull The Crown Estate's table of offshore wind farm ownership into data/raw/crown_estate/.

Why: data/reference/company_owners.csv holds the owners, shares and operator of every offshore wind joint venture
over time, and its offshore rows rest largely on The Crown Estate's tables (sources ce-2018 ... ce-2024 in
data/reference/ownership_sources.csv). The Crown Estate leases the seabed and publishes, once a year, who holds what
share of every operational and under-construction offshore wind farm in the UK at the end of the year before. This
puller keeps each year's table, so that gbpowerdata.build.build_crown_estate can check company_owners.csv against
all of them in code rather than by hand.

Source: The Crown Estate, "Offshore wind farm ownership",
https://www.thecrownestate.co.uk/our-business/marine/wind-farm-ownership: one web page, headed "UK operational and
under construction wind farm ownership as at 31 December <year>", with two tables:
  "Fully operational projects | Operator | Share ownership %"
  "Under construction projects* | Lead developer | Share ownership %"  (* under construction, not yet fully operational)
whose share cell lists the holders: "40% SSE; 25% SDIC Power Holdings; 17.5% Equitix; 17.5% TRIG (The Renewables
Infrastructure Group)". The page is replaced when the table is updated, so earlier years' tables survive only in the
Internet Archive's captures of the page (ARCHIVED, pulled with --archived) and, for the ends of 2018-2020, in The
Crown Estate's offshore wind operational reports (PDF; transcribed by hand into
data/reference/crown_estate_ownership_reports.csv, a local file that is never published, which the build reads where
it exists). The reports draw each farm's holders as a bar, and the transcription keeps two names for each: holder,
the holder's full name without its footnote marker, completed from the table's footnote where the bar cuts the name
short or prints only a share and a marker; and holder_printed, the label exactly as printed, with the marker as plain
digits straight after it ("Marubeni...3", "DBJ2", "10.0%10"), kept to check the transcription. The build does not
read holder_printed.

Terms: The Crown Estate's terms of use (https://www.thecrownestate.co.uk/about-us/terms-of-use, read 6 Oct 2026)
make the site's material its copyright, to be downloaded or copied for personal use, reproduced accurately and not
in a misleading context, neither altered nor sold, with the copyright owner acknowledged where re-published; the
licence for information downloaded from the site is for the licensee's own use, and digital copies must not be
provided to third parties. So the snapshots, and the table the build parses from them, stay on the machine that
pulled them: data/raw/ and data/processed/ are not in git, and neither file is in a data pack
(gbpowerdata.datapack). What this repository uses and publishes are facts, which company held what share of a farm
on a date, each cited to The Crown Estate in data/reference/ownership_sources.csv.

Personal data: none. The page names companies; its only contact details are The Crown Estate's own general
enquiries address and switchboard number.

Gotchas:
  - The as-at date is in the page's heading, not in its URL, and names the snapshot, so a pull before the next
    update finds its file and skips it. If the table downloaded differs from the file of the same as-at date (a
    correction without a new date), the pull says so and keeps the file it has.
  - as_at_of() reads every "ownership as at <day> <month> <year>" in the text a reader sees, leaving out scripts,
    styles and the page's head (both the end-2023 and the end-2024 pages repeat their heading in a script's data),
    and refuses a page whose dates disagree. A page without one (an error page served in place of the table) is not
    a snapshot.
  - The layout changed between versions: the end-2023 page puts the column names in the tables' header row, the
    end-2024 page an empty header row first and the names in the first body row. parse() takes the row whose first
    cell names a section ("... operational projects", "... construction projects") as the header, in either. A
    body row with fewer cells than that header (a cell spanning two rows), with cells but no farm name, whose share
    cell names no holder, or with a holder that starts with a digit (a share written with a decimal comma, "24,95%
    X", reads as 95% of "24, X", and two such shares can still add up to 100: "75,05% A; 24,95% B"; written after
    the name, "A 75,05%", it leaves "75," before the share) stops the parse ("has the layout changed?") rather than
    losing the row; an empty row is skipped. Once every row is read, a farm (of one section) whose shares are all
    given but add up to more than SHARE_SUM_PP (0.5) points away from 100 stops it too, so does a farm listed in two
    rows of one section; a farm with a holder without a share is not summed.
  - Holders are separated by ";", or by a line break where the next line starts with a percentage ("60% Ørsted",
    new line, "40% GIG Renewable Energy Fund"); any other line break is a name carried onto the next line ("25% SDIC
    Power", new line, "Holdings") and is joined with a space. A holder without a percentage is kept, with share_pct
    NaN; a percentage without a holder, or two in one holder, stops the parse.
  - Farm names change between years ("Hywind Scotland", "Hywind Scotland (Buchan Deep)"), and holders are named as
    the page names them: a fund, its manager, or a vehicle of several owners ("Diamond Green Ltd", "Equitix and
    TRIG"). Matching them to company_owners.csv is the build's job (data/reference/crown_estate_farms.csv,
    build_crown_estate.HOLDER_GROUPS).
  - Text is cleaned: footnote stars are dropped, non-breaking and other unusual spaces become plain ones, and UTF-8
    read as Windows-1252, as in copies saved with the wrong encoding ("Ã˜rsted" for "Ørsted"), is repaired. Each
    lead character takes as many continuation characters as its byte says (one after C2-DF, two after E0-EF, three
    after F0-F4), so a correct character that follows ("Ã˜" then a no-break space) is not swallowed. A repair is
    made only where it gives a character a Western page holds: U+0080-U+024F (Latin-1 and Latin Extended) from two
    bytes; U+2000-U+20CF (punctuation, super- and subscripts, currency signs) or U+2100-U+214F (letterlike symbols,
    such as ™) from three; any character from four. Genuine text that only looks like mojibake ("CAFÉ”", whose last
    two characters would give "ɔ"; "café’”", whose last three would give a Chinese character) is left as it is, as
    is a sequence that does not decode as UTF-8.
  - The archived captures are fetched in the Internet Archive's raw form ("<timestamp>id_/<url>"): the page as The
    Crown Estate served it, without the archive's toolbar.
  - A URL that cannot be pulled (the download fails after its retries, or the page has no as-at heading) is
    reported with a WARNING naming it and skipped, and the other URLs are still pulled. pull() returns the snapshots
    it obtained and raises only when it obtained none (so a caller that pulls the live page alone, such as
    scripts/snapshot_registers.py, sees the failure); the command exits 1 if any URL failed.

Output (one file per as-at date, never overwritten): data/raw/crown_estate/wind_farm_ownership_{YYYYMMDD}.html, the
page byte for byte as served. table() parses every snapshot: one row per as_at, farm and holder, with columns
as_at, section ("operational" or "under_construction"), farm, operator (the lead developer for a farm under
construction), holder, share_pct, and source (the snapshot's file name).

Usage:
  python -m gbpowerdata.pull.crown_estate_pull               # the live page
  python -m gbpowerdata.pull.crown_estate_pull --archived    # and the archived captures of earlier years
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from html.parser import HTMLParser
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from gbpowerdata import config as cfg

PAGE = "https://www.thecrownestate.co.uk/our-business/marine/wind-farm-ownership"
WAYBACK = "https://web.archive.org/web"
# Internet Archive captures of PAGE, one per as-at date (the archive's index of the page, read 6 Oct 2026: its
# captures of 21 Jun 2024 to 27 Mar 2025 hold the end-2023 table, those of 11 Mar and 8 Apr 2026 the end-2024 table)
ARCHIVED = {
    "20240621132923": "as at 31 December 2023 (ownership_sources.csv: ce-2023)",
    "20260408080732": "as at 31 December 2024, the live page's table on 6 Oct 2026, kept for when the page moves on",
}
UA = {"User-Agent": "Mozilla/5.0 (research data pull)"}
FILE_PATTERN = "wind_farm_ownership_*.html"
COLUMNS = ["as_at", "section", "farm", "operator", "holder", "share_pct"]

_AS_AT = re.compile(r"ownership\s+as\s+at\s+(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", re.I)
_AS_AT_ANY = re.compile(r"\bas\s+at\s+(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", re.I)
_SECTION = re.compile(r"(operational|construction)\s+projects", re.I)
_PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_LEADING_PERCENT = re.compile(r"\d+(?:\.\d+)?\s*%")          # used with match(): a line that starts with a share
# every kind of space a web page uses beyond \s: no-break, the typographic spaces U+2000-U+200B, narrow no-break,
# medium mathematical and ideographic space, and the byte-order mark
_SPACE_CHARS = "".join(map(chr, (0xA0, *range(0x2000, 0x200C), 0x202F, 0x205F, 0x3000, 0xFEFF)))
_SPACES = re.compile(rf"[\s{_SPACE_CHARS}]+")
# UTF-8 read as Windows-1252 (or Latin-1): a lead byte shows as the Latin-1 letter of its code, each continuation byte
# (0x80-0xBF) as the character Windows-1252 gives it (Latin-1's where Windows-1252 has none). The lead byte says how
# many continuation bytes follow: one after C2-DF, two after E0-EF, three after F0-F4.
_SHOWN = {chr(b) for b in range(0x80, 0xC0)} | {bytes([b]).decode("cp1252", errors="ignore") for b in range(0x80, 0xC0)}
_CONTINUATION = f"[{re.escape(''.join(sorted(_SHOWN - {''})))}]"
_MOJIBAKE = re.compile(f"[{chr(0xC2)}-{chr(0xDF)}]{_CONTINUATION}"
                       f"|[{chr(0xE0)}-{chr(0xEF)}]{_CONTINUATION}{{2}}"
                       f"|[{chr(0xF0)}-{chr(0xF4)}]{_CONTINUATION}{{3}}")
# The characters a repair may give, by the length of the sequence: those a Western page holds. Genuine text can look
# like mojibake (the "É”" that ends "CAFÉ”" shows the bytes C9 94, which decode to U+0254), and what it would decode
# to is then a character no such page holds. Two bytes: Latin-1 and Latin Extended-A and -B. Three: general
# punctuation, super- and subscripts and currency signs, then letterlike symbols (™). Four bytes are not limited.
_PLAUSIBLE = {2: ((0x0080, 0x024F),), 3: ((0x2000, 0x20CF), (0x2100, 0x214F))}
# How far the shares of one share cell, all given, may add up from 100 (in percentage points): The Crown Estate
# rounds shares (its end-2019 report prints Race Bank as 50 + 25 + 12.5 + 6.3 + 6.3 = 100.1)
SHARE_SUM_PP = 0.5
_DIGIT = re.compile(r"\d")


def out_dir() -> Path:
    return cfg.raw_dir() / "crown_estate"


def archived_url(stamp: str) -> str:
    """The raw form of an Internet Archive capture of PAGE (the page as served, without the archive's toolbar)."""
    return f"{WAYBACK}/{stamp}id_/{PAGE}"


def download(url: str, tries: int = 4) -> bytes:
    for i in range(tries):
        try:
            r = requests.get(url, headers=UA, timeout=120)
            r.raise_for_status()
            return r.content
        except (requests.ConnectionError, requests.Timeout, requests.HTTPError):
            if i == tries - 1:
                raise
            time.sleep(2 ** (i + 1))       # the Internet Archive answers 503 under load; it passes
    return b""


def decode(data: bytes) -> str:
    """The page's text: UTF-8 (what the site declares), else Windows-1252."""
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


# ---------------------------------------------------------------------------- text
def _byte(c: str) -> int:
    """The byte a character of mojibake shows: its Windows-1252 code, else (the five bytes Windows-1252 leaves
    undefined, shown as Latin-1's control characters) its Latin-1 one."""
    try:
        return c.encode("cp1252")[0]
    except UnicodeEncodeError:
        return ord(c)


def _unmangle(m: re.Match) -> str:
    """The character a run of mojibake stands for; the run as it is where its bytes are not UTF-8, or decode to a
    character a Western page does not hold (_PLAUSIBLE), for then the run is genuine text."""
    s = m.group(0)
    try:
        c = bytes(_byte(ch) for ch in s).decode("utf-8")
    except UnicodeDecodeError:          # not UTF-8 after all (an overlong form, a surrogate): left as it is
        return s
    ranges = _PLAUSIBLE.get(len(s))     # one character per byte; a sequence that decodes is one character
    if ranges is not None and not any(lo <= ord(c) <= hi for lo, hi in ranges):
        return s
    return c


def clean(text) -> str:
    """A cell's text: mojibake repaired, footnote stars dropped, every kind of space one plain space."""
    s = "" if text is None or (isinstance(text, float) and np.isnan(text)) else str(text)
    s = _MOJIBAKE.sub(_unmangle, s)
    return _SPACES.sub(" ", s.replace("*", " ")).strip()


class _Text(HTMLParser):
    """The text a reader of the page sees: without scripts, styles, templates and the head (title and metadata),
    which can carry other dates. The head ends at </head>, at <body>, or at the first tag a head cannot hold, as in
    a browser. Every tag counts as a space, so words in neighbouring elements stay apart."""

    SKIP = ("script", "style", "template", "title")
    HEAD = ("head", "title", "meta", "link", "style", "script", "base", "noscript", "template")

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0
        self._head = False

    def handle_starttag(self, tag, attrs):
        if tag == "head":
            self._head = True
        elif self._head and (tag == "body" or tag not in self.HEAD):
            self._head = False
        if tag in self.SKIP:
            self._skip += 1
        self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag == "head":
            self._head = False
        elif tag in self.SKIP:
            self._skip = max(0, self._skip - 1)
        self.parts.append(" ")

    def handle_data(self, data):
        if not self._skip and not self._head:
            self.parts.append(data)


def page_text(html: str) -> str:
    """The page's visible text (see _Text), its spaces made plain."""
    parser = _Text()
    parser.feed(html)
    parser.close()
    return _SPACES.sub(" ", "".join(parser.parts)).strip()


def as_at_of(html: str) -> pd.Timestamp:
    """The table's date from the page's heading ("... ownership as at 31 December 2024"): every "ownership as at
    <date>" in the page's text (else every "as at <date>"), which must agree."""
    text = page_text(html)
    found = _AS_AT.findall(text) or _AS_AT_ANY.findall(text)
    if not found:
        raise ValueError("crown_estate_pull: no 'as at <day> <month> <year>' on the page; has its layout changed?")
    try:
        dates = {pd.to_datetime(f"{d} {m} {y}", format="%d %B %Y") for d, m, y in found}
    except ValueError as e:
        raise ValueError(f"crown_estate_pull: an as-at date that is no date ({e}); has the layout changed?") from e
    if len(dates) > 1:
        named = ", ".join(f"{d:%d %B %Y}" for d in sorted(dates))
        raise ValueError(f"crown_estate_pull: the page names several as-at dates ({named}); has its layout changed?")
    return dates.pop()


def split_shares(cell: str) -> list[tuple[str, float]]:
    """A share cell as (holder, share in %) pairs, each holder with its percentage ("17.5% Equitix"); a holder
    without one gets NaN. Holders are separated by ";", or by a line break where the next line starts with a
    percentage; any other line break is a name carried onto the next line, joined with a space."""
    out = []
    for chunk in str(cell).split(";"):
        parts: list[str] = []
        for line in chunk.split("\n"):
            line = clean(line)
            if not line:
                continue
            if parts and not _LEADING_PERCENT.match(line):
                parts[-1] += " " + line          # the name goes on: "25% SDIC Power" / "Holdings"
            else:
                parts.append(line)
        for part in parts:
            found = _PERCENT.findall(part)
            if len(found) > 1:
                raise ValueError(f"crown_estate_pull: several percentages in one holder, {part!r}: "
                                 "has the format changed?")
            m = _PERCENT.search(part)
            if m and re.search(r"\d,\s*$", part[:m.start()]):     # "Foo 75,05%": a decimal comma before the share
                raise ValueError(f"crown_estate_pull: a share with a decimal comma, {part!r}: has the format changed?")
            holder = clean(part[:m.start()] + " " + part[m.end():]) if m else part
            if not holder:
                raise ValueError(f"crown_estate_pull: a share without a holder, {part!r}: has the format changed?")
            out.append((holder, float(m[1]) if m else np.nan))
    return out


# ---------------------------------------------------------------------------- tables
class _Tables(HTMLParser):
    """Every <table> as rows of cell texts. A <br>, <p>, <li> or <div> inside a cell starts a new line, so holders
    set one per line still split."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.tables.append([])
        elif tag == "tr" and self.tables:
            self._end_row()
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._end_cell()
            self._cell = []
        elif tag in ("br", "p", "li", "div") and self._cell is not None:
            self._cell.append("\n")

    def handle_endtag(self, tag):
        if tag in ("td", "th"):
            self._end_cell()
        elif tag == "tr":
            self._end_row()
        elif tag == "table":
            self._end_row()

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)

    def _end_cell(self):
        if self._cell is not None and self._row is not None:
            self._row.append("".join(self._cell))
        self._cell = None

    def _end_row(self):
        self._end_cell()
        if self._row is not None and self.tables:
            self.tables[-1].append(self._row)
        self._row = None


def tables_of(html: str) -> list[list[list[str]]]:
    parser = _Tables()
    parser.feed(html)
    parser.close()
    return parser.tables


def _columns(header: list[str]) -> tuple[str, int, int]:
    """(section, operator column, share column) of a header row."""
    names = [clean(c).lower() for c in header]
    section = "under_construction" if "construction" in names[0] else "operational"
    share = next((i for i, n in enumerate(names) if "share" in n), None)
    operator = next((i for i, n in enumerate(names) if "operator" in n or "developer" in n), None)
    if share is None or operator is None:
        raise ValueError(f"crown_estate_pull: unexpected columns {names}: has the layout changed?")
    return section, operator, share


def parse(html: str) -> pd.DataFrame:
    """The page's ownership tables: one row per farm and holder (COLUMNS), as_at from the page's heading. A body row
    that cannot be read whole (fewer cells than the header, no farm name, no holder, a holder that starts with a
    digit) raises ValueError; so, once every row is read, does a farm (of one section) whose shares are all given but
    add up to more than SHARE_SUM_PP points away from 100, a farm listed in two rows of one section included. The rows
    are read first so that a row that cannot be read whole is named as such, not by the shares it leaves short."""
    as_at = as_at_of(html)
    rows, by_farm = [], {}                  # (section, farm) -> every share given for it on the page
    for table in tables_of(html):
        columns = None
        for cells in table:
            texts = [clean(c) for c in cells]
            if texts and _SECTION.search(texts[0]):
                columns = (*_columns(cells), len(cells))
                continue
            if columns is None or not any(texts):
                continue                    # a row before the header (the end-2024 page's empty one), or empty
            section, operator, share, width = columns
            if len(cells) < width:          # a cell of an earlier row spans this one: the cells are not where expected
                raise ValueError(f"crown_estate_pull: a row of {len(cells)} cells under a header of {width}, {texts}: "
                                 "has the layout changed?")
            if not texts[0]:
                raise ValueError(f"crown_estate_pull: a row without a farm name, {texts}: has the layout changed?")
            holders = split_shares(cells[share])
            if not holders:
                raise ValueError(f"crown_estate_pull: no holder in the share cell of {texts[0]!r}: "
                                 "has the layout changed?")
            digit = next((h for h, _ in holders if _DIGIT.match(h)), None)
            if digit is not None:           # "24,95% X": the decimal comma leaves "24," before the holder
                raise ValueError(f"crown_estate_pull: a holder that starts with a digit, {digit!r}, in the share cell "
                                 f"of {texts[0]!r} (a share with a decimal comma?): has the layout changed?")
            by_farm.setdefault((section, texts[0]), []).extend(pct for _, pct in holders)
            for holder, pct in holders:
                rows.append({"as_at": as_at, "section": section, "farm": texts[0], "operator": texts[operator],
                             "holder": holder, "share_pct": pct})
    if not rows:
        raise ValueError("crown_estate_pull: no ownership table on the page; has its layout changed?")
    for (_, farm), shares in by_farm.items():
        if not np.isnan(shares).any() and abs(sum(shares) - 100.0) > SHARE_SUM_PP + 1e-9:
            raise ValueError(f"crown_estate_pull: the shares of {farm!r} add up to {round(float(sum(shares)), 4):g}: "
                             "has the layout changed?")
    return pd.DataFrame(rows, columns=COLUMNS)


def _one_row_per_holder(t: pd.DataFrame) -> pd.DataFrame:
    """A holder named twice for one farm is one row, its shares summed (NaN if either is not given)."""
    keys = ["as_at", "farm", "holder"]
    if not t.duplicated(keys).any():
        return t.reset_index(drop=True)
    share = t.groupby(keys, sort=False)["share_pct"].agg(lambda s: s.sum() if s.notna().all() else np.nan)
    first = t.drop_duplicates(keys).set_index(keys)
    first["share_pct"] = share
    return first.reset_index()[t.columns.tolist()]


def snapshot_files() -> list[Path]:
    return sorted(out_dir().glob(FILE_PATTERN))


def read_snapshot(path: Path) -> pd.DataFrame:
    return parse(decode(Path(path).read_bytes())).assign(source=Path(path).name)


def table() -> pd.DataFrame:
    """Every snapshot pulled, parsed: one row per as_at, farm and holder (COLUMNS + source)."""
    files = snapshot_files()
    if not files:
        raise FileNotFoundError(f"no {FILE_PATTERN} under {out_dir()}: "
                                "run python -m gbpowerdata.pull.crown_estate_pull")
    t = pd.concat([read_snapshot(p) for p in files], ignore_index=True)
    return _one_row_per_holder(t)


# ---------------------------------------------------------------------------- pull
def _check_same(path: Path, html: str) -> str:
    """"" if the file holds the table just downloaded, else a warning for the log."""
    try:
        same = parse(decode(path.read_bytes())).equals(parse(html))
    except ValueError as e:
        return f"; WARNING: could not compare it with the page downloaded now ({e})"
    return "" if same else ("; WARNING: the table downloaded now differs from this file's although the as-at date is "
                            "the same (corrected without a new date?); the file is kept as it is")


def pull(archived: bool = False, failed: list[str] | None = None) -> list[Path]:
    """Download the live page (and, with archived=True, the captures in ARCHIVED) to one file per as-at date; returns
    the snapshot of each page obtained, written now or already there.

    A URL that cannot be pulled (the download fails after its retries, or the page has no as-at heading, as an error
    page) is skipped with a WARNING naming it, and the others are still pulled; its URL is added to `failed` where a
    list is passed. When no page at all was obtained, the first error is raised once every URL has been tried."""
    out = out_dir()
    out.mkdir(parents=True, exist_ok=True)
    urls = [PAGE] + ([archived_url(s) for s in ARCHIVED] if archived else [])
    paths, errors = [], []
    for url in urls:
        try:
            data = download(url)
            html = decode(data)
            when = as_at_of(html)
        except (requests.RequestException, ValueError) as e:
            errors.append(e)
            if failed is not None:
                failed.append(url)
            print(f"  WARNING: {url} not pulled ({type(e).__name__}: {' '.join(str(e).split())}); "
                  "the other pages are pulled all the same")
            continue
        path = out / f"wind_farm_ownership_{when:%Y%m%d}.html"
        if path.exists():
            print(f"  {path.name} exists (raw snapshots are immutable), skipped{_check_same(path, html)}")
        else:
            path.write_bytes(data)
            try:
                t = parse(html)
                size = f"{t['farm'].nunique()} farms, {len(t)} holdings"
            except ValueError as e:      # the page is kept even if the parser no longer reads it
                size = f"WARNING: not parsed ({e})"
            print(f"  {url}: as at {when:%d %B %Y}, {size} -> {path}")
        paths.append(path)
    if errors and not paths:
        raise errors[0]
    return paths


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--archived", action="store_true",
                    help="also pull the Internet Archive's captures of earlier years' tables (ARCHIVED)")
    a = ap.parse_args(argv)
    failed: list[str] = []
    try:
        pull(archived=a.archived, failed=failed)
    except (requests.RequestException, ValueError) as e:
        print(f"  no page pulled: {type(e).__name__}: {' '.join(str(e).split())}")
        return 1
    if failed:
        print(f"  {len(failed)} of the pages could not be pulled: {', '.join(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
