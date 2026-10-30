"""The cap's make-up on Ofgem's real pre-levelised rates model (the newest in raw/ofgem/): the benchmarks of Ofgem's
two reviews of 2026, and the headline table divided by its own period's benchmark."""
from __future__ import annotations

import pandas as pd
import pytest

from gbpowerdata.build import build_cap_tariff as C

pytestmark = pytest.mark.realdata


@pytest.fixture(scope="module")
def real():
    if not any(C.OFGEM.glob(p) for p in ("cap_tariff_model_*.xlsx", "cap_prelevelised_*.xlsx",
                                          "*pre-levelised*rates*model*.xlsx")):
        pytest.skip(f"data absent: no cap model in {C.OFGEM}")
    path = C._latest_model()
    grids = {s: pd.read_excel(path, sheet_name=s, header=None)
             for s in (C.SHEET, C.HISTORY_SHEET, C.SCHEME_SHEET, C.WHOLESALE_SHEET)}
    return grids, C.history(grids[C.HISTORY_SHEET], grids[C.SCHEME_SHEET], grids[C.WHOLESALE_SHEET])


def test_the_real_benchmarks_are_those_of_ofgems_reviews(real):
    _, t = real
    want = {"electricity": (3100, 2700, 2500), "gas": (12000, 11500, 9500)}   # to Dec 2025, Jan-Jun, from Jul 2026
    for fuel, (old, jan26, jul26) in want.items():
        f = t[t["fuel"] == fuel]
        assert (f.loc[f["start"] < "2026-01-01", "benchmark_kwh"] == old).all()
        assert (f.loc[(f["start"] >= "2026-01-01") & (f["start"] < "2026-07-01"), "benchmark_kwh"] == jan26).all()
        assert (f.loc[f["start"] >= "2026-07-01", "benchmark_kwh"] == jul26).all()


def test_the_headline_divides_by_its_periods_benchmark(real):
    grids, t = real
    elec = t[t["fuel"] == "electricity"].set_index("start")
    first = C.period_dates(next(v for v in grids[C.SHEET].iloc[:12].to_numpy().ravel()
                                if C.period_dates(v) is not None))[0]
    _, out = C.headline(grids[C.SHEET], float(elec.loc[first, "benchmark_kwh"]))
    dd = out[out["payment_method"] == "Direct Debit"]
    gb = (dd["total_gbp_yr"].mean() - dd["nil_gbp_yr"].mean()) / elec.loc[first, "benchmark_kwh"] * C.MWH
    assert gb == pytest.approx(elec.loc[first, "unit_rate_gbp_mwh"], abs=0.05)
