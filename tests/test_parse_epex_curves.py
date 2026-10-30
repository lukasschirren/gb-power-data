"""The EPEX curve parser (gbpowerdata.build.parse_epex_curves) on synthetic labels: the pre-2020 hourly files' hours
are GB local time, the autumn day's repeated hour labelled "01X" is the second 01:00 (GMT), and the spring day's
missing hour has no start. No data/ and no licensed data needed."""
import pandas as pd

from gbpowerdata.build import parse_epex_curves as P

T = pd.Timestamp


def test_legacy_hours_are_london_time_and_01x_is_the_repeated_hour():
    autumn = T("2012-10-28")                                # BST ends at 02:00 BST (01:00 GMT)
    assert P._legacy_start(autumn, 0) == T("2012-10-27 23:00", tz="UTC")
    assert P._legacy_start(autumn, "01") == T("2012-10-28 00:00", tz="UTC")    # 01:00 BST
    assert P._legacy_start(autumn, "01X") == T("2012-10-28 01:00", tz="UTC")   # 01:00 GMT, an hour later
    assert P._legacy_start(autumn, 2) == T("2012-10-28 02:00", tz="UTC")
    assert P._legacy_start(T("2012-07-01"), 13) == T("2012-07-01 12:00", tz="UTC")


def test_the_spring_days_missing_hour_has_no_start():
    assert P._legacy_start(T("2012-03-25"), 1) is pd.NaT                       # 01:00 to 02:00 does not exist
