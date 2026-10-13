"""The Capacity Market tables on real data against LCCC's capacity payments and NESO's register (docs/AUDIT.md
A9-4). Thresholds are set from the measurements of 10 Oct 2026."""
import pandas as pd
import pytest

from gbpowerdata.build import capacity_market as C

from .conftest import need, years_with

pytestmark = pytest.mark.realdata


@pytest.fixture(scope="module")
def payments(processed):
    years = years_with(processed, "capacity_market")
    if not years:
        pytest.skip("data absent: capacity_market_{y}.csv")
    return pd.concat([pd.read_csv(processed / f"capacity_market_{y}.csv", parse_dates=["month"]) for y in years],
                     ignore_index=True)


def test_weighting_factors_sum_to_one(processed):
    need([processed / "capacity_market_weights.csv"])
    w = pd.read_csv(processed / "capacity_market_weights.csv")
    full = w[(w["delivery_year"] >= 2017) & w["basis"].isin(["lccc_payments", "residual"])]
    sums = full.groupby("delivery_year").agg(total=("weighting_factor", "sum"), months=("month", "nunique"))
    sums = sums[sums["months"] == 12]
    assert ((sums["total"] - 1).abs() < 2e-4).all(), sums.round(6).to_dict()     # 0.99984-1.0 measured


def test_payments_reconcile_with_lcccs_where_new_build_is_small(payments, raw):
    need([raw / "lccc" / C.LCCC_FILE])
    r = C.reconcile(payments, C.lccc_payments(raw))
    assert (r["ratio"] >= 0.995).all(), r.loc[r["ratio"] < 0.995].round(4).to_dict("records")
    existing = r[(r["new_build_share"] < 0.15) & (r["lccc_payment_gbp"] > 1e6)]
    assert len(existing) >= 10                                                     # 15 measured
    # above LCCC by the suspended agreements' and late new builds' payments, 1.0036-1.0546 measured
    assert existing["ratio"].between(0.99, 1.07).all(), existing.round(4).to_dict("records")


def test_obligations_add_up_to_the_registers_summary(raw):
    paths = [C.newest(raw, "cmu")]
    if paths[0] is None:
        pytest.skip("data absent: raw/neso/cm_register/cmu_*.csv")
    agr = C.agreements(C.read_text(paths[0]))
    bad = C.summary_mismatches(agr, C.segments(agr))
    assert bad["agreement_id"].nunique() <= 10, bad.head(20).to_dict("records")   # 6 of 9,225 measured


def test_storage_units_hold_no_more_obligation_than_capacity(processed):
    years = years_with(processed, "storage_revenue")
    if not years:
        pytest.skip("data absent: storage_revenue_{y}.csv")
    t = pd.concat([pd.read_csv(processed / f"storage_revenue_{y}.csv") for y in years], ignore_index=True)
    if "cm_obligation_mw" not in t or t["cm_obligation_mw"].isna().all():
        pytest.skip("storage_revenue built without the capacity_market tables")
    over = t[t["cm_obligation_mw"] > 1.1 * t["capacity_mw"] + 1.0]
    assert over.empty, over[["year", "month", "unit_id", "capacity_mw", "cm_obligation_mw"]].head(20).to_dict("records")
