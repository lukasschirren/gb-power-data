"""The N2EX curve features (gbpowerdata.build.parse_n2ex_curves): run without years, it parses the years that have
both curves and the panel's tables it reads (the curves start in 2016, the panel in 2018). No data/ and no licensed
data needed."""
from gbpowerdata.build import parse_n2ex_curves as N


def test_default_years_have_curves_and_the_panels_tables(tmp_path, monkeypatch):
    curves, proc = tmp_path / "curves", tmp_path / "processed"
    curves.mkdir(), proc.mkdir()
    for y in (2016, 2017, 2018, 2019):
        (curves / f"{y}-01-01.json").write_text("{}")
    for y in (2018, 2019, 2020):
        for t in ("demand", "capacity_factors", "agents"):
            (proc / f"{t}_{y}.csv").write_text("")
    (proc / "agents_2019.csv").unlink()                     # a year without one of the tables
    monkeypatch.setattr(N, "CURVES", curves)
    monkeypatch.setattr(N.cfg, "processed_dir", lambda: proc)
    built = []
    monkeypatch.setattr(N, "build", built.append)
    N.main(["parse_n2ex_curves"])
    assert built == [2018]
