"""Aurora's leaderboard export as tables (gbpowerdata.build.storage_revenue_aurora) on synthetic exports: per-MW and
per-kW figures scale to MWh and GBP by the day's installed MW, a later export replaces the days an earlier one also
held, a market not mapped stops the build, the monthly view has storage_revenue's column names, and the comparison
sets each stream beside the open table's. No data/, no network and no licensed data needed."""
import zipfile

import numpy as np
import pandas as pd
import pytest

from gbpowerdata.build import storage_revenue_aurora as SA

HEADER = list(SA.RAW)


def _row(date, unit, market, mw=50.0, vch=None, vdis=None, cch=None, cdis=None, optimiser="Opt A"):
    return [date, unit, market, "Great Britain (i.e. without Northern Ireland NIR)", "South Scotland", f"{unit} site",
            2.0, 2 * mw, optimiser, "Lead Party Ltd", None, mw, vch, vdis, cch, cdis]


def _export(path, rows, as_zip=True):
    d = pd.DataFrame(rows, columns=HEADER)
    if as_zip:
        with zipfile.ZipFile(path, "w") as z:
            z.writestr(path.stem + " (2).csv", d.to_csv(index=False))
    else:
        d.to_csv(path, index=False)
    return path


def test_per_mw_and_per_kw_figures_scale_by_the_days_installed_mw(tmp_path):
    _export(tmp_path / "leaderboard-gbr-2026-01-01-2026-12-31.zip", [
        _row("2026-01-01", "T_AAAB-1", "Wholesale Market", 50.0, vch=-1.0, vdis=0.9, cch=-0.05, cdis=0.12),
        _row("2026-01-01", "T_AAAB-1", "Dynamic Containment", 50.0, vch=None, vdis=10.0, cch=None, cdis=0.03),
    ])
    t = SA.revenue(SA.read(tmp_path))
    w = t[t["market"] == "wholesale"].iloc[0]
    assert w["charge_mwh"] == pytest.approx(-50.0) and w["discharge_mwh"] == pytest.approx(45.0)
    assert w["gbp"] == pytest.approx((-0.05 + 0.12) * 50 * 1000)
    dc = t[t["market"] == "dc"].iloc[0]
    assert np.isnan(dc["charge_gbp"]) and dc["gbp"] == pytest.approx(0.03 * 50 * 1000)   # an empty side counts as zero


def test_a_later_export_replaces_the_days_an_earlier_one_also_held(tmp_path):
    _export(tmp_path / "leaderboard-gbr-2026-01-01-2026-12-31.zip", [
        _row("2026-01-01", "T_AAAB-1", "Balancing Market", cdis=0.01),
        _row("2026-01-02", "T_AAAB-1", "Balancing Market", cdis=0.02),
    ])
    _export(tmp_path / "leaderboard-gbr-2026-01-02-2026-01-03.csv", [
        _row("2026-01-02", "T_AAAB-1", "Balancing Market", cdis=0.05),          # revised
        _row("2026-01-03", "T_AAAB-1", "Balancing Market", cdis=0.03),
    ], as_zip=False)
    d = SA.read(tmp_path)
    assert d.groupby("date")["discharge_gbp_per_kw"].first().tolist() == [0.01, 0.05, 0.03]


def test_a_market_not_mapped_stops_the_build(tmp_path):
    _export(tmp_path / "leaderboard-gbr-2026-01-01-2026-12-31.zip", [_row("2026-01-01", "T_AAAB-1", "Slow Reserve")])
    with pytest.raises(ValueError, match="Slow Reserve"):
        SA.read(tmp_path)


def test_a_missing_column_is_named(tmp_path):
    p = tmp_path / "leaderboard-gbr-2026-01-01-2026-12-31.csv"
    pd.DataFrame([_row("2026-01-01", "T_AAAB-1", "Balancing Market")], columns=HEADER).drop(
        columns=["optimiser"]).to_csv(p, index=False)
    with pytest.raises(ValueError, match="optimiser"):
        SA.read(tmp_path)


def test_units_take_the_last_days_attributes_and_their_span(tmp_path):
    _export(tmp_path / "leaderboard-gbr-2026-01-01-2026-12-31.zip", [
        _row("2026-01-01", "T_AAAB-1", "Balancing Market", mw=40.0, optimiser="Opt A"),
        _row("2026-02-01", "T_AAAB-1", "Balancing Market", mw=50.0, optimiser="Opt B"),
    ])
    u = SA.units(SA.read(tmp_path)).iloc[0]
    assert u["capacity_mw"] == 50.0 and u["optimiser"] == "Opt B" and u["energy_mwh"] == 100.0
    assert u["first_date"] == pd.Timestamp("2026-01-01") and u["last_date"] == pd.Timestamp("2026-02-01")


def test_the_monthly_view_has_storage_revenues_columns_and_annualises_over_its_days(tmp_path):
    rows = [_row(f"2026-01-{d:02d}", "T_AAAB-1", m, cdis=0.1) for d in (1, 2) for m in ("Wholesale Market",
                                                                                         "Quick Reserve")]
    _export(tmp_path / "leaderboard-gbr-2026-01-01-2026-12-31.zip", rows)
    m = SA.monthly(SA.revenue(SA.read(tmp_path))).iloc[0]
    assert m["month"] == "2026-01" and m["days"] == 2
    assert m["wholesale_gbp"] == pytest.approx(2 * 0.1 * 50_000) and m["anc_qr_gbp"] == pytest.approx(10_000)
    assert m["bm_gbp"] == 0.0 and m["total_gbp"] == pytest.approx(20_000)
    assert m["gbp_per_kw_yr"] == pytest.approx(20_000 / 50_000 * 365 / 2)


def test_compare_sets_each_stream_beside_the_open_tables_and_totals_only_shared_streams():
    a = pd.DataFrame({"unit_id": ["T_AAAB-1"], "month": ["2026-01"], "days": [31], "capacity_mw": [50.0],
                      **{c: [100.0] for c in SA.STREAMS}})
    o = pd.DataFrame({"unit_id": ["T_AAAB-1", "T_OTHER-1"], "month": ["2026-01", "2026-01"], "kind": ["bm", "bm"],
                      "capacity_mw": [49.0, 10.0], "has_fpn": [True, True], "fpn_coverage": [1.0, 1.0],
                      "wholesale_gbp": [90.0, 1.0], "bm_offer_gbp": [30.0, 1.0], "bm_bid_gbp": [-5.0, 1.0],
                      **{f"anc_{s}_gbp": [100.0, 1.0] for s in SA.ANCILLARY}, "anc_stor_gbp": [1e6, 0.0]})
    c = SA.compare(a, o)
    assert len(c) == 1                                                     # units in both only
    r = c.iloc[0]
    assert r["bm_gbp_open"] == 25.0 and r["bm_gbp_aurora"] == 100.0
    assert r["total_gbp_open"] == pytest.approx(90 + 25 + 5 * 100)         # STOR is not one of Aurora's streams
    assert r["total_gbp_aurora"] == pytest.approx(7 * 100)
