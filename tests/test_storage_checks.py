"""The storage feasibility checks (gbpowerdata.checks.storage) and the accepted BM volumes they take
(gbpowerdata.build.storage_revenues.accepted_volumes) on synthetic half-hours: the implied state of charge's daily
swing, the position after the BM as the notified energy plus the accepted volumes, the MWh discharged per MWh
charged, and the volume files read with the months they cover. No data/ and no network needed."""
import numpy as np
import pandas as pd
import pytest

from gbpowerdata.build import storage_revenues as S
from gbpowerdata.checks import storage as CS

UTC = "UTC"


def test_the_daily_swing_counts_the_opening_state():
    t = pd.date_range("2025-06-01 23:00", periods=4, freq="30min", tz=UTC)   # 00:00-01:30 on 2 Jun, UK local
    e = pd.Series([-5.0, -5.0, 4.0, 4.0], index=t)                          # charge 10 MWh, discharge 8
    assert CS.daily_swing(e).tolist() == [10.0]


def test_the_position_after_the_bm_adds_the_accepted_volumes():
    t = pd.date_range("2025-06-01", periods=3, freq="30min", tz=UTC)
    notified = pd.Series([-10.0, 0.0, 5.0], index=t)                         # charging, idle, discharging
    accepted = pd.Series([2.0, 6.0, -1.0, 7.0], index=[t[0], t[1], t[1], t[0] - pd.Timedelta("30min")])
    after = CS.after_bm(notified, accepted)                                  # an acceptance outside: ignored
    assert after.tolist() == [-8.0, 5.0, 5.0]
    assert CS.discharge_ratio(notified) == pytest.approx(0.5) and CS.discharge_ratio(after) == pytest.approx(10 / 8)
    assert np.isnan(CS.discharge_ratio(pd.Series([1.0, 2.0])))


def test_accepted_volumes_are_read_with_the_months_they_cover(tmp_path):
    folder = tmp_path / "bm_volumes"
    folder.mkdir()
    cols = ["settlementDate", "settlementPeriod", "startTime", "bmUnit", "nationalGridBmUnit", "side", "volume_mwh",
            "createdDateTime"]
    pd.DataFrame([["2025-06-01", 1, "2025-05-31T23:00:00Z", "E_A-1", "A-1", "bid", -3.0, "x"]], columns=cols).to_csv(
        folder / "bm_volumes_2025-06.csv", index=False)
    pd.DataFrame(columns=cols).to_csv(folder / "bm_volumes_2025-07.csv", index=False)       # a quiet month
    d, months = S.accepted_volumes(2025, tmp_path)
    assert months == {"2025-06", "2025-07"} and d["volume_mwh"].tolist() == [-3.0]
    assert d["startTime"].iat[0] == pd.Timestamp("2025-05-31 23:00", tz=UTC)
    assert S.accepted_volumes(2024, tmp_path)[1] == set()
