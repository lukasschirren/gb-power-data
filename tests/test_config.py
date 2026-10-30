"""Path helpers of gbpowerdata.config."""

from gbpowerdata import config as cfg


def test_relative_path_outside_the_repo_is_normalised(monkeypatch):
    # A relative path may leave the repo (`../x`). The `..` must not survive into the path: it adds
    # the repo's own folder name to every file path, and on Windows that pushed a DNO charging
    # statement past the 260-character limit (FileNotFoundError).
    monkeypatch.setattr(cfg, "load_config", lambda: {"paths": {"raw": "../x/raw"}})
    p = cfg.raw_dir()
    assert ".." not in p.parts
    assert p == cfg.REPO_ROOT.parent / "x" / "raw"


def test_absolute_path_is_kept(monkeypatch, tmp_path):
    monkeypatch.setattr(cfg, "load_config", lambda: {"paths": {"raw": str(tmp_path)}})
    assert cfg.raw_dir() == tmp_path
