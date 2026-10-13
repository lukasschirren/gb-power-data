"""The licensed day-ahead outputs, local only (docs/AUDIT.md A3): the aggregated curves of each auction are monotone
and clear at the published price (gbpowerdata.build.dayahead_curves), and the volume-weighted N2EX/EPEX blend tracks
LCCC's IMRP, the same average LCCC computes with the exchanges' own volumes (gbpowerdata.common.lccc). Every input is
licensed data on this machine; the tests assert on aggregates and write nothing. Skipped without the files."""
import pandas as pd
import pytest

from .conftest import need

pytestmark = [pytest.mark.realdata, pytest.mark.licensed]

VENUES = ("n2ex", "epex_hourly", "epex_hh")


def _checks(processed, venue: str) -> dict[int, pd.DataFrame]:
    files = sorted(processed.glob(f"{venue}_curve_checks_20*.csv"))
    if not files:
        pytest.skip(f"no {venue}_curve_checks_*.csv (python -m gbpowerdata.build.dayahead_curves {venue})")
    return {int(f.stem[-4:]): pd.read_csv(f) for f in files}


@pytest.mark.parametrize("venue", VENUES)
def test_aggregated_curves_are_monotone(processed, venue):
    for y, d in _checks(processed, venue).items():
        if venue == "epex_hourly" and y == 2018:
            continue                       # the legacy 2018 hourly files: test_the_2018_hourly_legacy_curves
        assert d["monotone"].astype(bool).all(), (venue, y, int((~d["monotone"].astype(bool)).sum()))


@pytest.mark.xfail(strict=True, reason="AUDIT A3-4: EPEX's legacy hourly curve files of early 2018 hold a single "
                                       "demand point per hour and a supply curve that loses volume as the price rises")
def test_the_2018_hourly_legacy_curves(processed):
    d = _checks(processed, "epex_hourly").get(2018)
    if d is None:
        pytest.skip("no 2018 EPEX hourly checks")
    assert d["monotone"].astype(bool).all()


@pytest.mark.parametrize("venue", VENUES)
def test_curves_clear_at_the_published_price_since_decoupling(processed, venue):
    for y, d in _checks(processed, venue).items():
        if y < 2021:
            continue                       # coupled to the continent and to each other until the end of 2020
        checked = d[d["passed"].notna()]
        share = checked["passed"].map(lambda v: str(v) == "True").mean()
        assert share >= 0.99, (venue, y, round(share, 4))


def test_the_volume_weighted_blend_tracks_lccc_imrp(processed, raw):
    from gbpowerdata.common import lccc
    imrp = lccc.imrp(raw)
    if imrp.empty:
        pytest.skip("no data/raw/lccc/imrp_actuals.csv (python -m gbpowerdata.pull.lccc_pull imrp-actuals)")
    for y in range(2021, 2026):
        f = processed / f"dayahead_price_gb_{y}.csv"
        if not f.exists():
            continue
        c = pd.read_csv(f)
        c["startTime"] = pd.to_datetime(c["startTime"], utc=True)
        c = c[c["startTime"].dt.minute == 0].set_index("startTime")
        if "blend_basis" in c:
            c = c[c["blend_basis"] == "volume"]
        j = c.join(imrp.rename("imrp"), how="inner").dropna(subset=["imrp", "blend_gbp_per_mwh"])
        mae = (j["blend_gbp_per_mwh"] - j["imrp"]).abs().mean()
        plain = (j[["n2ex_gbp_per_mwh", "epex_hourly_gbp_per_mwh"]].mean(axis=1) - j["imrp"]).abs().mean()
        assert mae < plain / 2, (y, round(mae, 3), round(plain, 3))   # far closer than the plain mean
