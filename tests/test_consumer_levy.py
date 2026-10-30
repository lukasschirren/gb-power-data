"""gbpowerdata.build.build_consumer_levy.load_reconciled on a synthetic LCCC file: the latest settlement run of each
day, with the electricity exempted for energy-intensive industries beside the eligible demand."""

import pandas as pd

from gbpowerdata.build import build_consumer_levy as L


def test_reconciled_rows_carry_the_energy_intensive_exemption(tmp_path, monkeypatch):
    pd.DataFrame({
        "Settlement_Date": ["2024-07-01", "2024-07-01", "2024-07-02"],
        "Settlement_Run_Type": ["II", "R1", "R1"],
        "Reconciled_Daily_Levy_Rate_GBP_Per_MWh": ["5.0", "5.1", "4.9"],
        "Reconciled_Eligible_Demand_MWh": ["600000", "590000", "610000"],
        "Reconciled_Energy_Intensive_Industries_Demand_MWh": ["20000", "30000", "31000"],
        "Reconciled_Green_Excluded_Electricity_MWh": ["0", "0", "0"],
        "Latest_Flag": ["Not Latest", "Latest Settlement Run", "Latest Settlement Run"],
    }).to_csv(tmp_path / "levy_reconciled_daily.csv", index=False)
    monkeypatch.setattr(L, "LCCC", tmp_path)

    df = L.load_reconciled()

    assert df["eii_demand_mwh"].tolist() == [30000.0, 31000.0]
    assert df["settlement_run"].tolist() == ["R1", "R1"]
