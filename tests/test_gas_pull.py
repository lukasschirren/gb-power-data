"""The SAP puller's editions on synthetic workbooks: each dated edition appends the days after the series' last,
shared days must agree, and the raw series is never replaced by a shorter one (gbpowerdata.pull.gas_pull, EDITIONS).
No data/ and no network needed."""
import pandas as pd
import pytest

from gbpowerdata import config as cfg
from gbpowerdata.pull import gas_pull as GP


def _edition(path, start: str, days: int, p_kwh=2.5, bump: dict | None = None):
    dates = pd.date_range(start, periods=days, freq="D")
    p = pd.Series(p_kwh + 0.01 * (dates - pd.Timestamp("2018-01-01")).days, index=dates)    # a price per date
    for d, v in (bump or {}).items():
        p[pd.Timestamp(d)] = v
    frame = pd.DataFrame({"Date": dates, "SAP (p/kWh)": p.to_numpy()})
    with pd.ExcelWriter(path) as w:                     # four lines above the header, as ONS's workbook has
        frame.to_excel(w, sheet_name=GP.SHEET, index=False, startrow=4)


@pytest.fixture
def raw(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "raw_dir", lambda: tmp_path)
    monkeypatch.setattr(GP, "download", lambda url, dst: pytest.fail(f"no download expected ({url})"))
    return tmp_path


def test_editions_append_their_new_days(raw):
    _edition(raw / GP.BASE, "2018-01-01", 10)
    _edition(raw / "ons_sap_gas_2026-09-24.xlsx", "2018-01-05", 11)      # shares 01-05..01-10, adds 01-11..01-15
    s = GP.series(raw)
    assert s["date"].iloc[0] == "2018-01-01" and s["date"].iloc[-1] == "2018-01-15" and s["date"].is_unique
    assert s.set_index("date").loc["2018-01-12", "gas_price_pence_per_kwh"] == pytest.approx(2.5 + 0.01 * 11)


def test_editions_that_disagree_stop(raw):
    _edition(raw / GP.BASE, "2018-01-01", 10)
    _edition(raw / "ons_sap_gas_2026-09-24.xlsx", "2018-01-05", 11, bump={"2018-01-06": 9.0})
    with pytest.raises(SystemExit, match="disagree"):
        GP.series(raw)


def test_the_series_never_shrinks(raw):
    _edition(raw / GP.BASE, "2018-01-01", 10)
    _edition(raw / "ons_sap_gas_2026-09-24.xlsx", "2018-01-05", 16)
    GP.main(["gas_pull", "--no-download"])
    assert pd.read_csv(raw / GP.OUT)["date"].iloc[-1] == "2018-01-20"
    with pytest.raises(SystemExit, match="refusing"):
        GP.main(["gas_pull", "--file", str(raw / GP.BASE)])         # the base alone ends earlier
    GP.main(["gas_pull", "--file", str(raw / GP.BASE), "--force"])
    assert pd.read_csv(raw / GP.OUT)["date"].iloc[-1] == "2018-01-10"


def test_no_download_when_every_edition_is_on_disk(raw):
    _edition(raw / GP.BASE, "2018-01-01", 10)
    for date in GP.EDITIONS:
        _edition(raw / GP.edition_file(date), "2018-01-08", 5)
    GP.main(["gas_pull"])                                       # the fixture fails any download
    assert (raw / GP.OUT).exists()
