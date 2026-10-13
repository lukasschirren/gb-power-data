"""The Capacity Market stage's rules (gbpowerdata.build.capacity_market) on synthetic values: auction ids, the CPI
indexation of T-4 and T-3 auctions only, weighting factors from LCCC's payments (the largest implied ratio, the
residual month, the estimate), obligations from acquired and traded obligations cut at termination, the payment
formula, the storage kind, the links to storage BM units and the reconciliation over the months LCCC reports. No data/
and no network needed."""
import numpy as np
import pandas as pd
import pytest

from gbpowerdata.build import capacity_market as C

T = pd.Timestamp
T4_2024 = "2024-25 (T-4) Four Year Ahead Capacity Auction"
T1_2024 = "2024-25 (T-1) One Year Ahead Capacity Auction"


def test_auction_ids_types_and_delivery_years():
    assert C.auction_key("2020-21 (T-4) Four Year Ahead Capacity Auction") == ("T-4", 2020)
    assert C.auction_id("2016-17 (TR) Transitional Capacity Auction") == "TR-2016"
    assert C.auction_id("2022-23 (T-3) Three Year Ahead Capacity Auction") == "T-3-2022"
    assert C.auction_id("not an auction") is None
    assert C.delivery_year_of(T("2020-10-01")) == 2020 and C.delivery_year_of(T("2021-09-01")) == 2020


def cpi_series(level_by_month: dict | None = None) -> pd.Series:
    idx = pd.date_range("2014-01-01", "2026-08-01", freq="MS")
    s = pd.Series(100.0, index=idx)
    for m, v in (level_by_month or {}).items():
        s[T(m)] = v
    return s


def test_only_t4_and_t3_auctions_are_indexed_by_winter_cpi_means():
    cpi = cpi_series()
    cpi[T("2019-10-01"):T("2020-04-01")] = 110.0             # the winter before delivery year 2020/21
    assert C.cpi_ratio(cpi, "T-4", 2015, 2020)[2] == pytest.approx(1.10)
    assert C.cpi_ratio(cpi, "T-3", 2015, 2020)[2] == pytest.approx(1.10)
    assert C.cpi_ratio(cpi, "T-1", np.nan, 2020)[2] == 1.0 and C.cpi_ratio(cpi, "TR", np.nan, 2020)[2] == 1.0
    assert np.isnan(C.cpi_ratio(cpi, "T-4", 2015, 2027)[2])  # the winter 2026/27 is not published yet


def paid_rows(dy: int, auction: str, months, mw: float, gbp) -> list[dict]:
    return [{"auction_id": auction, "delivery_year": dy, "month": m, "obligation_mw": mw, "payment_gbp": g,
             "suspended": "Not Suspended"} for m, g in zip(months, gbp)]


def test_weighting_factors_are_the_largest_implied_ratio_with_a_residual_and_an_estimate():
    wf = np.array([0.085, 0.092, 0.097, 0.10, 0.088, 0.09, 0.077, 0.074, 0.071, 0.074, 0.074, 0.078])
    wf = wf / wf.sum()
    price = pd.DataFrame({"auction_id": ["T-1-2021", "T-4-2018", "T-1-2022", "T-1-2023", "T-1-2024"],
                          "auction_type": ["T-1", "T-4", "T-1", "T-1", "T-1"],
                          "first_delivery_year": [2021, 2018, 2022, 2023, 2024], "delivery_year": [2021, 2021, 2022, 2023, 2024],
                          "price_gbp_per_kw_year": [10.0, 20.0, 10.0, 10.0, 10.0]})
    rows = []
    for dy, aid in ((2021, "T-1-2021"), (2022, "T-1-2022"), (2023, "T-1-2023")):
        months = pd.date_range(f"{dy}-10-01", periods=12, freq="MS")
        rows += paid_rows(dy, aid, months, 1000.0, wf * 1000 * 10.0 * 1000)
    m21 = pd.date_range("2021-10-01", periods=12, freq="MS")
    rows += paid_rows(2021, "T-4-2018", m21, 500.0, wf * 500 * 20.0 * 1000 * 0.97)   # an obligation that fell mid-month
    rows += paid_rows(2021, "T-1-2021", m21[:1], 50.0, [1e9])                       # too small to count
    m24 = pd.date_range("2024-10-01", periods=11, freq="MS")                        # September not reported yet
    rows += paid_rows(2024, "T-1-2024", m24, 1000.0, wf[:11] * 1000 * 10.0 * 1000)
    w = C.weighting_factors(pd.DataFrame(rows), price, through=2025)
    y21 = w[w["delivery_year"] == 2021]
    assert np.allclose(y21["weighting_factor"].values, wf) and set(y21["basis"]) == {"lccc_payments"}
    y24 = w[w["delivery_year"] == 2024].set_index("month")
    assert y24.loc[T("2025-09-01"), "basis"] == "residual"
    assert y24.loc[T("2025-09-01"), "weighting_factor"] == pytest.approx(wf[11])
    y25 = w[w["delivery_year"] == 2025]
    assert set(y25["basis"]) == {"estimated"} and y25["weighting_factor"].sum() == pytest.approx(1.0)


def cmu_row(**kw) -> dict:
    row = {"Capacity Agreement Awarded": "Yes", "Auction Name": T4_2024, "Unique Agreement Identifier": "CAN-1",
           "Type": "T-4", "CMU ID": "CMU1", "CM Unit Name": "Holes Bay Battery", "Parent Company": "P Ltd",
           "Transmission or Distribution": "Distribution", "CM Unit Type": "CMRS",
           "CM Unit Category": "Existing Generating CMU", "Primary Fuel Type": "Storage - Battery",
           "CMU Technology": "Storage (Duration 2h)", "Connection or DSR Capacity": "20", "De Rated Capacity": "10",
           "Auction Acquired Capacity Obligation": "10", "Delivery Years for which Agreement Valid": "2024/2025",
           "Date of Termination of Capacity Agreement": "", "Capacity Agreement has been Terminated": "",
           "Has Capacity Agreement been Suspended": "", "List of Traded Capacity Obligations": "",
           "Period for which the transfer applies": "", "Capacity obligation Summary": ""}
    row.update(kw)
    return row


def test_obligations_add_acquired_and_traded_obligations_and_stop_at_termination():
    cmu = pd.DataFrame([
        cmu_row(**{"List of Traded Capacity Obligations": "T1: -4.000 MW",
                   "Period for which the transfer applies": "T1: 28/11/2024 - 11/12/2024",
                   "Capacity obligation Summary": "01/10/2024 - 27/11/2024:10.000 MW; 28/11/2024 - 11/12/2024:6.000 MW; "
                                                  "12/12/2024 - 26/12/2024:10.000 MW; 27/12/2024 - 16/01/2025:14.000 MW; "
                                                  "17/01/2025 - 30/09/2025:10.000 MW"}),
        cmu_row(**{"Auction Name": T1_2024, "Type": "ST", "Auction Acquired Capacity Obligation": "0",
                   "List of Traded Capacity Obligations": "T1: 4.000 MW",
                   "Period for which the transfer applies": "T1: 27/12/2024 - 16/01/2025",
                   "Capacity obligation Summary": "01/10/2024 - 27/11/2024:10.000 MW; 28/11/2024 - 11/12/2024:6.000 MW; "
                                                  "12/12/2024 - 26/12/2024:10.000 MW; 27/12/2024 - 16/01/2025:14.000 MW; "
                                                  "17/01/2025 - 30/09/2025:10.000 MW"}),
        cmu_row(**{"Unique Agreement Identifier": "CAN-2", "CMU ID": "CMU2", "CM Unit Name": "Elsewhere",
                   "Capacity Agreement has been Terminated": "Yes", "Date of Termination of Capacity Agreement": "01/02/2025"}),
        cmu_row(**{"Unique Agreement Identifier": "CAN-3", "Capacity Agreement Awarded": "No"}),
    ])
    agr = C.agreements(cmu)
    assert agr["agreement_id"].tolist() == ["CAN-1", "CAN-1", "CAN-2"]
    assert agr["row_type"].tolist() == ["own", "traded", "own"] and agr["storage"].eq("battery").all()
    seg = C.segments(agr)
    assert C.summary_mismatches(agr, seg).empty                 # the rows add up to the register's summary
    ob = C.monthly_obligation(seg, pd.date_range("2024-10-01", periods=12, freq="MS")).join(agr[["auction_id", "agreement_id"]], on="row")
    nov = ob[(ob["agreement_id"] == "CAN-1") & (ob["month"] == T("2024-11-01")) & (ob["auction_id"] == "T-4-2024")]
    assert nov["obligation_mw"].iat[0] == pytest.approx(10 - 4 * 3 / 30)
    dec = ob[(ob["agreement_id"] == "CAN-1") & (ob["month"] == T("2024-12-01"))].set_index("auction_id")["obligation_mw"]
    assert dec["T-4-2024"] == pytest.approx(10 - 4 * 11 / 31) and dec["T-1-2024"] == pytest.approx(4 * 5 / 31)
    ended = ob[ob["agreement_id"] == "CAN-2"].set_index("month")["obligation_mw"]
    assert ended[T("2025-01-01")] == pytest.approx(10.0) and T("2025-02-01") not in ended.index
    broken = agr.copy()
    broken.loc[1, "traded"] = "T1: 5.000 MW"
    assert not C.summary_mismatches(broken, C.segments(broken)).empty


def test_a_payment_is_weight_times_price_times_obligation():
    agr = C.agreements(pd.DataFrame([cmu_row()]))
    seg = C.segments(agr)
    price = pd.DataFrame({"auction_id": ["T-4-2024"], "delivery_year": [2024], "price_gbp_per_kw_year": [20.0]})
    months = pd.date_range("2024-10-01", periods=12, freq="MS")
    weights = pd.DataFrame({"delivery_year": 2024, "month": months, "weighting_factor": 1 / 12, "basis": "lccc_payments"})
    p = C.payments(agr, seg, price, weights, 2025)
    assert len(p) == 9 and p["payment_gbp"].iat[0] == pytest.approx(10 * 20.0 * 1000 / 12)   # Jan-Sep 2025
    assert p["storage"].iat[0] == "battery" and p["weighting_basis"].iat[0] == "lccc_payments"


def test_the_storage_kind_of_older_auctions_without_a_fuel():
    assert C.storage_kind("Storage - Pumped", "Storage (Duration 6h)", "x") == "pumped_storage"
    assert C.storage_kind("", "Storage", "Dinorwig Unit 1") == "pumped_storage"
    assert C.storage_kind("", "Storage", "KPBL01") == "battery"
    assert C.storage_kind("Gas", "Combined Cycle Gas Turbine (CCGT)", "x") == ""


def test_links_by_component_id_and_by_name_within_the_units_capacity():
    cmu = pd.DataFrame([
        cmu_row(),                                                                          # name: Holes Bay
        cmu_row(**{"Unique Agreement Identifier": "CAN-2", "CMU ID": "BIG", "CM Unit Name": "HOLESBAY"}),
        cmu_row(**{"Unique Agreement Identifier": "CAN-3", "CMU ID": "DIN", "CM Unit Name": "Dinorwig Unit 1",
                   "Primary Fuel Type": "", "CMU Technology": "Storage"}),
        cmu_row(**{"Unique Agreement Identifier": "CAN-4", "CMU ID": "DSR", "CM Unit Name": "Holes Bay",
                   "CM Unit Type": "Non CMRS"}),                                            # not metered as a BM unit
    ])
    comp = pd.DataFrame({"Auction Name": T4_2024, "CMU ID": ["CMU1", "BIG", "DIN", "DSR"],
                         "Component ID": ["X01", "X02", "T_DINO-1", "X04"],
                         "Description of CMU Components": ["", "", "", ""],
                         "Connection or DSR Capacity": ["7", "60", "300", "5"]})
    units = pd.DataFrame({"unit_id": ["E_BHOLB-1", "T_DINO-1"], "ngc_id": ["BHOLB-1", "DINO-1"],
                          "unit_name": ["Holes Bay Battery", "Dinorwig 1"], "capacity_mw": [7.12, 300.0]})
    links = C.storage_links(C.agreements(cmu, comp), comp, units).set_index("agreement_id")
    assert links.loc["CAN-1", "unit_id"] == "E_BHOLB-1" and links.loc["CAN-1", "basis"] == "name"
    assert "CAN-2" not in links.index                      # 60 MW: larger than the 7 MW unit, another project
    assert links.loc["CAN-3", "unit_id"] == "T_DINO-1" and links.loc["CAN-3", "basis"] == "component_id"
    assert "CAN-4" not in links.index
    assert C.name_match("Holes Bay Battery", "HOLESBAY") and not C.name_match("Battery Storage", "Any Battery")


def test_the_reconciliation_compares_only_the_months_lccc_reports():
    months = pd.date_range("2025-10-01", periods=12, freq="MS")
    pay = pd.DataFrame({"auction_id": "T-1-2025", "delivery_year": 2025, "month": months, "payment_gbp": 10.0,
                        "cm_unit_category": ["New Build Generating CMU"] + ["Existing Generating CMU"] * 11})
    paid = pd.DataFrame({"auction_id": "T-1-2025", "delivery_year": 2025, "month": months[:11], "payment_gbp": 10.0})
    r = C.reconcile(pay, paid).iloc[0]
    assert r["months"] == 11 and r["ratio"] == pytest.approx(1.0) and r["new_build_share"] == pytest.approx(1 / 11)
