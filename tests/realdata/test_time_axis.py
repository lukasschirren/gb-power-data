"""The half-hourly UTC spine of every built time series, and settlement periods against UTC in the raw pulls
(docs/AUDIT.md A1)."""
import pandas as pd
import pytest

from gbpowerdata.checks import timeseries as T

from .conftest import need, years_with

pytestmark = pytest.mark.realdata

WIDE = ["demand", "capacity_factors", "fuel_prices", "mid_target", "system_prices", "lolp_drm", "forecast_state",
        "capacity_factors_pecd", "wind_farm_fpn", "generation_mix", "generation_battery"]


@pytest.mark.parametrize("family", WIDE)
def test_every_year_has_its_full_utc_spine_once(processed, family):
    years = years_with(processed, family)
    if not years:
        pytest.skip(f"no {family}_*.csv")
    for y in years:
        s = T.spine(pd.read_csv(processed / f"{family}_{y}.csv", usecols=["startTime"]), y)
        assert s["rows"] == s["expected"] == s["times"], (family, y, s)
        assert s["missing"] == s["extra"] == s["off_grid"] == s["duplicates"] == 0, (family, y, s)


def test_clock_change_days_hold_46_and_50_periods(processed):
    years = years_with(processed, "demand")
    if not years:
        pytest.skip("no demand_*.csv")
    for y in years:
        n = T.local_day_periods(pd.read_csv(processed / f"demand_{y}.csv", usecols=["startTime"])["startTime"])
        spring, autumn = T.clock_change_days(y)
        assert n[spring.date()] == 46 and n[autumn.date()] == 50, y
        inner = n.drop([spring.date(), autumn.date()])
        inner = inner[(inner.index > min(inner.index)) & (inner.index < max(inner.index))]   # whole local days
        assert (inner == 48).all(), y


@pytest.mark.parametrize("glob", ["mid_apx_*.csv", "system_prices/system_prices_20*.csv"])
def test_settlement_periods_map_to_their_utc_start(raw, glob):
    files = sorted(raw.glob(glob))
    need(files[:1] or [raw / glob])
    d = pd.concat([pd.read_csv(f, usecols=["startTime", "settlementDate", "settlementPeriod"]) for f in files])
    bad = pd.to_datetime(d["startTime"], utc=True) != T.settlement_start(d["settlementDate"], d["settlementPeriod"])
    assert not bad.any(), d[bad].head()


def test_ancillary_blocks_start_on_efa_hours_and_span_the_clock_change(processed):
    files = sorted(processed.glob("ancillary_by_unit_20*.csv"))
    need(files[:1] or [processed / "ancillary_by_unit_2025.csv"])
    a = pd.concat([pd.read_csv(f, usecols=["delivery_start", "hours", "product", "source"]) for f in files])
    blocks = a[a["product"].str.match(r"^D[CMR][LH]$|^SFFR$") & ~a["source"].str.startswith("dc_tender")]
    start = pd.to_datetime(blocks["delivery_start"], utc=True).dt.tz_convert("Europe/London")
    assert start.dt.hour.isin([23, 3, 7, 11, 15, 19]).all()
    odd = blocks[blocks["hours"] != 4]
    assert set(odd["hours"]) <= {3.0, 5.0}
    # an EFA day starting on the Saturday evening before a clock change holds the 3- or 5-hour block
    days = set(pd.to_datetime(odd["delivery_start"], utc=True).dt.tz_convert("Europe/London").dt.date)
    changes = {d for y in range(2020, 2027) for d in (c.date() - pd.Timedelta(days=1) for c in T.clock_change_days(y))}
    assert days <= changes
