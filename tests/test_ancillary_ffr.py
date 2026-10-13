"""The Firm Frequency Response sources of gbpowerdata.build.ancillary_services on synthetic rows shaped like NESO's
files: post-tender reports read by column position after a check of their header, the service days of both date
conventions and Excel serial dates, a frame per day type with bank holidays and clock changes, one report per round,
the weekly auction files' weeks given in UTC, tender rounds as separate contracts, NESO's spellings of unit ids, and
the puller's names for the reports. No data/ and no network needed."""
import csv
from datetime import datetime

import pandas as pd
import pytest

from gbpowerdata.build import ancillary_services as A
from gbpowerdata.pull import ancillary_pull as AP

T = pd.Timestamp


def _labels() -> list[str]:
    h = [""] * A.FFR_WIDTH
    h[0], h[1], h[3], h[4], h[6], h[7], h[8] = ("Tender Ref", "Status", "Company Name", "Tendered Unit", "Generation Type",
                                                "Start Date", "End Date")
    for j, day in ((11, "Mon-Fri"), (14, "Saturday"), (17, "Sunday/Bank Holidays")):
        h[j], h[j + 1], h[j + 2] = (f"Tendered Frames per Service Day - {w} ({day})" for w in ("From", "To", "Duration"))
    h[20], h[21] = "Tendered Prices - Availability Fee (\xa3/h)", "Tendered Prices - Nomination Fee (\xa3/h)"
    for j, w in zip(range(28, 35), ("Primary", "Primary", "Primary", "Secondary", "Secondary", "High Frequency",
                                    "High Frequency")):
        h[j] = f"{w} Response (max.) (MW)"
    return h


def _tender(ref, status, unit, start, end, frames, fee, dynamic_mw=0.0, static_mw=0.0, tech="Battery") -> list:
    r = [None] * A.FFR_WIDTH
    r[0], r[1], r[3], r[4], r[6], r[7], r[8] = ref, status, "Co", unit, tech, start, end
    for j, (a, b, h) in zip((11, 14, 17), frames):
        r[j], r[j + 1], r[j + 2] = a, b, h
    r[20], r[29], r[39] = fee, dynamic_mw or None, static_mw or None
    return r


def test_a_report_is_read_by_column_position_after_its_header_is_checked(tmp_path):
    path = tmp_path / "ffr_post_tender_tr139.csv"
    rows = [_labels(), _tender("139", None, "Ex-FFR-1", "", "", [("2300", "700", "8")] * 3, "100"),   # NESO's example
            _tender("139.001", "Accepted", "REST-1", "31/07/2021", "31/08/2021", [("2300", "1500", "16")] * 3, "168",
                    dynamic_mw=6.4),
            _tender("139.002", "Rejected", "REST-1", "01/08/2021", "31/08/2021", [("1500", "2300", "8")] * 3, "180",
                    dynamic_mw=6.4)]
    with open(path, "w", encoding="cp1252", newline="") as f:
        csv.writer(f).writerows(rows)
    t = A.ffr_rows(path)
    assert t[A.FFR_COLUMNS["ref"]].tolist() == ["139.001", "139.002"]
    moved = [_labels()[:20] + [""] + _labels()[20:-1]] + rows[2:]             # a column inserted before the fees
    with open(path, "w", encoding="cp1252", newline="") as f:
        csv.writer(f).writerows(moved)
    with pytest.raises(AssertionError, match="layout"):
        A.ffr_rows(path)


def test_report_dates_take_excel_serials_and_day_first_text():
    assert A.report_date(43861) == T("2020-01-31") and A.report_date("44592") == T("2022-01-31")   # TR121, TR145
    assert A.report_date("31/07/2021") == T("2021-07-31") and A.report_date("01/08/2021") == T("2021-08-01")
    assert A.report_date(datetime(2019, 1, 1)) == T("2019-01-01")
    assert A.report_date("2021-03-31 00:00:00") == T("2021-03-31")
    assert pd.isna(A.report_date("#REF!"))


def test_service_days_of_both_date_conventions():
    # from 2020 a frame for August that begins at 23:00 is dated from 31 July; before, every tender from the 1st
    assert A.service_days(T("2021-07-31"), T("2021-08-31"))[[0, -1]].tolist() == [T("2021-08-01"), T("2021-08-31")]
    assert len(A.service_days(T("2021-08-01"), T("2021-08-31"))) == 31
    assert len(A.service_days(T("2019-01-01"), T("2019-01-31"))) == 31
    assert len(A.service_days(T("2021-03-31"), T("2021-03-31"))) == 1          # no later end: the day itself


def test_accepted_tenders_become_a_frame_per_service_day_by_day_type(monkeypatch):
    monkeypatch.setattr(A, "bank_holidays", lambda path=None: frozenset({T("2021-08-30"), T("2019-01-01")}))
    t = pd.DataFrame([
        _tender("139.001", "Accepted", "AG -GEDF02", "31/07/2021", "31/08/2021",
                [("2300", "1500", "16"), ("2300", "2300", "24"), ("2300", "700", "8")], "100", dynamic_mw=10.0),
        _tender("139.002", "Rejected", "AG -GEDF02", "01/08/2021", "31/08/2021", [("1500", "2300", "8")] * 3, "500",
                dynamic_mw=10.0),
        _tender("108.003", "Accepted", "OPEN-1", datetime(2019, 1, 1), datetime(2019, 1, 31),
                [("700", "1500", "8"), (None, None, None), (None, None, None)], "40", static_mw=5.0,
                tech="DSF: Load response"),
    ])
    d = A.ffr_tender(t, "ffr_post_tender_tr139")
    dyn, sta = d[d["product"] == "FFR-D"], d[d["product"] == "FFR-S"]
    assert len(dyn) == 31 and dyn["delivery_start"].min() == T("2021-07-31 22:00", tz="UTC")     # 23:00 BST
    hours = ((dyn["delivery_end"] - dyn["delivery_start"]).dt.total_seconds() / 3600).tolist()
    assert hours.count(24.0) == 4 and hours.count(8.0) == 6 and hours.count(16.0) == 21          # 30 Aug: bank holiday
    assert dyn["mw"].eq(10.0).all() and dyn["price_gbp_per_mw_h"].eq(10.0).all()                  # GBP 100/h on 10 MW
    assert len(sta) == 22 and sta["mw"].eq(5.0).all()                                            # weekdays, not 1 Jan
    assert dyn["result_id"].is_unique and dyn["unit"].iat[0] == "AG -GEDF02"


def test_a_frame_over_the_clock_change_counts_its_hours_in_utc(monkeypatch):
    monkeypatch.setattr(A, "bank_holidays", lambda path=None: frozenset())
    t = pd.DataFrame([_tender("135.001", "Accepted", "REST-1", "27/03/2021", "28/03/2021",
                              [("2300", "2300", "24")] * 3, "100", dynamic_mw=10.0)])
    d = A.ffr_tender(t, "ffr_post_tender_tr135")
    day = d[d["delivery_end"] == T("2021-03-28 22:00", tz="UTC")]             # Sunday 28 Mar: clocks go forward
    assert ((day["delivery_end"] - day["delivery_start"]).dt.total_seconds() / 3600).tolist() == [23.0]


def test_one_report_per_round_amended_first_then_the_csv(tmp_path):
    for name in ("ffr_post_tender_tr139.csv", "ffr_post_tender_tr139.xlsm", "ffr_post_tender_tr151.xlsm",
                 "ffr_post_tender_tr151_amended.csv", "ffr_post_tender_tr127.xlsx", "ffr_post_tender_tr127_amended.xlsx",
                 "eac_by_unit_current_20261007.csv", "eac_by_unit_current_20261010.csv", "eac_by_unit_fy2025.xlsx"):
        (tmp_path / name).write_text("")
    assert sorted(p.name for p, _, _ in A.raw_files(tmp_path)) == [
        "eac_by_unit_current_20261010.csv", "ffr_post_tender_tr127_amended.xlsx", "ffr_post_tender_tr139.csv",
        "ffr_post_tender_tr151_amended.csv"]


def test_weekly_auction_weeks_given_in_utc_are_read_as_utc():
    # the weekly auction files give EFA 1 at 22:00 from the clock change of 29 Mar 2020 into May 2020 (UTC), else 23:00
    t = pd.DataFrame({"Delivery Start": ["2020-04-04T22:00:00", "2020-06-06T23:00:00", "07/12/2019 23:00"],
                      "Delivery End": ["2020-04-05T02:00:00", "2020-06-07T03:00:00", "08/12/2019 03:00"],
                      "Service": ["DLH", "LFS", "DLH"], "Unit Name": ["AG-AEDF01"] * 3, "Company": ["EDF"] * 3,
                      "Cleared Volume": [6, 6, 6], "Clearing Price": [6.07, 1.5, 7.91], "Cancelled": ["", "", ""]})
    d = A.ffr_auction(t, "ffr_auction_by_unit_2019_2020")
    assert d["delivery_start"].tolist() == [T("2020-04-04 22:00", tz="UTC"), T("2020-06-06 22:00", tz="UTC"),
                                            T("2019-12-07 23:00", tz="UTC")]
    assert set(A.SERVICE[p] for p in d["product"]) == {"DFFR", "SFFR"}


def test_tender_rounds_are_separate_contracts_but_two_auction_files_are_a_repeat():
    start = T("2020-08-01 06:00", tz="UTC")
    two_rounds = pd.DataFrame({"unit": ["OPEN2", "OPEN2"], "product": ["FFR-D", "FFR-D"],
                               "delivery_start": [start, start],
                               "source": ["ffr_post_tender_tr108", "ffr_post_tender_tr127"]})
    A.check_no_overlap(two_rounds)                    # a long-term tender and a monthly top-up: both paid
    with pytest.raises(AssertionError):
        A.check_no_overlap(two_rounds.assign(source=["eac_by_unit_fy2024", "eac_by_unit_current_20261007"]))


def test_neso_spellings_find_their_elexon_ids():
    ids = {"AG-GEDF02": "2__GEDF002", "ARNKB-2": "E_ARNKB-2", "CHAPB-1": "E_CHAPB-1"}
    got = A.map_elexon(pd.Series(["AG -GEDF02", "E_ARNKB-2", "GSET-07", "CHAPB-1"]), ids)
    assert got.tolist()[:2] == ["2__GEDF002", "E_ARNKB-2"] and pd.isna(got.iat[2]) and got.iat[3] == "E_CHAPB-1"


def test_the_puller_names_each_report_by_round_and_version():
    assert AP.stem_for("firm-frequency-response-post-tender-reports", "Post Tender Report - TR122 Feb-20") == \
        ("ffr_post_tender_tr122", False, "file")
    assert AP.stem_for("firm-frequency-response-post-tender-reports", "Post Tender Report- TR124 Apr- 20")[0] == \
        "ffr_post_tender_tr124"
    url = "https://api.neso.energy/dataset/x/resource/y/download/post-tender-report-tr127-july-2020-amended-ext.xlsx"
    assert AP.file_name("ffr_post_tender_tr127", "Post Tender Report - TR127 July 2020 - Amended", url) == \
        "ffr_post_tender_tr127_amended.xlsx"
    assert AP.file_name("ffr_post_tender_tr127", "x", "https://example.org/report.pdf") is None
    assert AP.stem_for("phase-2-ffr-auction-results-summary", "Phase 2 FFR Auction ResultsByUnit Masterdata-2019-2020") \
        == ("ffr_auction_by_unit_2019_2020", False, "dump")
    assert AP.stem_for("phase-2-ffr-auction-results-summary", "Phase 2: FFR Auction Results by Unit 26.11.2021") is None
