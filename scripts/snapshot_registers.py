r"""Keep a dated snapshot of each register that publishes only its current state; run it once a month.

Why: three registers behind the ownership tables publish only their current version: Elexon's BM unit register (the
trader of each unit), NESO's Capacity Market register (each applicant's parent) and The Crown Estate's ownership page
(shares as at its stated date; read by gbpowerdata.build.build_crown_estate to check company_owners.csv). Elexon's
register names each unit's lead party, the company that trades it, on the day it is read; NESO updates a parent after
a sale for every agreement still running; The Crown Estate replaces its table about once a year. Once a newer version
replaces a register the older one is gone, so the only way to a history is to keep each version as it comes.
gbpowerdata.build.bm_units already reads every kept snapshot of Elexon's register and gives each year the latest one
on or before its as-of date, so from the first monthly snapshot on, a year's traders are its own (party_basis
"register") rather than today's standing in ("proxy").
Between the snapshots of 5 June and 6 October 2026, 8 of the 655 transmission and embedded units in both changed
lead party (456 MW: four of Uskmouth's battery units, Crystal Rig IV, Greengairs East, Kype Muir and Middle Muir),
26 units were added (2.3 GW, 17 of them batteries), and 32 capacities and 25 fuel types changed (Bad a Cheo from
270 to 27 MW). A snapshot dates a change of trader, not every sale: a sale of the company that trades a station
leaves the lead party as it was (Centrica bought Severn Power Limited, the lead party of Severn's two units, on 7
May 2026, and that company still trades them), so the dated rows of data/reference/company_owners.csv remain the
record of sales.

Sources and terms (each puller's docstring has the details):
  bmunits       Elexon, BMRS API, reference/bmunits/all; BMRS open data licence (commercial use allowed):
                https://data.elexon.co.uk/bmrs/api/v1/reference/bmunits/all
                https://www.elexon.co.uk/bsc/data/balancing-mechanism-reporting-agent/copyright-licence-bmrs-data/
  cm            NESO data portal, dataset capacity-market-register, resources "Capacity Market Unit (CMU)",
                "Components" and the three auction resources (static data, capacity and cost, de-rating factors;
                cm_register_pull.RESOURCES); NESO Open Licence:
                https://api.neso.energy/api/3/action/package_show?id=capacity-market-register
                https://www.neso.energy/data-portal/neso-open-licence
  crown_estate  The Crown Estate, offshore wind farm ownership. Its terms of use license the page for one's own use
                only, so its snapshots stay on the machine that pulled them and are never packed (no data pack of
                gbpowerdata.datapack holds them):
                https://www.thecrownestate.co.uk/our-business/marine/wind-farm-ownership
                https://www.thecrownestate.co.uk/about-us/terms-of-use

What each snapshot dates (the file name carries the date):
  bmunits       raw/bm_units_{YYYYMMDD}.csv: Elexon's register on the UTC day of the pull (gbpowerdata.pull
                .elexon_pull, pull_bmunits), every BM unit with its lead party (id and name), fuel type, capacities,
                GSP group and FPN flag. A year takes the latest snapshot on or before its as-of date (31 December;
                the build date for the current year; gbpowerdata.build.bm_units.snapshot_for).
  cm            raw/neso/cm_register/cmu_{YYYYMMDD}.csv and components_{YYYYMMDD}.csv: NESO's register on the local
                day of the pull (gbpowerdata.pull.cm_register_pull), every CM unit of every auction with its
                applicant, parent company, holder and terminations, and every component, with the auction files
                (auction_static, auction_capacity_cost, derating_factors) of the same day. Successive pairs date the
                changes of parent; gbpowerdata.build.build_ownership and gbpowerdata.build.capacity_market read the
                newest files only (so far).
  crown_estate  raw/crown_estate/wind_farm_ownership_{YYYYMMDD}.html: The Crown Estate's offshore wind farm
                ownership page byte for byte (gbpowerdata.pull.crown_estate_pull, pull(): the live page), named by
                the page's own as-at date and written only when that date is new. Its files date the table, not
                the pull: the table is updated about once a year, so most months add nothing.

Where the snapshots go: the configured raw folder (gbpowerdata.config.raw_dir(): `paths: raw` of the config that
GBPOWERDATA_CONFIG names, else of config.yaml), which every run prints first. The builds read the same folder, so a
new snapshot changes their inputs on their next run: this package's bm_units gives the current year the newest
bm_units_*.csv (an earlier year keeps the latest on or before its 31 December), and build_ownership reads the newest
CM pair. With a local config whose raw folder is another repository's data/raw (as on the author's machine), a build
there that reads the NEWEST bm_units_*.csv changes with every snapshot, so such a repository should read a pinned
snapshot (the author's does since 7 October 2026). Decide the raw folder before scheduling: a config of the task's
own, with a raw folder that no other repository reads, leaves every other repository's inputs as they are.

Sizes (measured 6 October 2026): Elexon's register 0.47 MB (3,115 rows), the CM pair 16.4 MB (8.1 MB for 18,191
CMU rows, 8.3 MB for 29,838 components; the auction files 0.1 MB), the Crown Estate page 0.1 MB when its as-at date
changes: about 17 MB a month and 0.2 GB a year, nearly all of it the CM register.

Gotchas:
  - "Already there" is decided by today's file names: a register whose files of today all exist is not pulled, so
    no snapshot is ever overwritten, whatever a puller does with an existing file (the Elexon and CM pullers also
    skip one). A file of
    today counts only if it holds rows and, for the CM register, no contact column (see Personal data); otherwise
    its register fails and the file is left in place, to be checked and removed by hand. A second run on the same
    day is safe and pulls only what is missing.
  - A snapshot is all or nothing. The files a pull wrote (those not in their folder before it) are removed again
    when the puller fails, returns without writing every file of the day (the CMU file without its components), or
    writes a file that cannot be read, holds no rows (an empty answer from the source) or, for the CM register, has
    a contact column: gbpowerdata.build.build_ownership pairs the newest cmu_*.csv with the components file of its
    date, and bm_units would take an empty register for the year. A Crown Estate page written by a call that then
    fails is removed too (it may be cut short; the live page is pulled again on the next run). Files that were
    there before the run are never removed. An interrupt (Ctrl-C) during a pull removes what that pull wrote first
    and then ends the run, as an interrupt does, without pulling the registers after it. A run killed outright (the
    process ended, so no clean-up runs) can leave a file cut short, which the next run takes as there if it holds
    rows and no contact column; the next point flags it if it lost more than SHRINK of its rows.
  - A snapshot file of today with more than 20% (SHRINK) fewer rows than the newest earlier one of its kind is
    kept, with a WARNING on its line, not removed: a register can shrink for real (NESO has aggregated the
    components under 30 kW since 22 July 2026), and a month not kept can never be pulled again, while a doubtful
    file can be removed by hand. A file of today that was already there is compared too, for a warning only (it is
    never removed), so each run of the same day repeats its warning. Warnings do not change the exit code: read the
    log after each run.
  - Elexon's file takes the UTC day and the CM pair the local day (each puller's own convention): in the UK the two
    differ only between midnight and 01:00 in summer. If the UTC day turns while Elexon's puller runs, its file is
    the next day's, and that file is the snapshot (its line says so) if the pull wrote it: a next day's file that
    was there before the run is not this run's, and the register fails as a pull that wrote nothing.
  - The Crown Estate puller is optional: where this installation has no gbpowerdata.pull.crown_estate_pull, its
    line says "skipped" and the run does not fail. A module that is there but cannot be imported (a package it needs
    is missing) counts as a failure. The puller decides for itself whether the page is new, so a page counts as
    written when the listing of the puller's pages (its FILE_PATTERN, wind_farm_ownership_*.html, in its folder)
    changed during the call: a page that was not there before, or one whose modification time (st_mtime_ns)
    changed. Other files in that folder are neither counted nor removed.
  - The pullers' own progress lines are hidden (--verbose shows them), so the log holds one line per register; a
    line a puller prints with "WARNING" in it is added to its register's line, since an unattended run's log may be
    the only place it is seen (The Crown Estate's puller warns when the table changed without a new as-at date, and
    keeps the file it has). An error or warning longer than 285 characters keeps its first and last 140 (CLIP): the
    start says what failed, the end often why (the server's answer after a long URL).

Personal data: Elexon's register and The Crown Estate's page name companies. The CM register also lists each
applicant's secondary trading contact (telephone, e-mail): the CM puller drops every column whose name matches
gbpowerdata.pull.cm_register_pull.PERSONAL before it writes, and this script checks every CM file of the day for
such a column. One written by this run is removed (the register fails); one that was there already (written by
another program) is not taken as the snapshot: the register fails and the file is left in place, to be removed by
hand. The script writes nothing of its own (it only removes what a failed or interrupted pull wrote); it prints a
header with the time and the raw folder, then one line per register: file names, row counts, sizes, errors and the
pullers' warnings.

Output: the pullers' files above, under the configured raw folder (see "Where the snapshots go"); on stdout a header
with the time and the raw folder, then one line per register (written, already there, skipped, or failed with the
reason). Exit code 0 when every register was written, already there or skipped, possibly with a WARNING on its line
(a warning leaves the exit code at 0, so read the log after each run); 1 when one failed (the others still run).
Ctrl-C during a pull removes what that pull wrote, then ends the run with Python's status for an interrupt
(0xC000013A on Windows, 130 in a POSIX shell) and a note in its traceback naming what was removed.

Usage:
  python scripts/snapshot_registers.py                       # every register whose snapshot of today is missing
  python scripts/snapshot_registers.py --only bmunits cm     # some of them
  python scripts/snapshot_registers.py --verbose             # with the pullers' own output and any traceback

Scheduling (once a month; nothing here creates a task). Any day works; the 28th exists in every month and puts a
year's last snapshot three days before 31 December, the date the year's tables describe. Decide the raw folder
first (see "Where the snapshots go").

  Windows, Task Scheduler. A small wrapper sets the config, names the interpreter by its full path and keeps a log,
  e.g. C:\gbpd\snapshot_registers.cmd:

      @echo off
      set "GBPOWERDATA_CONFIG=C:\gbpd\config.yaml"
      set "PYTHONIOENCODING=utf-8"
      set "PY=C:\Users\you\AppData\Local\anaconda3\python.exe"
      "%PY%" "C:\path\to\gb-power-data\scripts\snapshot_registers.py" >> "C:\gbpd\snapshot_registers.log" 2>&1

  PY is the interpreter of the environment that has the package's dependencies (Anaconda's default for one user is
  shown; `where python` in that environment gives yours), and GBPOWERDATA_CONFIG the config whose `paths: raw` keeps
  the snapshots. Register the wrapper for 07:00 on the 28th of every month, from a normal (not elevated) prompt; a
  wrapper path without spaces keeps the quoting simple:

      schtasks /Create /TN "gbpowerdata snapshots" /SC MONTHLY /D 28 /ST 07:00 /TR C:\gbpd\snapshot_registers.cmd

  `schtasks /Run /TN "gbpowerdata snapshots"` runs it once now, and `schtasks /Query /TN "gbpowerdata snapshots" /V
  /FO LIST` shows the last result (0: every register written, already there or skipped, possibly with a WARNING on
  its line; 1: one failed; read the log after each run). The task runs while you are logged on; to run it logged off
  add /RU <your account> /RP * to the schtasks /Create line (the * makes schtasks ask for the password rather than
  take it on the command line). A run missed because the machine was off or asleep is skipped unless the task may
  start late ("Run task as soon as possible after a scheduled start is missed", the setting StartWhenAvailable),
  which schtasks /Create cannot set: tick it on the task's Settings tab in Task Scheduler, create the task from an
  XML definition instead (schtasks /Create /XML), or set it from PowerShell once the task exists
  (New-ScheduledTaskTrigger has no monthly trigger, so schtasks still creates the task):

      $s = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
      Set-ScheduledTask -TaskName "gbpowerdata snapshots" -Settings $s

  -Settings replaces all of the task's settings with $s, where every setting it does not name takes its default,
  so name all the ones wanted at once, straight after schtasks /Create, rather than ticking some by hand first. The
  two battery switches let a laptop start and finish the run on battery (unticking "Start the task only if the
  computer is on AC power" on the Conditions tab does the same); add -WakeToRun to $s if a sleeping machine should
  wake for the run ("Wake the computer to run this task"). For a task created with /RU and /RP, Set-ScheduledTask
  also needs -User and -Password, the account the task runs as and its password; Get-Credential reads them without
  the password going on the command line:

      $c = Get-Credential
      $p = $c.GetNetworkCredential().Password
      Set-ScheduledTask -TaskName "gbpowerdata snapshots" -Settings $s -User $c.UserName -Password $p

  `schtasks /Delete /TN "gbpowerdata snapshots" /F` removes the task (/F: without asking).

  Linux, cron (`crontab -e`; cron keeps local time, while Elexon's file takes the UTC day). The first line sets the
  config for the entries below it:

      GBPOWERDATA_CONFIG=/data/gbpd/config.yaml
      0 7 28 * * /opt/conda/bin/python /path/to/gb-power-data/scripts/snapshot_registers.py >> /data/gbpd/snapshots.log 2>&1
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import io
import re
import sys
import traceback
from importlib import import_module
from pathlib import Path
from typing import Callable, Iterable, NamedTuple

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))    # runs from a clone without `pip install -e .`, as the other scripts
from gbpowerdata import config as cfg  # noqa: E402

REGISTERS = ("bmunits", "cm", "crown_estate")
CROWN_ESTATE = "gbpowerdata.pull.crown_estate_pull"
WRITTEN, THERE, SKIPPED, FAILED = "written", "already there", "skipped", "failed"
CLIP = 140      # a message longer than 2 * CLIP + 5 characters keeps its first and last CLIP: one readable line
SHRINK = 0.2    # a new snapshot with more than this share fewer rows than the newest kept one is flagged (and kept)


class Outcome(NamedTuple):
    register: str
    status: str
    detail: str

    def line(self) -> str:
        return f"  {self.register:<14}{self.status:<15}{self.detail}"


# ---------------------------------------------------------------------------- today's files and the pullers
def utc_day() -> str:
    """The day in the name of Elexon's snapshot: elexon_pull.pull_bmunits dates it in UTC."""
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d")


def local_day() -> str:
    """The day in the names of the CM register's snapshot: cm_register_pull's own default, the local date."""
    return dt.date.today().strftime("%Y%m%d")


def bmunits_files() -> list[Path]:
    return [cfg.raw_dir() / f"bm_units_{utc_day()}.csv"]


def pull_bmunits() -> None:
    from gbpowerdata.pull import elexon_pull    # imported only to pull: it creates the raw folder on import
    elexon_pull.pull_bmunits(None, None)         # the register of the day; the window arguments are ignored


def cm_files(day: str) -> list[Path]:
    from gbpowerdata.pull import cm_register_pull
    return [cm_register_pull.out_dir() / f"{stem}_{day}.csv" for stem in cm_register_pull.RESOURCES.values()]


def pull_cm(day: str) -> None:
    from gbpowerdata.pull import cm_register_pull
    cm_register_pull.pull(day)


# ---------------------------------------------------------------------------- one register
def snapshot(register: str, todays: Callable[[], list[Path]], pull: Callable[[], object], verbose: bool = False,
             personal: re.Pattern | None = None) -> Outcome:
    """Pull a register unless all its files of today (`todays()`, the names its puller writes) are there.

    A file of today counts as there only if it holds rows and no column whose name matches `personal` (the CM
    register's contact columns); otherwise the register fails and the file is left as it is. A snapshot is all or
    nothing: the files the pull wrote (those not in their folder before it) are removed again if the puller fails
    or is interrupted (an interrupt is then raised again: see _interrupted), returns without writing every file of
    the day, or writes one that is unreadable, empty or has such a column. Every file of the snapshot, written now
    or already there, is compared with the newest earlier one of its kind (_shrunk: a warning only)."""
    files = todays()
    there = [p for p in files if p.exists()]
    rows: dict[Path, int] = {}
    problems = []
    for p in there:
        rows[p], problem = _check(p, personal, verbose)
        if problem:
            problems.append(f"{p.name} already there {problem}")
    if problems:
        return Outcome(register, FAILED, _clip("; ".join(problems))
                       + f"; left in place (remove {'it' if len(problems) == 1 else 'them'} to pull again)")
    globs = _globs(files)
    before = _listing(globs)
    if len(there) == len(files):
        flags = "".join(_shrunk(p, rows[p], before) for p in files)
        return Outcome(register, THERE, f"{_sizes(files, rows)} in {files[0].parent}" + flags)

    try:
        _, warnings = _call(pull, verbose)
    except BaseException as e:               # Ctrl-C too: what the pull wrote goes first, whatever ended it
        undone = _undo(_since(before, globs)[0])
        if not isinstance(e, (Exception, SystemExit)):
            e.add_note(_interrupted(e, register, undone))
            raise                             # an interrupt ends the run, as it would without this script
        return Outcome(register, FAILED, _error(e, verbose) + undone)   # a puller that exits must not end the run
    new = _since(before, globs)[0]           # what the pull wrote, under whatever day its puller chose
    turned = False
    if not all(p.exists() for p in files):
        later = todays()                      # the day turned while the puller ran (Elexon's file takes the UTC day)
        if later != files and all(p in new for p in later):
            files, turned = later, True
        else:
            lacking = ", ".join(p.name for p in files if not p.exists())
            return Outcome(register, FAILED,
                           f"the puller returned without writing {lacking}" + _undo(new) + _notes(warnings))
    fresh = [p for p in files if p not in there]
    for p in fresh:
        rows[p], problem = _check(p, personal, verbose)
        if problem:
            problems.append(f"{p.name} written {problem}")
    if problems:
        return Outcome(register, FAILED, _clip("; ".join(problems)) + _undo(new) + _notes(warnings))
    detail = _sizes(fresh, rows)
    if there:
        detail += f"; {', '.join(p.name for p in there)} already there"
    detail += f" in {files[0].parent}" + ("; the day turned during the pull" if turned else "")
    flags = "".join(_shrunk(p, rows[p], before) for p in files)     # those already there too, for a warning only
    return Outcome(register, WRITTEN, detail + flags + _notes(warnings))


def run_bmunits(verbose: bool = False) -> Outcome:
    return snapshot("bmunits", bmunits_files, pull_bmunits, verbose)


def run_cm(verbose: bool = False) -> Outcome:
    from gbpowerdata.pull import cm_register_pull
    day = local_day()       # one day for the check and the pull, also when the pull runs past midnight
    return snapshot("cm", lambda: cm_files(day), lambda: pull_cm(day), verbose, personal=cm_register_pull.PERSONAL)


def run_crown_estate(verbose: bool = False) -> Outcome:
    """The Crown Estate's puller decides for itself whether the page is new (by its as-at date), so there is no
    file of today to look for. It returns its snapshot whether written now or already there; a page (a file of the
    puller's FILE_PATTERN in its folder) counts as written now if it was not there before the call or its
    modification time changed during it, and other files in the folder are neither counted nor removed. A page that
    was not there before a call that then fails or is interrupted is removed: it may be cut short, and the live
    page is pulled again on the next run. A page that was there before is never removed."""
    try:
        module = import_module(CROWN_ESTATE)
    except ModuleNotFoundError as e:
        if e.name != CROWN_ESTATE:            # the module is there, a package it needs is not
            return Outcome("crown_estate", FAILED, _error(e, verbose))
        return Outcome("crown_estate", SKIPPED, f"{CROWN_ESTATE} is not in this installation")
    # the puller's pages only: another file in the folder (a note saved there by hand) is not its to count or remove
    pages = [(Path(module.out_dir()), getattr(module, "FILE_PATTERN", "wind_farm_ownership_*.html"))]
    before = _listing(pages)
    try:
        result, warnings = _call(module.pull, verbose)        # the live page only (archived=False, its default)
    except BaseException as e:               # Ctrl-C too, as in snapshot()
        undone = _undo(_since(before, pages)[0])
        if not isinstance(e, (Exception, SystemExit)):
            e.add_note(_interrupted(e, "crown_estate", undone))
            raise
        return Outcome("crown_estate", FAILED, _error(e, verbose) + undone)
    new, changed = _since(before, pages)
    written = sorted(new + changed)
    paths = [Path(p) for p in (result or [])]
    if written:
        return Outcome("crown_estate", WRITTEN, _where(written) + _notes(warnings))
    if paths:
        return Outcome("crown_estate", THERE, _where(paths) + _notes(warnings))
    return Outcome("crown_estate", THERE, "nothing new: the page's as-at date is kept already" + _notes(warnings))


RUNNERS: dict[str, Callable[[bool], Outcome]] = {"bmunits": run_bmunits, "cm": run_cm,
                                                  "crown_estate": run_crown_estate}


# ---------------------------------------------------------------------------- helpers
def _call(fn: Callable[[], object], verbose: bool) -> tuple[object, list[str]]:
    """Run a puller: its result, and the warnings it printed. Its progress lines are kept out of the report unless
    verbose (then everything it prints is shown as it comes), but its warnings go on the register's line, since a
    scheduled run's log may be the only place they are seen (The Crown Estate's puller warns when the page changed
    without a new as-at date)."""
    if verbose:
        return fn(), []
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        result = fn()
    return result, [ln[ln.index("WARNING"):].strip() for ln in out.getvalue().splitlines() if "WARNING" in ln]


def _notes(warnings: list[str]) -> str:
    return "".join(f"; {_clip(w)}" for w in warnings)


def _check(path: Path, personal: re.Pattern | None, verbose: bool) -> tuple[int, str]:
    """The data rows of a file of today, and what is wrong with it, worded to follow "<name> already there" or
    "<name> written": the empty string if it is a snapshot (it holds rows and no column matching `personal`)."""
    try:
        rows, columns = _inspect(path, personal)
    except Exception as e:                    # a file no CSV reader can read is no snapshot either
        return 0, f"but unreadable ({_error(e, verbose)})"
    if not rows:
        return 0, "but empty (no rows)"
    return rows, (f"with contact columns ({', '.join(columns)})" if columns else "")


def _inspect(path: Path, personal: re.Pattern | None = None) -> tuple[int, list[str]]:
    """The data rows of a CSV a puller wrote (0 for an empty file), and its columns whose names match `personal`."""
    try:
        header = pd.read_csv(path, nrows=0, encoding="utf-8-sig", encoding_errors="replace").columns
    except pd.errors.EmptyDataError:          # not even a header: zero bytes or blank lines
        return 0, []
    return _rows(path), [str(c) for c in header if personal is not None and personal.search(str(c))]


def _rows(path: Path) -> int:
    """The data rows of a CSV a puller wrote; 0 for an empty file."""
    try:
        return len(pd.read_csv(path, usecols=[0], dtype=str, encoding="utf-8-sig", encoding_errors="replace"))
    except pd.errors.EmptyDataError:
        return 0


def _count(n: int, noun: str = "row") -> str:
    """A count with its noun, singular for one: "1 row", "3,115 rows"."""
    return f"{n:,} {noun}{'' if n == 1 else 's'}"


def _sizes(paths: list[Path], rows: dict[Path, int]) -> str:
    return ", ".join(f"{p.name} ({_count(rows[p])}, {p.stat().st_size / 1e6:.2f} MB)" for p in paths)


def _pattern(path: Path) -> str:
    """A dated snapshot's name with its date as a wildcard: bm_units_20261006.csv -> bm_units_*.csv."""
    return f"{path.stem.rsplit('_', 1)[0]}_*{path.suffix}"


def _globs(files: list[Path]) -> list[tuple[Path, str]]:
    """(folder, pattern) of every kind of file a register writes, its date a wildcard: the listing then also holds
    a file the puller dated otherwise (the next day's, when the day turns during the pull)."""
    return list(dict.fromkeys((p.parent, _pattern(p)) for p in files))


def _listing(globs: Iterable[tuple[Path, str]]) -> dict[Path, int]:
    """The files matching each (folder, pattern), with their modification times in ns. A listing before a pull and
    one after it tell what the pull wrote: the paths that are new, and those whose time changed."""
    out = {}
    for folder, pattern in globs:
        for p in Path(folder).glob(pattern):     # a folder not there yet lists nothing
            try:
                if p.is_file():
                    out[p] = p.stat().st_mtime_ns
            except OSError:                       # gone between the listing and the look
                pass
    return out


def _since(before: dict[Path, int], globs: Iterable[tuple[Path, str]]) -> tuple[list[Path], list[Path]]:
    """(new, changed) since the listing `before`: the files not there then, and those whose modification time
    changed. Only new files are ever removed: a file that was there before the run is never touched."""
    after = _listing(globs)
    return (sorted(p for p in after if p not in before),
            sorted(p for p in after if p in before and after[p] != before[p]))


def _shrunk(path: Path, rows: int, before: dict[Path, int]) -> str:
    """A WARNING for the report if a snapshot file of today (written now, or already there) has more than SHRINK
    fewer rows than the newest file of its kind with an earlier date in the listing `before` (taken before the
    pull); "" otherwise. The file is kept either way: a register can shrink for real, and a month not kept can never
    be pulled again (see the module's Gotchas)."""
    def dated(q: Path) -> bool:
        return bool(re.fullmatch(r"\d{8}", q.stem.rsplit("_", 1)[-1]))

    older = sorted(q.name for q in before if q.parent == path.parent and _pattern(q) == _pattern(path)
                   and dated(q) and q.name < path.name)
    if not older:
        return ""
    last = path.parent / older[-1]
    try:
        kept = _rows(last)
    except Exception as e:                    # only a comparison: it never fails or removes the snapshot
        return f"; WARNING: could not count the rows of {last.name} to compare ({type(e).__name__})"
    if kept and rows < (1 - SHRINK) * kept:
        return (f"; WARNING: {_count(rows)} in {path.name}, {1 - rows / kept:.0%} fewer than in {last.name} "
                f"({kept:,}); kept, check it before a build reads it")
    return ""


def _interrupted(e: BaseException, register: str, undone: str) -> str:
    """The note added to an interrupt (KeyboardInterrupt, or any BaseException that is not an Exception or
    SystemExit) raised during a pull, before it is raised again: what the run removed, since its report line is
    never printed. `undone` is _undo's note."""
    return (f"snapshot_registers: {type(e).__name__} during the {register} pull"
            + (undone or "; it had written no new file"))


def _undo(paths: list[Path]) -> str:
    """Remove the files this run wrote of a snapshot it could not complete; returns the note for the report."""
    removed, left = [], []
    for p in paths:
        try:
            p.unlink()
            removed.append(p.name)
        except FileNotFoundError:
            pass
        except OSError as e:
            left.append(f"{p.name} ({type(e).__name__})")
    note = f"; removed {', '.join(removed)}, written by this run (a snapshot is all or nothing)" if removed else ""
    return note + (f"; could not remove {', '.join(left)}: delete by hand" if left else "")


def _clip(text: str) -> str:
    """The text on one line, cut in the middle if longer than 2 * CLIP + 5 characters: the start of an error says
    what failed, its end often why (the server's answer after a long URL)."""
    text = " ".join(str(text).split())
    return text if len(text) <= 2 * CLIP + 5 else f"{text[:CLIP]} ... {text[-CLIP:]}"


def _error(e: BaseException, verbose: bool = False) -> str:
    if verbose:
        traceback.print_exception(e)          # to stderr; the report itself keeps one line per register
    text = " ".join(str(e).split())
    return _clip(f"{type(e).__name__}: {text}") if text else type(e).__name__


def _where(files: list[Path]) -> str:
    return f"{', '.join(p.name for p in files)} in {files[0].parent}"


def _say(text: str) -> None:
    """Print a line whatever the console's or the log's encoding (an error message may hold any character)."""
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    print(text.encode(encoding, "backslashreplace").decode(encoding), flush=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--only", nargs="+", choices=REGISTERS, metavar="REGISTER",
                    help=f"pull only these, of {', '.join(REGISTERS)} (default: all)")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="show the pullers' own output and the traceback of a failed pull")
    a = ap.parse_args(argv)
    _say(f"Register snapshots, {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC, raw folder {cfg.raw_dir()}")
    failed = False
    for register in REGISTERS:
        if a.only and register not in a.only:
            continue
        try:
            outcome = RUNNERS[register](a.verbose)
        except Exception as e:    # an error around the pull (an import, a reader): this register fails, the rest run
            outcome = Outcome(register, FAILED, _error(e, a.verbose))
        _say(outcome.line())
        failed = failed or outcome.status == FAILED
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
