"""gbpowerdata.common.pecd_regions: weighted-average reweighting + offshore weight-table validation.

Fast, synthetic, no geometry/network -- `build_nuts2_gsp_group_weights` (the actual GISCO/GSP
polygon overlay) is exercised manually against real boundary files, not here.
"""

from __future__ import annotations

import pandas as pd
import pytest

from gbpowerdata.common import pecd_regions


def test_reweight_wide_is_weighted_average_not_sum():
    """Two source zones splitting into one target must AVERAGE (capacity factor is intensive),
    never sum -- summing would double-count and produce CF > 1."""
    idx = pd.to_datetime(["2023-01-01T00:00Z", "2023-01-01T01:00Z"])
    wide = pd.DataFrame({"Z1_solar_pv": [1.0, 0.5], "Z2_solar_pv": [0.0, 0.5]}, index=idx)
    weights = pd.DataFrame({"nuts2": ["Z1", "Z2"], "gsp_group": ["A", "A"], "weight": [0.5, 0.5]})

    out = pecd_regions.reweight_wide(wide, weights, "nuts2", "solar_pv")

    assert list(out.columns) == ["A_solar_pv"]
    assert out["A_solar_pv"].tolist() == pytest.approx([0.5, 0.5])


def test_reweight_wide_single_source_passes_through_regardless_of_weight_magnitude():
    """A target fed by exactly one source must reproduce that source's value exactly, whatever
    the (nonzero) weight is -- the weight is a split fraction, not a magnitude driver."""
    idx = pd.to_datetime(["2023-01-01T00:00Z"])
    wide = pd.DataFrame({"Z1_onshore_wind": [0.8]}, index=idx)
    weights = pd.DataFrame({"nuts2": ["Z1"], "gsp_group": ["A"], "weight": [0.3]})

    out = pecd_regions.reweight_wide(wide, weights, "nuts2", "onshore_wind")

    assert out["A_onshore_wind"].tolist() == pytest.approx([0.8])


def test_offshore_zone_weights_loads_valid_table(monkeypatch, tmp_path):
    (tmp_path / pecd_regions.OFFSHORE_ZONE_WEIGHTS_CSV).write_text(
        "# comment line\npecd_offshore_zone,nuts2,weight,basis,note\nZ1,UKM7,1.0,single,\n",
        encoding="utf-8")
    monkeypatch.setattr(pecd_regions.cfg, "reference_dir", lambda: tmp_path)

    w = pecd_regions.offshore_zone_weights(["Z1"])

    assert list(w.columns) == ["pecd_offshore_zone", "nuts2", "weight"]
    assert w["nuts2"].tolist() == ["UKM7"]


def test_offshore_zone_weights_raises_on_unmapped_zone(monkeypatch, tmp_path):
    (tmp_path / pecd_regions.OFFSHORE_ZONE_WEIGHTS_CSV).write_text(
        "pecd_offshore_zone,nuts2,weight,basis,note\nZ1,UKM7,1.0,single,\n", encoding="utf-8")
    monkeypatch.setattr(pecd_regions.cfg, "reference_dir", lambda: tmp_path)

    with pytest.raises(SystemExit, match="Z2"):
        pecd_regions.offshore_zone_weights(["Z1", "Z2"])


def test_offshore_zone_weights_raises_when_weights_dont_sum_to_one(monkeypatch, tmp_path):
    (tmp_path / pecd_regions.OFFSHORE_ZONE_WEIGHTS_CSV).write_text(
        "pecd_offshore_zone,nuts2,weight,basis,note\nZ1,UKM7,0.4,partial,\n", encoding="utf-8")
    monkeypatch.setattr(pecd_regions.cfg, "reference_dir", lambda: tmp_path)

    with pytest.raises(SystemExit, match="sum to 1"):
        pecd_regions.offshore_zone_weights(["Z1"])
