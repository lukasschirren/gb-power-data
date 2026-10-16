"""The notifications of the units that left Elexon's register (gbpowerdata.pull.fpn_left_register_pull) on synthetic
days: only units no kept snapshot holds are kept; a day with output needs bm_units' thresholds; the table's units are
cut to FPN files, a unit without a row is recorded as an empty pull, and a file this module did not write is never
overwritten."""
import pandas as pd
import pytest

from gbpowerdata import config as cfg
from gbpowerdata.build import bm_units as B
from gbpowerdata.pull import fpn_left_register_pull as L
from gbpowerdata.pull import fpn_pull

T = pd.Timestamp


def row(ngc, day, sp, level, unit=None):
    return {"dataset": "PN", "nationalGridBmUnit": ngc, "bmUnit": unit, "settlementDate": day, "settlementPeriod": sp,
            "timeFrom": f"{day}T{(sp - 1) // 2:02d}:{30 * ((sp - 1) % 2):02d}:00Z", "timeTo": "", "levelFrom": level,
            "levelTo": level}


def test_only_units_no_kept_snapshot_holds_by_either_id_are_kept():
    data = [row("COTPS-1", "2019-01-15", 1, 500), row("RATS-1", "2019-01-15", 1, 500, "T_RATS-1"),
            row("NEWID-1", "2019-01-15", 1, 5, "T_X-1"), row("", "2019-01-15", 1, 5)]
    kept = L.unregistered_rows(data, {"RATS-1", "T_RATS-1", "T_X-1"})
    assert kept["nationalGridBmUnit"].tolist() == ["COTPS-1"] and kept.columns.tolist() == L.COLUMNS


def test_a_day_with_output_needs_the_thresholds_of_bm_units():
    rows = [row("A-1", "2019-01-15", p, 400) for p in range(1, 5)]           # four half-hours: a day with output
    rows += [row("A-1", "2019-01-16", p, 400) for p in range(1, 4)]          # three: not
    rows += [row("B-1", "2019-01-15", p, 0.5) for p in range(1, 49)]         # under 1 MW all day: not
    out, spans = L.scan_month(pd.DataFrame(rows, columns=L.COLUMNS))
    assert out.values.tolist() == [["A-1", T("2019-01-15")]]
    assert spans.loc["A-1", "max_level_mw"] == 400 and spans.loc["B-1", "last_row"] == T("2019-01-15")


def test_the_window_is_whole_months():
    assert [str(m) for m in L.months("2016-03-01", "2016-05-01")] == ["2016-03", "2016-04"]
    assert L.window("2016-03-15", "2016-04-02") == (T("2016-03-01"), T("2016-05-01"))


@pytest.fixture
def folders(tmp_path, monkeypatch):
    for d in ("raw", "processed", "reference"):
        (tmp_path / d).mkdir()
    monkeypatch.setattr(cfg, "raw_dir", lambda: tmp_path / "raw")
    monkeypatch.setattr(cfg, "processed_dir", lambda: tmp_path / "processed")
    monkeypatch.setattr(cfg, "reference_dir", lambda: tmp_path / "reference")
    pd.DataFrame([{"unit_id": u, "ngc_id": n, "unit_name": u, "station": "Gone", "fuel_type": "COAL",
                   "capacity_mw": "500", "eic": "", "closed": "2019-09-30", "sources": "s", "evidence": "e",
                   "checked": "2026-10-14"} for u, n in (("T_GONE-1", "GONE-1"), ("T_QUIET-1", "QUIET-1"))]).to_csv(
        tmp_path / "reference" / B.LEFT_REGISTER, index=False)
    pd.DataFrame({"station_name": ["Gone"], "elexon_bmu_id": ["T_GONE-1"], "ngc_bmu_id": ["GONE-1"]}).to_csv(
        tmp_path / "reference" / "bmu_crosswalk.csv", index=False)
    # a snapshot listing one unit with Elexon's id and one by its National Grid id alone
    pd.DataFrame({"elexonBmUnit": ["T_RATS-1", ""], "nationalGridBmUnit": ["RATS-1", "OTHER-1"]}).to_csv(
        tmp_path / "raw" / "bm_units_20260605.csv", index=False)
    (tmp_path / "raw" / L.MONTHS).mkdir()
    for month, day in (("2016-03", "2016-03-02"), ("2016-04", "2016-04-02")):
        rows = [row("GONE-1", day, p, 480) for p in range(1, 49)] + [row("OTHER-1", day, 1, 50)]
        pd.DataFrame(rows, columns=L.COLUMNS).to_csv(tmp_path / "raw" / L.MONTHS / f"{month}.csv.gz", index=False,
                                                    compression="gzip")
    return tmp_path


def test_the_tables_units_are_cut_to_fpn_files_and_a_silent_one_is_an_empty_pull(folders):
    scan = L.cut("2016-03-01", "2016-05-01")
    f = pd.read_csv(folders / "raw" / "fpn" / "T_GONE-1.csv")
    assert f.columns.tolist() == fpn_pull.KEEP and len(f) == 96
    assert [u for u, _, _ in B.empty_pulls()] == ["T_QUIET-1"]
    rec = pd.read_csv(folders / "raw" / L.RECORD)
    assert rec["unit_id"].tolist() == ["T_GONE-1"] and rec["window_to"].tolist() == ["2016-05-01"]
    s = scan.set_index("ngc_id")
    assert s.loc["GONE-1", "output_days"] == 2 and s.loc["GONE-1", "in_table"]
    assert s.loc["GONE-1", "psd_unit_id"] == "T_GONE-1" and s.loc["GONE-1", "first_output"] == T("2016-03-02")
    assert s.loc["OTHER-1", "output_days"] == 0 and not s.loc["OTHER-1", "in_table"]
    assert s.loc["OTHER-1", "snapshot_ngc_only"] and not s.loc["GONE-1", "snapshot_ngc_only"]
    assert L.known_ids() == {"T_RATS-1", "RATS-1"} and L.ngc_only_ids() == {"OTHER-1"}
    assert (folders / "processed" / L.SCAN).exists()
    assert len(L.cut("2016-03-01", "2016-05-01")) == len(scan)                  # a second cut rewrites its own files


def test_the_sample_of_the_later_years_lists_the_unregistered_units_with_output(folders):
    def get(t0, t1):                    # an hour of the stream: a unit the table lacks, a registered one, one at zero
        day = f"{t0:%Y-%m-%d}"
        return [row("LATER-1", day, 35, 48), row("RATS-1", day, 35, 500, "T_RATS-1"), row("ZERO-1", day, 35, 0)]

    s = L.sample("2021-01-01", "2021-01-22", every=7, get=get).set_index("ngc_id")
    assert s.index.tolist() == ["LATER-1"]
    assert (s.loc["LATER-1", "samples"], s.loc["LATER-1", "max_level_mw"]) == (3, 48)
    assert s.loc["LATER-1", "first_sampled"] == T("2021-01-01") and s.loc["LATER-1", "last_sampled"] == T("2021-01-15")
    assert (folders / "processed" / L.SAMPLE).exists()


def test_months_must_be_pulled_first_and_a_file_from_elsewhere_is_never_overwritten(folders):
    with pytest.raises(FileNotFoundError):
        L.cut("2016-03-01", "2016-07-01")
    (folders / "raw" / "fpn").mkdir()
    pd.DataFrame(columns=fpn_pull.KEEP).to_csv(folders / "raw" / "fpn" / "T_GONE-1.csv", index=False)
    with pytest.raises(FileExistsError):
        L.cut("2016-03-01", "2016-05-01")
