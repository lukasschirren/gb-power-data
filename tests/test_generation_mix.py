"""The generation mix (gbpowerdata.build.generation_mix) on synthetic data: NESO's settlement periods to UTC (both
date formats, the 46- and 50-period days) without its forecast rows; FUELHH's pumped storage split into generation and
pumping, every interconnector named and signed, a link absent from a published half-hour at 0 and an unpublished
half-hour empty, biomass empty before Elexon reported it; the totals; and the summary's energy, shares and coverage.
No data/ and no network needed."""
import numpy as np
import pandas as pd
import pytest

from gbpowerdata.build import generation_mix as G

T = pd.Timestamp


def test_settlement_periods_start_at_local_midnight_in_either_date_format():
    s = G.settlement_start(pd.Series(["2023-02-01", "01-Feb-23", "26-Mar-23", "29-Oct-23"]), pd.Series([1, 2, 3, 50]))
    assert list(s) == [T("2023-02-01 00:00", tz="UTC"), T("2023-02-01 00:30", tz="UTC"),   # ISO stays year-month-day
                       T("2023-03-26 01:00", tz="UTC"),       # period 3 of the 46-period day: 02:00 BST
                       T("2023-10-29 23:30", tz="UTC")]       # period 50 of the 50-period day


def test_neso_embedded_keeps_actuals_only(tmp_path):
    (tmp_path / "neso").mkdir()
    pd.DataFrame({"SETTLEMENT_DATE": ["2026-01-01"] * 3, "SETTLEMENT_PERIOD": [1, 2, 3],
                  "FORECAST_ACTUAL_INDICATOR": ["A", "A", "F"], "EMBEDDED_WIND_GENERATION": [100, 110, 999],
                  "EMBEDDED_SOLAR_GENERATION": [0, 0, 999]}).to_csv(tmp_path / "neso" / "historic_demand_2026.csv")
    e = G.neso_embedded(tmp_path, 2026)
    assert e["wind_embedded_mw"].tolist() == [100, 110] and list(e.columns) == ["wind_embedded_mw", "solar_embedded_mw"]
    assert G.neso_embedded(tmp_path, 2025).empty


def _fuelhh():
    idx = pd.date_range("2017-10-31 23:00", periods=4, freq="30min", tz="UTC", name="startTime")
    w = pd.DataFrame({"CCGT": [10000.0, 9000, np.nan, 8000], "NUCLEAR": [5000.0, 5000, np.nan, 5000],
                      "WIND": [3000.0, 3500, np.nan, 4000], "PS": [-500.0, 800, np.nan, 0],
                      "BIOMASS": [np.nan, np.nan, np.nan, 2000], "OTHER": [2500.0, 2500, np.nan, 500],
                      "INTFR": [-1000.0, 2000, np.nan, 1500], "INTELEC": [np.nan, 500, np.nan, np.nan],
                      "INTELE": [np.nan, np.nan, np.nan, 0.0], "INTVKL": [np.nan, np.nan, np.nan, -700]}, index=idx)
    w.loc[idx[2], :] = np.nan                                  # a half-hour FUELHH did not publish
    return w


def test_metered_columns_split_pumped_storage_and_sign_the_links():
    m = G.metered(_fuelhh())
    assert m["pumped_storage_generation_mw"].tolist()[:2] == [0, 800]
    assert m["pumped_storage_pumping_mw"].tolist()[:2] == [500, 0]
    assert m["interconnector_ifa_mw"].tolist()[:2] == [-1000, 2000]
    assert m["interconnector_eleclink_mw"].iloc[[0, 1, 3]].tolist() == [0, 500, 0]     # INTELE joins eleclink
    assert m["interconnector_viking_mw"].iloc[0] == 0 and m["interconnector_viking_mw"].iloc[3] == -700
    assert m.iloc[2].drop("metered_source").isna().all() and m["metered_source"].iloc[2] == "missing"
    assert m["biomass_mw"].iloc[:2].isna().all() and m["biomass_mw"].iloc[3] == 2000   # from 1 Nov 2017
    assert m["coal_mw"].iloc[0] == 0                            # a fuel without a row in a published half-hour


def test_totals_and_sources_on_the_spine():
    w = _fuelhh()
    emb = pd.DataFrame({"wind_embedded_mw": [400.0, 400, 400, 400], "solar_embedded_mw": [0.0, 0, 0, np.nan]},
                       index=w.index)
    t = G.assemble(w, emb, 2017)
    assert len(t) == 17520 and t.index[0] == T("2017-01-01", tz="UTC")
    r = t.loc[w.index[1]]
    assert r["generation_mw"] == 9000 + 5000 + 3500 + 800 + 2500 + 400      # pumping not subtracted
    assert (r["imports_mw"], r["exports_mw"], r["net_imports_mw"]) == (2500, 0, 2500)
    r0 = t.loc[w.index[0]]
    assert (r0["imports_mw"], r0["exports_mw"], r0["net_imports_mw"]) == (0, 1000, -1000)
    assert t.loc[w.index[3], "embedded_source"] == "missing" and np.isnan(t.loc[w.index[3], "generation_mw"])
    assert (t.loc[t.index.difference(w.index), "metered_source"] == "missing").all()


def test_summary_energy_shares_and_coverage():
    idx = pd.date_range("2023-01-01", periods=4, freq="30min", tz="UTC", name="startTime")
    t = pd.DataFrame({c: 0.0 for c in G.GENERATING}, index=idx)
    t["gas_ccgt_mw"], t["wind_metered_mw"] = 6000.0, 2000.0
    t["pumped_storage_pumping_mw"] = 0.0
    t["generation_mw"], t["imports_mw"], t["exports_mw"], t["net_imports_mw"] = 8000.0, 2000.0, 0.0, 2000.0
    t["metered_source"], t["embedded_source"] = ["FUELHH", "FUELHH", "FUELHH", "missing"], "NESO"
    s = G.summarise(t)
    y = s[s["resolution"] == "year"].set_index("technology")
    assert y.loc["gas_ccgt", "energy_gwh"] == pytest.approx(3 * 6000 * 0.5 / 1000)          # 3 complete half-hours
    assert y.loc["gas_ccgt", "share_of_generation"] == pytest.approx(0.75)
    assert y.loc["gas_ccgt", "share_of_supply"] == pytest.approx(0.6)
    assert y.loc["net_imports", "share_of_supply"] == pytest.approx(0.2) and np.isnan(y.loc["imports", "share_of_supply"])
    assert y.loc["gas_ccgt", "coverage"] == pytest.approx(3 / 4) and y.loc["gas_ccgt", "half_hours"] == 3
    assert set(s["resolution"]) == {"year", "month"}


def test_wind_units_are_offshore_by_the_farm_map_else_by_name():
    reg = pd.DataFrame({"elexonBmUnit": ["T_WLNYO-1", "T_ACHRW-1", "E_BURBO", "E_ABRTW-1", "2__ABCD", "T_CCGT-1",
                                         "T_WLNYO-1"],                                    # a unit listed twice
                        "bmUnitName": ["Walney", "A'Chruach", "Burbo Offshore Wind", "Auchrobert", "x", "y", "Walney"],
                        "fuelType": ["WIND", "WIND", "WIND", "WIND", "WIND", "CCGT", "WIND"]})
    farm = pd.DataFrame({"elexon_bmu_id": ["T_WLNYO-1", "T_ACHRW-1"], "is_offshore": [True, False]})
    f = G.wind_offshore_flags(reg, farm)
    assert f.to_dict() == {"T_WLNYO-1": True, "T_ACHRW-1": False, "E_BURBO": True, "E_ABRTW-1": False}


def test_a_map_row_without_a_repd_site_falls_back_to_the_name():
    # The map leaves is_offshore blank where no REPD site matched (North Kyle, Moy, Hywind); a blank is not offshore,
    # the unit's name decides (read from the CSV as the map is: True/False/blank -> object column with NaN).
    reg = pd.DataFrame({"elexonBmUnit": ["T_NOKYW-1", "E_HYWDW-1", "T_WLNYO-1"],
                        "bmUnitName": ["North Kyle Wind Farm-1", "Hywind Generator BMU1", "Walney"],
                        "fuelType": ["WIND", "WIND", "WIND"]})
    farm = pd.DataFrame({"elexon_bmu_id": ["T_NOKYW-1", "E_HYWDW-1", "T_WLNYO-1"],
                         "is_offshore": [np.nan, np.nan, True]}, dtype=object)
    f = G.wind_offshore_flags(reg, farm)
    assert f.to_dict() == {"T_NOKYW-1": False, "E_HYWDW-1": True, "T_WLNYO-1": True}


def test_wind_units_are_read_in_mw_on_utc_and_summed_by_flag(tmp_path):
    for unit, q in (("T_OFF-1", [50.0, 60.0]), ("E_ON-1", [10.0, -0.5])):
        pd.DataFrame({"settlementDate": ["2023-07-01", "2023-07-01"], "settlementPeriod": [1, 2],
                      "quantity": q}).to_csv(tmp_path / f"{unit}.csv", index=False)
    u = G.wind_units_metered(tmp_path, pd.Series({"T_OFF-1": True, "E_ON-1": False, "T_NOFILE": True}))
    assert u.index[0] == T("2023-06-30 23:00", tz="UTC")                 # period 1 of a BST day
    assert u["offshore_mw"].tolist() == [100.0, 120.0] and u["all_mw"].tolist() == [120.0, 119.0]


def test_metered_wind_splits_by_the_units_offshore_share_and_adds_up():
    idx = pd.date_range("2023-07-01", periods=3, freq="30min", tz="UTC")
    units = pd.DataFrame({"offshore_mw": [600.0, 10.0, 0.0], "all_mw": [800.0, 20.0, 0.0]}, index=idx)
    s = G.split_wind(pd.Series([1000.0, 30.0, 500.0], index=idx), units)
    assert s["wind_offshore_metered_mw"].iloc[0] == 750.0 and s["wind_onshore_metered_mw"].iloc[0] == 250.0
    assert s["wind_split_source"].tolist() == ["B1610", "missing", "missing"]   # under MIN_SPLIT_MW, or no units
    assert s["wind_offshore_metered_mw"].iloc[1:].isna().all()
