"""The fuel price rules on synthetic values: the carbon months before the first UK ETS auction priced at the EUA of
the same month (or, as a sensitivity, at the first UKA month) and labelled as a back-fill (gbpowerdata.pull.carbon_pull,
AUDIT A4-1); the landed coal price as CIF value over tonnes in a centred three-month window, without suppressed rows
(gbpowerdata.pull.coal_pull, A4-6); and stage 2 carrying the landed price beside the Richards Bay one only where the
raw file has it. No data/ and no network needed."""
import numpy as np
import pandas as pd
import pytest

from gbpowerdata.build import stage2_build_timeseries as S2
from gbpowerdata.pull import carbon_pull as CP
from gbpowerdata.pull import coal_pull as CO


def _eua():
    months = pd.period_range("2020-11", "2021-06", freq="M")
    return pd.DataFrame({"month": months, "carbon_price_gbp_per_tonne": [20.0, 25.0, 30.0, 32.0, 35.0, 39.0, 45.0, 44.0],
                         "scheme": "EU-ETS"})


def _uka():
    return pd.DataFrame({"month": pd.period_range("2021-05", "2021-07", freq="M"),
                         "carbon_price_gbp_per_tonne": [49.09, 46.08, 44.15], "scheme": "UK-ETS"})


def test_the_months_before_the_first_uk_auction_take_that_months_eua_price():
    c = CP.combine(_eua(), _uka()).set_index("month")
    assert c.loc["2020-12", "scheme"] == "EU-ETS" and c.loc["2020-12", "carbon_price_gbp_per_tonne"] == 25.0
    gap = c.loc["2021-01":"2021-04"]
    assert gap["carbon_price_gbp_per_tonne"].tolist() == [30.0, 32.0, 35.0, 39.0]
    assert (gap["scheme"] == "UK-ETS (EUA proxy)").all()
    assert c.loc["2021-05", "scheme"] == "UK-ETS" and c.loc["2021-05", "carbon_price_gbp_per_tonne"] == 49.09
    assert c.index.is_unique and list(c.index) == sorted(c.index)       # the EUA's May and June are not kept


def test_the_first_uka_back_fill_is_kept_as_a_labelled_sensitivity():
    gap = CP.combine(_eua(), _uka(), "first-uka").set_index("month").loc["2021-01":"2021-04"]
    assert (gap["carbon_price_gbp_per_tonne"] == 49.09).all() and (gap["scheme"] == "UK-ETS (first UKA month)").all()
    with pytest.raises(ValueError):
        CP.combine(_eua(), _uka(), "civil-penalty")
    with pytest.raises(ValueError):                                     # an EUA month missing from the gap
        CP.combine(_eua()[_eua()["month"].astype(str) != "2021-02"], _uka())


def _imports(rows):
    return pd.DataFrame(rows, columns=["MonthId", "FlowTypeId", "CountryId", "PortId", "Value", "NetMass",
                                       "SuppressionIndex"])


def test_the_landed_price_weighs_a_centred_three_month_window_by_tonnes():
    imp = _imports([(201801, 3, 75, 0, 70e6, 1e9, 0),          # 1 Mt at GBP 70/t
                    (201802, 3, 75, 0, 1e6, 1e7, 0),           # 10 kt at GBP 100/t: one small cargo
                    (201802, 3, 400, 0, 9e9, 1e9, 1),          # suppressed: left out
                    (201802, 1, 3, 0, 5e5, 0, 0),              # no mass: left out
                    (201804, 3, 400, 0, 80e6, 1e9, 0)])        # nothing landed in March
    got = CO.landed(imp).set_index("month")
    assert got.index.tolist() == ["2018-01", "2018-02", "2018-03", "2018-04"]
    assert got.loc["2018-01", "coal_cif_uk_gbp_per_tonne"] == pytest.approx(71e6 / 1.01e6, abs=0.01)  # Jan-Feb
    assert got.loc["2018-02", "coal_cif_uk_gbp_per_tonne"] == pytest.approx(71e6 / 1.01e6, abs=0.01)  # Jan-Mar
    assert got.loc["2018-03", "coal_cif_uk_gbp_per_tonne"] == pytest.approx(81e6 / 1.01e6, abs=0.01)  # Feb-Apr
    assert got.loc["2018-04", "coal_cif_uk_gbp_per_tonne"] == 80.0 and got.loc["2018-04", "coal_cif_uk_kt"] == 1000.0
    assert got.loc["2018-01", "coal_landed_gbp_per_mwh_thermal"] == pytest.approx(70.3 / CO.MWH_PER_TONNE, abs=1e-3)


def _raw_fuel(path, landed: bool):
    days = pd.date_range("2020-11-01", "2022-02-28", freq="D")
    pd.DataFrame({"date": days.strftime("%Y-%m-%d"), "gas_price_pence_per_therm": 50.0}).to_csv(
        path / "gas_sap_daily.csv", index=False)
    months = pd.period_range("2020-11", "2022-02", freq="M").astype(str)
    pd.DataFrame({"month": months, "carbon_price_gbp_per_tonne": 40.0, "scheme": "UK-ETS"}).to_csv(
        path / "carbon_monthly.csv", index=False)
    coal = pd.DataFrame({"month": months, "coal_usd_per_tonne": 80.0, "coal_gbp_per_mwh_thermal": 9.0})
    if landed:
        coal["coal_landed_gbp_per_mwh_thermal"] = 10.0
    coal.to_csv(path / "coal_monthly.csv", index=False)


@pytest.mark.parametrize("landed", [True, False])
def test_stage_2_carries_the_landed_coal_price_only_where_the_raw_file_has_it(tmp_path, monkeypatch, landed):
    _raw_fuel(tmp_path, landed)
    monkeypatch.setattr(S2, "RAW", tmp_path)
    monkeypatch.setattr(S2, "YEAR", 2021)
    idx = pd.date_range("2021-01-01", "2021-01-03", freq="30min", tz="UTC", inclusive="left")
    f = S2.build_fuel_prices(idx)
    assert (f["coal_price_gbp_per_mwh_thermal"] == 9.0).all()
    assert ("coal_landed_price_gbp_per_mwh_thermal" in f) == landed
    if landed:
        assert np.allclose(f["coal_landed_price_gbp_per_mwh_thermal"], 10.0)
