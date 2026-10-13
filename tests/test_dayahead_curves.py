"""The day-ahead curve checks (gbpowerdata.build.dayahead_curves) on synthetic curves: Nord Pool's piecewise-linear
curves cross where supply meets demand once accepted blocks and flows are added (from 2021; before, its curves
already hold them), EPEX SPOT's step curves clear at a price where supply and demand at it overlap (a riser is
partly accepted), a curve running against its direction is caught, and a period without a published price is not
counted as a failure. No data/ and no licensed data needed."""
import json

import numpy as np
import pandas as pd
import pytest

from gbpowerdata.build import dayahead_curves as D


def _curve(points):
    return pd.DataFrame(points, columns=["price", "volume"])


LIN_SUPPLY = _curve([(0, 0), (100, 1000)])          # S(p) = 10 p
LIN_DEMAND = _curve([(0, 1000), (100, 0)])          # D(p) = 1000 - 10 p


def test_linear_curves_cross_where_supply_meets_demand_with_blocks_added():
    r = D.check_period(LIN_SUPPLY, LIN_DEMAND, 50.0)
    assert r["crossing_price"] == pytest.approx(50.0) and r["passed"] is True
    assert r["traded_mwh"] == pytest.approx(500.0)
    b = D.check_period(LIN_SUPPLY, LIN_DEMAND, 45.0, block_sell=100.0)       # 10 p + 100 = 1000 - 10 p
    assert b["crossing_price"] == pytest.approx(45.0) and b["clears"] is True
    assert b["crossing_price_curves_only"] == pytest.approx(50.0)


# EPEX-style steps: 100 MW offered at 20, 100 more at 40; 150 MW bid at or above 30
STEP_SUPPLY = _curve([(-500, 0), (20, 0), (20, 100), (40, 100), (40, 200), (3000, 200)])
STEP_DEMAND = _curve([(-500, 150), (30, 150), (30, 0), (3000, 0)])


def test_step_curves_clear_on_a_partly_accepted_riser_and_a_wrong_price_fails():
    r = D.check_period(STEP_SUPPLY, STEP_DEMAND, 30.0, curve="step")
    assert r["crossing_price"] == 30.0 and r["imbalance_mw"] == 0.0 and r["passed"] is True
    assert r["traded_mwh"] == pytest.approx(100.0)                        # the demand riser is cut at 100 MW
    w = D.check_period(STEP_SUPPLY, STEP_DEMAND, 35.0, curve="step")
    assert w["imbalance_mw"] == pytest.approx(100.0) and w["clears"] is False and w["passed"] is False


def test_a_supply_curve_that_loses_volume_as_the_price_rises_is_caught():
    n, worst = D.violations([0, 10, 20], [100, 50, 120], "supply")
    assert (n, worst) == (1, 50.0)
    assert D.violations([0, 10, 20], [300, 200, 250], "demand") == (1, 50.0)
    r = D.check_period(_curve([(0, 0), (10, 600), (20, 500), (100, 1000)]), LIN_DEMAND, 50.0)
    assert r["monotone"] is False and r["passed"] is False
    u = D.check_period(_curve([(0, 0), (10, 600), (20, 500), (100, 1000)]), LIN_DEMAND, np.nan)
    assert u["clears"] is None and u["passed"] is False          # fails even where no price can be checked


def test_a_period_without_a_published_price_is_not_a_failure():
    r = D.check_period(LIN_SUPPLY, LIN_DEMAND, np.nan)
    assert r["clears"] is None and r["passed"] is None and r["monotone"] is True
    rows = pd.DataFrame([{**r, "deliveryStart": "2018-06-01T10:00:00Z"},
                         {**D.check_period(LIN_SUPPLY, LIN_DEMAND, 80.0), "deliveryStart": "2018-06-02T10:00:00Z"}])
    bad = D.failing_dates(rows)
    assert bad["date"].astype(str).tolist() == ["2018-06-02"] and int(bad["not_clearing"].iloc[0]) == 1


def _n2ex_day(path, day, start, blocks):
    path.write_text(json.dumps({
        "deliveryDateCET": day,
        "orderPositions": [{"deliveryStart": start, "deliveryEnd": start,
                            "supplyCurve": [{"price": 0, "volume": 0}, {"price": 100, "volume": 1000}],
                            "demandCurve": [{"price": 0, "volume": 1000}, {"price": 100, "volume": 0}]}],
        "blockOrders": blocks}), encoding="utf-8")


def test_n2ex_adds_blocks_and_flows_only_after_the_decoupling(tmp_path):
    start = "2021-06-01T10:00:00Z"
    blocks = [{"id": 1, "side": "sell", "intervals": [{"deliveryStart": start, "volume": 100, "acceptedVolume": 100}]}]
    _n2ex_day(tmp_path / "2021-06-01.json", "2021-06-01", start, blocks)
    prices = pd.Series([45.0], index=[pd.Timestamp(start)])
    imports = pd.Series([0.0], index=[pd.Timestamp(start)])
    r = D.n2ex_day(tmp_path / "2021-06-01.json", prices, imports)[0]
    assert r["balance"] == "curves+blocks+flows" and r["crossing_price"] == pytest.approx(45.0)
    old = "2019-06-01T10:00:00Z"
    _n2ex_day(tmp_path / "2019-06-01.json", "2019-06-01", old,
              [{"id": 2, "side": "sell", "intervals": [{"deliveryStart": old, "volume": 100, "acceptedVolume": 100}]}])
    r = D.n2ex_day(tmp_path / "2019-06-01.json", pd.Series([50.0], index=[pd.Timestamp(old)]), imports)[0]
    assert r["balance"] == "curves" and r["block_sell_mw"] == 0.0 and r["crossing_price"] == pytest.approx(50.0)
