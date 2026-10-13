"""The storage revenue layer on synthetic rows shaped like the sources: notified energy from physical notification
segments; the position valued at the market index price, else the system price; active days and the annual rate;
NESO's four schemas of ancillary results put into one (UTC and UK local times, checked on the EFA hours), with
repeats dropped by id and an overlap between files refused; Elexon's cashflow rows; the resource names the
ancillary puller matches. No data/ and no network needed."""
import numpy as np
import pandas as pd
import pytest

from gbpowerdata.build import ancillary_services as A
from gbpowerdata.build import storage_revenues as S
from gbpowerdata.pull import ancillary_pull as AP
from gbpowerdata.pull import ebocf_pull as E

UTC = "UTC"


def test_notified_energy_integrates_each_segment_within_its_half_hour(tmp_path):
    f = tmp_path / "T_TESTB-1.csv"
    pd.DataFrame({
        "settlementDate": ["2025-01-08"] * 3, "settlementPeriod": [1, 1, 2],
        "timeFrom": ["2025-01-08T00:00:00Z", "2025-01-08T00:15:00Z", "2025-01-08T00:30:00Z"],
        "timeTo": ["2025-01-08T00:15:00Z", "2025-01-08T00:30:00Z", "2025-01-08T01:00:00Z"],
        "levelFrom": [100.0, 0.0, -50.0], "levelTo": [100.0, 100.0, -50.0],
    }).to_csv(f, index=False)
    e = S.fpn_energy(f)
    assert e.loc[pd.Timestamp("2025-01-08 00:00", tz=UTC)] == pytest.approx(25.0 + 12.5)   # flat, then a ramp
    assert e.loc[pd.Timestamp("2025-01-08 00:30", tz=UTC)] == pytest.approx(-25.0)          # charging


def test_a_segment_longer_than_its_half_hour_is_refused(tmp_path):
    f = tmp_path / "T_TESTB-1.csv"
    pd.DataFrame({"timeFrom": ["2025-01-08T00:00:00Z"], "timeTo": ["2025-01-08T01:00:00Z"],
                  "levelFrom": [10.0], "levelTo": [10.0]}).to_csv(f, index=False)
    with pytest.raises(AssertionError):
        S.fpn_energy(f)


def test_the_position_is_valued_at_the_mid_else_the_system_price():
    t = pd.date_range("2025-03-01", periods=3, freq="30min", tz=UTC)
    energy = pd.Series([10.0, -20.0, 5.0], index=t)
    mid = pd.Series([100.0, np.nan, 80.0], index=t).dropna()        # the MID had no volume in the second period
    sp = pd.Series([90.0, 30.0, 70.0], index=t)
    w = S.wholesale(energy, mid, sp).loc["2025-03"]
    assert w["wholesale_gbp"] == pytest.approx(10 * 100 - 20 * 30 + 5 * 80)
    assert (w["discharge_mwh"], w["charge_mwh"]) == (15.0, 20.0)
    assert w["price_fallback_share"] == pytest.approx(20 / 35)


def test_a_day_missing_from_the_notifications_lowers_the_months_coverage_not_its_position():
    # Elexon's archive misses whole days for every unit (18 days of November 2020): an unknown position, not zero
    t = pd.date_range("2020-11-01", "2020-12-01", freq="30min", tz=UTC, inclusive="left")
    held = t[(t < pd.Timestamp("2020-11-03", tz=UTC)) | (t >= pd.Timestamp("2020-11-04", tz=UTC))]   # 2 Nov missing
    share = S.notified_share(held, 2020, np.nan, np.nan)
    assert share["2020-11"] == pytest.approx(29 / 30)
    assert share["2020-01"] == 0.0                                       # nothing notified in January
    # inside the unit's activity only: from 15 Nov the month is complete
    assert S.notified_share(held, 2020, "2020-11-15", np.nan)["2020-11"] == pytest.approx(1.0)


def test_annual_coverage_is_weighted_by_days():
    gbp = {c: 0.0 for c in S.GBP}
    t = pd.DataFrame([
        {"year": 2020, "month": "2020-10", "unit_id": "T_X-1", "ngc_id": "X-1", "unit_name": "X", "tech": "battery",
         "connection": "transmission", "capacity_mw": 10.0, "lead_party": "A", "trader": "A", "optimiser": pd.NA,
         "days": 31, "has_fpn": True, "fpn_coverage": 1.0, "trading": True, "discharge_mwh": 1.0, "charge_mwh": 1.0,
         **gbp, "total_gbp": 0.0},
        {"year": 2020, "month": "2020-11", "unit_id": "T_X-1", "ngc_id": "X-1", "unit_name": "X", "tech": "battery",
         "connection": "transmission", "capacity_mw": 10.0, "lead_party": "A", "trader": "A", "optimiser": pd.NA,
         "days": 30, "has_fpn": True, "fpn_coverage": 0.4, "trading": True, "discharge_mwh": 1.0, "charge_mwh": 1.0,
         **gbp, "total_gbp": 0.0},
    ])
    assert S.annual(t)["fpn_coverage"].iloc[0] == pytest.approx((31 * 1.0 + 30 * 0.4) / 61)


def test_active_days_and_the_annual_rate():
    d = S.active_days(2025, "2025-03-15", np.nan)
    assert d["2025-02"] == 0 and d["2025-03"] == 17 and d["2025-12"] == 31
    assert S.active_days(2024, np.nan, np.nan)["2024-02"] == 29
    rate = S.annualise([2000.0, 2000.0, 100.0], [2.0, 2.0, 1.0], [365, 0, 365])
    assert rate[0] == pytest.approx(1.0) and np.isnan(rate[1])
    assert np.isnan(rate[2])                     # a 1 MW pumping unit (Cruachan's T_CRUAD-1) gets no rate


def test_a_month_without_position_cashflow_or_payment_is_not_trading():
    gbp = {c: 0.0 for c in S.GBP}
    rows = pd.DataFrame([
        {"discharge_mwh": 0.0, "charge_mwh": 0.0, **gbp},                                # registered, zeros only
        {"discharge_mwh": np.nan, "charge_mwh": np.nan, **gbp, "bm_offer_gbp": 120.0},   # BM only
        {"discharge_mwh": 0.0, "charge_mwh": 0.0, **gbp, "anc_dr_gbp": -50.0},           # a negative DR price paid
        {"discharge_mwh": 10.0, "charge_mwh": 12.0, **gbp},
    ])
    assert S.trading(rows).tolist() == [False, True, True, True]


def test_capacity_payments_follow_the_links_share(tmp_path):
    pd.DataFrame({"month": ["2025-01-01", "2025-01-01"], "agreement_id": ["CAN-1", "CAN-2"],
                  "auction_id": ["T-4-2024", "T-1-2024"], "obligation_mw": [10.0, 4.0],
                  "payment_gbp": [1000.0, 300.0]}).to_csv(tmp_path / "capacity_market_2025.csv", index=False)
    pd.DataFrame({"agreement_id": ["CAN-1", "CAN-1", "CAN-2"], "auction_id": ["T-4-2024", "T-4-2024", "T-1-2024"],
                  "unit_id": ["E_A-1", "E_A-2", "E_A-1"], "share": [0.6, 0.4, 1.0]}).to_csv(
        tmp_path / "capacity_market_links.csv", index=False)
    cm = S.capacity_payments(2025, tmp_path)
    assert cm.loc[("E_A-1", "2025-01"), "cm_gbp"] == pytest.approx(900.0)
    assert cm.loc[("E_A-2", "2025-01"), "cm_obligation_mw"] == pytest.approx(4.0)
    assert S.capacity_payments(2024, tmp_path) is None                     # no table for the year


def test_capacity_payments_count_from_entry_outages_included(tmp_path):
    pd.DataFrame({"unit_id": ["E_NEW-1"], "entry_date": ["2025-03-20"]}).to_csv(tmp_path / "storage_fleet.csv",
                                                                               index=False)
    t = pd.DataFrame({"unit_id": ["E_NEW-1"] * 4 + ["E_OLD-1"] * 2,
                      "month": ["2025-02", "2025-03", "2025-04", "2025-05", "2025-01", "2025-02"],
                      "trading": [False, True, False, True, False, True]})
    built = S.built_months(t, tmp_path)
    assert built.tolist() == [False, True, True, True, False, True]   # an outage month still pays; before entry not


def test_supplier_and_vlp_batteries_join_for_the_years_they_trade_with_a_lower_bound_capacity(tmp_path):
    pd.DataFrame({"unit_id": ["E_A-1", "2__FBPGM001", "V__NHABI005", "GSET-07"],
                  "ngc_id": ["A-1", "FBPG01", "NHAB05", "GSET-07"], "kind": ["bm", "supplier", "vlp", "non_bm"],
                  "tech": ["battery"] * 4, "unit_name": ["A", "Wormald Green BESS", None, None],
                  "lead_party": ["X", "BP Gas Marketing Limited", "Habitat", None],
                  "capacity_mw": [10.0, 49.0, 30.0, 5.0],
                  "capacity_source": ["register", "ancillary_max_mw", "ancillary_max_mw", "ancillary_max_mw"],
                  "entry_date": ["2020-01-01", "2023-05-02", "2026-01-10", "2021-01-01"],
                  "last_seen": ["2026-10-08"] * 4}).to_csv(tmp_path / "storage_fleet.csv", index=False)
    u = S.fleet_units(2025, tmp_path)
    # T_/E_ units come from the register, a non-BM unit has no Elexon id, the V__ unit trades from 2026
    assert u["unit_id"].tolist() == ["2__FBPGM001"]
    assert (u["active_from"].iat[0], u["capacity_source"].iat[0]) == ("2023-05-02", "ancillary_max_mw")
    rate = S.annualise([49_000.0, 49_000.0], [49.0, 49.0], [365, 365], ["register", "ancillary_max_mw"])
    assert rate[0] == pytest.approx(1.0) and np.isnan(rate[1])          # a lower-bound capacity gets no rate


def test_an_unlinked_supplier_unit_has_no_capacity_payment_rather_than_zero(tmp_path):
    pd.DataFrame({"unit_id": ["E_A-1", "2__B-1"], "entry_date": ["2024-01-01", "2024-01-01"]}).to_csv(
        tmp_path / "storage_fleet.csv", index=False)
    t = pd.DataFrame({"unit_id": ["E_A-1", "E_A-1", "2__B-1"], "month": ["2025-01", "2025-02", "2025-01"],
                      "kind": ["bm", "bm", "supplier"], "trading": [True, True, True]})
    cm = pd.DataFrame({"cm_obligation_mw": [5.0], "cm_gbp": [800.0]},
                      index=pd.MultiIndex.from_tuples([("E_A-1", "2025-01")], names=["unit_id", "month"]))
    c = S.capacity_columns(t, cm, tmp_path)
    assert c["cm_gbp"].iloc[:2].tolist() == [800.0, 0.0] and np.isnan(c["cm_gbp"].iat[2])
    assert S.capacity_columns(t, None, tmp_path)["cm_gbp"].isna().all()      # without the tables: unknown


def test_dc_tenders_keep_accepted_rows_and_agree_with_their_total_cost():
    t = pd.DataFrame({
        "Market Name": ["DC LF", "DC LF", "Withdraw"], "Accepted/Rejected": ["Accepted", "Rejected", "Rejected"],
        "Response Unit": ["ARNKB-1", "AG-HEL00G", "X-1"], "Agent/Applicant": ["Arenko Cleantech Limited"] * 3,
        "Technology Type": ["Battery"] * 3, "Volume Accepted": [49, 0, 0], "Availability Fee": [15.03, 24, 1],
        "Delivery Start UTC": ["2020-10-01T22:00:00"] * 3, "Delivery End UTC": ["2020-10-02T22:00:00"] * 3,
        "Service Duration": [24, 24, 24], "Total Cost": [17675.28, None, None],
    })
    d = A.dc_tender(t, "dc_tender_2020_2021")
    assert len(d) == 1 and d["product"].iloc[0] == "DCL"
    n = A.normalise(d.assign(priority=0))
    assert n["revenue_gbp"].iloc[0] == pytest.approx(17675.28) and n["hours"].iloc[0] == 24


def test_auction_results_in_uk_local_time_land_on_utc_and_a_wrong_zone_fails():
    t = pd.DataFrame({"Company": ["A"], "Unit Name": ["CHAPB-1"], "Service": ["DCL"], "Cleared Volume": [10],
                      "Clearing Price": [5.0], "Technology Type": ["Battery"], "Cancelled": [""],
                      "Delivery Start": ["2022-07-01T23:00:00"], "Delivery End": ["2022-07-02T03:00:00"]})
    d = A.dc_dr_dm(t, "dc_dr_dm_by_unit_2021_2023")
    assert d["delivery_start"].iloc[0] == pd.Timestamp("2022-07-01 22:00", tz=UTC)       # 23:00 BST
    wrong = t.assign(**{"Delivery Start": ["2022-07-01T22:00:00"], "Delivery End": ["2022-07-02T02:00:00"]})
    with pytest.raises(AssertionError):                                                 # UTC read as local time
        A.dc_dr_dm(wrong, "dc_dr_dm_by_unit_2021_2023")


def _eac(ids, units, starts, mw=10.0, product="DCH", source="eac_by_unit_fy2025"):
    t = pd.DataFrame({"registeredAuctionParticipant": "TESLA MOTORS LIMITED", "auctionUnit": units,
                      "serviceType": "Response", "auctionProduct": product, "executedQuantity": mw,
                      "clearingPrice": 2.0, "deliveryStart": starts,
                      "deliveryEnd": [str(pd.Timestamp(s) + pd.Timedelta(hours=4)) for s in starts],
                      "technologyType": "Batteries", "postCode": None, "unitResultID": ids})
    return A.eac(t, source)


def test_a_result_repeated_in_the_daily_file_counts_once():
    a = _eac(["1#||#2#||#DCH#||#3"], ["FARNB-1"], ["2026-10-07T22:00:00"], source="eac_by_unit_current_20261007")
    b = _eac(["1#||#2#||#DCH#||#3"], ["FARNB-1"], ["2026-10-07T22:00:00"], source="eac_by_unit_daily_20261007")
    n = A.normalise(pd.concat([a.assign(priority=3), b.assign(priority=4)], ignore_index=True))
    assert len(n) == 1 and n["source"].iloc[0].startswith("eac_by_unit_current")
    assert n["revenue_gbp"].iloc[0] == pytest.approx(10 * 2.0 * 4)


def test_two_files_holding_one_result_under_different_ids_are_refused():
    a = _eac(["1#||#2#||#DCH#||#3"], ["FARNB-1"], ["2025-07-01T22:00:00"], source="eac_by_unit_fy2025")
    b = _eac(["9#||#9#||#DCH#||#9"], ["FARNB-1"], ["2025-07-01T22:00:00"], source="br_by_unit_2023_2024")
    with pytest.raises(AssertionError):
        A.normalise(pd.concat([a.assign(priority=0), b.assign(priority=1)], ignore_index=True))


def test_zero_mw_rows_are_dropped_and_an_unknown_product_is_refused():
    z = _eac(["1"], ["FARNB-1"], ["2025-07-01T22:00:00"], mw=0.0)
    assert A.normalise(z.assign(priority=0)).empty
    odd = _eac(["2"], ["FARNB-1"], ["2025-07-01T22:00:00"], product="XYZ")
    with pytest.raises(AssertionError):
        A.normalise(odd.assign(priority=0))


def test_cashflow_rows_keep_the_non_zero_ones_with_their_sign():
    payload = {"data": [
        {"settlementDate": "2025-01-01", "settlementPeriod": 1, "startTime": "2025-01-01T00:00:00Z",
         "bmUnit": "E_ARNKB-1", "nationalGridBmUnit": "ARNKB-1", "totalCashflow": -63.5, "createdDateTime": "x"},
        {"settlementDate": "2025-01-01", "settlementPeriod": 2, "startTime": "2025-01-01T00:30:00Z",
         "bmUnit": "E_ARNKB-1", "nationalGridBmUnit": "ARNKB-1", "totalCashflow": 0.0, "createdDateTime": "x"},
        {"settlementDate": "2025-01-01", "settlementPeriod": 3, "startTime": "2025-01-01T01:00:00Z",
         "bmUnit": "E_ARNKB-1", "nationalGridBmUnit": "ARNKB-1", "totalCashflow": None, "createdDateTime": "x"},
    ]}
    r = E.rows(payload, "bid")
    assert len(r) == 1 and r[0]["cashflow_gbp"] == -63.5 and r[0]["side"] == "bid"
    assert list(r[0]) == E.COLUMNS


def test_the_ancillary_puller_matches_whole_resource_names():
    assert AP.stem_for("eac-auction-results", "NESO Response-Reserve Results By Unit FY2026 (Archive)") == \
        ("eac_by_unit_fy2026", False, "dump")
    assert AP.stem_for("eac-auction-results", "NESO Response-Reserve Results By Unit") == \
        ("eac_by_unit_current", True, "dump")
    assert AP.stem_for("eac-auction-results", "NESO Response-Reserve Sell Orders 202604 (Archive)") is None
    assert AP.stem_for("dynamic-containment-data", "DC, DR & DM Results By Unit Master Data 2021-2023") == \
        ("dc_dr_dm_by_unit_2021_2023", False, "dump")


def test_the_storage_layer_reads_no_licensed_market_data():
    # the MID comes from Elexon's mid_apx_* pulls; nothing from the day-ahead auctions (N2EX, EPEX) is read
    import inspect
    for mod in (S, A):
        src = inspect.getsource(mod)
        for token in ("nordpool", "dayahead_price", "mid_target", "epex_pull", "nordpool_pull", "parse_n2ex"):
            assert token not in src, (mod.__name__, token)
