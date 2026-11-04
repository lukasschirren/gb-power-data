"""The daily SAP table on a synthetic raw series: kept from 2018-01-01, one row per gas day, repeated dates and
non-positive prices refused, missing days reported and left missing (gbpowerdata.build.gas_sap_daily). No data/ and
no network needed."""
import pandas as pd
import pytest

from gbpowerdata.build import gas_sap_daily as G


def _raw(dates, p_kwh=2.5):
    d = pd.to_datetime(pd.Series(dates))
    p = pd.Series(p_kwh, index=d.index, dtype=float)
    return pd.DataFrame({"date": d.dt.strftime("%Y-%m-%d"), "gas_price_pence_per_kwh": p,
                         "gas_price_pence_per_therm": (p * 29.3071).round(3)})


def test_builds_the_daily_table_from_2018():
    raw = _raw(pd.date_range("2017-12-30", "2018-01-10"))
    t, gaps = G.build(raw)
    assert list(t.columns) == ["date", "gas_price_pence_per_kwh", "gas_price_pence_per_therm"]
    assert t["date"].iloc[0] == "2018-01-01" and len(t) == 10 and gaps == []


def test_reports_missing_days_and_leaves_them_missing():
    days = [d for d in pd.date_range("2018-01-01", "2018-01-10") if d.day not in (4, 5)]
    t, gaps = G.build(_raw(days))
    assert gaps == ["2018-01-04", "2018-01-05"] and len(t) == 8


def test_refuses_repeated_dates_and_non_positive_prices():
    with pytest.raises(SystemExit, match="repeat"):
        G.build(_raw(["2018-01-01", "2018-01-02", "2018-01-02"]))
    bad = _raw(pd.date_range("2018-01-01", "2018-01-03"))
    bad.loc[1, "gas_price_pence_per_therm"] = 0.0
    with pytest.raises(SystemExit, match="positive"):
        G.build(bad)
