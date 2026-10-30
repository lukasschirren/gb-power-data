"""The transmission wind-farm map (scripts/build_wind_farm_map.py) and its tracked overrides
(data/reference/wind_farm_map_overrides.csv). Bad a Cheo (T_BDCHW-1) stood at ten times its capacity: Elexon's
register gives 270 MW, REPD 26.7 MW, and its notified output is a 3.5% capacity factor on 270 MW, 35% on 26.7. An
override may correct the register's capacity. What must hold:
  - a unit whose override gives a capacity takes it, and the override's note says why;
  - a unit with no override, or an override without a capacity, keeps the register's;
  - the tracked map carries Bad a Cheo at 26.7 MW, no longer flagged for its capacity ratio.
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_wind_farm_map as M  # noqa: E402


def units() -> pd.DataFrame:
    return pd.DataFrame({"elexon_bmu_id": ["T_BDCHW-1", "T_ACHRW-1", "T_DUNGW-1"],
                         "bmu_capacity_mw": [270.0, 48.3, 94.0]})


def overrides() -> pd.DataFrame:
    return pd.DataFrame({"elexon_bmu_id": ["T_BDCHW-1", "T_ACHRW-1"], "repd_ref_ids": [None, "4331"],
                         "bmu_capacity_mw": ["26.7", None], "note": ["register ten times REPD", "name match"]}
                        ).set_index("elexon_bmu_id")


def test_an_override_with_a_capacity_replaces_the_registers():
    w = M.apply_capacity_overrides(units(), overrides())
    assert w.set_index("elexon_bmu_id").loc["T_BDCHW-1", "bmu_capacity_mw"] == pytest.approx(26.7)


def test_units_without_an_override_capacity_keep_the_registers():
    w = M.apply_capacity_overrides(units(), overrides()).set_index("elexon_bmu_id")["bmu_capacity_mw"]
    assert w["T_ACHRW-1"] == pytest.approx(48.3) and w["T_DUNGW-1"] == pytest.approx(94.0)


def test_the_tracked_map_carries_bad_a_cheo_at_its_reported_capacity():
    r = pd.read_csv(ROOT / "data" / "reference" / "wind_farm_map.csv").set_index("elexon_bmu_id").loc["T_BDCHW-1"]
    assert r["bmu_capacity_mw"] == pytest.approx(26.7)
    assert "capacity_ratio" not in str(r["qa_flag"])
