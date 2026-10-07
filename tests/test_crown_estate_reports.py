"""data/reference/crown_estate_ownership_reports.csv, the hand transcription of The Crown Estate's ownership tables
for the ends of 2018, 2019 and 2020 (offshore wind operational reports ce-2018, ce-2019, ce-2020), checked where it
exists: its columns in order, UTF-8 without a byte-order mark and with LF line ends; the three dates, operational
farms only, every source cited in ownership_sources.csv; 39, 39 and 40 farms in 82, 87 and 91 rows; one operator per
farm and date, each holder once, shares adding up to 100 (Race Bank at the end of 2019 to 100.1, as printed: 6.3% for
Arjun's and Gravis's 6.25% each); farm, operator, holder and the holder as printed never blank; the holder as printed
the holder, the holder with its footnote number, or a label its footnote completes, each footnote number of a
report naming one holder; every row read by the build (gbpowerdata.build.build_crown_estate.reports); every farm
mapped or left out on purpose, and those left out holding what NOT_COMPARED expects; and the file ignored by git.

The file is LOCAL ONLY: The Crown Estate's terms (information downloaded is for the user's own use; digital copies
must not be passed to third parties) forbid publishing it, so it is not in the public repository and every test here
skips where it is absent."""
import re
import shutil
import subprocess
from pathlib import Path

import pandas as pd
import pytest

from gbpowerdata import config as cfg
from gbpowerdata.build import build_crown_estate as B
from gbpowerdata.common import companies as co

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = cfg.reference_dir()
PATH = REFERENCE / B.REPORTS_FILE
COLUMNS = ["as_at", "section", "farm", "operator", "holder", "holder_printed", "share_pct", "source_id", "page"]
FARMS = {"2018-12-31": 39, "2019-12-31": 39, "2020-12-31": 40}
ROWS = {"2018-12-31": 82, "2019-12-31": 87, "2020-12-31": 91}
NOT_100 = {("2019-12-31", "Race Bank"): 100.1}       # 50 + 25 + 12.5 + 6.3 + 6.3, the shares as the report prints them

pytestmark = pytest.mark.skipif(not PATH.exists(), reason=f"{B.REPORTS_FILE} is local only, and not here")


@pytest.fixture(scope="module")
def reports() -> pd.DataFrame:
    return pd.read_csv(PATH, dtype=str, keep_default_na=False)


def test_the_columns_encoding_and_line_ends():
    data = PATH.read_bytes()
    assert not data.startswith(b"\xef\xbb\xbf"), "a byte-order mark"
    data.decode("utf-8")                                        # raises if not UTF-8
    assert b"\r" not in data, "CR line ends"
    assert pd.read_csv(PATH, dtype=str, nrows=0).columns.tolist() == COLUMNS


def test_three_dates_operational_farms_and_cited_sources(reports):
    assert set(reports["as_at"]) == set(FARMS)
    assert set(reports["section"]) == {"operational"}
    sources = set(pd.read_csv(REFERENCE / co.SOURCES_FILE, dtype=str, keep_default_na=False)["source_id"])
    assert set(reports["source_id"]) <= sources, set(reports["source_id"]) - sources


def test_farms_and_rows_per_date(reports):
    by_date = reports.groupby("as_at")
    assert by_date["farm"].nunique().to_dict() == FARMS
    assert by_date.size().to_dict() == ROWS


def test_one_operator_per_farm_and_date_and_each_holder_once(reports):
    operators = reports.groupby(["as_at", "farm"])["operator"].nunique()
    assert (operators == 1).all(), operators[operators != 1].to_dict()
    twice = reports[reports.duplicated(["as_at", "farm", "holder"], keep=False)]
    assert twice.empty, twice[["as_at", "farm", "holder"]].values.tolist()


def test_the_shares_of_each_farm_and_date_add_up_to_100(reports):
    shares = pd.to_numeric(reports["share_pct"])                  # raises on a blank or a share that is no number
    total = shares.groupby([reports["as_at"], reports["farm"]]).sum()
    off = {k: round(v, 9) for k, v in total.items() if abs(v - NOT_100.get(k, 100.0)) > 1e-9}
    assert not off, off
    assert set(NOT_100) <= set(total.index)


def test_farm_operator_holder_and_the_holder_as_printed_are_never_blank(reports):
    for column in ("farm", "operator", "holder", "holder_printed"):
        blank = reports[reports[column].str.strip() == ""]
        assert blank.empty, (column, blank[["as_at", "farm", "holder"]].values.tolist())


def test_the_holder_as_printed_is_the_holder_or_completed_from_its_footnote(reports):
    """holder_printed is the label exactly as printed, a footnote marker as plain digits straight after it: the
    holder; the holder and its footnote number ("DBJ2"); or a label the footnote completes, a name cut short with dots
    whose start is the holder's ("Marubeni...3", "S..5") or, where the bar prints no name, the share, "%" and the
    footnote number ("10.0%10"). Within a report, each footnote number names one holder."""
    kinds, footnotes = {}, {}
    for r in reports.itertuples(index=False):
        printed, holder = r.holder_printed, r.holder
        marked = re.fullmatch(re.escape(holder) + r"(\d+)", printed)
        cut = re.fullmatch(r"(.*[^.\s])\s*\.{2,}(\d+)", printed)
        share = re.fullmatch(r"(\d+(?:\.\d+)?)%(\d+)", printed)
        if printed == holder:
            kind, footnote = "the holder", None
        elif marked:
            kind, footnote = "the holder and its footnote", marked[1]
        elif cut and holder.startswith(cut[1]) and len(cut[1]) < len(holder):
            kind, footnote = "completed from the footnote", cut[2]
        elif share and float(share[1]) == float(r.share_pct):
            kind, footnote = "completed from the footnote", share[2]
        else:
            kind, footnote = "none of these", None
        kinds.setdefault(kind, []).append((r.as_at, r.farm, holder, printed))
        if footnote is not None:
            footnotes.setdefault((r.source_id, footnote), set()).add(holder)
    assert "none of these" not in kinds, kinds["none of these"]
    assert {k: len(v) for k, v in kinds.items()} == {
        "the holder": 196, "the holder and its footnote": 33, "completed from the footnote": 31}
    several = {k: sorted(v) for k, v in footnotes.items() if len(v) > 1}
    assert not several, several


def test_the_build_reads_every_row(reports):
    t = B.reports()                     # raises on a blank farm, operator or holder, a share that is no number, ...
    assert len(t) == len(reports) and set(t["section"]) == {"operational"} and t["share_pct"].notna().all()


def test_every_farm_is_mapped_or_left_out_on_purpose(reports):
    known = set(pd.read_csv(REFERENCE / B.FARMS_FILE, dtype=str, keep_default_na=False)["farm"].map(B.farm_key))
    known |= {B.farm_key(f) for f in B.NOT_COMPARED}
    neither = sorted({f for f in reports["farm"] if B.farm_key(f) not in known})
    assert not neither, f"farms in neither {B.FARMS_FILE} nor NOT_COMPARED: {neither}"


def test_the_farms_left_out_hold_what_not_compared_expects():
    t = B.with_groups(B.reports())
    left_out = t[t["farm"].map(B.farm_key).isin({B.farm_key(f) for f in B.NOT_COMPARED})]
    assert set(left_out["as_at"].dt.strftime("%Y-%m-%d")) == set(FARMS)     # each report lists some of them
    assert B.not_compared_changed(t) == []


def test_the_file_is_ignored_by_git_and_not_tracked():
    """LOCAL ONLY: .gitignore must keep the file out of every commit (it leaves out every file of data/reference/
    that it does not name)."""
    try:
        relative = PATH.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        pytest.skip(f"{PATH} is outside the repository")
    if shutil.which("git") is None:
        pytest.skip("git is not available")

    def git(*args):
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)

    if git("rev-parse", "--is-inside-work-tree").returncode != 0:
        pytest.skip("not a git repository")
    assert git("check-ignore", "--no-index", "-q", relative).returncode == 0, f"{relative} is NOT ignored by git"
    assert git("ls-files", "--", relative).stdout.strip() == "", f"{relative} is tracked by git"
