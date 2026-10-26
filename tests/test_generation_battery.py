"""The battery generation table (gbpowerdata.build.generation_battery) on synthetic data: B1610's settlement periods
to UTC, each unit split into discharge and charge before the fleet's sum (two units moving opposite ways are not
netted), a group with no active unit at 0 and one with active units but no value empty; the frequency response MW
by product and group from NESO's rows, kept as published and split exactly at month ends (non-BM units by NESO's id, other technologies left out, empty before the
results); the GSP groups in one spelling; and the summary's energy, share of generation, units, time-weighted
capacity, coverage and regions, and the units table. No data/ and no network needed."""
import numpy as np
import pandas as pd
import pytest

from gbpowerdata.build import generation_battery as B

T = pd.Timestamp


def test_group_of_the_unit_kinds():
    assert [B.group_of(u, k) for u, k in [("T_PILLB-1", "bm"), ("E_ARBRB-1", "bm"), ("2__EFLEX001", "supplier"),
                                          ("V__AZENO002", "vlp"), ("AFFR-1", "non_bm")]] == [
        "transmission", "embedded", "supplier", "vlp", "non_bm"]


def test_gsp_group_names_in_one_spelling():
    assert [B.gsp_group_name(n) for n in ["Eastern GSP Group", "_F - Northern", "SOUTH of SCOTLAND GSP", "London",
                                          "Merseyside North Wales", np.nan, "", "Atlantis"]] == [
        "Eastern", "Northern", "South Scotland", "London", "Merseyside North Wales", None, None, None]


def test_metered_energy_on_utc_start(tmp_path):
    p = tmp_path / "E_X-1.csv"
    pd.DataFrame({"settlementDate": ["2023-07-01", "2023-07-01", "2023-07-01"], "settlementPeriod": [1, 2, 2],
                  "quantity": [10.0, -5.0, -6.0]}).to_csv(p, index=False)
    e = B.metered_energy(p)
    assert list(e.index) == [T("2023-06-30 23:00", tz="UTC"), T("2023-06-30 23:30", tz="UTC")]   # BST
    assert e.tolist() == [10.0, -6.0]                                                           # the last row kept


def _fleet():
    units = pd.DataFrame({"unit_id": ["T_A-1", "E_B-1", "E_C-1", "NB-1"],
                          "group": ["transmission", "embedded", "embedded", "non_bm"],
                          "gsp_group": ["unknown", "Eastern", "London", "unknown"],
                          "capacity_mw": [100.0, 50.0, 20.0, 10.0],
                          "active_from": [np.nan, np.nan, "2023-07-01", np.nan], "active_to": [np.nan] * 4})
    h = pd.date_range("2023-01-01", periods=4, freq="30min", tz="UTC")
    energy = {"metered": {"T_A-1": pd.Series([50.0, -40.0, 0.0, np.nan], index=h),
                          "E_B-1": pd.Series([-10.0, 20.0, 0.0, np.nan], index=h)},
              "notified": {"T_A-1": pd.Series([50.0, -50.0, 0.0, 0.0], index=h)}}
    gen = pd.Series(20000.0, index=h)
    anc = pd.DataFrame({
        "delivery_start": ["2022-12-31T23:00:00Z", "2023-01-01T03:00:00Z", "2023-01-01T03:00:00Z",
                           "2023-01-01T00:00:00Z", "2023-01-01T00:00:00Z", "2023-01-01T00:00:00Z"],
        "delivery_end": ["2023-01-01T03:00:00Z", "2023-01-01T07:00:00Z", "2023-01-01T07:00:00Z",
                         "2023-01-01T01:00:00Z", "2023-01-01T01:00:00Z", "2023-01-01T01:00:00Z"],
        "service": ["DC", "DC", "DFFR", "SFFR", "QR", "DC"], "product": ["DCL", "DCH", "FFR-D", "SFFR", "PQR", "DCL"],
        "unit": ["A-1", "B-1", "NB-1", "B-1", "A-1", "GAS-1"],
        "elexon_unit": ["T_A-1", "E_B-1", np.nan, "E_B-1", "T_A-1", np.nan], "mw": [30.0, 10, 5, 8, 99, 7]})
    fleet = pd.Series({"T_A-1": "transmission", "E_B-1": "embedded", "E_C-1": "embedded", "NB-1": "non_bm"})
    return units, energy, gen, h, anc, fleet


def _table(units, energy, gen, anc, fleet):
    t, um = B.assemble(2023, units, energy, gen)
    rows = B.response_rows(anc, fleet)
    resp, rm = B.response_held(rows, t.index, T("2023-12-31", tz="UTC"))
    return t.join(resp), um, rows, rm


def test_units_split_before_the_sum_and_empty_versus_zero():
    units, energy, gen, h, anc, fleet = _fleet()
    t, _, _, _ = _table(units, energy, gen, anc, fleet)
    assert len(t) == 17520
    r = t.loc[h[0]]
    assert (r["discharge_metered_mw"], r["charge_metered_mw"], r["net_metered_mw"]) == (100, 20, 80)   # not 80, 0
    assert (r["discharge_metered_transmission_mw"], r["charge_metered_embedded_mw"]) == (100, 20)
    assert r["discharge_metered_supplier_mw"] == 0                     # no supplier unit: 0, not empty
    assert np.isnan(t.loc[h[3], "discharge_metered_mw"])               # active units, none with a value
    assert t.loc[h[3], "discharge_notified_mw"] == 0                   # T_A-1 notified 0
    assert np.isnan(t.loc[h[3], "discharge_notified_embedded_mw"])     # E_B-1 has no notifications at all
    assert (r["units_active"], r["units_metered"], r["units_notified"]) == (2, 2, 1)   # E_C-1 not yet active, NB-1 not BM
    assert t.loc[T("2023-07-01", tz="UTC"), "units_active"] == 3


def test_response_held_by_product_and_group():
    units, energy, gen, h, anc, fleet = _fleet()
    t, _, rows, rm = _table(units, energy, gen, anc, fleet)
    assert set(rows["unit_id"]) == {"T_A-1", "E_B-1", "NB-1"}          # reserve and a gas engine left out
    r = t.loc[T("2023-01-01 00:00", tz="UTC")]
    assert (r["response_dcl_mw"], r["response_sffr_mw"], r["response_dch_mw"]) == (30, 8, 0)   # the block from 2022
    assert (r["response_dcl_transmission_mw"], r["response_sffr_embedded_mw"]) == (30, 8)
    r = t.loc[T("2023-01-01 03:00", tz="UTC")]
    assert (r["response_dcl_mw"], r["response_dch_mw"], r["response_dffr_mw"], r["response_dffr_non_bm_mw"]) == (
        0, 10, 5, 5)
    assert t.loc[T("2023-01-01 07:00", tz="UTC"), "response_dch_mw"] == 0
    assert not any(c.startswith(("response_low", "response_high")) for c in t)   # products are not added together
    assert t.loc[T("2023-12-31 00:00", tz="UTC"):, "response_dcl_mw"].isna().all()    # after the results end
    early, _ = B.response_held(rows, B.spine(2018), T("2019-02-01", tz="UTC"))
    assert early["response_dcl_mw"].isna().all()                       # before the first unit-level results
    m = rm.set_index(["unit_id", "product", "month"])["mwh_held"]
    assert m[("T_A-1", "dcl", "2023-01")] == 30 * 3                    # the 2022 hour left out


def test_a_block_over_a_month_end_is_split():
    idx = B.spine(2023)
    rows = pd.DataFrame({"delivery_start": [T("2023-01-31 23:00", tz="UTC")],
                         "delivery_end": [T("2023-02-01 03:00", tz="UTC")], "unit_id": ["T_A-1"],
                         "group": ["transmission"], "product": ["dcl"], "mw": [10.0]})
    _, rm = B.response_held(rows, idx, T("2024-01-01", tz="UTC"))
    assert rm.set_index("month")["mwh_held"].to_dict() == {"2023-01": 10.0, "2023-02": 30.0}


def test_summary_energy_share_capacity_coverage_and_regions():
    units, energy, gen, h, anc, fleet = _fleet()
    t, um, _, rm = _table(units, energy, gen, anc, fleet)
    s = B.summarise(t, um, units, rm)
    y = s[(s["resolution"] == "year") & (s["basis"] == "metered") & (s["gsp_group"] == "all")]
    y = y.set_index(["group", "flow"])
    assert y.loc[("all", "discharge"), "energy_gwh"] == pytest.approx((100 + 40) * 0.5 / 1000)
    assert y.loc[("all", "charge"), "energy_gwh"] == pytest.approx((20 + 80) * 0.5 / 1000)
    assert y.loc[("all", "net"), "energy_gwh"] == pytest.approx(40 * 0.5 / 1000)
    assert y.loc[("all", "discharge"), "mean_mw"] == pytest.approx(140 / 3, abs=0.01)   # over the half-hours with a value
    # discharge over generation in the half-hours both hold (the three with a metered value)
    assert y.loc[("all", "discharge"), "share_of_generation"] == pytest.approx(140 / 60000, abs=1e-6)
    assert np.isnan(y.loc[("all", "charge"), "share_of_generation"])
    assert y.loc[("all", "discharge"), "units"] == 2
    days_c = (T("2024-01-01") - T("2023-07-01")).days
    assert y.loc[("embedded", "discharge"), "capacity_mw"] == pytest.approx(50 + 20 * days_c / 365, abs=0.1)
    assert y.loc[("all", "discharge"), "capacity_mw"] == pytest.approx(150 + 20 * days_c / 365, abs=0.1)  # BM only
    covered, act = 3 + 3, 17520 * 2 + days_c * 48       # A and B have values in 3 half-hours; C none
    assert y.loc[("all", "discharge"), "coverage"] == pytest.approx(covered / act, abs=1e-5)
    reg = s[(s["resolution"] == "year") & (s["basis"] == "metered") & (s["gsp_group"] != "all")]
    reg = reg.set_index(["gsp_group", "flow"])
    assert reg.loc[("unknown", "discharge"), "energy_gwh"] == pytest.approx(0.05)     # T_A-1 has no GSP group
    assert reg.loc[("Eastern", "charge"), "energy_gwh"] == pytest.approx(0.01)
    assert reg.xs("discharge", level="flow")["energy_gwh"].sum() == pytest.approx(y.loc[("all", "discharge"), "energy_gwh"])
    r = s[(s["resolution"] == "year") & (s["basis"] == "response") & (s["gsp_group"] == "all")].set_index(["group", "flow"])
    assert set(r.index.get_level_values("flow")) == set(B.PRODUCTS)
    assert np.isnan(r.loc[("all", "dcl"), "energy_gwh"]) and r.loc[("all", "dcl"), "units"] == 1
    assert r.loc[("non_bm", "dffr"), "units"] == 1 and r.loc[("non_bm", "dcl"), "units"] == 0
    rr = s[(s["resolution"] == "year") & (s["basis"] == "response") & (s["gsp_group"] != "all")]
    assert rr.groupby("flow")["mean_mw"].sum()["dch"] == pytest.approx(r.loc[("all", "dch"), "mean_mw"], abs=0.01)
    m = s[(s["period"] == "2023-01") & (s["basis"] == "response") & (s["gsp_group"] == "all")].set_index(["group", "flow"])
    assert m.loc[("all", "dffr"), "mean_mw"] == pytest.approx(5 * 8 / (31 * 48), abs=0.005)    # 4 h of 5 MW in January
    assert r.loc[("all", "dcl"), "capacity_mw"] == pytest.approx(160 + 20 * days_c / 365, abs=0.1)  # non-BM included
    jan = s[(s["resolution"] == "month") & (s["period"] == "2023-01")]
    assert len(s[s["resolution"] == "month"]["period"].unique()) == 12 and not jan.empty


def test_unit_table_energy_coverage_and_response():
    units, energy, gen, h, anc, fleet = _fleet()
    t, um, _, rm = _table(units, energy, gen, anc, fleet)
    hours = float(t["response_dcl_mw"].notna().sum()) * 0.5
    units = units.assign(ngc_id=["A-1", "B-1", "C-1", "NB-1"])
    codes = pd.Series({"B1": "AB555PE", "NB1": "RM143PR"})          # NESO's spellings, punctuation dropped
    u = B.unit_table(2023, units, um, rm, hours, postcodes=codes).set_index("unit_id")
    assert u["postcode"].tolist() == [None, "AB555PE", None, "RM143PR"]
    assert list(u.columns) == B.UNIT_COLUMNS[:1] + B.UNIT_COLUMNS[2:]
    assert (u.at["T_A-1", "discharge_metered_mwh"], u.at["T_A-1", "charge_metered_mwh"]) == (50, 40)
    assert u.at["T_A-1", "coverage_metered"] == pytest.approx(3 / 17520, abs=1e-5)
    assert u.at["T_A-1", "response_dcl_mw"] == pytest.approx(30 * 3 / hours, abs=1e-3)   # 3 h of the block in 2023
    assert np.isnan(u.at["NB-1", "discharge_metered_mwh"]) and u.at["NB-1", "response_dffr_mw"] > 0
    assert u.at["E_B-1", "gsp_group"] == "Eastern" and u.at["E_C-1", "response_dcl_mw"] == 0


def test_a_period_without_any_value_is_empty_not_zero():
    units = pd.DataFrame({"unit_id": ["E_B-1"], "group": ["embedded"], "gsp_group": ["Eastern"], "capacity_mw": [50.0],
                          "active_from": ["2018-09-06"], "active_to": [np.nan]})
    t, um = B.assemble(2018, units, {"metered": {}, "notified": {}})
    t = t.join(B.response_held(B.response_rows(pd.DataFrame(columns=["delivery_start", "delivery_end", "service",
                                                                      "product", "unit", "elexon_unit", "mw"]),
                                               pd.Series(dtype=object)), t.index, None)[0])
    s = B.summarise(t, um, units)
    y = s[(s["resolution"] == "year") & (s["basis"] == "metered") & (s["group"] == "all") & (s["gsp_group"] == "all")]
    assert y["energy_gwh"].isna().all() and (y["coverage"] == 0).all()       # unknown, not 0
    jan = s[(s["period"] == "2018-01") & (s["basis"] == "metered") & (s["group"] == "all") & (s["gsp_group"] == "all")]
    assert (jan["energy_gwh"] == 0).all()                                     # no battery active yet: 0
