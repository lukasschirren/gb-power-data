"""Data packs (gbpowerdata.datapack) on a synthetic data tree: export -> unpack restores the files
byte for byte; licensed data and an N2EX-filled mid_target are refused; a damaged archive, an
unsafe member path and an overwrite of a differing file are all refused."""
import json
import zipfile
from pathlib import Path

import pandas as pd
import pytest

from gbpowerdata import config as cfg
from gbpowerdata import datapack as dp


def _tree(root: Path, monkeypatch) -> Path:
    """A data/ tree with raw, processed and reference folders, and the config pointed at it."""
    for d in ("raw", "processed", "reference"):
        (root / d).mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(cfg, "raw_dir", lambda: root / "raw")
    monkeypatch.setattr(cfg, "processed_dir", lambda: root / "processed")
    monkeypatch.setattr(cfg, "reference_dir", lambda: root / "reference")
    return root


def _mid(path: Path, sources: list[str]) -> None:
    pd.DataFrame({"startTime": range(len(sources)), "price_gbp_per_mwh": 50.0,
                  "mid_source": sources}).to_csv(path, index=False)


@pytest.fixture
def src(tmp_path, monkeypatch) -> Path:
    root = _tree(tmp_path / "src", monkeypatch)
    p = root / "processed"
    (p / "demand_2023.csv").write_text("startTime,national_demand_mw\n2023-01-01 00:00:00+00:00,25000.5\n")
    (p / "demand_2017.csv").write_text("startTime,national_demand_mw\n")
    (p / "pecd").mkdir()
    (p / "pecd" / "cf_historical.csv").write_text("time,UKC1\n2023-01-01T00:00:00Z,0.3\n")
    _mid(p / "mid_target_2023.csv", ["APXMIDP", "interpolated", "missing"])
    (p / "dayahead_price_n2ex_2023.csv").write_text("licensed\n")      # never in the pack list
    (p / "scratch_notes.csv").write_text("not a pipeline table\n")
    return root


def test_export_then_unpack_restores_the_files_byte_for_byte(src, tmp_path, monkeypatch):
    archive = dp.export("processed", tmp_path / "dist", years=(2018, 2025))
    with zipfile.ZipFile(archive) as z:
        names = set(z.namelist())
        man = json.loads(z.read(dp.MANIFEST))
    assert names == {dp.MANIFEST, "processed/demand_2023.csv", "processed/mid_target_2023.csv",
                     "processed/pecd/cf_historical.csv"}                 # no 2017, licensed or stray file
    assert man["n_files"] == 3 and dp.verify(archive)["pack"] == "processed"

    dst = _tree(tmp_path / "dst", monkeypatch)
    assert dp.unpack(archive) == (3, 0)
    for e in man["files"]:
        assert (dst / e["path"]).read_bytes() == (src / e["path"]).read_bytes()
    assert dp.unpack(archive) == (0, 3)                                   # idempotent


def test_every_packable_file_has_sources_and_the_flags_follow_them(src, tmp_path):
    names = ([f"processed/{f}_2023.csv" for f in dp.PROCESSED_YEARLY]
             + [f"processed/{s}" for s in dp.PROCESSED_SINGLE]
             + ["raw/powerplants.csv", "raw/CfD_Register_2026-05-22.xlsx", "raw/repd_q1_2026.csv",
                "raw/espeni.csv", "raw/gis/gsp_regions_20220314.geojson",
                "raw/ofgem/cap_prelevelised_2026-05.xlsx", "raw/manual/dno_duos/ssen/x.xlsx",
                "raw/manual/desnz_subnational/x.xlsx"])
    for n in names:
        assert set(dp.sources_for(n)) <= set(dp.SOURCES), n
    assert "ninja" in dp.sources_for("processed/capacity_factors_by_zone_2023.csv")
    with pytest.raises(ValueError, match="FILE_SOURCES"):
        dp.sources_for("processed/something_new_2023.csv")

    man = dp.verify(dp.export("processed", tmp_path / "dist"))
    flags = {e["path"]: (e["non_commercial"], e["check_terms"]) for e in man["files"]}
    assert flags["processed/demand_2023.csv"] == (True, False)            # ESPENI: CC BY-NC
    assert flags["processed/mid_target_2023.csv"] == (False, False)       # Elexon: open
    assert set(man["sources"]) == {"espeni", "elexon", "pecd"}
    assert "© Elexon" in man["sources"]["elexon"]["attribution"]


def test_licensed_data_and_n2ex_filled_mid_target_are_refused(src, tmp_path):
    with pytest.raises(ValueError, match="licensed"):
        dp.check_shareable(src / "processed" / "dayahead_price_n2ex_2023.csv",
                           "processed/dayahead_price_n2ex_2023.csv")
    _mid(src / "processed" / "mid_target_2023.csv", ["APXMIDP", "N2EX"])
    with pytest.raises(ValueError, match="N2EX"):
        dp.export("processed", tmp_path / "dist")


def test_unpack_refuses_damage_unsafe_paths_and_silent_overwrites(src, tmp_path, monkeypatch):
    archive = dp.export("processed", tmp_path / "dist")
    with zipfile.ZipFile(archive) as z:
        man, members = json.loads(z.read(dp.MANIFEST)), {n: z.read(n) for n in z.namelist()}

    damaged = tmp_path / "damaged.zip"
    with zipfile.ZipFile(damaged, "w") as z:
        for n, data in members.items():
            z.writestr(n, data + b"x" if n == "processed/demand_2023.csv" else data)
    with pytest.raises(ValueError, match="checksum"):
        dp.verify(damaged)

    unsafe = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(unsafe, "w") as z:
        z.writestr("processed/../../evil.csv", b"x")
        z.writestr(dp.MANIFEST, json.dumps({"files": [{"path": "processed/../../evil.csv",
                                                       "bytes": 1, "sha256": dp._sha256(b"x")}]}))
    dst = _tree(tmp_path / "dst", monkeypatch)
    with pytest.raises(ValueError, match="unsafe"):
        dp.unpack(unsafe)

    (dst / "processed" / "demand_2023.csv").write_text("edited locally\n")
    with pytest.raises(FileExistsError):
        dp.unpack(archive)
    assert (dst / "processed" / "demand_2023.csv").read_text() == "edited locally\n"   # nothing written
    assert dp.unpack(archive, force=True)[0] == man["n_files"]
