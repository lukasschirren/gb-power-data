"""Pull GB day-ahead auction prices from the EPEX SPOT market-data sFTP server.

A second, independent GB day-ahead price alongside N2EX (Nord Pool). GB is not a
single coupled zone post-Brexit: N2EX and EPEX run separate, uncoupled day-ahead
auctions that can clear at slightly different prices, so having both lets the ABM
validate against either venue (and the venue layer stays swappable).

EPEX publishes GB as market area "great-britain", and — unlike the continental
zones on ENTSO-E — **already in GBP/MWh**, so no FX conversion is needed. GB runs
TWO separate day-ahead auctions (the `--modality` flag picks one):
  hourly  — 60-min, gate closure ~09:20 GMT. The like-for-like counterpart to the
            N2EX day-ahead auction (~09:20); the two were an IDENTICAL coupled
            price until GB left SDAC end-2020, then diverge. This is the default.
  hh      — 30-min, gate closure 15:30 GMT. A LATER, separate auction for
            post-hourly balancing (matches the 30-min settlement spine, but is NOT
            the N2EX counterpart). File names carry an "hh_" prefix.
Source of truth is the file spec PDF in data/reference/.

Remote layout (read-only sFTP, all files CSV, volumes in MWh):
  /great-britain/Day-Ahead Auction/{Hourly,Half-hourly}/Historical/Prices_Volumes/
      auction_spot_prices_great-britain_<YYYY>.csv       (hourly)
      hh_auction_spot_prices_great-britain_<YYYY>.csv    (half-hourly)

Observed for the Imperial subscription (2026-07): historical-only — there is NO
Current folder (we skip its I/O error). Both modalities' CSVs cover 2020..2025.
Deeper HOURLY history exists as legacy "DAM - Historical data - <YYYY>.xls" for
2008..2019 in the Hourly folder — a separate .xls parse, not pulled here.

Each file is wide: line 1 is a "# ... Currency: GBP" comment, then a header row and
one row per delivery day, with columns "Hour <h>" (hourly) or "Hour <h> Q1/Q2"
(hh) for h=1..24 in CET/CEST. DST is encoded with duplicate hour-3 columns: on a
normal day Hour 3A is filled and 3B empty; spring-forward leaves both empty (hour
skipped); fall-back fills both (hour occurs twice). We melt to long UTC by zipping
the non-empty cells onto a DST-aware CET/CEST timeline at the modality's frequency
(60/30 min), so the encoding needs no per-column time math.

Connection (see PDF §2.2): host sftp.marketdata.epexspot.com, port 22, the server
only accepts host-key algorithms rsa-sha2-512/256 (needs paramiko >= 2.9; we run
5.x). Credentials (gitignored):
  - env EPEX_USER / EPEX_PASS, or
  - data/reference/epex_credentials.txt  (line 1 user, line 2 password)
Access needs your own (or your institution's) EPEX SPOT market-data subscription; the data it
returns is licensed and must not be committed or redistributed.

Products (positional, like nordpool_pull):
  prices     GB day-ahead clearing prices -> one long CSV per --modality
             (default modality=hourly, the N2EX-comparable auction)
  curves     aggregated supply/demand curves: download yearly zips to a raw cache,
             read a day on demand with load_curve(date, modality). BOTH auctions
             publish them under their own subtree — `--modality hourly` (2008-2025,
             the N2EX-comparable one) or `--modality hh` (2017-2025, ~512 MB). From
             2025 the two trees reuse the same zip filename, so each modality caches
             to its own directory. Inner files are CSV (2020+) or legacy .xls;
             load_curve normalises both to [date, hour, half_hour, side, price, volume].
  blocks     per-ORDER block bids for a day-ahead auction (--modality): id, limit price,
             hourly volume shape, min/actual acceptance ratio, executed flag, and the
             block family (C01 normal / C02 linked / C04 exclusive / C88 loop).
             Parse with gbpowerdata.build.parse_blocks. NOT a missing piece of the EPEX curve
             — see the BLOCK_DIRS note below before combining them.
  legacy-prices  pre-2020 "DAM - Historical data - <YYYY>.xls" workbooks (hourly tree
             2008-2019), melted to long prices AND volumes. Hours are labelled in GB
             LOCAL time ("Hour 23" = the previous day, "Hour 01x" = the DST repeat).
  intraday   IDA1/IDA2 auction prices+volumes and the continuous per-contract statistics.
  intraday-extras  the intraday AUCTIONS' own aggregated curves + block bids, plus the
             continuous index/RPD archives — completes the DA -> IDA1 -> IDA2 ->
             continuous gate-closure sequence.
  trades     intraday-continuous per-TRANSACTION archives (~1.9 GB, 2016-2025): price,
             volume and execution timestamp per trade. Parse with
             gbpowerdata.build.parse_epex_trades — five format eras, read its docstring first.
  czc-flows  BritNed (GB<->NL) cross-zonal capacity + commercial flows, 2020 only
             (the ONLY interconnector/year EPEX carries) -> two CSVs. Real GB
             capacity/flows are better sourced from ENTSO-E / Nord Pool; this is
             for completeness. Flow series GB-GB vs GB-NL differ by the 3% loss.
Note: hh_prices is clearing prices only — the supply/demand curves are the
separate `curves` product, not inside the price file.

Usage:
  python -m gbpowerdata.pull.epex_pull                              # prices hourly, all years
  python -m gbpowerdata.pull.epex_pull prices --modality hourly --start 2020 --end 2026
  python -m gbpowerdata.pull.epex_pull prices --modality hh --start 2020 --end 2026
  python -m gbpowerdata.pull.epex_pull curves --start 2017 --end 2025
  python -m gbpowerdata.pull.epex_pull czc-flows
"""

from __future__ import annotations

import argparse
import io
import os
import re
import sys
import zipfile
from datetime import datetime, timedelta, timezone
from xml.etree import ElementTree as ET

import pandas as pd

from gbpowerdata import config as cfg

HOST = "sftp.marketdata.epexspot.com"
PORT = 22
CET = "Europe/Berlin"  # EPEX reference time (CET/CEST); DST rules identical across CET zones
LONDON = "Europe/London"  # the pre-2020 GB workbooks label their hours in GB local time
OUT = cfg.raw_dir() / "epex" / "great-britain"

# GB runs two SEPARATE day-ahead auctions, not one product at two granularities:
#   hourly  — 60-min, gate closure ~09:20 GMT (post-Brexit; was 11:00). This is the
#             like-for-like counterpart to the N2EX day-ahead auction (~09:20).
#   hh      — 30-min, gate closure 15:30 GMT, a LATER auction for post-hourly
#             portfolio balancing. NOT directly comparable to N2EX timing.
# Both are GBP/MWh, wide (Hour <h> [Q1/Q2] columns in CET/CEST, DST via 3A/3B).
MODALITIES = {
    "hourly": {"base": "/great-britain/Day-Ahead Auction/Hourly",
               "re": re.compile(r"^auction_spot_prices_great-britain_(\d{4})\.csv$"),
               "vol_re": re.compile(r"^auction_spot_volumes_great-britain_(\d{4})\.csv$"),
               "freq": "60min"},
    "hh": {"base": "/great-britain/Day-Ahead Auction/Half-hourly",
           "re": re.compile(r"^hh_auction_spot_prices_great-britain_(\d{4})\.csv$"),
           "vol_re": re.compile(r"^hh_auction_spot_volumes_great-britain_(\d{4})\.csv$"),
           "freq": "30min"},
}
# What each `kind` pulls: its filename regex, the raw sub-folder, and the melted value column.
# The VOLUMES file (auction_spot_volumes_*) sits beside the prices file in .../Prices_Volumes/ and
# is the cleared traded volume per delivery period (MWh) - the like-for-like weight for blending
# N2EX and EPEX day-ahead prices.
KINDS = {"prices": ("re", "price_gbp_mwh"), "volumes": ("vol_re", "volume_mwh")}
REMOTE_BASE = MODALITIES["hh"]["base"]

# Aggregated supply/demand curves (the EPEX analogue of Nord Pool N2EX curves):
# one zip per year of daily files. 2020+ inner files are CSV, older ones are .xls.
# BOTH auctions publish them, in their own subtree — and from 2025 the two trees use
# the SAME zip filename, so each modality gets its own local cache dir.
#   hourly — 2008..2025, the like-for-like counterpart to the N2EX hourly curves
#   hh     — 2017..2025, the later 15:30 auction (what this module pulled originally)
CURVE_DIRS = {m: f"{spec['base']}/Historical/Aggregated curves"
              for m, spec in MODALITIES.items()}
CURVE_DIR = CURVE_DIRS["hh"]
CURVE_RE = re.compile(r"aggregated_curves_great-britain_(\d{4})\.zip$")
RAW_CURVE_DIRS = {"hourly": OUT / "aggregated_curves_hourly", "hh": OUT / "aggregated_curves"}
RAW_CURVES = RAW_CURVE_DIRS["hh"]

# BLOCK BIDS ("bbof" = block bids and offers), ~40 MB for both day-ahead auctions, same
# yearly-zip-of-daily-files layout as the curves.
# ⚠️ These are an ORDER-LEVEL view, NOT a missing piece of the curve. Measured on 2021-25:
# the EPEX aggregated curve ALREADY contains its blocks — it clears at its own supply==demand
# crossing to MAE £0.34 and reproduces published cleared volume to 0.7%, and adding this file
# on top double counts (+27% volume error). Nord Pool is the opposite: its curve EXCLUDES
# blocks (own crossing off by MAE £53), which is why it ships them inside the curve JSON.
# (Measured by the order-book analysis of the research code, gbabm.analysis.compare_blocks,
# which is not part of this package.)
BLOCK_DIRS = {m: f"{spec['base']}/Historical/Block bids" for m, spec in MODALITIES.items()}
BLOCK_RE = re.compile(r"bbof_great-britain_(\d{4})\.zip$")
RAW_BLOCK_DIRS = {"hourly": OUT / "block_bids_hourly", "hh": OUT / "block_bids"}

# Legacy day-ahead Prices_Volumes: the Hourly tree carries "DAM - Historical data - YYYY.xls"
# for 2008-2019, a decade deeper than the 2020+ CSVs the price puller reads.
LEGACY_RE = {"hourly": re.compile(r"^DAM - Historical data - (\d{4})\.xls$"),
             "hh": re.compile(r"^HH DAM - Historical data - (\d{4})\.xls$")}

# CZC (cross-zonal capacity) + Flows: EPEX only carries BritNed (GB<->NL), 2020 only,
# as daily ETSO-style XML. Kept for completeness; real GB capacity/flows live in the
# ENTSO-E / Nord Pool pulls. GB node EIC on the BritNed border:
CZCFLOWS_ROOT = "/czc_and_flows"
GB_BRITNED_EIC = "10Y1001A1001A58E"
RAW_CZC = cfg.raw_dir() / "epex" / "czc_and_flows"


def credentials() -> tuple[str, str]:
    u, p = os.environ.get("EPEX_USER"), os.environ.get("EPEX_PASS")
    if u and p:
        return u, p
    f = cfg.reference_dir() / "epex_credentials.txt"
    if f.exists():
        lines = [ln.strip() for ln in f.read_text(encoding="utf-8").splitlines()
                 if ln.strip() and not ln.lstrip().startswith("#")]
        if len(lines) >= 2:            # line 1 username, line 2 password
            return lines[0], lines[1]
    sys.exit("No EPEX credentials. Set EPEX_USER and EPEX_PASS, or put the username (line 1) "
             "and password (line 2) in data/reference/epex_credentials.txt")


def _connect():
    """Open an SFTP session. Accepts the host key on first connect (read-only server)."""
    import paramiko
    user, pwd = credentials()
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, port=PORT, username=user, password=pwd,
                timeout=300, banner_timeout=60, auth_timeout=60,
                look_for_keys=False, allow_agent=False)
    return ssh, ssh.open_sftp()


def _download(sftp, start_year: int, end_year: int, modality: str, kind: str = "prices") -> list:
    """Download GB day-ahead price OR volume CSVs for one modality into a raw cache.

    Historical (past-year) files are cached and skipped once present; the current
    year's file is always re-fetched because it is appended to daily.
    """
    spec = MODALITIES[modality]
    regex = spec[KINDS[kind][0]]
    dirs = [f"{spec['base']}/Current/Prices_Volumes",
            f"{spec['base']}/Historical/Prices_Volumes"]
    raw_dir = OUT / f"{modality}_{kind}"
    raw_dir.mkdir(parents=True, exist_ok=True)
    now_year = datetime.now(timezone.utc).year
    seen, local = set(), []
    for rdir in dirs:
        try:
            names = sftp.listdir(rdir)
        except IOError as e:
            print(f"  (skip {rdir}: {e})", flush=True)
            continue
        for name in names:
            m = regex.match(name)
            if not m:
                continue
            year = int(m.group(1))
            if not (start_year <= year <= end_year) or year in seen:
                continue
            seen.add(year)
            dst = raw_dir / name
            if dst.exists() and year < now_year:
                local.append(dst)
                continue
            sftp.get(f"{rdir}/{name}", str(dst))
            print(f"  downloaded {name} ({dst.stat().st_size:,} bytes)", flush=True)
            local.append(dst)
    return sorted(local)


_COL_RE = re.compile(r"(?i)^hour\s*(\d+)\s*([ab])?\s*(?:q\s*(\d))?\s*$")


def _col_utc(day: pd.Timestamp, col: str):
    """UTC start of the 'Hour <h>[A/B] [Q<q>]' delivery period on CET day `day`.

    Maps each column to its own timestamp (rather than zipping by position), so files with
    interior/leading blanks — the intraday auctions cover only part of the day — parse correctly.
    Hour 1 = 00:00; Q2 = +30 min; hour-3 DST twins 3A/3B both map to 02:00-03:00 CET, 3A the
    first (summer) occurrence, 3B the second (winter). Nonexistent spring-forward slots -> NaT."""
    m = _COL_RE.match(col)
    if not m:
        return pd.NaT
    h, ab, q = int(m.group(1)), (m.group(2) or "").lower(), int(m.group(3) or 1)
    naive = pd.Timestamp(day) + pd.Timedelta(hours=h - 1, minutes=(q - 1) * 30)
    ts = naive.tz_localize(CET, ambiguous=(ab != "b"), nonexistent="NaT")
    return pd.NaT if ts is pd.NaT else ts.tz_convert("UTC")


def _parse_file(path, freq: str, value_col: str = "price_gbp_mwh") -> list[dict]:
    """Melt one wide GB price OR volume CSV to long rows [deliveryStart(UTC), <value_col>].

    Layout: a "# ... Currency: GBP" line, then Hour <h> [Q1/Q2] period columns plus trailing
    Total/Buy/Sell/Min/Max/Baseload aggregates (excluded by the period-column filter). Each
    non-blank period cell is placed at the UTC time its column maps to (`_col_utc`); blanks
    (DST twins, or delivery periods outside an intraday auction's window) are simply skipped.
    freq is the delivery-period length ("30min" hh/intraday, "60min" hourly)."""
    step = pd.Timedelta(freq)
    text = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if not text:
        return []
    cur = re.search(r"Currency:\s*([A-Za-z]{3})", text[0])
    currency = cur.group(1).upper() if cur else "GBP"

    df = pd.read_csv(path, skiprows=1, dtype=str)
    df.columns = [str(c).strip() for c in df.columns]
    day_col = next((c for c in df.columns if c.lower().startswith("delivery day")), df.columns[0])
    period_cols = [c for c in df.columns if _COL_RE.match(c)]

    rows = []
    for _, r in df.iterrows():
        day = pd.to_datetime(r[day_col], format="%d/%m/%Y", errors="coerce")
        if pd.isna(day):
            continue
        for c in period_cols:
            v = r[c]
            if pd.isna(v) or str(v).strip() == "":
                continue
            ts = _col_utc(day, c)
            if ts is pd.NaT:
                continue
            rows.append({"deliveryStart": ts, "deliveryEnd": ts + step,
                         value_col: float(str(v).replace(",", ".")), "currency": currency})
    return rows


def pull_prices(start_year: int, end_year: int, modality: str = "hh",
                kind: str = "prices") -> None:
    """Pull GB day-ahead PRICES (kind='prices') or cleared VOLUMES (kind='volumes') for a
    modality into one long CSV `epex_gb_dayahead_{modality}_{kind}_{y0}_{y1}.csv`."""
    spec = MODALITIES[modality]
    regex, value_col = spec[KINDS[kind][0]], KINDS[kind][1]
    ssh, sftp = _connect()
    try:
        files = _download(sftp, start_year, end_year, modality, kind)
    finally:
        sftp.close()
        ssh.close()
    if not files:
        sys.exit(f"No GB {modality} {kind} files found in the requested range.")

    rows = []
    for f in files:
        rows.extend(_parse_file(f, spec["freq"], value_col))
    df = pd.DataFrame(rows)
    if not df.empty:
        df["deliveryStart"] = pd.to_datetime(df["deliveryStart"], utc=True)
        df = (df.drop_duplicates("deliveryStart")
                .sort_values("deliveryStart")
                .reset_index(drop=True))
    OUT.mkdir(parents=True, exist_ok=True)
    yrs = sorted({int(regex.match(f.name).group(1)) for f in files})
    path = OUT / f"epex_gb_dayahead_{modality}_{kind}_{yrs[0]}_{yrs[-1]}.csv"
    df.to_csv(path, index=False)
    print(f"Saved {len(df):,} {modality} {kind} points "
          f"({df['deliveryStart'].min()} -> {df['deliveryStart'].max()}) -> {path}"
          if not df.empty else f"Saved 0 points -> {path}", flush=True)


# --------------------------------------------------------------------------- #
# Aggregated supply/demand curves
# --------------------------------------------------------------------------- #
def pull_curves(start_year: int, end_year: int, modality: str = "hh") -> None:
    """Download one auction's yearly aggregated-curve zips into its raw cache.

    These are large (~550 MB for hh 2017-2025). Like the Nord Pool curves we keep the
    raw archives rather than exploding ~2.8 GB of daily points into one CSV; use
    load_curve(date) to read a single day on demand. Zips are historical/static, so
    a present file is never re-downloaded.
    """
    _pull_year_zips(CURVE_DIRS[modality], CURVE_RE, RAW_CURVE_DIRS[modality],
                    start_year, end_year, "Curve zips")


# Bytes to pull per connection. The server cuts a session at 300 s, so take a window that
# comfortably completes inside it and reconnect for the next one rather than racing the clock.
RESUME_WINDOW = 128 << 20


def _download_resumable(rdir: str, name: str, part, remote_size: int,
                        attempts: int = 8) -> bool:
    """Fetch one remote file into `part`, RESUMING across dropped connections.

    The largest archives (the ~690 MB trade zips) cannot finish inside the server's
    300-second user timeout no matter how fast the link is, so a plain sftp.get can never
    succeed. Instead: seek to whatever is already on disk, append until the connection
    drops, reconnect, repeat. Returns True once `part` holds the full remote size.
    """
    for attempt in range(1, attempts + 1):
        offset = part.stat().st_size if part.exists() else 0
        if offset >= remote_size:
            return True
        want = min(remote_size - offset, RESUME_WINDOW)
        try:
            ssh, sftp = _connect()
            try:
                with sftp.open(f"{rdir}/{name}", "rb") as rf:
                    rf.seek(offset)
                    # Without prefetch paramiko round-trips every read and manages ~70 KB/s,
                    # far too slow to finish inside the server's window. prefetch() queues
                    # async reads from the CURRENT position up to the absolute byte given.
                    rf.prefetch(offset + want)
                    got = 0
                    with open(part, "ab") as lf:
                        while got < want:
                            chunk = rf.read(min(1 << 20, want - got))
                            if not chunk:
                                break
                            lf.write(chunk)
                            got += len(chunk)
            finally:
                sftp.close()
                ssh.close()
        except Exception as e:
            got = part.stat().st_size if part.exists() else 0
            print(f"    attempt {attempt} dropped at {got:,}/{remote_size:,} "
                  f"({100 * got / remote_size:.0f}%): {e} — resuming", flush=True)
        if part.exists() and part.stat().st_size >= remote_size:
            return True
    return part.exists() and part.stat().st_size >= remote_size


def _pull_year_zips(rdir: str, regex, ldir, start_year: int, end_year: int, what: str,
                    attempts: int = 24) -> None:
    """Download every <regex>-matching yearly zip in one remote dir into a raw cache.

    Robust because some of these archives are hundreds of MB and the server enforces a
    300-second user timeout (spec 2.2), so a single long transfer gets its connection
    dropped mid-file. Three things follow:
      * one FRESH connection per file, so the clock restarts each time;
      * download to a .part file and rename only on success — a half-written archive must
        never be left behind looking like a valid cache hit;
      * skip only when the local size MATCHES the remote size, so an earlier truncated
        pull self-heals instead of being trusted forever.
    """
    ldir.mkdir(parents=True, exist_ok=True)
    ssh, sftp = _connect()
    try:
        avail = {int(regex.search(n).group(1)): (n, a.st_size)
                 for n, a in ((e.filename, e) for e in sftp.listdir_attr(rdir))
                 if regex.search(n)}
    finally:
        sftp.close()
        ssh.close()

    for year in sorted(avail):
        if not (start_year <= year <= end_year):
            continue
        name, remote_size = avail[year]
        dst, part = ldir / name, ldir / (name + ".part")
        if dst.exists() and dst.stat().st_size == remote_size:
            print(f"  cached {name}", flush=True)
            continue
        if dst.exists():
            print(f"  re-fetching {name} (local {dst.stat().st_size:,} != "
                  f"remote {remote_size:,} bytes)", flush=True)
        print(f"  downloading {name} ({remote_size / 1e6:.0f} MB) ...", flush=True)
        if _download_resumable(rdir, name, part, remote_size, attempts):
            part.replace(dst)
            print(f"    -> {dst.stat().st_size:,} bytes", flush=True)
        else:
            got = part.stat().st_size if part.exists() else 0
            print(f"    GIVING UP on {name} ({got:,}/{remote_size:,} bytes kept as .part "
                  f"— re-run to resume)", flush=True)
    print(f"{what} under {ldir}", flush=True)


def pull_blocks(start_year: int, end_year: int, modality: str = "hourly") -> None:
    """Download one day-ahead auction's yearly BLOCK-BID zips into its raw cache."""
    _pull_year_zips(BLOCK_DIRS[modality], BLOCK_RE, RAW_BLOCK_DIRS[modality],
                    start_year, end_year, f"{modality} block bids")


_LEGACY_COL_RE = re.compile(r"(?i)^hour\s*(\d{1,2})\s*(x?)\s*$")


def _parse_legacy_workbook(path, sheet: str, value_col: str) -> list[dict]:
    """Melt one legacy .xls sheet (prices|volumes) to long rows.

    Layout differs from the 2020+ CSVs in two ways that matter: the hour columns run
    "Hour 23, Hour 00, ... Hour 22" and are labelled in EUROPE/LONDON local time — so
    "Hour 23" belongs to the PREVIOUS calendar day, and the 24 columns together make up
    one CET delivery day. "Hour 01x" is the repeated hour at the autumn clock change.
    """
    df = pd.read_excel(path, engine="xlrd", sheet_name=sheet)
    df.columns = [str(c).strip() for c in df.columns]
    hour_cols = [c for c in df.columns if _LEGACY_COL_RE.match(c)]
    if not hour_cols:
        return []
    day_col = next((c for c in df.columns if str(c).strip().lower() in ("date", "prices",
                                                                       "volumes")), df.columns[0])
    rows = []
    for _, r in df.iterrows():
        day = pd.to_datetime(r[day_col], errors="coerce")
        if pd.isna(day):
            continue
        day = day.normalize()
        for c in hour_cols:
            v = pd.to_numeric(r[c], errors="coerce")   # early years use "-" for no data
            if pd.isna(v):
                continue
            m = _LEGACY_COL_RE.match(c)
            h, rep = int(m.group(1)), bool(m.group(2))
            base = day - pd.Timedelta(days=1) if h == 23 else day
            ts = (base + pd.Timedelta(hours=h)).tz_localize(
                LONDON, ambiguous=not rep, nonexistent="NaT")
            if ts is pd.NaT:
                continue
            ts = ts.tz_convert("UTC")
            rows.append({"deliveryStart": ts, "deliveryEnd": ts + pd.Timedelta(hours=1),
                         value_col: float(v), "currency": "GBP"})
    return rows


def parse_legacy_prices(modality: str = "hourly") -> None:
    """Melt the cached legacy workbooks into long price and volume CSVs."""
    ldir = OUT / f"{modality}_legacy_prices"
    files = sorted(ldir.glob("*.xls"))
    if not files:
        sys.exit(f"No cached legacy workbooks in {ldir}; pull them first.")
    for sheet, kind, vcol in [("prices", "prices", "price_gbp_mwh"),
                              ("volumes", "volumes", "volume_mwh")]:
        rows = []
        for f in files:
            try:
                rows.extend(_parse_legacy_workbook(f, sheet, vcol))
            except Exception as e:
                print(f"  skip {f.name} [{sheet}]: {e}", flush=True)
        df = pd.DataFrame(rows)
        if df.empty:
            print(f"  no {kind} parsed", flush=True)
            continue
        df = (df.drop_duplicates("deliveryStart").sort_values("deliveryStart")
                .reset_index(drop=True))
        yrs = sorted({int(LEGACY_RE[modality].match(f.name).group(1)) for f in files})
        path = OUT / f"epex_gb_dayahead_{modality}_{kind}_legacy_{yrs[0]}_{yrs[-1]}.csv"
        df.to_csv(path, index=False)
        print(f"Saved {len(df):,} legacy {kind} ({df['deliveryStart'].min()} -> "
              f"{df['deliveryStart'].max()}) -> {path.name}", flush=True)


def pull_legacy_prices(start_year: int, end_year: int, modality: str = "hourly") -> None:
    """Download the pre-2020 'DAM - Historical data - YYYY.xls' price workbooks."""
    _pull_year_zips(f"{MODALITIES[modality]['base']}/Historical/Prices_Volumes",
                    LEGACY_RE[modality], OUT / f"{modality}_legacy_prices",
                    start_year, end_year, f"{modality} legacy price workbooks")


def load_curve(date, modality: str = "hh") -> pd.DataFrame:
    """Read one delivery day's aggregated curve from the cached zips.

    Returns long rows [date, hour, half_hour, side ('supply'|'demand'),
    price_gbp_mwh, volume_mwh]. Handles both the CSV era (2020+) and the .xls era
    (2017-2019). `side` maps EPEX Sell->supply, Purchase->demand. The hourly auction
    has no sub-hour column, so half_hour is 1 throughout.
    """
    day = pd.Timestamp(date)
    zpath = None
    for z in RAW_CURVE_DIRS[modality].glob("*.zip"):
        m = CURVE_RE.search(z.name)
        if m and int(m.group(1)) == day.year:
            zpath = z
            break
    if zpath is None:
        raise FileNotFoundError(f"No cached curve zip for {day.year}; run pull_curves first.")
    stamp = day.strftime("%Y%m%d")
    with zipfile.ZipFile(zpath) as zf:
        inner = next((n for n in zf.namelist() if stamp in n), None)
        if inner is None:
            raise FileNotFoundError(f"No curve file for {day.date()} in {zpath.name}")
        raw = zf.read(inner)
    if inner.lower().endswith(".csv"):
        # 2020+ : Date,Week,Week Day,Hour(1-24),Quarter hour(1-2),Price,Volume,Sale/Purchase
        df = pd.read_csv(io.BytesIO(raw), skiprows=1)
        df.columns = [str(c).strip() for c in df.columns]
        df = df.rename(columns={"Quarter hour": "half_hour", "Half hour": "half_hour",
                                "Hour": "hour",
                                "Price": "price_gbp_mwh", "Volume": "volume_mwh",
                                "Sale/Purchase": "side", "Date": "date"})
        if "half_hour" not in df.columns:          # hourly auction: no sub-hour column
            df["half_hour"] = 1
    else:
        # 2017-2019 legacy .xls : Date,Period(HHMM),Side(P/S),Volume (MW),Price (GBP/MWh),Type
        df = pd.read_excel(io.BytesIO(raw), engine="xlrd")
        df.columns = [str(c).strip() for c in df.columns]
        mins = (df["Period"] // 100) * 60 + (df["Period"] % 100)  # HHMM -> minutes-of-day
        df["hour"] = mins // 60 + 1
        df["half_hour"] = (mins % 60 == 30).astype(int) + 1
        df = df.rename(columns={"Date": "date", "Side": "side",
                                "Price (GBP/MWh)": "price_gbp_mwh", "Volume (MW)": "volume_mwh"})
    # normalise side across both schemas
    df["side"] = df["side"].map({"Sell": "supply", "Purchase": "demand",
                                 "S": "supply", "P": "demand"}).fillna(df["side"])
    return df[["date", "hour", "half_hour", "side", "price_gbp_mwh", "volume_mwh"]]


# --------------------------------------------------------------------------- #
# BritNed (GB<->NL) CZC + Flows — 2020 only, daily ETSO XML
# --------------------------------------------------------------------------- #
_RES = {"PT60M": timedelta(hours=1), "PT30M": timedelta(minutes=30),
        "PT15M": timedelta(minutes=15)}


def _v(elem, tag):
    """Value of child <tag v='...'/>, or None."""
    c = elem.find(tag)
    return c.get("v") if c is not None else None


def _periods(container, interval_tag: str, fields: dict) -> list[dict]:
    """Flatten every Period/<interval_tag> under one time-series element.

    fields maps output-key -> Interval child tag (parsed as float). deliveryStart is
    the period start (UTC) advanced by (Pos-1) * resolution.
    """
    rows = []
    for period in container.iter("Period"):
        ti, res = _v(period, "TimeInterval"), _v(period, "Resolution")
        if ti is None or res is None:
            continue
        step = _RES.get(res)
        if step is None:      # skip daily-total (P1D) and any non-sub-hourly period
            continue
        start = datetime.strptime(ti.split("/")[0], "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc)
        for iv in period.iter(interval_tag):
            if iv.find("Pos") is None:
                continue
            pos = int(iv.find("Pos").get("v"))
            row = {"deliveryStart": start + step * (pos - 1)}
            for key, tag in fields.items():
                val = _v(iv, tag)
                row[key] = float(val) if val is not None else None
            rows.append(row)
    return rows


def _download_xml_days(sftp, seg: str) -> list:
    """Download every daily XML under /czc_and_flows/<seg>/Britned/**; return local paths."""
    base = f"{CZCFLOWS_ROOT}/{seg}/Britned"
    local_root = RAW_CZC / seg
    got = []
    for year in sftp.listdir(base):
        for month in sftp.listdir(f"{base}/{year}"):
            rdir = f"{base}/{year}/{month}"
            ldir = local_root / year / month
            ldir.mkdir(parents=True, exist_ok=True)
            for name in sftp.listdir(rdir):
                if not name.endswith(".xml"):
                    continue
                dst = ldir / name
                if not dst.exists():
                    sftp.get(f"{rdir}/{name}", str(dst))
                got.append(dst)
    print(f"  {seg}: {len(got)} daily XML files", flush=True)
    return got


def pull_czcflows() -> None:
    """Pull BritNed (GB<->NL) CZC capacity + commercial flows (2020 only) to CSV."""
    RAW_CZC.mkdir(parents=True, exist_ok=True)
    ssh, sftp = _connect()
    try:
        czc_files = _download_xml_days(sftp, "CZC")
        flow_files = _download_xml_days(sftp, "Flows")
    finally:
        sftp.close()
        ssh.close()

    def zone(eic):  # BritNed border EICs -> readable labels
        if eic == GB_BRITNED_EIC:
            return "GB"
        return "NL" if (eic or "").startswith("10YNL") else eic

    czc = []
    for f in czc_files:
        root = ET.fromstring(f.read_text(encoding="utf-8"))
        for ts in root.iter("CapacityTimeSeries"):
            in_area, out_area = _v(ts, "InArea"), _v(ts, "OutArea")
            for r in _periods(ts, "Interval",
                              {"capacity_mw": "Qty", "loss": "Loss", "tariff": "Tariff"}):
                r["fromZone"], r["toZone"] = zone(out_area), zone(in_area)
                czc.append(r)
    flows = []
    for f in flow_files:
        root = ET.fromstring(f.read_text(encoding="utf-8"))
        # Each file has directional series: GB-GB (GB busbar), GB-NL (border
        # nomination), NL-NL (NL busbar); In=import to GB, Out=export from GB. The
        # In/Out gap between GB-GB and GB-NL is the ~3% cable loss. Keep all three
        # (labelled) and skip the daily ExchangeRates (P1D) series via the resolution guard.
        for ts in root.iter("AccountTimeSeries"):
            series = _v(ts, "SendersTimeSeriesIdentification")
            for r in _periods(ts, "AccountInterval",
                              {"import_mw": "InQty", "export_mw": "OutQty"}):
                r["series"] = series
                r["net_mw"] = (r.get("import_mw") or 0) - (r.get("export_mw") or 0)
                flows.append(r)

    for rows, name, keys in [
        (czc, "britned_czc_capacity_2020.csv", ["deliveryStart", "fromZone", "toZone"]),
        (flows, "britned_flows_2020.csv", ["deliveryStart", "series"])]:
        df = pd.DataFrame(rows)
        if not df.empty:
            df["deliveryStart"] = pd.to_datetime(df["deliveryStart"], utc=True)
            df = df.drop_duplicates(keys).sort_values("deliveryStart").reset_index(drop=True)
        path = RAW_CZC / name
        df.to_csv(path, index=False)
        print(f"Saved {len(df):,} rows -> {path}", flush=True)


# --------------------------------------------------------------------------- #
# Intraday — GB 30-min IDM auctions (IDA1 D-1 ~19:15, IDA2 D ~09:40) + continuous
# --------------------------------------------------------------------------- #
INTRADAY_ROOT = "/great-britain/Intraday Auction"
IDA_AUCTIONS = {"ida1": "GB 30min IDM Auction D-1",   # D-1 gate ~19:15 CET
                "ida2": "GB 30min IDM Auction D"}     # D    gate ~09:40 CET
IDA_RE = {"prices": re.compile(r"^intraday_auction_spot_prices_.*_(\d{4})\.csv$"),
          "volumes": re.compile(r"^intraday_auction_spot_volumes_.*_(\d{4})\.csv$")}
CONT_ROOT = "/great-britain/Intraday Continuous/EOD/Historical/Results"
CONT_STATS_RE = re.compile(r"^Continuous_Statistics-GB-(\d{4})\.zip$")
RAW_INTRADAY = OUT / "intraday"

# Intraday continuous TRANSACTIONS — every individual trade, not the daily statistics.
# The finest-grained thing EPEX publishes for GB (~1.8 GB for 2016-2025), and the only
# per-transaction record in the whole subscription: price, volume and timestamp per trade.
TRADES_ROOT = "/great-britain/Intraday Continuous/EOD/Historical/Transactions"
# EPEX changed the separator mid-series: Continuous_Trades_GB_2016..2022 (underscores)
# but Continuous_Trades-GB-2023..2025 (hyphens). Match both or you silently get 3 of 10.
TRADES_RE = re.compile(r"^Continuous_Trades[-_]GB[-_](\d{4})\.zip$")
RAW_TRADES = RAW_INTRADAY / "continuous_trades_zips"


def _fetch_year_files(sftp, rdir, regex, start_year, end_year, raw_dir) -> list:
    """Download every <regex>-matching file (year=group 1) in one remote dir; cache historical."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    now_year = datetime.now(timezone.utc).year
    out = []
    try:
        names = sftp.listdir(rdir)
    except IOError as e:
        print(f"  (skip {rdir}: {e})", flush=True)
        return out
    for name in sorted(names):
        m = regex.match(name)
        if not m:
            continue
        year = int(m.group(1))
        if not (start_year <= year <= end_year):
            continue
        dst = raw_dir / name
        if dst.exists() and year < now_year:
            out.append(dst)
            continue
        sftp.get(f"{rdir}/{name}", str(dst))
        print(f"  downloaded {name} ({dst.stat().st_size:,} bytes)", flush=True)
        out.append(dst)
    return sorted(out)


def _write_long(rows: list[dict], stem: str, years: list[int]) -> None:
    df = pd.DataFrame(rows)
    if not df.empty:
        df["deliveryStart"] = pd.to_datetime(df["deliveryStart"], utc=True)
        df = df.drop_duplicates("deliveryStart").sort_values("deliveryStart").reset_index(drop=True)
    path = OUT / f"{stem}_{years[0]}_{years[-1]}.csv"
    df.to_csv(path, index=False)
    print(f"Saved {len(df):,} points "
          f"({df['deliveryStart'].min()} -> {df['deliveryStart'].max()}) -> {path.name}"
          if not df.empty else f"Saved 0 points -> {path.name}", flush=True)


def pull_intraday(start_year: int, end_year: int) -> None:
    """Pull GB intraday: IDA1/IDA2 auction prices+volumes (wide, like the DA files) and the
    intraday-continuous per-contract statistics (VWAP + buy/sell volume)."""
    ssh, sftp = _connect()
    try:
        for aid, folder in IDA_AUCTIONS.items():
            base = f"{INTRADAY_ROOT}/{folder}/Historical/Prices_Volumes"
            for kind, vcol in [("prices", "price_gbp_mwh"), ("volumes", "volume_mwh")]:
                files = _fetch_year_files(sftp, base, IDA_RE[kind], start_year, end_year,
                                          RAW_INTRADAY / f"{aid}_{kind}")
                if not files:
                    continue
                rows = []
                for f in files:
                    rows.extend(_parse_file(f, "30min", vcol))  # same 30-min Q1/Q2 wide layout
                yrs = sorted({int(IDA_RE[kind].match(f.name).group(1)) for f in files})
                _write_long(rows, f"epex_gb_intraday_{aid}_{kind}", yrs)

        # Intraday continuous — yearly zips of daily, already-tidy per-contract statistics.
        zips = _fetch_year_files(sftp, CONT_ROOT, CONT_STATS_RE, start_year, end_year,
                                 RAW_INTRADAY / "continuous_stats_zips")
    finally:
        sftp.close()
        ssh.close()

    frames = []
    for z in zips:
        with zipfile.ZipFile(z) as zf:
            for n in zf.namelist():
                if not n.lower().endswith(".csv"):
                    continue
                try:                                    # daily files carry a "# ..." comment line 1
                    fr = pd.read_csv(io.BytesIO(zf.read(n)), skiprows=1)
                except Exception:
                    continue
                if "DeliveryStart" in fr.columns and len(fr):
                    frames.append(fr)
    if frames:
        df = pd.concat(frames, ignore_index=True)
        df["DeliveryStart"] = pd.to_datetime(df["DeliveryStart"], utc=True)
        df = (df.drop_duplicates(["DeliveryStart", "DeliveryEnd"])
                .sort_values("DeliveryStart").reset_index(drop=True))
        yrs = sorted({int(CONT_STATS_RE.match(z.name).group(1)) for z in zips})
        path = OUT / f"epex_gb_intraday_continuous_stats_{yrs[0]}_{yrs[-1]}.csv"
        df.to_csv(path, index=False)
        print(f"Saved {len(df):,} continuous-contract rows -> {path.name}", flush=True)


# The intraday AUCTIONS publish curves and block bids of their own, and the continuous
# segment publishes index/reference-price archives. Small (~200 MB all in) and they are
# what completes the gate-closure cascade DA -> IDA1 -> IDA2 -> continuous, so the whole
# sequence can be studied with one consistent order-level view.
IDA_EXTRA_DIRS = {
    f"{aid}_{kind}": f"{INTRADAY_ROOT}/{folder}/Historical/{sub}"
    for aid, folder in IDA_AUCTIONS.items()
    for kind, sub in [("curves", "Aggregated curves"), ("blocks", "Block bids")]
}
INDEX_DIRS = {
    "continuous_index": "/great-britain/Intraday Continuous/Indices/Historical/Intraday indices",
    "rpd_all": "/great-britain/Intraday Continuous/Indices/Historical/RPD HH 1H 2H 4H",
    "rpd_hh": "/great-britain/Intraday Continuous/Indices/Historical/RPD HH Only",
}
# Names are inconsistent across renames (SEM GB IDA1 -> GB_30min_IDM_Auction_D-1, and the
# RPD files carry a trailing code that is not a year), so match any 4-digit tail.
ANY_YEAR_ZIP = re.compile(r"(\d{4})\.zip$")


def pull_intraday_extras(start_year: int, end_year: int) -> None:
    """Pull the intraday auctions' curves + block bids and the continuous index archives."""
    for name, rdir in {**IDA_EXTRA_DIRS, **INDEX_DIRS}.items():
        print(f"--- {name}", flush=True)
        try:
            _pull_year_zips(rdir, ANY_YEAR_ZIP, RAW_INTRADAY / name,
                            start_year, end_year, name)
        except Exception as e:
            print(f"  (skip {rdir}: {e})", flush=True)


def pull_trades(start_year: int, end_year: int) -> None:
    """Download the intraday-continuous per-TRADE yearly zips (large: ~1.8 GB for 10 years)."""
    _pull_year_zips(TRADES_ROOT, TRADES_RE, RAW_TRADES, start_year, end_year,
                    "intraday continuous trade archives")


def main(argv: list[str]) -> None:
    p = argparse.ArgumentParser(description="Pull GB market data from EPEX SPOT sFTP.")
    p.add_argument("product", nargs="?", default="prices",
                   choices=["prices", "volumes", "curves", "blocks", "legacy-prices",
                            "intraday", "intraday-extras", "trades", "czc-flows"])
    p.add_argument("--modality", default="hourly", choices=list(MODALITIES),
                   help="prices/volumes/curves: hourly (N2EX-comparable, ~09:20) or hh "
                        "(15:30 auction). Each auction publishes its own curves.")
    p.add_argument("--start", type=int, default=2016, help="first year (inclusive)")
    p.add_argument("--end", type=int, default=datetime.now(timezone.utc).year,
                   help="last year (inclusive)")
    args = p.parse_args(argv[1:])
    if args.product in ("prices", "volumes"):
        print(f"EPEX GB {args.modality} day-ahead {args.product} {args.start}..{args.end}",
              flush=True)
        pull_prices(args.start, args.end, args.modality, args.product)
    elif args.product == "curves":
        print(f"EPEX GB {args.modality} aggregated curves {args.start}..{args.end}", flush=True)
        pull_curves(args.start, args.end, args.modality)
    elif args.product == "blocks":
        print(f"EPEX GB {args.modality} block bids {args.start}..{args.end}", flush=True)
        pull_blocks(args.start, args.end, args.modality)
    elif args.product == "legacy-prices":
        print(f"EPEX GB {args.modality} legacy price workbooks {args.start}..{args.end}",
              flush=True)
        pull_legacy_prices(args.start, args.end, args.modality)
        parse_legacy_prices(args.modality)
    elif args.product == "intraday-extras":
        print(f"EPEX GB intraday auction curves/blocks + indices {args.start}..{args.end}",
              flush=True)
        pull_intraday_extras(args.start, args.end)
    elif args.product == "trades":
        print(f"EPEX GB intraday continuous trades {args.start}..{args.end}", flush=True)
        pull_trades(args.start, args.end)
    elif args.product == "intraday":
        print(f"EPEX GB intraday (IDA1/IDA2 + continuous) {args.start}..{args.end}", flush=True)
        pull_intraday(args.start, args.end)
    else:
        print("EPEX BritNed CZC + Flows (2020)", flush=True)
        pull_czcflows()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
