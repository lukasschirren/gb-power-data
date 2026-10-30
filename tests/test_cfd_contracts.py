"""The CfD contracts table (build.cfd_contracts) on a synthetic register: the day a contract begins (its start date,
else its expected start, else its target commissioning date; Hinkley Point C on 1 July 2030), its term and the first
day without it, a terminated contract without a date kept while a live one raises, the 2012 to 2024 price factor read
off the register's own indexation, the columns and classes, and the written dates read back by the loader."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from gbpowerdata import config as cfg
from gbpowerdata import processed
from gbpowerdata.build import cfd_contracts as C

ROOT = Path(__file__).resolve().parents[1]
T = pd.Timestamp
NA = np.nan
# the two indexation dates the register shows: every 2012-base contract indexed on the first date has the same
# current over initial ratio (1.4761), every 2024-base one 1.0566; the later date 1.4800 and 1.0594
R12, R24, R12_LATER, R24_LATER = 1.4761, 1.0566, 1.4800, 1.0594
FACTOR = R12 / R24


def _contract(cid, rnd, tech, status, start, expected, tcw_start, target, base_year=2012, mw=100.0, later=False):
    ratio = (R12_LATER if later else R12) if base_year == 2012 else (R24_LATER if later else R24)
    return dict(contract_id=cid, project_name=f"Project {cid}", allocation_round=rnd, technology_type=tech,
                current_installed_capacity=mw, start_date=start, expected_start_date=expected,
                target_commissioning_window_start_date=tcw_start, target_commissioning_date=target,
                base_year=base_year, initial_strike_price=100.0, current_strike_price=round(100.0 * ratio, 2),
                status=status)


def _rows(filler: int = 25) -> list[dict]:
    """The named contracts that exercise each rule, plus `filler` plain solar contracts per base year and indexation
    date, so price_factor can read the two dates off more than SHARED_MIN contracts each."""
    named = [
        # on time: the start date comes before the window's last day, so the term counts from the start
        _contract("IC-OFF", "Investment Contract", "Offshore Wind", "Live (Post-FIC)",
                  "2017-12-19", "2017-12-19", "2017-03-31", "2018-03-30"),
        # late: the window's last day (the target commissioning date) comes first
        _contract("AR2-LATE", "Allocation Round 2", "Offshore Wind", "Live (Pre-FIC)",
                  "2024-03-28", NA, "2022-04-01", "2023-03-31"),
        # not started: the expected start dates it
        _contract("AR5-EXP", "Allocation Round 5", "Onshore Wind", "Pre-MDD",
                  NA, "2027-01-01", "2027-01-01", "2027-01-01"),
        # neither: the target commissioning date; AR7 solar takes the 20-year term and is already in 2024 money
        _contract("AR7-TARGET", "Allocation Round 7", "Solar PV", "Pre-MDD",
                  NA, NA, "2028-03-31", "2028-03-31", base_year=2024, mw=7.6),
        # Hinkley Point C: no start or expected start; placed on 1 July 2030 before the target rule, 35 years
        _contract("HPC", "Bespoke", "Nuclear", "Pre-Start Date", NA, NA, "2025-05-01", "2025-05-01", mw=3260.0),
        # AR7 tidal stream keeps the 15-year term and its own strike class
        _contract("AR7-TIDAL", "Allocation Round 7", "Tidal Stream", "Pre-MDD",
                  NA, "2029-01-01", "2029-01-01", "2029-01-01", base_year=2024, mw=4.9),
        # a biomass conversion ends on 31 March 2027 whatever its start
        _contract("IC-BIO", "Investment Contract", "Biomass Conversion", "Live (Post-FIC)",
                  "2016-12-21", "2016-12-21", "2015-07-01", "2016-02-01", mw=420.0),
        # terminated, no date of any kind: kept, undated
        _contract("AR4-TERM", "Allocation Round 4", "Solar PV", "Terminated", NA, NA, NA, NA, mw=NA),
    ]
    filler = [_contract(f"F{b}-{d}-{i}", "Allocation Round 4" if b == 2012 else "Allocation Round 7", "Solar PV",
                        "Pre-MDD", NA, "2027-06-01", "2027-06-01", "2027-06-01", base_year=b, mw=10.0, later=bool(d))
              for b in (2012, 2024) for d in (0, 1) for i in range(filler)]
    return named + filler


def _frames(rows=None):
    """A register frame, a status frame (one status row more than the register, as LCCC's has) and the terms."""
    rows = _rows() if rows is None else rows
    reg = pd.DataFrame(rows).drop(columns="status")
    reg.attrs["source"] = "CfD_Register_test.xlsx"
    status = pd.DataFrame({"CFD_ID": [r["contract_id"] for r in rows] + ["NOT-IN-REGISTER"],
                           "Status": [r["status"] for r in rows] + ["Terminated"]})
    terms = pd.read_csv(ROOT / "data" / "reference" / "cfd_round_params.csv").set_index("allocation_round")
    return reg, status, terms


@pytest.fixture
def table() -> pd.DataFrame:
    return C.contracts(*_frames()).set_index("contract_id")


def test_begin_is_the_start_else_the_expected_start_else_the_target_commissioning_date(table):
    assert table.loc["IC-OFF", "begin"] == T("2017-12-19") and table.loc["IC-OFF", "dated_by"] == "start"
    assert table.loc["AR2-LATE", "begin"] == T("2024-03-28") and table.loc["AR2-LATE", "dated_by"] == "start"
    assert table.loc["AR5-EXP", "begin"] == T("2027-01-01") and table.loc["AR5-EXP", "dated_by"] == "expected"
    assert table.loc["AR7-TARGET", "begin"] == T("2028-03-31") and table.loc["AR7-TARGET", "dated_by"] == "target"


def test_hinkley_point_c_is_placed_on_1_july_2030_and_runs_35_years_from_it(table):
    assert table.loc["HPC", "begin"] == C.HPC_START == T("2030-07-01") and table.loc["HPC", "dated_by"] == "edf"
    assert table.loc["HPC", "term_years"] == 35 and table.loc["HPC", "end"] == T("2065-07-01")
    assert table.loc["HPC", "round_short"] == "HPC" and table.loc["HPC", "tech"] == "Nuclear"


def test_end_is_the_first_day_without_the_contract_and_after_the_begin_of_every_live_contract(table):
    assert table.loc["IC-OFF", "end"] == T("2032-12-19")          # 15 years from the start
    assert table.loc["AR2-LATE", "end"] == T("2038-03-31")        # 15 years from the window's last day
    assert table.loc["AR2-LATE", "tcw_end"] == T("2023-03-31")
    assert table.loc["AR5-EXP", "end"] == T("2042-01-01")         # the expected start counts as the start
    assert table.loc["AR7-TARGET", "end"] == T("2048-03-31")      # AR7 solar: 20 years
    assert table.loc["AR7-TIDAL", "end"] == T("2044-01-01")       # AR7 tidal: 15 years
    assert table.loc["IC-BIO", "end"] == T("2027-04-01")          # the biomass conversions' date
    assert table.loc[["IC-OFF", "AR2-LATE", "AR5-EXP", "AR7-TARGET", "HPC", "AR7-TIDAL", "IC-BIO"], "term_years"].tolist() \
        == [15, 15, 15, 20, 35, 15, 15]
    live = table[table["status"] != "terminated"]
    assert live["begin"].notna().all() and (live["end"] > live["begin"]).all()


def test_a_terminated_contract_without_a_date_is_kept_undated_and_a_live_one_raises():
    t = C.contracts(*_frames()).set_index("contract_id")
    assert t.loc["AR4-TERM", "status"] == "terminated" and t.loc["AR4-TERM", "mw"] == 0.0
    assert pd.isna(t.loc["AR4-TERM", "begin"]) and pd.isna(t.loc["AR4-TERM", "end"]) and t.loc["AR4-TERM", "dated_by"] == ""
    rows = _rows()
    rows[-1] = _contract("AR4-UNDATED", "Allocation Round 4", "Solar PV", "Pre-MDD", NA, NA, NA, NA)
    with pytest.raises(AssertionError, match="without a date"):
        C.contracts(*_frames(rows))


def test_every_register_contract_needs_a_status_and_a_known_round_and_technology():
    reg, status, terms = _frames()
    with pytest.raises(AssertionError, match="no LCCC status"):
        C.contracts(reg, status[status["CFD_ID"] != "HPC"], terms)
    with pytest.raises(AssertionError, match="without a class"):
        C.contracts(reg.assign(technology_type=reg["technology_type"].replace({"Tidal Stream": "Wave"})), status, terms)


def test_price_factor_is_the_ratio_of_the_two_bases_modal_indexation_and_puts_2012_money_into_2024(table):
    assert abs(C.price_factor(table.reset_index()) - FACTOR) < 1e-6
    assert (table["price_factor"] == table["price_factor"].iloc[0]).all()
    assert abs(table.loc["IC-OFF", "price_factor"] - FACTOR) < 1e-6
    assert abs(table.loc["IC-OFF", "strike_2024"] - 100.0 * FACTOR) < 1e-6      # 2012 money, factored
    assert table.loc["AR7-TARGET", "strike_2024"] == 100.0                      # already 2024 money
    assert table.loc["AR7-TARGET", "strike_base"] == 100.0 and table.loc["AR7-TARGET", "strike_current"] == 105.66
    # the two indexation dates must agree: the later date's 2024-base ratio moved on its own
    rows = [r | {"current_strike_price": 107.0} if r["base_year"] == 2024 and r["current_strike_price"] == 105.94
            else r for r in _rows()]
    with pytest.raises(AssertionError, match="price factors"):
        C.contracts(*_frames(rows))


def test_columns_classes_and_status_follow_the_register(table):
    assert list(table.reset_index().columns) == list(C.COLUMNS)
    assert table.loc["IC-OFF", ["round_short", "tech", "strike_class", "status"]].tolist() == \
        ["FIDeR", "Offshore", "Offshore", "operating"]
    assert table.loc["AR7-TIDAL", ["round_short", "tech", "strike_class", "status", "lccc_status"]].tolist() == \
        ["AR7", "Other", "Tidal", "contracted", "Pre-MDD"]
    assert table.loc["IC-BIO", ["tech", "strike_class"]].tolist() == ["Biomass", "Biomass"]
    assert table.loc["AR7-TARGET", "mw"] == 7.6 and table.loc["AR7-TARGET", "base_year"] == 2024
    assert table.loc["IC-OFF", "project"] == "Project IC-OFF"
    assert set(C.TECH) == set(C.STRIKE_CLASS)


def test_build_writes_iso_dates_that_the_loader_reads_back(tmp_path, monkeypatch):
    reg, status, _ = _frames()
    reg.to_excel(tmp_path / "CfD_Register_test.xlsx", index=False)
    status.to_csv(tmp_path / "status.csv", index=False)
    monkeypatch.setattr(cfg, "processed_dir", lambda: tmp_path / "processed")
    out = C.build(tmp_path / "CfD_Register_test.xlsx", tmp_path / "status.csv")
    text = (tmp_path / "processed" / "cfd_contracts.csv").read_text()
    assert text.splitlines()[0] == ",".join(C.COLUMNS)
    assert ",2017-12-19,2017-12-19,2017-03-31,2018-03-30," in text and "2065-07-01" in text and "00:00" not in text
    back = processed.read_cfd_contracts().set_index("contract_id")
    assert back.loc["IC-OFF", "end"] == T("2032-12-19") and back.loc["HPC", "begin"] == T("2030-07-01")
    assert pd.isna(back.loc["AR4-TERM", "end"]) and back.loc["AR4-TERM", "dated_by"] == ""
    assert len(back) == len(out) and (back["price_factor"] == out["price_factor"].iloc[0]).all()
