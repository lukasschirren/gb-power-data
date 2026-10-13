"""Storage, ancillary services and CfDs on real data against their own sources and the official totals
(docs/AUDIT.md A7, A9, A10, A11). Thresholds are set from the measurements of 10 Oct 2026."""
import numpy as np
import pandas as pd
import pytest

from gbpowerdata.checks import official as O
from gbpowerdata.checks import storage as CS

from .conftest import need

pytestmark = pytest.mark.realdata


@pytest.fixture(scope="module")
def fleet(processed):
    need([processed / "storage_fleet.csv"])
    from gbpowerdata import processed as P
    return P.read_storage_fleet()


def test_each_storage_unit_is_one_row(fleet):
    assert not fleet["unit_id"].duplicated().any(), fleet.loc[fleet["unit_id"].duplicated(keep=False), "unit_id"].tolist()


def test_battery_fleet_covers_most_of_desnz_capacity(fleet):
    from gbpowerdata.build.storage_fleet import operating
    dukes = O.series("battery_capacity_grid_scale")
    b = fleet[fleet["tech"] == "battery"]
    for y in range(2022, 2026):
        share = operating(b, f"{y}-12-31")["capacity_mw"].sum() / dukes[y]
        assert 0.85 <= share <= 1.10, (y, round(share, 3))       # 0.88-0.95 measured (UK, incl. sites outside)


def test_declared_energy_agrees_with_the_capacity_market_class(fleet):
    both = fleet[fleet["mdv_mwh"].notna() & fleet["cm_duration_h"].notna()]
    if both.empty:
        pytest.skip("no unit with both MDV and a CM duration class")
    hours = both["mdv_mwh"] / both["capacity_mw"]
    ok = abs(hours - both["cm_duration_h"]) <= 0.5 * both["cm_duration_h"] + 0.1
    by_id = both.get("cm_duration_basis", pd.Series("component_id", index=both.index)).eq("component_id")
    assert ok[by_id].all()                                   # the component names the unit: 15 of 15 measured
    assert ok.mean() >= 0.85, round(ok.mean(), 3)            # with the name and postcode links: 59 of 65 measured


def test_storage_notifications_are_feasible_for_their_power_and_fleet_energy(fleet, raw):
    from gbpowerdata.build.storage_revenues import accepted_volumes, fpn_energy
    b = fleet[(fleet["tech"] == "battery") & (fleet["kind"] == "bm") & fleet["energy_mwh"].notna()]
    vol, months = accepted_volumes(None, raw)
    acc = {u: g.set_index("startTime")["volume_mwh"] for u, g in vol.groupby("bmUnit")}
    notified, after = [], []
    for r in b.itertuples():
        f = raw / "fpn" / f"{r.unit_id}.csv"
        if not f.exists():
            continue
        e = fpn_energy(f)
        e = e[e.index >= pd.Timestamp("2022-01-01", tz="UTC")]
        if not len(e) or e.abs().sum() == 0:
            continue
        # within the registered capacity in all but a few half-hours: T_KEMB-1 notifies up to 49 MW against its
        # registered 40.1 MW in 434 of 70,125 (0.6%, 2022-2025; docs/AUDIT.md A9-10), the others in all
        assert CS.power_share(e, r.capacity_mw) >= 0.99, r.unit_id
        notified.append(CS.energy_share(e, r.energy_mwh))
        after.append(CS.energy_share(CS.after_bm(e, acc.get(r.unit_id, pd.Series(dtype=float))), r.energy_mwh))
    if not notified:
        pytest.skip("no notification files for the units with stated energy")
    # notifications are moved by accepted BM actions after gate closure, so energy is checked for the fleet, not each
    # unit: the median unit's daily swing stays within 1.25 x its stated energy on 0.87 of days from its notifications,
    # 0.95 after the BM (notifications plus accepted volumes; 71 units, 10 Oct 2026; docs/AUDIT.md A9-8)
    assert np.median(notified) >= 0.75, np.median(notified)
    if len(months) >= 48:                                    # the volume files of 2022-2025
        assert np.median(after) >= 0.90, np.median(after)


def test_storage_revenue_coverage_marks_the_archive_holes(processed):
    path = processed / "storage_revenue_2020.csv"
    need([path])
    t = pd.read_csv(path)
    if "fpn_coverage" not in t:
        pytest.skip("storage_revenue built before fpn_coverage")
    nov = t[(t["month"] == "2020-11") & t["has_fpn"].astype(bool)]
    assert nov["fpn_coverage"].median() < 0.5                    # 18 days of November 2020 are not in Elexon's archive
    assert t[t["month"] == "2020-03"]["fpn_coverage"].dropna().median() == pytest.approx(1.0)


def _fy_service_totals(processed) -> pd.DataFrame:
    files = sorted(processed.glob("ancillary_by_unit_20*.csv"))
    need(files[:1] or [processed / "ancillary_by_unit_2025.csv"])
    a = pd.concat([pd.read_csv(f, usecols=["delivery_start", "service", "revenue_gbp"]) for f in files])
    t = pd.to_datetime(a["delivery_start"], utc=True).dt.tz_convert("Europe/London")
    a["fy"] = np.where(t.dt.month >= 4, t.dt.year, t.dt.year - 1)
    return a.groupby(["fy", "service"])["revenue_gbp"].sum()


@pytest.mark.parametrize("stat,service", [("response_spend_dc", "DC"), ("response_spend_dm", "DM"),
                                          ("response_spend_dr", "DR"), ("response_spend_sffr", "SFFR"),
                                          ("reserve_spend_qr", "QR"), ("reserve_spend_br", "BR")])
def test_ancillary_totals_reconcile_with_nesos_published_spend(processed, stat, service):
    """Contracted MW x clearing price x hours is NESO's ex-ante award; its spend report gives what it paid. Ours
    must not be below it and was within 40% above it (2022/23-2024/25: DC 7-9%, DM 7-20%, DR 9-38%, Static FFR
    under 1%, QR 26%, BR 19%; docs/AUDIT.md A10-2)."""
    ours = _fy_service_totals(processed)
    neso = O.series(stat)
    checked = 0
    for fy, v in neso.items():
        if (fy, service) not in ours.index:
            continue
        ratio = ours[(fy, service)] / v
        assert 0.98 <= ratio <= 1.40, (stat, fy, round(ratio, 3))
        checked += 1
    if not checked:
        pytest.skip(f"no overlap with NESO's figures for {service}")


def _fy_product_totals(processed) -> pd.Series:
    files = sorted(processed.glob("ancillary_by_unit_20*.csv"))
    need(files[:1] or [processed / "ancillary_by_unit_2023.csv"])
    a = pd.concat([pd.read_csv(f, usecols=["delivery_start", "product", "revenue_gbp"]) for f in files])
    t = pd.to_datetime(a["delivery_start"], utc=True).dt.tz_convert("Europe/London")
    a["fy"] = np.where(t.dt.month >= 4, t.dt.year, t.dt.year - 1)
    return a.groupby(["fy", "product"])["revenue_gbp"].sum()


def test_dynamic_ffr_tenders_reconcile_with_nesos_spend_without_response_energy(processed):
    """The monthly tenders valued as accepted (fees x tendered hours) against what NESO paid for Dynamic FFR in
    2023/24 without the response energy (C9 report, Figure 20: BM 4.93 + non-BM 1.98 GBP m): 7.12 against 6.91 GBP m,
    1.03, and within 6% in every month (measured 10 Oct 2026)."""
    ours = _fy_product_totals(processed)
    if (2023, "FFR-D") not in ours.index:
        pytest.skip("ancillary_by_unit built without the FFR tenders")
    paid = O.series("response_spend_dffr_bm")[2023] + O.series("response_spend_dffr_nbm")[2023]
    assert 0.98 <= ours[(2023, "FFR-D")] / paid <= 1.10, round(ours[(2023, "FFR-D")] / paid, 3)


@pytest.mark.xfail(strict=True, reason="docs/AUDIT.md A10-5: the FFR tenders of 2022/23 valued as accepted come 70% "
                                       "above what NESO paid")
def test_ffr_tenders_of_2022_reconcile_with_nesos_spend_without_response_energy(processed):
    ours = _fy_product_totals(processed)
    if (2022, "FFR-D") not in ours.index:
        pytest.skip("ancillary_by_unit built without the FFR tenders")
    paid = O.series("response_spend_ffr_bm")[2022] + O.series("response_spend_ffr_nbm")[2022]
    v = ours[(2022, "FFR-D")] + ours.get((2022, "FFR-S"), 0.0)
    assert 0.98 <= v / paid <= 1.40, round(v / paid, 3)                  # 1.70 measured (63.3 against 37.2 GBP m)


def test_stor_auctions_of_bm_units_reconcile_with_nesos_bm_stor_spend(processed):
    """The daily STOR auctions' availability (contracted MW x clearing price x the committed windows' hours) of the
    units with an Elexon id against NESO's BM STOR spend (C9 reports, monthly tables): 49.1 against 45.1 GBP m in
    2022/23 and 6.9 against 6.6 in 2023/24, every month within -10% to +18% (measured 10 Oct 2026). The non-BM units'
    long-term contracts are not in the auctions, so they are not compared."""
    files = sorted(processed.glob("ancillary_by_unit_20*.csv"))
    need(files[:1] or [processed / "ancillary_by_unit_2023.csv"])
    a = pd.concat([pd.read_csv(f, usecols=["delivery_start", "service", "elexon_unit", "revenue_gbp"]) for f in files])
    a = a[(a["service"] == "STOR") & a["elexon_unit"].notna()]
    if a.empty:
        pytest.skip("ancillary_by_unit built without the STOR auctions")
    t = pd.to_datetime(a["delivery_start"], utc=True).dt.tz_convert("Europe/London")
    ours = a.groupby(np.where(t.dt.month >= 4, t.dt.year, t.dt.year - 1))["revenue_gbp"].sum()
    for fy, paid in O.series("reserve_spend_stor_bm").items():
        assert 0.95 <= ours[fy] / paid <= 1.20, (fy, round(ours[fy] / paid, 3))


def test_cfd_payments_follow_strike_minus_reference_and_sum_to_lccc(raw, processed):
    path = raw / "lccc" / "cfd_actual_generation.csv"
    need([path])
    g = pd.read_csv(path)
    for c in ("CFD_Generation_MWh", "Strike_Price_GBP_Per_MWh", "CFD_Payments_GBP",
              "Market_Reference_Price_GBP_Per_MWh", "Weighted_IMRP_GBP_Per_MWh"):
        g[c] = pd.to_numeric(g[c], errors="coerce")
    g = g[g["CFD_Generation_MWh"] > 0]
    ref = np.where(g["Reference_Type"].eq("IMRP") & g["Weighted_IMRP_GBP_Per_MWh"].notna(),
                   g["Weighted_IMRP_GBP_Per_MWh"], g["Market_Reference_Price_GBP_Per_MWh"])
    exp = (g["Strike_Price_GBP_Per_MWh"] - ref) * g["CFD_Generation_MWh"]
    rel = (g["CFD_Payments_GBP"] - exp).abs() / exp.abs().clip(lower=1)
    assert (rel <= 0.01).mean() >= 0.99                          # 99.4% measured; the rest: negative-price rules
    above = g[ref > g["Strike_Price_GBP_Per_MWh"] + 1]
    assert (above["CFD_Payments_GBP"] <= 0).mean() >= 0.95       # a reference above strike: the generator pays back
    g["year"] = pd.to_datetime(g["Settlement_Date"]).dt.year
    for y in range(2018, 2026):
        f = processed / f"cfd_fleet_{y}.csv"
        if f.exists():
            assert pd.read_csv(f)["cfd_payments_gbp"].sum() == pytest.approx(
                g.loc[g["year"] == y, "CFD_Payments_GBP"].sum(), rel=1e-6), y


def test_cfd_financial_year_payments_match_lccc_annual_report(raw):
    path = raw / "lccc" / "cfd_actual_generation.csv"
    need([path])
    g = pd.read_csv(path, usecols=["Settlement_Date", "CFD_Payments_GBP"])
    t = pd.to_datetime(g["Settlement_Date"])
    fy = np.where(t.dt.month >= 4, t.dt.year, t.dt.year - 1)
    ours = pd.Series(pd.to_numeric(g["CFD_Payments_GBP"], errors="coerce").to_numpy(), index=fy).groupby(level=0).sum() / 1e6
    report = O.series("cfd_net_payments")
    for y, v in report.items():
        if y in ours.index:
            assert ours[y] == pytest.approx(v, rel=0.05), (y, round(ours[y], 1), v)   # 2024/25: 2,238 vs 2,196
