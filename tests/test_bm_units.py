"""The BM-unit register by year (gbpowerdata.build.bm_units) on synthetic data: technology from the register's
fuel type and names; a unit is active in the years it produced, dated by its first and last day of output (not
by its file's first and last line, which zero notifications stretch); metering noise and one-off readings do not
count; a battery is dated by its files; a unit listed at zero capacity that ran gets its notified capacity; a year
takes the register snapshot of its as-of date, else a later one marked as a proxy."""
import pandas as pd
import pytest

from gbpowerdata import config as cfg
from gbpowerdata.build import bm_units as B

T = pd.Timestamp
WINDOWS = {"fpn": (T("2016-03-01"), T("2026-01-01")), "b1610": (T("2019-02-01"), T("2026-01-01")),
           "bod": (T("2022-01-01"), T("2026-01-01"))}


def files(fpn=None, out=None, any_=None, bod=None, b1610=None):
    a = {}
    if fpn:
        a["fpn"] = {"file": fpn, "output": out, "output_any": any_ if any_ is not None else out}
    if b1610:
        a["b1610"] = {"file": b1610[0], "output": b1610[1], "output_any": b1610[1]}
    if bod:
        a["bod"] = {"file": bod, "output": None, "output_any": None}
    return a


def test_technology_from_fuel_type_then_names_then_the_unit_codes_letter():
    assert B.classify_tech("CCGT", "T_X-1", "") == "ccgt"
    assert B.classify_tech("OTHER", "E_ARBRB-1", "E_ARBRB-1") == "battery"          # type letter B
    assert B.classify_tech(None, "T_ABCW-1", "Some Offshore WF") == "wind"           # the name decides
    assert B.classify_tech(None, "T_ABCW-1", "T_ABCW-1") == "wind"                   # letter W, names say nothing
    assert B.classify_tech("OTHER", "E_GEN-1", "Peaking Power Ltd") == "other"
    assert B.classify_tech(None, "E_SOLS-1", "E_SOLS-1") == "solar"
    # whole words: a repowered wind farm and a PV power park are not "other", a coal station's company is
    assert B.classify_tech(None, "T_HAGHW-2", "Hagshaw Repower 2", "HAGSHAW HILL REPOWERING LTD") == "wind"
    assert B.classify_tech(None, "T_TEBWS-1", "Tebworth PV Power Park", "Sundon Green Limited") == "solar"
    assert B.classify_tech(None, "T_RUGPS-6", "Rugeley B Unit 06", "Rugeley Power Generation Ltd") == "other"
    # a closed unit the register lists without its fuel type takes its documented technology
    assert B.classify_tech(None, "T_FIDL-1", "Fiddler's Ferry 1", "Keadby Generation Limited") == "coal"
    assert B.classify_tech(None, "T_FIDL-2G", "Fiddler's Ferry GT2", "Keadby Generation Limited") == "ocgt"
    assert B.classify_tech(None, "T_CRUAD-1", "T_CRUAD-1", "Drax Pumped Storage Limited") == "pumped_storage"


def test_a_unit_is_dated_by_its_output_not_by_its_files_first_and_last_line():
    # a retired unit notifying zeros to the end of the pull (Hinkley Point B)
    w = B.activity_window(files(fpn=(T("2016-03-01"), T("2026-01-01")), out=(T("2016-03-21"), T("2022-08-01"))), WINDOWS)
    assert w["active_to"] == T("2022-08-01") and w["activity_source"] == "fpn"
    assert B.active_in(2022, w["active_from"], w["active_to"]) and not B.active_in(2023, w["active_from"], w["active_to"])
    # a new unit notifying zeros before it first generates (Keadby 2)
    w = B.activity_window(files(fpn=(T("2020-10-01"), T("2026-01-01")), out=(T("2021-10-31"), T("2025-12-31"))), WINDOWS)
    assert w["active_from"] == T("2021-10-31") and w["active_to"] is None
    assert not B.active_in(2020, w["active_from"], w["active_to"]) and B.active_in(2025, w["active_from"], w["active_to"])
    # output from the start of the FPN pull: there before it
    w = B.activity_window(files(fpn=(T("2016-03-01"), T("2026-01-01")), out=(T("2016-03-02"), T("2025-12-31"))), WINDOWS)
    assert w["active_from"] is None and B.active_in(2018, w["active_from"], w["active_to"])


def test_the_kind_that_saw_the_unit_first_decides_whether_its_start_is_censored():
    # metered output from the start of B1610 (2019) but notified output from 2017: dated 2017, not censored
    w = B.activity_window(files(fpn=(T("2016-03-01"), T("2026-01-01")), out=(T("2017-05-01"), T("2025-12-31")),
                                b1610=((T("2019-02-01"), T("2026-01-01")), (T("2019-02-01"), T("2025-12-31")))), WINDOWS)
    assert w["active_from"] == T("2017-05-01") and w["activity_source"] == "b1610+fpn"


def test_files_without_output_mean_inactive_and_units_without_files_follow_the_register():
    w = B.activity_window(files(fpn=(T("2016-03-01"), T("2026-01-01")), out=None), WINDOWS)
    assert w["activity_source"] == "no_output" and not B.active_in(2025, w["active_from"], w["active_to"])
    assert B.activity_window({}, WINDOWS, "T_RATS-1")["activity_source"] == "retirement_table"
    assert B.activity_window({}, WINDOWS, "T_X-1", capacity_mw=0.0)["activity_source"] == "zero_capacity"
    w = B.activity_window({}, WINDOWS, "T_X-1", capacity_mw=50.0, fuel_known=False)
    assert w["activity_source"] == "no_evidence" and not B.active_in(2025, w["active_from"], w["active_to"])
    assert B.activity_window({}, WINDOWS, "T_X-1", capacity_mw=50.0)["activity_source"] == "assumed"
    # a battery is dated by its files: without one there is no evidence, whatever its fuel type
    assert B.activity_window({}, WINDOWS, "T_XB-1", capacity_mw=50.0, tech="battery")["activity_source"] == "no_evidence"


def test_a_battery_notifying_zero_is_dated_by_its_files_and_storage_counts_charging():
    # zero notifications only: the notification file dates the battery
    w = B.activity_window(files(fpn=(T("2023-04-02"), T("2026-01-01")), out=None), WINDOWS, tech="battery")
    assert w["active_from"] == T("2023-04-02") and w["active_to"] is None and w["activity_source"] == "fpn_file"
    # its bids date it before its notifications
    w = B.activity_window(files(fpn=(T("2023-04-02"), T("2026-01-01")), out=None, bod=(T("2022-06-01"), T("2026-01-01"))),
                          WINDOWS, tech="battery")
    assert w["active_from"] == T("2022-06-01") and w["activity_source"] == "bod_file"
    # pumped storage that only pumped in the period still counts, a generator would not
    a = files(fpn=(T("2016-03-01"), T("2026-01-01")), out=None, any_=(T("2016-03-01"), T("2025-12-31")))
    assert B.activity_window(a, WINDOWS, tech="pumped_storage")["activity_source"] == "fpn"
    assert B.activity_window(a, WINDOWS, tech="ccgt")["activity_source"] == "no_output"


def test_output_needs_the_thresholds_and_a_day_of_several_half_hours(tmp_path):
    rows = [{"settlementDate": "2024-01-01", "settlementPeriod": p, "levelFrom": 400, "levelTo": 400} for p in range(1, 49)]
    rows += [{"settlementDate": "2024-06-01", "settlementPeriod": 1, "levelFrom": 25, "levelTo": 25}]        # one half-hour
    rows += [{"settlementDate": "2024-07-01", "settlementPeriod": p, "levelFrom": 0.4, "levelTo": 0.4} for p in range(1, 49)]
    rows += [{"settlementDate": "2024-08-01", "settlementPeriod": p, "levelFrom": -50, "levelTo": -50} for p in range(1, 49)]
    # six rows but three half-hours: an FPN half-hour often holds several segments (Drax's gas turbines, 2025)
    rows += [{"settlementDate": "2024-10-01", "settlementPeriod": p, "levelFrom": 30, "levelTo": 30}
             for p in (31, 32, 33) for _ in range(2)]
    rows += [{"settlementDate": "2025-12-31", "settlementPeriod": 48, "levelFrom": 0, "levelTo": 0}]
    pd.DataFrame(rows).to_csv(tmp_path / "u.csv", index=False)
    s = B._output_span(str(tmp_path / "u.csv"), "fpn")
    assert s["file"] == (T("2024-01-01"), T("2025-12-31"))
    # not the lone half-hour, not 0.4 MW, not -50 MW, not three half-hours in six segments
    assert s["output"] == (T("2024-01-01"), T("2024-01-01"))
    assert s["output_any"] == (T("2024-01-01"), T("2024-08-01"))   # charging counts for storage
    pd.DataFrame({"settlementDate": ["2024-05-01"] * 4 + ["2024-09-01"] * 6, "settlementPeriod": [*range(1, 5), *range(1, 7)],
                  "quantity": [0.001] * 4 + [10.0] * 6}).to_csv(tmp_path / "m.csv", index=False)
    assert B._output_span(str(tmp_path / "m.csv"), "b1610")["output"] == (T("2024-09-01"), T("2024-09-01"))


@pytest.fixture
def raw(tmp_path, monkeypatch):
    for k in ("fpn", "b1610", "bod"):
        (tmp_path / k).mkdir()
    pd.DataFrame([
        {"elexonBmUnit": "T_OLD-1", "nationalGridBmUnit": "OLD-1", "bmUnitName": "Old nuclear", "leadPartyId": "P1",
         "leadPartyName": "Nuclear Co", "fuelType": "NUCLEAR", "generationCapacity": 0.0},
        {"elexonBmUnit": "T_NEW-1", "nationalGridBmUnit": "NEW-1", "bmUnitName": "New CCGT", "leadPartyId": "P2",
         "leadPartyName": "Gas Co", "fuelType": "CCGT", "generationCapacity": 800.0},
        {"elexonBmUnit": "E_BATB-1", "nationalGridBmUnit": "BATB-1", "bmUnitName": "Battery", "leadPartyId": "P3",
         "leadPartyName": "Optimiser Ltd", "fuelType": "OTHER", "generationCapacity": 50.0},
        {"elexonBmUnit": "2__SUPPLY", "nationalGridBmUnit": "", "bmUnitName": "Supplier", "leadPartyId": "P4",
         "leadPartyName": "Supplier", "fuelType": "", "generationCapacity": 0.0},
    ]).assign(demandCapacity=0.0, gspGroupName="_A", fpnFlag=True, eic="").to_csv(tmp_path / "bm_units_20260605.csv", index=False)

    def fpn(unit, days, level):
        pd.DataFrame([{"settlementDate": d, "settlementPeriod": p, "timeFrom": "", "timeTo": "",
                       "levelFrom": lvl, "levelTo": lvl}
                      for d, lvl in zip(days, level) for p in range(1, 49)]).to_csv(tmp_path / "fpn" / f"{unit}.csv", index=False)

    fpn("T_OLD-1", ["2016-03-01", "2020-06-30", "2025-12-31"], [540, 540, 0])       # ran to mid-2020, zeros after
    fpn("T_NEW-1", ["2016-03-01", "2022-03-01", "2025-12-31"], [0, 790, 790])       # zeros until 2022
    fpn("E_BATB-1", ["2023-05-01", "2025-12-31"], [0, 0])                           # a battery notifying zero
    monkeypatch.setattr(cfg, "raw_dir", lambda: tmp_path)
    return tmp_path


def test_build_year_on_a_synthetic_register(raw):
    y2019, y2023 = (B.build_year(y).set_index("unit_id") for y in (2019, 2023))
    assert set(y2019.index) == {"T_NEW-1", "T_OLD-1", "E_BATB-1"}                   # no supplier unit
    assert y2019.loc["T_OLD-1", "active"] and not y2023.loc["T_OLD-1", "active"]
    assert y2019.loc["T_OLD-1", "capacity_mw"] == 540 and y2019.loc["T_OLD-1", "capacity_source"] == "fpn_max"
    assert not y2019.loc["T_NEW-1", "active"] and y2023.loc["T_NEW-1", "active"]
    assert not y2019.loc["E_BATB-1", "active"] and y2023.loc["E_BATB-1", "active"]
    assert y2023.loc["E_BATB-1", "is_battery"] and y2023.loc["E_BATB-1", "activity_source"] == "fpn_file"
    assert (y2019["activity_year"] == 2019).all() and (y2023["activity_year"] == 2023).all()   # the files reach both


def test_a_year_takes_the_snapshot_of_its_date_else_a_later_one_as_proxy(tmp_path, monkeypatch):
    for stamp in ("20240115", "20260605"):
        (tmp_path / f"bm_units_{stamp}.csv").write_text("elexonBmUnit\n")
    monkeypatch.setattr(cfg, "raw_dir", lambda: tmp_path)
    assert B.snapshot_for(T("2023-12-31")) == (T("2024-01-15"), "proxy")
    assert B.snapshot_for(T("2024-12-31")) == (T("2024-01-15"), "register")
    assert B.snapshot_for(T("2026-07-01")) == (T("2026-06-05"), "register")
    assert B.as_of(2019) == T("2019-12-31") and B.as_of(2999) == pd.Timestamp.today().normalize()


def test_a_documented_closure_ends_activity_even_where_the_files_show_output_later():
    # Drax unit 5: its Capacity Market obligation ended in September 2022; in the winter 2022/23 contingency it
    # ran until March 2023 outside the market, on the system operator's instruction (its metered output shows it)
    out = files(fpn=(T("2016-03-01"), T("2026-01-01")), out=(T("2016-03-02"), T("2022-09-28")),
                b1610=((T("2019-02-01"), T("2026-01-01")), (T("2019-02-01"), T("2023-03-30"))))
    w = B.activity_window(out, WINDOWS, "T_DRAXX-5")
    assert w["active_to"] == T("2022-09-30") and w["activity_source"] == "b1610+fpn+retirement_table"
    assert B.active_in(2022, w["active_from"], w["active_to"]) and not B.active_in(2023, w["active_from"], w["active_to"])
    # a closure on or after the last output changes nothing (Ratcliffe ran to its closure)
    out = files(fpn=(T("2016-03-01"), T("2026-01-01")), out=(T("2016-03-02"), T("2024-09-30")))
    w = B.activity_window(out, WINDOWS, "T_RATS-1")
    assert w["active_to"] == T("2024-09-30") and w["activity_source"] == "fpn"


def test_a_window_opening_after_the_panel_start_says_nothing_about_the_years_before():
    # Lynemouth unit 1: metered from the B1610 window's start (Feb 2019) but in an outage until March: there in 2018
    a = files(b1610=((T("2019-02-01"), T("2026-01-01")), (T("2019-03-04"), T("2025-12-31"))))
    w = B.activity_window(a, WINDOWS, "E_LYNE1", tech="biomass")
    assert w["active_from"] is None and B.active_in(2018, w["active_from"], w["active_to"])
    # a unit metered only from later on is dated by its first output
    a = files(b1610=((T("2019-06-01"), T("2026-01-01")), (T("2019-06-20"), T("2025-12-31"))))
    assert B.activity_window(a, WINDOWS, "E_NEW1", tech="biomass")["active_from"] == T("2019-06-20")
    # the FPN window opens before the panel: there a file from its start still dates the unit by its first output
    a = files(fpn=(T("2016-03-01"), T("2026-01-01")), out=(T("2017-05-01"), T("2025-12-31")))
    assert B.activity_window(a, WINDOWS)["active_from"] == T("2017-05-01")


def test_a_year_the_files_do_not_reach_carries_the_last_reached_years_activity():
    early = {"fpn": (T("2016-03-01"), T("2020-01-01")), "b1610": (T("2019-02-01"), T("2020-01-01"))}
    assert B.observed_year(2019, early) == 2019 and B.observed_year(2023, early) == 2019
    assert B.observed_year(2018, WINDOWS) == 2018 and B.observed_year(2025, WINDOWS) == 2025
    # a reactor in an outage at the end of the pull (Hartlepool's last output 29 Oct) counts in the years after it
    w = B.activity_window(files(fpn=(T("2016-03-01"), T("2020-01-01")), out=(T("2016-03-02"), T("2019-10-29"))), early)
    assert w["active_to"] == T("2019-10-29") and B.active_in(B.observed_year(2023, early), w["active_from"], w["active_to"])
    # a unit without evidence is inactive in every year, reached or not
    w = B.activity_window({}, WINDOWS, "T_X-1", capacity_mw=50.0, fuel_known=False)
    assert not any(B.active_in(y, w["active_from"], w["active_to"]) for y in range(2018, 2031))


def test_pull_missing_dates_every_unit_without_a_file_that_notifies():
    # Enderby's battery (fuel type OTHER) and an embedded CCGT the rules counted as active throughout ("assumed")
    # are pulled alike; a unit that submits no physical notifications has none to pull
    reg = pd.DataFrame({"unit_id": ["T_BLANK-1", "T_ENDRB-1", "E_SHOS-1", "E_QUIET-1", "T_FILED-1"],
                        "fuel_type": [None, "OTHER", "CCGT", "CCGT", None],
                        "tech": ["other", "battery", "ccgt", "ccgt", "wind"],
                        "fpn_flag": [True, True, "True", False, True]})
    assert B.undated_units(reg, {"T_FILED-1"}) == ["T_BLANK-1", "T_ENDRB-1", "E_SHOS-1"]


def test_a_pulled_file_keeps_to_the_window_of_the_fpn_files(tmp_path, monkeypatch):
    (tmp_path / "fpn").mkdir()
    for unit, days in (("T_A-1", ["2016-03-01", "2020-01-01"]), ("T_B-1", ["2018-05-01", "2026-01-01"])):
        pd.DataFrame({"settlementDate": days, "settlementPeriod": [1, 1], "levelFrom": [5, 5], "levelTo": [5, 5]}).to_csv(
            tmp_path / "fpn" / f"{unit}.csv", index=False)
    monkeypatch.setattr(cfg, "raw_dir", lambda: tmp_path)
    assert B.fpn_window() == (T("2016-03-01"), T("2026-01-01"))


def test_a_unit_pulled_without_notifications_is_inactive_in_every_year():
    # Dogger Bank B: its notifications pulled over the whole window came back empty; a battery likewise
    empty = {"fpn": {"file": (T("2016-03-01"), T("2026-01-01")), "output": None, "output_any": None, "empty": True}}
    for tech in ("wind", "battery"):
        w = B.activity_window(empty, WINDOWS, "T_DBBWO-1", 302.4, True, tech)
        assert w["activity_source"] == "no_notifications"
        assert not any(B.active_in(y, w["active_from"], w["active_to"]) for y in range(2018, 2027))
    assert B.pull_windows({"T_DBBWO-1": empty}) == {}                     # nor does it set the window


def test_the_record_of_empty_pulls_is_read_unless_a_file_says_more(tmp_path, monkeypatch):
    (tmp_path / "fpn").mkdir()
    pd.DataFrame({"settlementDate": ["2024-01-01"] * 4, "settlementPeriod": [1, 2, 3, 4], "levelFrom": [9] * 4,
                  "levelTo": [9] * 4}).to_csv(tmp_path / "fpn" / "T_LATER-1.csv", index=False)
    monkeypatch.setattr(cfg, "raw_dir", lambda: tmp_path)
    window = (T("2016-03-01"), T("2026-01-01"))
    B.record_empty_pulls(["T_DBBWO-1", "T_LATER-1"], window)
    B.record_empty_pulls(["T_DBBWO-1"], window)                           # recorded once
    assert [u for u, _, _ in B.empty_pulls()] == ["T_DBBWO-1", "T_LATER-1"]
    a = B.activity_files()
    assert a["T_DBBWO-1"]["fpn"]["empty"] and a["T_DBBWO-1"]["fpn"]["file"] == window
    assert not a["T_LATER-1"]["fpn"].get("empty")                          # its file wins over the record
