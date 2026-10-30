"""The model-inputs export (modelinputs): the table list, the manifest, the licensed guard and the refusals, on a
synthetic data tree."""
from __future__ import annotations

import json

import pytest

from gbpowerdata import modelinputs as M


@pytest.fixture
def tree(tmp_path, monkeypatch):
    raw, proc, ref = tmp_path / "raw", tmp_path / "processed", tmp_path / "reference"
    for d in (raw / "ecb_fx", raw / "lccc", raw / "gis", proc / "pecd", ref):
        d.mkdir(parents=True)
    for name in M.YEARLY:
        (proc / f"{name}_2023.csv").write_text("startTime,x\n2023-01-01T00:00Z,1\n")
    for name in M.SINGLE:
        p = proc / M.file_name(name)
        p.write_bytes(b"PAR1" if p.suffix == ".parquet" else b"a,b\n1,2\n")
    for name in M.REFERENCE:
        (ref / M.file_name(name)).write_text("k: v\n" if name.endswith(".yaml") else "a\n1\n")
    (raw / "ecb_fx" / "eur_gbp_daily.csv").write_text("date,eur_gbp\n")
    (raw / "lccc" / "cfd_actual_generation.csv").write_text("a\n")
    (raw / "coal_monthly.csv").write_text("month,coal_gbp_per_mwh_thermal\n2023-01,19.0\n")
    (raw / "repd_q1_2026.csv").write_text("a\n")
    (raw / "gis" / "gsp_regions_2024.geojson").write_text("{}")
    (proc / "mid_target_2023.csv").write_text("startTime,mid_source\n2023-01-01T00:00Z,N2EX\n")
    (proc / "dayahead_price_n2ex_2023.csv").write_text("startTime,p\n")
    monkeypatch.setattr(M.cfg, "raw_dir", lambda: raw)
    monkeypatch.setattr(M.cfg, "processed_dir", lambda: proc)
    monkeypatch.setattr(M.cfg, "reference_dir", lambda: ref)
    return tmp_path


def test_export_writes_every_table_and_a_manifest_that_checks(tree, tmp_path):
    out = tmp_path / "inputs"
    man = M.export(out, years=(2023, 2023))
    names = {t["name"] for t in man["tables"]}
    assert "demand_2023.csv" in names and "fx_eur_gbp_daily.csv" in names and "gis/gsp_regions.geojson" in names
    assert "pecd/gsp_cf_era5.parquet" in names and "thermal_parameters.csv" in names and "repd.csv" in names
    assert "coal_monthly.csv" in names
    assert (out / "demand_2023.csv").exists() and (out / "gis" / "gsp_regions.geojson").exists()
    assert json.loads((out / M.MANIFEST).read_text())["kind"] == M.KIND
    assert man["years"] == [2023, 2023] and man["licensed"] is False
    assert M.check(out)["ok"]
    (out / "demand_2023.csv").write_text("tampered")
    (out / "agents_2023.csv").unlink()
    c = M.check(out)
    assert not c["ok"] and "demand_2023.csv" in c["changed"] and "agents_2023.csv" in c["missing"]


def test_licensed_tables_are_left_out_unless_asked(tree, tmp_path):
    man = M.export(tmp_path / "a", years=(2023, 2023))
    assert not any(t["name"].startswith("dayahead_price") for t in man["tables"])
    assert "dayahead_price_n2ex_2023.csv" in man["left_out_licensed"]
    man = M.export(tmp_path / "b", years=(2023, 2023), licensed=True)
    assert any(t["name"] == "dayahead_price_n2ex_2023.csv" and t["licensed"] for t in man["tables"])
    assert man["licensed"] is True and not man["left_out_licensed"]


def test_mid_target_with_n2ex_rows_is_licensed(tree, tmp_path):
    man = M.export(tmp_path / "a", years=(2023, 2023))
    assert not any(t["name"] == "mid_target_2023.csv" for t in man["tables"])
    assert "mid_target_2023.csv" in man["left_out_licensed"]
    (tree / "processed" / "mid_target_2023.csv").write_text("startTime,mid_source\n2023-01-01T00:00Z,APX\n")
    man = M.export(tmp_path / "b", years=(2023, 2023))
    assert any(t["name"] == "mid_target_2023.csv" and not t["licensed"] for t in man["tables"])


def test_missing_table_aborts_before_writing(tree, tmp_path):
    (tree / "processed" / "agents_2023.csv").unlink()
    with pytest.raises(SystemExit, match="agents_2023.csv"):
        M.export(tmp_path / "inputs", years=(2023, 2023))
    assert not (tmp_path / "inputs").exists()


def test_export_refuses_existing_folder_without_overwrite(tree, tmp_path):
    M.export(tmp_path / "inputs", years=(2023, 2023))
    with pytest.raises(SystemExit, match="overwrite"):
        M.export(tmp_path / "inputs", years=(2023, 2023))
    M.export(tmp_path / "inputs", years=(2023, 2023), overwrite=True)
    assert M.check(tmp_path / "inputs")["ok"]


def test_every_table_has_sources_or_is_marked_unregistered():
    for name in (*M.SINGLE, *(f"{t}_2023" for t in M.YEARLY)):
        assert M.table_sources(M.file_name(name))
