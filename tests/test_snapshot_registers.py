"""The monthly snapshot of the registers that publish only their current state (scripts/snapshot_registers.py), with
the pullers replaced (no network): each register is pulled once and reported on one line; a register whose snapshot
of today exists is not pulled again and its files are not touched, but a file of today that is empty or (CM) holds a
contact column fails its register and stays as it is; a puller that fails, exits, or returns without writing every
file of the day makes the exit code 1 while the others still run, and leaves no half, empty or contact-holding
snapshot behind, while files that were there before stay as they were (a valid CMU file of today among them); an
interrupt (Ctrl-C) removes what its pull wrote and still ends the run; the day turning during a pull keeps the next
day's file, but only one the pull wrote; --only pulls only the registers it names; the Crown Estate puller is
optional, but a broken one fails, only its pages are looked at, and a page counts as written only if the call wrote
it; a puller's progress lines stay out of the report and its warnings go into it; long messages keep their start
and end; a much shorter register, new or already there, is kept with a warning ("1 row" for one) and the exit code
stays 0; and the files the script looks for are the ones the real pullers write."""
import importlib.util
import os
import sys
import time
import types
from pathlib import Path

import pandas as pd
import pytest
import requests

from gbpowerdata import config as cfg
from gbpowerdata.pull import cm_register_pull

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("snapshot_registers", ROOT / "scripts" / "snapshot_registers.py")
snap = importlib.util.module_from_spec(_spec)
sys.modules["snapshot_registers"] = snap       # a script is no package module: register it as an import would
_spec.loader.exec_module(snap)

UNITS = [{"elexonBmUnit": "T_ABC-1", "leadPartyId": "P1", "leadPartyName": "Alpha Generation Ltd"},
         {"elexonBmUnit": "E_XYZB-1", "leadPartyId": "P2", "leadPartyName": "Beta Optimiser Ltd"}]
CMU = [{"CMU ID": "X1", "Name of Applicant": "Foo Ltd", "Parent Company": "Foo plc"}]
PAGE = "wind_farm_ownership_20241231.html"     # crown_estate_pull names a page by its as-at date
HEADING = "<h2>UK operational and under construction wind farm ownership as at 31 December 2024</h2>"
LINE_START = 2 + 14 + 15                       # Outcome.line(): indent, register and status columns


@pytest.fixture
def raw(tmp_path, monkeypatch):
    """An empty raw folder and stand-in pullers that write today's files under the real pullers' names and behave as
    they do (an existing CM file is skipped; the Crown Estate page is written only when its as-at date is new, and its
    file is returned either way); `calls` lists the registers pulled, in order."""
    monkeypatch.setattr(cfg, "raw_dir", lambda: tmp_path)
    from gbpowerdata.pull import elexon_pull     # imported after the move: it creates its RAW_DIR on import

    calls = []

    def bmunits(start, end):
        calls.append("bmunits")
        pd.DataFrame(UNITS).to_csv(tmp_path / f"bm_units_{snap.utc_day()}.csv", index=False)

    def cm(stamp=None):
        calls.append("cm")
        out = cm_register_pull.out_dir()
        out.mkdir(parents=True, exist_ok=True)
        for stem in cm_register_pull.RESOURCES.values():
            if not (out / f"{stem}_{stamp}.csv").exists():
                pd.DataFrame(CMU).to_csv(out / f"{stem}_{stamp}.csv", index=False)

    def crown(archived=False):
        calls.append("crown_estate")
        path = tmp_path / "crown_estate" / PAGE
        if not path.exists():
            path.parent.mkdir(exist_ok=True)
            path.write_text(HEADING)
        return [path]

    crown_module = types.ModuleType(snap.CROWN_ESTATE)
    crown_module.pull = crown
    crown_module.out_dir = lambda: tmp_path / "crown_estate"
    monkeypatch.setattr(elexon_pull, "RAW_DIR", tmp_path)
    monkeypatch.setattr(elexon_pull, "pull_bmunits", bmunits)
    monkeypatch.setattr(cm_register_pull, "pull", cm)
    monkeypatch.setitem(sys.modules, snap.CROWN_ESTATE, crown_module)
    return types.SimpleNamespace(dir=tmp_path, calls=calls, elexon=elexon_pull, crown=crown_module)


def run(capsys, *argv) -> tuple[int, dict[str, str]]:
    """The exit code and the report, register -> its line."""
    code = snap.main(list(argv))
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("Register snapshots")
    return code, {ln.split()[0]: ln for ln in lines[1:]}


def status(line: str) -> str:
    return " ".join(line.split()[1:3]) if line.split()[1] == "already" else line.split()[1]


def contents(folder: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted(folder.iterdir())}


def test_each_register_is_pulled_once_and_reported_on_one_line(raw, capsys):
    code, report = run(capsys)
    assert code == 0 and raw.calls == ["bmunits", "cm", "crown_estate"]
    assert list(report) == ["bmunits", "cm", "crown_estate"]
    assert {status(line) for line in report.values()} == {"written"}
    assert f"bm_units_{snap.utc_day()}.csv (2 rows" in report["bmunits"] and "WARNING" not in report["bmunits"]
    day = snap.local_day()
    assert sorted(p.name for p in (raw.dir / "neso" / "cm_register").iterdir()) == sorted(
        f"{stem}_{day}.csv" for stem in cm_register_pull.RESOURCES.values())


def test_a_snapshot_of_today_is_not_pulled_again_nor_touched(raw, capsys):
    kept = raw.dir / f"bm_units_{snap.utc_day()}.csv"
    kept.write_bytes(b"elexonBmUnit,leadPartyName\nT_KEEP-1,Kept Ltd\n")
    code, report = run(capsys)
    assert code == 0 and raw.calls == ["cm", "crown_estate"]
    assert status(report["bmunits"]) == "already there" and f"{kept.name} (1 row," in report["bmunits"]
    assert kept.read_bytes() == b"elexonBmUnit,leadPartyName\nT_KEEP-1,Kept Ltd\n"
    # the same day again: nothing is pulled; the Crown Estate puller decides for itself and returns its file untouched
    code, report = run(capsys)
    assert code == 0 and raw.calls == ["cm", "crown_estate", "crown_estate"]
    assert {status(line) for line in report.values()} == {"already there"}


def test_half_a_cm_snapshot_is_completed_without_touching_its_other_half(raw, capsys):
    day = snap.local_day()
    cmu = raw.dir / "neso" / "cm_register" / f"cmu_{day}.csv"
    cmu.parent.mkdir(parents=True)
    cmu.write_bytes(b"CMU ID\nKEEP\n")
    code, report = run(capsys, "--only", "cm")
    assert code == 0 and raw.calls == ["cm"] and status(report["cm"]) == "written"
    assert f"components_{day}.csv (1 row," in report["cm"] and f"cmu_{day}.csv already there" in report["cm"]
    assert cmu.read_bytes() == b"CMU ID\nKEEP\n"


def test_a_cmu_file_of_today_stays_when_the_components_pull_fails(raw, capsys, monkeypatch):
    day = snap.local_day()
    folder = raw.dir / "neso" / "cm_register"
    folder.mkdir(parents=True)
    (folder / f"cmu_{day}.csv").write_bytes(b"CMU ID\nKEEP\n")

    def components_down(stamp=None):       # as the real puller: the CMU file of the day is skipped, the next fails
        raise requests.HTTPError("503 Server Error: Service Unavailable")

    monkeypatch.setattr(cm_register_pull, "pull", components_down)
    code, report = run(capsys, "--only", "cm")
    assert code == 1 and status(report["cm"]) == "failed" and "HTTPError: 503" in report["cm"]
    assert "removed" not in report["cm"]
    assert contents(folder) == {f"cmu_{day}.csv": b"CMU ID\nKEEP\n"}


def test_a_cmu_file_of_today_stays_when_the_puller_returns_without_the_components(raw, capsys, monkeypatch):
    day = snap.local_day()
    folder = raw.dir / "neso" / "cm_register"
    folder.mkdir(parents=True)
    cmu = folder / f"cmu_{day}.csv"
    cmu.write_bytes(b"CMU ID,Parent Company\nKEEP,Keep plc\n")      # a valid file of today, there before the run
    mtime = cmu.stat().st_mtime_ns

    def returns_without_writing(stamp=None):
        return {}

    monkeypatch.setattr(cm_register_pull, "pull", returns_without_writing)
    code, report = run(capsys, "--only", "cm")
    assert code == 1 and status(report["cm"]) == "failed"
    assert f"the puller returned without writing components_{day}.csv" in report["cm"]
    assert "removed" not in report["cm"]                           # it was not this run's to remove
    assert contents(folder) == {cmu.name: b"CMU ID,Parent Company\nKEEP,Keep plc\n"}
    assert cmu.stat().st_mtime_ns == mtime


def test_a_failing_puller_fails_the_run_and_the_others_still_run(raw, capsys, monkeypatch):
    def elexon_down(start, end):
        raise requests.ConnectionError("Elexon is down")

    monkeypatch.setattr(raw.elexon, "pull_bmunits", elexon_down)
    code, report = run(capsys)
    assert code == 1 and raw.calls == ["cm", "crown_estate"]
    assert status(report["bmunits"]) == "failed" and "ConnectionError: Elexon is down" in report["bmunits"]
    assert status(report["cm"]) == "written" and status(report["crown_estate"]) == "written"
    assert not list(raw.dir.glob("bm_units_*.csv"))


def test_an_interrupt_removes_what_its_pull_wrote_and_still_ends_the_run(raw, capsys, monkeypatch):
    earlier = raw.dir / "bm_units_20000101.csv"
    earlier.write_bytes(b"elexonBmUnit\nT_OLD-1\n")
    today = raw.dir / f"bm_units_{snap.utc_day()}.csv"

    def exits(start, end):                     # a puller that calls sys.exit fails its register, and the run goes on
        today.write_bytes(b"elexonBmUnit\nT_ABC-1\n")
        raise SystemExit(2)

    monkeypatch.setattr(raw.elexon, "pull_bmunits", exits)
    code, report = run(capsys, "--only", "bmunits", "cm")
    assert code == 1 and status(report["bmunits"]) == "failed" and "SystemExit: 2" in report["bmunits"]
    assert f"removed {today.name}, written by this run" in report["bmunits"]
    assert status(report["cm"]) == "written" and raw.calls == ["cm"] and not today.exists()

    def interrupted(start, end):               # Ctrl-C while the register is being written
        today.write_bytes(b"elexonBmUnit,leadPartyName\nT_ABC-1,Alpha Gen")
        raise KeyboardInterrupt

    monkeypatch.setattr(raw.elexon, "pull_bmunits", interrupted)
    with pytest.raises(KeyboardInterrupt) as stopped:
        snap.main(["--only", "bmunits", "crown_estate"])
    assert not today.exists() and earlier.read_bytes() == b"elexonBmUnit\nT_OLD-1\n"
    assert raw.calls == ["cm"]                 # the run ended there: the Crown Estate's page was not pulled
    assert stopped.value.__notes__ == [f"snapshot_registers: KeyboardInterrupt during the bmunits pull; removed "
                                       f"{today.name}, written by this run (a snapshot is all or nothing)"]

    page = raw.crown.out_dir() / "wind_farm_ownership_20251231.html"

    def interrupted_page(archived=False):      # the Crown Estate's page alike
        page.parent.mkdir(exist_ok=True)
        page.write_text("<h2>UK operational and under")
        raise KeyboardInterrupt

    monkeypatch.setattr(raw.crown, "pull", interrupted_page)
    with pytest.raises(KeyboardInterrupt) as stopped:
        snap.main(["--only", "crown_estate"])
    assert not page.exists() and f"removed {page.name}, written by this run" in stopped.value.__notes__[0]


def test_no_half_or_empty_snapshot_is_left_behind(raw, capsys, monkeypatch):
    # the CMU file is written, then the components download fails: the ownership build reads the components of the
    # newest CMU file's date, so the lone CMU file goes again
    def cmu_then_error(stamp=None):
        out = cm_register_pull.out_dir()
        out.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(CMU).to_csv(out / f"cmu_{stamp}.csv", index=False)
        raise requests.HTTPError("503 Server Error: Service Unavailable")

    monkeypatch.setattr(cm_register_pull, "pull", cmu_then_error)
    code, report = run(capsys, "--only", "cm")
    assert code == 1 and "HTTPError: 503 Server Error" in report["cm"] and "removed cmu_" in report["cm"]
    assert not list((raw.dir / "neso" / "cm_register").glob("*.csv"))

    # an empty answer is no register: bm_units would take it for the year
    def empty_answer(start, end):
        pd.DataFrame().to_csv(raw.dir / f"bm_units_{snap.utc_day()}.csv", index=False)

    monkeypatch.setattr(raw.elexon, "pull_bmunits", empty_answer)
    code, report = run(capsys, "--only", "bmunits")
    assert code == 1 and f"bm_units_{snap.utc_day()}.csv written but empty (no rows)" in report["bmunits"]
    assert "removed bm_units_" in report["bmunits"] and not list(raw.dir.glob("bm_units_*.csv"))


def test_a_puller_that_returns_without_writing_every_file_leaves_nothing_behind(raw, capsys, monkeypatch):
    folder = raw.dir / "neso" / "cm_register"
    folder.mkdir(parents=True)
    earlier = {"cmu_20000101.csv": b"CMU ID\nOLD\n", "components_20000101.csv": b"CMU ID,Component ID\nOLD,T_OLD-1\n"}
    for name, data in earlier.items():
        (folder / name).write_bytes(data)

    def cmu_only(stamp=None):              # returns normally, without the components file
        pd.DataFrame(CMU).to_csv(cm_register_pull.out_dir() / f"cmu_{stamp}.csv", index=False)

    monkeypatch.setattr(cm_register_pull, "pull", cmu_only)
    code, report = run(capsys, "--only", "cm")
    day = snap.local_day()
    assert code == 1 and status(report["cm"]) == "failed"
    assert f"the puller returned without writing components_{day}.csv" in report["cm"]
    assert f"removed cmu_{day}.csv, written by this run" in report["cm"]
    assert contents(folder) == earlier     # nothing of today is left, and the earlier pair is as it was


def test_the_day_turning_during_a_pull_keeps_the_next_days_file(raw, capsys, monkeypatch):
    # Elexon's puller dates its file by the UTC day when it writes, so a pull across midnight writes the next day's
    clock = {"day": "20261231"}
    monkeypatch.setattr(snap, "utc_day", lambda: clock["day"])

    def across_midnight(start, end):
        clock["day"] = "20270101"
        pd.DataFrame(UNITS).to_csv(raw.dir / f"bm_units_{clock['day']}.csv", index=False)

    monkeypatch.setattr(raw.elexon, "pull_bmunits", across_midnight)
    code, report = run(capsys, "--only", "bmunits")
    assert code == 0 and status(report["bmunits"]) == "written"
    assert "bm_units_20270101.csv (2 rows" in report["bmunits"] and "the day turned during" in report["bmunits"]
    assert [p.name for p in raw.dir.glob("bm_units_*.csv")] == ["bm_units_20270101.csv"]

    # the next day's file is checked like any other: an empty one is removed, the earlier snapshot stays
    clock["day"] = "20271231"

    def empty_across_midnight(start, end):
        clock["day"] = "20280101"
        (raw.dir / f"bm_units_{clock['day']}.csv").write_bytes(b"\n")

    monkeypatch.setattr(raw.elexon, "pull_bmunits", empty_across_midnight)
    code, report = run(capsys, "--only", "bmunits")
    assert code == 1 and "bm_units_20280101.csv written but empty" in report["bmunits"]
    assert "removed bm_units_20280101.csv" in report["bmunits"]
    assert [p.name for p in raw.dir.glob("bm_units_*.csv")] == ["bm_units_20270101.csv"]


def test_a_next_days_file_there_before_the_run_is_not_taken_for_the_pull(raw, capsys, monkeypatch):
    # the next day's file is the snapshot only if the pull wrote it: one there before the run (a clock ahead, another
    # program) says nothing about this pull, which wrote nothing
    clock = {"day": "20261231"}
    monkeypatch.setattr(snap, "utc_day", lambda: clock["day"])
    ahead = raw.dir / "bm_units_20270101.csv"
    ahead.write_bytes(b"elexonBmUnit,leadPartyName\nT_AHEAD-1,Ahead Ltd\n")
    mtime = ahead.stat().st_mtime_ns

    def turns_the_day_without_writing(start, end):
        clock["day"] = "20270101"

    monkeypatch.setattr(raw.elexon, "pull_bmunits", turns_the_day_without_writing)
    code, report = run(capsys, "--only", "bmunits")
    assert code == 1 and status(report["bmunits"]) == "failed"
    assert "returned without writing bm_units_20261231.csv" in report["bmunits"]
    assert "the day turned" not in report["bmunits"]           # (not just "turned": "returned" holds it)
    assert "removed" not in report["bmunits"]
    assert [p.name for p in raw.dir.glob("bm_units_*.csv")] == [ahead.name]
    assert ahead.read_bytes() == b"elexonBmUnit,leadPartyName\nT_AHEAD-1,Ahead Ltd\n"
    assert ahead.stat().st_mtime_ns == mtime


def test_a_file_of_today_counts_only_with_rows_and_without_contact_columns(raw, capsys):
    bmunits = raw.dir / f"bm_units_{snap.utc_day()}.csv"
    bmunits.write_bytes(b"elexonBmUnit,leadPartyName\n")                      # a header, no rows
    day = snap.local_day()
    folder = raw.dir / "neso" / "cm_register"
    folder.mkdir(parents=True)
    with_contacts = b"CMU ID,Secondary Trading Contact_Telephone,Parent Company\nX1,0,Foo plc\n"
    (folder / f"cmu_{day}.csv").write_bytes(with_contacts)                      # written by another program
    code, report = run(capsys, "--only", "bmunits", "cm")
    assert code == 1 and raw.calls == []              # neither is pulled: a file of today is never replaced
    assert status(report["bmunits"]) == "failed" and f"{bmunits.name} already there but empty" in report["bmunits"]
    assert status(report["cm"]) == "failed" and "left in place" in report["cm"]
    assert f"cmu_{day}.csv already there with contact columns (Secondary Trading Contact_Telephone)" in report["cm"]
    assert bmunits.read_bytes() == b"elexonBmUnit,leadPartyName\n"
    assert contents(folder) == {f"cmu_{day}.csv": with_contacts}

    bmunits.write_bytes(b"")                                                    # zero bytes: empty too
    code, report = run(capsys, "--only", "bmunits")
    assert code == 1 and raw.calls == [] and "already there but empty" in report["bmunits"]
    assert bmunits.read_bytes() == b""


def test_a_new_cm_file_with_contact_columns_is_removed(raw, capsys, monkeypatch):
    def keeps_the_contacts(stamp=None):    # a puller that no longer drops the contact columns
        out = cm_register_pull.out_dir()
        out.mkdir(parents=True, exist_ok=True)
        pd.DataFrame([{**CMU[0], "Secondary Trading Contact_Email": "x"}]).to_csv(out / f"cmu_{stamp}.csv",
                                                                                  index=False)
        for stem in cm_register_pull.RESOURCES.values():
            if stem != "cmu":
                pd.DataFrame(CMU).to_csv(out / f"{stem}_{stamp}.csv", index=False)

    monkeypatch.setattr(cm_register_pull, "pull", keeps_the_contacts)
    code, report = run(capsys, "--only", "cm")
    day = snap.local_day()
    assert code == 1 and f"cmu_{day}.csv written with contact columns (Secondary Trading Contact_Email)" in report["cm"]
    assert not list((raw.dir / "neso" / "cm_register").glob("*.csv"))


def test_a_much_shorter_register_is_kept_with_a_warning(raw, capsys):
    older = raw.dir / "bm_units_20000101.csv"
    pd.DataFrame({"elexonBmUnit": [f"T_UNIT-{i}" for i in range(10)]}).to_csv(older, index=False)
    code, report = run(capsys, "--only", "bmunits")
    new = f"bm_units_{snap.utc_day()}.csv"
    assert code == 0 and status(report["bmunits"]) == "written"          # kept: a month not kept is lost for good,
    #                                                                      and a warning leaves the exit code at 0
    assert f"WARNING: 2 rows in {new}, 80% fewer than in {older.name} (10)" in report["bmunits"]
    assert (raw.dir / new).exists() and len(pd.read_csv(older)) == 10
    # the same day again: the file is already there and is compared the same way, for a warning only
    code, report = run(capsys, "--only", "bmunits")
    assert code == 0 and status(report["bmunits"]) == "already there" and raw.calls == ["bmunits"]
    assert f"WARNING: 2 rows in {new}, 80% fewer than in {older.name} (10)" in report["bmunits"]
    assert (raw.dir / new).exists()


def test_one_row_is_one_row_and_a_file_already_there_is_compared_too(raw, capsys):
    folder = raw.dir / "neso" / "cm_register"
    folder.mkdir(parents=True)
    for stem in cm_register_pull.RESOURCES.values():
        pd.DataFrame({"CMU ID": [f"X{i}" for i in range(10)]}).to_csv(folder / f"{stem}_20000101.csv", index=False)
    day = snap.local_day()
    (folder / f"cmu_{day}.csv").write_bytes(b"CMU ID\nKEEP\n")                # one row, there before the run
    code, report = run(capsys, "--only", "cm")
    assert code == 0 and status(report["cm"]) == "written" and raw.calls == ["cm"]
    assert f"components_{day}.csv (1 row," in report["cm"] and f"cmu_{day}.csv already there" in report["cm"]
    for stem in ("cmu", "components"):
        assert f"WARNING: 1 row in {stem}_{day}.csv, 90% fewer than in {stem}_20000101.csv (10)" in report["cm"]
    assert (folder / f"cmu_{day}.csv").read_bytes() == b"CMU ID\nKEEP\n"


def test_only_pulls_the_registers_named(raw, capsys):
    code, report = run(capsys, "--only", "cm")
    assert code == 0 and raw.calls == ["cm"] and list(report) == ["cm"]
    code, report = run(capsys, "--only", "crown_estate", "bmunits")
    assert code == 0 and raw.calls == ["cm", "bmunits", "crown_estate"]
    assert list(report) == ["bmunits", "crown_estate"]                   # in the script's order, not the arguments'
    with pytest.raises(SystemExit):
        snap.main(["--only", "dukes"])


def test_the_crown_estate_puller_is_optional_but_a_broken_one_fails(raw, capsys, monkeypatch):
    monkeypatch.setitem(sys.modules, snap.CROWN_ESTATE, None)               # not in this installation
    code, report = run(capsys, "--only", "crown_estate")
    assert code == 0 and status(report["crown_estate"]) == "skipped"

    folder = lambda: raw.dir / "crown_estate"                              # noqa: E731
    monkeypatch.setitem(sys.modules, snap.CROWN_ESTATE, types.SimpleNamespace(pull=lambda: [], out_dir=folder))
    code, report = run(capsys, "--only", "crown_estate")                    # the page's as-at date is kept already
    assert code == 0 and status(report["crown_estate"]) == "already there" and "nothing new" in report["crown_estate"]

    def corrected_without_a_new_date():             # the puller's progress lines are hidden, its warnings are not
        print("  wind_farm_ownership_20241231.html exists (raw snapshots are immutable), skipped; WARNING: the table "
              "downloaded now differs from this file's")
        return []

    monkeypatch.setitem(sys.modules, snap.CROWN_ESTATE,
                        types.SimpleNamespace(pull=corrected_without_a_new_date, out_dir=folder))
    code, report = run(capsys, "--only", "crown_estate")
    assert code == 0 and list(report) == ["crown_estate"]
    assert report["crown_estate"].endswith("; WARNING: the table downloaded now differs from this file's")

    def needs_a_missing_package(name):
        raise ModuleNotFoundError("No module named 'notinstalled'", name="notinstalled")

    monkeypatch.setattr(snap, "import_module", needs_a_missing_package)
    code, report = run(capsys, "--only", "crown_estate")
    assert code == 1 and status(report["crown_estate"]) == "failed" and "notinstalled" in report["crown_estate"]


def test_the_crown_estate_page_counts_as_written_only_if_the_call_wrote_it(raw, capsys, monkeypatch):
    page = raw.dir / "crown_estate" / PAGE
    page.parent.mkdir()
    page.write_text(HEADING)
    ahead = (int(time.time()) + 3_600) * 10**9  # stamped later than the run (a copied file, a clock ahead); whole
    #                                             seconds, which every file system keeps exactly (NTFS: 100 ns)
    os.utime(page, ns=(ahead, ahead))
    code, report = run(capsys, "--only", "crown_estate")
    assert code == 0 and raw.calls == ["crown_estate"] and status(report["crown_estate"]) == "already there"
    assert page.stat().st_mtime_ns == ahead and page.read_text() == HEADING

    def rewrites(archived=False):                # a call that writes the page again changes its modification time
        page.write_text(HEADING)
        return [page]

    monkeypatch.setattr(raw.crown, "pull", rewrites)
    code, report = run(capsys, "--only", "crown_estate")
    assert code == 0 and status(report["crown_estate"]) == "written" and PAGE in report["crown_estate"]

    def cut_short(archived=False):               # a new page half written when the disk fills up
        (page.parent / "wind_farm_ownership_20251231.html").write_text("<h2>UK operational and under")
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(raw.crown, "pull", cut_short)
    code, report = run(capsys, "--only", "crown_estate")
    assert code == 1 and status(report["crown_estate"]) == "failed" and "No space left" in report["crown_estate"]
    assert "removed wind_farm_ownership_20251231.html" in report["crown_estate"]
    assert contents(page.parent) == {PAGE: HEADING.encode()}


def test_only_the_crown_estate_pullers_pages_are_looked_at(raw, capsys, monkeypatch):
    folder = raw.crown.out_dir()
    folder.mkdir()
    (folder / PAGE).write_text(HEADING)
    notes = folder / "notes.txt"                 # no page: a file saved in the folder by hand while the puller runs

    def page_kept_while_notes_are_saved(archived=False):
        notes.write_text("checked against the operational report")
        return [folder / PAGE]

    monkeypatch.setattr(raw.crown, "pull", page_kept_while_notes_are_saved)
    code, report = run(capsys, "--only", "crown_estate")
    assert code == 0 and status(report["crown_estate"]) == "already there" and PAGE in report["crown_estate"]
    assert "notes.txt" not in report["crown_estate"]

    def cut_short_while_notes_are_saved(archived=False):
        (folder / "wind_farm_ownership_20251231.html").write_text("<h2>UK operational and under")
        (folder / "notes_2.txt").write_text("a second note")
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(raw.crown, "pull", cut_short_while_notes_are_saved)
    code, report = run(capsys, "--only", "crown_estate")
    assert code == 1 and "removed wind_farm_ownership_20251231.html, written by this run" in report["crown_estate"]
    assert "notes" not in report["crown_estate"]
    assert sorted(p.name for p in folder.iterdir()) == ["notes.txt", "notes_2.txt", PAGE]

    # the pages are those of the puller's own FILE_PATTERN, where it has one
    monkeypatch.setattr(raw.crown, "FILE_PATTERN", "ownership_*.htm", raising=False)

    def named_otherwise(archived=False):
        (folder / "ownership_20251231.htm").write_text(HEADING)
        return [folder / "ownership_20251231.htm"]

    monkeypatch.setattr(raw.crown, "pull", named_otherwise)
    code, report = run(capsys, "--only", "crown_estate")
    assert code == 0 and status(report["crown_estate"]) == "written"
    assert report["crown_estate"].split()[2] == "ownership_20251231.htm"           # the page this call wrote


def test_long_errors_and_warnings_keep_their_start_and_end(raw, capsys, monkeypatch):
    query = "&".join(f"bmUnit=T_UNIT-{i}" for i in range(200))

    def busy(start, end):
        raise requests.HTTPError(f"429 Client Error: Too Many Requests for url: https://data.elexon.co.uk/bmrs/api/"
                                 f"v1/reference/bmunits/all?{query} (retry after 60 seconds)")

    def warns_at_length(archived=False):
        print("  WARNING: " + "the table downloaded now differs from this file's " * 20 + "(end of the warning)")
        return [raw.crown.out_dir() / PAGE]

    monkeypatch.setattr(raw.elexon, "pull_bmunits", busy)
    monkeypatch.setattr(raw.crown, "pull", warns_at_length)
    code, report = run(capsys, "--only", "bmunits", "crown_estate")
    error = report["bmunits"]
    assert code == 1 and status(error) == "failed" and len(error) == LINE_START + 2 * snap.CLIP + 5
    assert error[LINE_START:].startswith("HTTPError: 429 Client Error: Too Many Requests for url: https://")
    assert " ... " in error and error.endswith("T_UNIT-199 (retry after 60 seconds)")
    warning = report["crown_estate"].rsplit("; ", 1)[1]
    assert len(warning) == 2 * snap.CLIP + 5 and " ... " in warning
    assert warning.startswith("WARNING: the table downloaded now differs") and warning.endswith("(end of the warning)")


def test_the_files_looked_for_are_those_the_real_pullers_write(tmp_path, monkeypatch, capsys):
    """The real pullers on canned answers: their files are today's snapshot (a second run pulls nothing), the CM
    register's contact columns are not in it, and the page The Crown Estate's puller writes is one of the pages the
    script lists (a second run finds its as-at date kept)."""
    monkeypatch.setattr(cfg, "raw_dir", lambda: tmp_path)
    from gbpowerdata.pull import elexon_pull

    monkeypatch.setattr(elexon_pull, "RAW_DIR", tmp_path)
    monkeypatch.setattr(elexon_pull, "_get", lambda url, params, timeout=60: UNITS)
    csv = ("\ufeffCMU ID,Name of Applicant,Secondary Trading Contact_Telephone,Secondary Trading Contact_Email,"
           "Parent Company\nX1,Foo Ltd,0123,a@b.c,Foo plc\n").encode("utf-8")   # NESO's files start with a BOM
    monkeypatch.setattr(cm_register_pull, "resources",
                        lambda: [{"name": name, "url": name} for name in cm_register_pull.RESOURCES])
    monkeypatch.setattr(cm_register_pull, "download", lambda url, tries=4: csv)
    page = (f"<html><body>{HEADING}<table><tr><th>Fully operational projects</th><th>Operator</th>"
            "<th>Share ownership %</th></tr><tr><td>Alpha Bank</td><td>Alpha Generation Ltd</td>"
            "<td>60% Alpha Generation Ltd; 40% Beta Optimiser Ltd</td></tr></table></body></html>").encode()
    crown = importlib.import_module(snap.CROWN_ESTATE)                     # the module the script imports
    monkeypatch.setattr(crown, "download", lambda url, tries=4: page)
    code, report = run(capsys)
    assert code == 0 and list(report) == ["bmunits", "cm", "crown_estate"]  # the pullers' own lines stay out
    assert {status(line) for line in report.values()} == {"written"}
    assert report["crown_estate"].split()[2] == PAGE and "WARNING" not in report["crown_estate"]
    cmu = pd.read_csv(cm_register_pull.out_dir() / f"cmu_{snap.local_day()}.csv")
    assert cmu.columns.tolist() == ["CMU ID", "Name of Applicant", "Parent Company"]
    code, report = run(capsys)
    assert code == 0 and {status(line) for line in report.values()} == {"already there"}
    assert "WARNING" not in "".join(report.values())
