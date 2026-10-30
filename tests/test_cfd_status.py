"""The end of a CfD (gbpowerdata.build.build_cfd_status.contract_end) on synthetic contracts: the term counts from the
earlier of the start date and the last day of the target commissioning window, so a late start shortens it; a
window whose last day the register does not give counts from its first day; biomass conversions end on 31 March
2027; Hinkley Point C's bespoke contract counts from its start; AR7 wind and solar take the 20-year term."""

from pathlib import Path

import pandas as pd

from gbpowerdata.build import build_cfd_status as S

ROOT = Path(__file__).resolve().parents[1]

T = pd.Timestamp


def test_the_term_counts_from_the_earlier_of_the_start_and_the_windows_last_day():
    # on time: the start comes first
    assert S.contract_end(T("2017-12-19"), T("2017-03-31"), T("2018-03-30"), 15, "Offshore Wind",
                          "Investment Contract") == T("2032-12-19")
    # late: the window's last day (the target commissioning date, 364 days after its first) comes first
    assert S.contract_end(T("2024-03-28"), T("2022-04-01"), T("2023-03-31"), 15, "Offshore Wind",
                          "Allocation Round 2") == T("2038-03-31")
    # no window length in the register: the window's first day stands in for its last
    assert S.contract_end(T("2025-04-16"), T("2019-03-31"), T("2019-03-31"), 15, "Offshore Wind",
                          "Allocation Round 1") == T("2034-03-31")


def test_conversions_end_in_2027_and_hinkley_point_c_counts_from_its_start():
    assert S.contract_end(T("2016-12-21"), T("2015-07-01"), T("2016-02-01"), 15, "Biomass Conversion",
                          "Investment Contract") == T("2027-04-01")
    assert S.contract_end(T("2030-07-01"), T("2025-05-01"), T("2025-05-01"), 35, "Nuclear", "Bespoke") == T("2065-07-01")
    assert pd.isna(S.contract_end(pd.NaT, T("2028-01-01"), T("2028-03-31"), 20, "Solar PV", "Allocation Round 7"))


def test_contracts_signed_before_2016_carry_no_negative_price_rule():
    # Investment Contracts (2014) and AR1 (signed 2015): Difference = MIN(SP, SP - MRP), never suspended (SI 2015/1425
    # explanatory note: the rule applies to contracts signed from 1 January 2016); AR2 on carry the rule.
    p = pd.read_csv(ROOT / "data" / "reference" / "cfd_round_params.csv").set_index("vintage")
    assert p.loc[["FIDeR", "AR1"], "neg_price_rule"].tolist() == ["none", "none"]
    assert (p.loc[["FIDeR", "AR1"], "neg_price_min_consecutive_hours"] == 0).all()
    assert p.loc["AR2", "neg_price_rule"] == "six_hour"


def test_ar7_wind_and_solar_take_the_key_technology_term():
    assert {"Offshore Wind", "Floating Offshore Wind", "Onshore Wind", "Remote Island Wind", "Solar PV"} == S.KEY_TERM
    assert S.TECH_MAP["Floating Offshore Wind"] == ("Wind", True, "offshore")
    assert "Tidal Stream" not in S.KEY_TERM
