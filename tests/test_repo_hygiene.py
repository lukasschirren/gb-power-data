"""Licensed market data and credentials never enter version control.

Nord Pool (N2EX) and EPEX SPOT data are commercial: the raw files AND everything derived from
them (day-ahead prices, curve features, block orders, trade panels) must stay out of git. The
same holds for API tokens and passwords, and for copies of The Crown Estate's ownership tables
(its terms: own use only). Two checks, both against git itself:

  1. .gitignore ignores representative paths of each kind, so `git add .` cannot pick them up;
  2. no file already tracked looks like one.

Skipped when git is not available or the folder is not a git repository.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

MUST_BE_IGNORED = [
    # commercial raw
    "data/raw/nordpool/curves/2023-01-01.json",
    "data/raw/nordpool/n2ex_prices_n2ex_2016_2025.csv",
    "data/raw/epex/great-britain/aggregated_curves/aggregated_curves_great-britain_2023.zip",
    "data/raw/epex/great-britain/epex_gb_dayahead_hh_prices_2020_2025.csv",
    # derived from commercial data
    "data/processed/dayahead_price_n2ex_2023.csv",
    "data/processed/dayahead_price_epex_hourly_2023.csv",
    "data/processed/dayahead_price_blend_2023.csv",
    "data/processed/dayahead_price_gb_2023.csv",
    "data/processed/n2ex_curve_features_2023.csv",
    "data/processed/epex_blocks_2023.csv",
    "data/processed/epex_trades_halfhourly_2023.csv",
    "data/processed/mid_target_2023.csv",            # carries N2EX gap-fill values
    "data/reference/n2ex_demand_shape.csv",
    "data/reference/EPEXSPOT_SFTP_file_specifications_2026-3a.pdf",
    # credentials
    "data/reference/entsoe_token.txt",
    "data/reference/renewables_ninja_token.txt",
    "data/reference/cds_api_token.txt",
    "data/reference/epex_credentials.txt",
    "data/reference/nordpool_credentials.txt",
    "data/reference/companies_house_token.txt",
    # The Crown Estate's terms: what is downloaded is for own use, digital copies are not passed on
    "data/reference/crown_estate_ownership_reports.csv",
    "data/raw/crown_estate/wind_farm_ownership_20241231.html",
    "data/processed/crown_estate_ownership.csv",
]
COMMERCIAL_MARKERS = ("nordpool", "n2ex", "epex", "dayahead_price", "mid_target")
SECRET_MARKERS = ("token", "credential", "password", ".pem", ".key")


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)


@pytest.fixture(scope="module", autouse=True)
def _require_git_repo():
    if shutil.which("git") is None or _git("rev-parse", "--is-inside-work-tree").returncode != 0:
        pytest.skip("not a git repository")


@pytest.mark.parametrize("path", MUST_BE_IGNORED)
def test_gitignore_blocks_licensed_data_and_credentials(path):
    r = _git("check-ignore", "--no-index", "-q", path)
    assert r.returncode == 0, f"{path} is NOT ignored by .gitignore"


def test_nothing_licensed_or_secret_is_tracked():
    tracked = _git("ls-files").stdout.splitlines()
    data = [p for p in tracked if p.startswith("data/")]
    bad = [p for p in data if any(m in p.lower() for m in COMMERCIAL_MARKERS)]
    bad += [p for p in tracked if any(m in Path(p).name.lower() for m in SECRET_MARKERS)]
    assert not bad, f"tracked files that must not be in git: {bad}"
