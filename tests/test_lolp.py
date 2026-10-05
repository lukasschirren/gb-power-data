"""The D-1 midday LoLP vintage (gbpowerdata.build.build_lolp) on synthetic data: the vintage rule
across a DST change, and that a delivery-day publication never counts as the D-1 view."""
import pandas as pd

from gbpowerdata import config as cfg
from gbpowerdata.build import build_lolp


def test_dayahead_vintage_is_the_last_publication_before_1300_uk_on_d_minus_1(tmp_path, monkeypatch):
    (tmp_path / "forecasts").mkdir()
    rows = []
    # delivery day 2024-03-31 (clocks go forward at 01:00 UTC): D-1 = 30 March, GMT all day
    for pub, drm in (("2024-03-30T11:41:00Z", 1.0), ("2024-03-30T12:42:00Z", 2.0), ("2024-03-30T13:12:00Z", 3.0)):
        rows.append({"publishTime": pub, "startTime": "2024-03-31T12:00:00Z", "lossOfLoadProbability": 0.0, "deratedMargin": drm})
    # delivery day 2024-07-10 in BST: 13:00 BST is 12:00 UTC, so the 12:11 UTC publication is too late
    for pub, drm in (("2024-07-09T11:11:00Z", 4.0), ("2024-07-09T11:41:00Z", 5.0), ("2024-07-09T12:11:00Z", 6.0)):
        rows.append({"publishTime": pub, "startTime": "2024-07-10T17:00:00Z", "lossOfLoadProbability": 0.0, "deratedMargin": drm})
    # a publication on the delivery day itself never counts as the D-1 view
    rows.append({"publishTime": "2024-07-10T08:00:00Z", "startTime": "2024-07-10T17:00:00Z", "lossOfLoadProbability": 0.0, "deratedMargin": 9.0})
    pd.DataFrame(rows).to_csv(tmp_path / "forecasts" / "LOLPDRM_2024.csv", index=False)
    monkeypatch.setattr(cfg, "raw_dir", lambda: tmp_path)
    d = build_lolp.dayahead(2024)
    assert d.loc[pd.Timestamp("2024-03-31T12:00Z"), "drm_da_mw"] == 2.0
    assert d.loc[pd.Timestamp("2024-07-10T17:00Z"), "drm_da_mw"] == 5.0
