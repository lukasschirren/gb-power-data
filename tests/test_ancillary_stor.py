"""The STOR day-ahead results of gbpowerdata.build.ancillary_services on synthetic rows shaped like NESO's files: the
committed windows of each service day, read from either date format, and an accepted result paid over each window of
its day at the clearing price, a rejected one or a day without windows left out; and the puller's names for the two
datasets. No data/ and no network needed."""
import pandas as pd
import pytest

from gbpowerdata.build import ancillary_services as A
from gbpowerdata.pull import ancillary_pull as AP

T = pd.Timestamp


def _windows(tmp_path, dates):
    pd.DataFrame({"Date": dates, "Season": ["16.2"] * len(dates), "WD_NWD": ["WD"] * len(dates),
                  "Window 1 Start Time": ["06:00"] * len(dates), "Window 1 End Time": ["13:00"] * len(dates),
                  "Window 2 Start Time": ["19:00:00"] * len(dates), "Window 2 End Time": ["22:00"] * len(dates)}).to_csv(
        tmp_path / "stor_windows_20261010.csv", index=False)


def test_the_windows_of_a_service_day_come_from_either_date_format(tmp_path):
    _windows(tmp_path, ["2022-06-01", "02/06/2022"])
    w = A.stor_windows(tmp_path)
    assert w["day"].tolist() == [T("2022-06-01"), T("2022-06-01"), T("2022-06-02"), T("2022-06-02")]
    assert (w["end"] - w["start"]).dt.total_seconds().div(3600).tolist() == [7.0, 3.0, 7.0, 3.0]


def test_an_accepted_result_is_paid_over_each_window_of_its_day(tmp_path, monkeypatch):
    _windows(tmp_path, ["2022-06-01"])
    monkeypatch.setattr(A, "RAW", tmp_path)
    t = pd.DataFrame({"Service Delivery From": ["2022-06-01T04:00:00Z", "2022-06-01T04:00:00Z", "2022-06-02T04:00:00Z"],
                      "Service Delivery To": ["2022-06-02T04:00:00Z"] * 2 + ["2022-06-03T04:00:00Z"],
                      "Unit ID": ["T_PEAK-1", "NBM-7", "T_PEAK-1"], "Company Name": ["A", "B", "A"],
                      "BM/NBM": ["BM", "NBM", "BM"], "Fuel Type": ["OCGT", "Other", "OCGT"],
                      "Tender Submission ID": ["TS-1", "TS-2", "TS-3"], "Contracted MW": [50.0, 10.0, 50.0],
                      "Market Clearing Price": [4.0, 4.0, 4.0], "Status": ["Accepted", "Rejected", "Accepted"]})
    d = A.normalise(A.stor_da(t, "stor_da_results_20261010").assign(priority=2))
    assert d["delivery_start"].tolist() == [T("2022-06-01 05:00", tz="UTC"), T("2022-06-01 18:00", tz="UTC")]
    assert d["revenue_gbp"].tolist() == pytest.approx([50 * 4.0 * 7, 50 * 4.0 * 3])   # 2 Jun: no windows yet
    assert set(d["service"]) == {"STOR"} and d["result_id"].tolist() == ["TS-1:1", "TS-1:2"]


def test_the_puller_names_the_stor_datasets():
    assert AP.stem_for("short-term-operating-reserve-stor-day-ahead-auction-results", "STOR DA Auction Results") == \
        ("stor_da_results", True, "dump")
    assert AP.stem_for("stor-windows", "STOR Windows") == ("stor_windows", True, "dump")
