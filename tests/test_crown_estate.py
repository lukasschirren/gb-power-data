"""The Crown Estate's offshore wind ownership tables (gbpowerdata.pull.crown_estate_pull, gbpowerdata.build.
build_crown_estate) on synthetic data: the page parses in both of its layouts, with the shares split (on ";", and on
a line break only before a percentage), a holder without a share kept and mojibake repaired, but only where the
repair gives a character a Western page holds; a row that cannot be read whole, a holder that starts with a digit (a
decimal comma) and shares that do not add up to 100 stop the parse; the as-at date comes from the page's text, not
its scripts or head, and must agree; a pull never overwrites a snapshot, and a page that cannot be pulled does not
stop the others; the comparison with company_owners.csv passes where the two agree and flags a wrong share, a
missing group, another operator and a farm without rows on the date, but not a vehicle named on one side only; a
known difference explains only the difference it names, and one that matches nothing is reported; a farm not
compared is checked against the holdings NOT_COMPARED expects; --strict fails on an unexplained difference, a farm
NOT MAPPED, an unused known difference and a farm not compared whose holdings changed; the report tables are read
as text with their sections and shares normalised, and a blank farm, operator or holder or an unknown section is
refused; the farm map, KNOWN_DIFFERENCES and NOT_COMPARED are well formed, and the map points at rows that exist in
the real company_owners.csv."""
import re

import numpy as np
import pandas as pd
import pytest
import requests

from gbpowerdata import config as cfg
from gbpowerdata.build import build_crown_estate as B
from gbpowerdata.common import companies as co
from gbpowerdata.pull import crown_estate_pull as ce

T = pd.Timestamp
REAL_REFERENCE = cfg.reference_dir()
NBSP = chr(0xA0)
# the dates of The Crown Estate's tables: the reports for the ends of 2018-2020 and the web tables for the ends of
# 2023 and 2024 (extend it when a table is added)
TABLE_DATES = {"2018-12-31", "2019-12-31", "2020-12-31", "2023-12-31", "2024-12-31"}


def mangled(text: str) -> str:
    """UTF-8 read as Windows-1252, as in a copy of a page saved with the wrong encoding."""
    return text.encode("utf-8").decode("cp1252")


MOJIBAKE_O = mangled("Ø")

# the end-2024 layout: an empty header row, the column names in the first body row
PAGE_2024 = f"""<html><body><h3>UK operational and under construction wind farm ownership as at 31 December 2024</h3>
<table><tbody>
<tr><th><p></p></th><th><p></p></th><th><p></p></th></tr>
<tr><td><p><strong>Fully operational projects</strong></p></td><td><p><strong>Operator</strong></p></td>
    <td><p><strong>Share ownership %</strong></p></td></tr>
<tr><td><p>Gunfleet&nbsp;Sands I</p></td><td><p>&Oslash;rsted</p></td>
    <td><p>50.1% &Oslash;rsted; 24.95% Dev Bank of Japan; 24.95% JERA</p></td></tr>
<tr><td><p>Moray East*</p></td><td><p>{MOJIBAKE_O}rsted</p></td>
    <td><p>40% Ocean Winds; 33.4% Diamond Green Ltd; Equitix</p></td></tr>
<tr><td><p>Lincs</p></td><td><p>&Oslash;rsted</p></td>
    <td><p>60% {MOJIBAKE_O}rsted<br/>40% GIG Renewable Energy Fund</p></td></tr>
</tbody></table>
<table><tbody>
<tr><th><p></p></th><th><p></p></th><th><p></p></th></tr>
<tr><td><p><strong>Under construction projects*</strong></p></td><td><p><strong>Lead developer</strong></p></td>
    <td><p><strong>Share ownership %</strong></p></td></tr>
<tr><td><p>Dogger Bank A</p></td><td><p>SSE Renewables</p></td>
    <td><p>40% SSE; 40% Equinor; 20% V&aring;rgr&oslash;nn</p></td></tr>
</tbody></table>
<p>* Offshore wind farms that are under construction but not yet fully operational</p></body></html>"""

# the end-2023 layout: the column names in the header row
FOO_ROW = "<tr><td><p>Foo Bank</p></td><td><p>Foo</p></td><td><p>10% Foo Fund; 5% Foo Fund; 85% Bar</p></td></tr>"
PAGE_2023 = f"""<html><body><h3>UK operational and under construction wind farm ownership as at 31 December 2023</h3>
<table><tr><th><p><strong>Fully operational projects</strong></p></th><th><p><strong>Operator</strong></p></th>
<th><p><strong>Share ownership %</strong></p></th></tr>
<tr><td><p>Gunfleet Sands I</p></td><td><p>Ørsted</p></td>
    <td><p>50.1% Ørsted; 24.95% Dev Bank of Japan; 24.95% JERA</p></td></tr>
{FOO_ROW}
</table></body></html>"""


# ---------------------------------------------------------------------------- parsing
def _holders(t, farm):
    rows = t[t["farm"] == farm]
    return list(zip(rows["holder"], rows["share_pct"]))


def test_the_page_parses_in_either_layout_with_shares_split_and_text_repaired():
    t = ce.parse(PAGE_2024)
    assert t.columns.tolist() == ce.COLUMNS
    assert set(t["as_at"]) == {T("2024-12-31")}
    assert t.groupby("section")["farm"].unique().map(sorted).to_dict() == {
        "operational": ["Gunfleet Sands I", "Lincs", "Moray East"], "under_construction": ["Dogger Bank A"]}
    assert _holders(t, "Gunfleet Sands I") == [("Ørsted", 50.1), ("Dev Bank of Japan", 24.95), ("JERA", 24.95)]
    assert _holders(t, "Dogger Bank A") == [("SSE", 40.0), ("Equinor", 40.0), ("Vårgrønn", 20.0)]
    assert _holders(t, "Lincs") == [("Ørsted", 60.0), ("GIG Renewable Energy Fund", 40.0)]   # one per line
    moray = t[t["farm"] == "Moray East"]                                                       # star dropped
    assert set(moray["operator"]) == {"Ørsted"}                                                 # mojibake repaired
    equitix = moray[moray["holder"] == "Equitix"]["share_pct"]
    assert len(equitix) == 1 and np.isnan(equitix.iloc[0])                                     # no share, kept
    assert set(t.loc[t["farm"] == "Dogger Bank A", "operator"]) == {"SSE Renewables"}
    old = ce.parse(PAGE_2023)
    assert set(old["as_at"]) == {T("2023-12-31")} and set(old["section"]) == {"operational"}
    assert _holders(old, "Gunfleet Sands I") == _holders(t, "Gunfleet Sands I")


def test_text_is_cleaned_and_shares_split_on_semicolons():
    assert ce.clean(f"{MOJIBAKE_O}rsted") == "Ørsted"
    assert ce.clean(mangled("Vårgrønn")) == "Vårgrønn"
    assert ce.clean(mangled("Stadtwerke München")) == "Stadtwerke München"
    assert ce.clean("Crédit Agricole Assurances") == "Crédit Agricole Assurances"          # already right: untouched
    assert ce.clean(f" Moray{NBSP}West* ") == "Moray West"
    assert ce.split_shares("40% SSE; 25% SDIC Power Holdings; 17.5% Equitix; 17.5% TRIG (The Renewables Infrastructure "
                           "Group)") == [("SSE", 40.0), ("SDIC Power Holdings", 25.0), ("Equitix", 17.5),
                                         ("TRIG (The Renewables Infrastructure Group)", 17.5)]
    holder, share = ce.split_shares("Pilot Offshore Renewables")[0]
    assert holder == "Pilot Offshore Renewables" and np.isnan(share)
    with pytest.raises(ValueError):
        ce.split_shares("50% Foo 50% Bar")          # two shares in one holder: the format changed, say so
    with pytest.raises(ValueError):
        ce.split_shares("60% SSE; 40%")             # a share without a holder


def test_a_line_break_separates_holders_only_before_a_percentage():
    assert ce.split_shares("40% SSE\n25% SDIC Power\nHoldings; 35% Equitix") == [
        ("SSE", 40.0), ("SDIC Power Holdings", 25.0), ("Equitix", 35.0)]           # a name carried on is joined
    assert ce.split_shares("60% Ørsted\n\n 40% GIG Renewable\n   Energy Fund") == [
        ("Ørsted", 60.0), ("GIG Renewable Energy Fund", 40.0)]
    page = PAGE_2023.replace("<td><p>10% Foo Fund; 5% Foo Fund; 85% Bar</p></td>",
                             "<td><p>15% Foo<br/>Fund</p><p>85% Bar</p></td>")    # <br> in a name, <p> per holder
    assert _holders(ce.parse(page), "Foo Bank") == [("Foo Fund", 15.0), ("Bar", 85.0)]


def test_mojibake_repair_takes_the_continuation_characters_its_lead_character_says():
    assert ce.clean(mangled("Ø") + NBSP + "Wind") == "Ø Wind"        # a correct no-break space is not swallowed
    assert ce.clean(mangled("é") + "©") == "é©"                        # two bytes, then a correct character
    assert ce.clean(mangled("’") + "©") == "’©"                        # three bytes (E2 80 99)
    assert ce.clean(mangled("Gwynt y Môr’s") + "°") == "Gwynt y Môr’s°"
    four = chr(0x20000)                                                  # four bytes (F0 A0 80 80)
    assert ce.clean(mangled(four) + "°") == four + "°"
    assert ce.clean("à€€") == "à€€"                                     # not UTF-8 (an overlong form): left alone


def test_mojibake_is_repaired_only_into_a_character_a_western_page_holds():
    for real in ("œ", "ș", "–", "€", "™"):          # Latin Extended-A and -B, punctuation, currency, letterlike
        assert ce.clean(mangled(real)) == real, real
    # genuine text that only looks like mojibake: its bytes would decode to a character no Western page holds
    # ("É”" would be U+0254, "É’" U+0252, "É–" U+0256, "É»" U+027B, "ß“" U+07D3, "é’”" U+9494); "à…”" is no UTF-8
    for genuine in ("CAFÉ”", "ROSÉ’S", "CAFÉ–BAR", "«ÉTÉ»", "„Fuß“", "café’”", "voilà…”"):
        assert ce.clean(genuine) == genuine, genuine
    assert mangled("CAFɔ") == "CAFÉ”"               # the same characters: read as the genuine text they also are
    assert ce.clean(mangled("物")) == mangled("物")  # three bytes of a character no Western page holds: left alone


def test_a_page_without_an_as_at_date_or_tables_is_refused():
    with pytest.raises(ValueError):
        ce.parse("<html><table><tr><td>Fully operational projects</td></tr></table></html>")
    with pytest.raises(ValueError):
        ce.parse("<html><h3>ownership as at 31 December 2024</h3><p>no table</p></html>")
    assert ce.as_at_of(f"UK ... wind farm ownership as{NBSP}at 31 December 2024") == T("2024-12-31")


def test_the_as_at_date_comes_from_the_page_text_and_must_agree():
    page = ("<html><head><title>Wind farm ownership as at 30 June 2025</title></head><body>"
            "<h3>UK operational and under construction wind farm ownership as at 31 December 2024</h3>"
            '<script>{"value":"UK operational and under construction wind farm ownership as at 31 December 2023"}'
            "</script><p>Wind farm ownership as at 31 December 2024: the tables below.</p></body></html>")
    assert ce.as_at_of(page) == T("2024-12-31")                     # the head's title and the script do not count
    disagreeing = page.replace("<p>Wind farm ownership as at 31 December 2024", "<p>Ownership as at 31 December 2023")
    with pytest.raises(ValueError, match="several as-at dates"):
        ce.as_at_of(disagreeing)
    # a head closed only by the first tag it cannot hold, as a browser reads it
    assert ce.as_at_of("<head><title>ownership as at 30 June 2025</title><h3>ownership as at 31 December 2024</h3>"
                       ) == T("2024-12-31")
    # an element a head can hold (<noscript>) is skipped with the head, though it is no script, style or title
    assert ce.as_at_of("<head><noscript>ownership as at 30 June 2025</noscript></head><body><h3>ownership as at 31 "
                       "December 2024</h3></body>") == T("2024-12-31")
    assert ce.as_at_of("<h3>Offshore wind farms as at 31 December 2025</h3>") == T("2025-12-31")   # no "ownership"
    with pytest.raises(ValueError):
        ce.as_at_of("<p>as at 31 December 2024</p><p>as at 31 December 2025</p>")


def test_a_row_that_cannot_be_read_whole_stops_the_parse():
    rowspan = PAGE_2023.replace(FOO_ROW, '<tr><td rowspan="2"><p>Foo Bank</p></td><td><p>Foo</p></td>'
                                         "<td><p>15% Foo Fund</p></td></tr>"
                                         "<tr><td><p>Foo</p></td><td><p>85% Bar</p></td></tr>")
    with pytest.raises(ValueError, match="2 cells under a header of 3"):
        ce.parse(rowspan)
    empty_share = PAGE_2023.replace(FOO_ROW, "<tr><td><p>Foo Bank</p></td><td><p>Foo</p></td><td><p></p></td></tr>")
    with pytest.raises(ValueError, match="no holder in the share cell of 'Foo Bank'"):
        ce.parse(empty_share)
    no_farm = PAGE_2023.replace(FOO_ROW, "<tr><td></td><td><p>Foo</p></td><td><p>100% Foo Fund</p></td></tr>")
    with pytest.raises(ValueError, match="without a farm name"):
        ce.parse(no_farm)
    blank = PAGE_2023.replace(FOO_ROW, FOO_ROW + "<tr><td></td><td> </td><td><p></p></td></tr>")
    assert ce.parse(blank).equals(ce.parse(PAGE_2023))                       # an empty row is only skipped


def test_a_holder_that_starts_with_a_digit_or_shares_that_do_not_add_up_stop_the_parse():
    def page(cell):
        return PAGE_2023.replace(FOO_ROW, f"<tr><td><p>Foo Bank</p></td><td><p>Foo</p></td><td><p>{cell}</p></td></tr>")

    # a decimal comma: "24,95% X" would read as 95% of "24, X"; caught where the share is split
    with pytest.raises(ValueError, match="a share with a decimal comma, '24,95% X'"):
        ce.parse(page("75.05% Foo Fund; 24,95% X"))
    with pytest.raises(ValueError, match="decimal comma"):
        ce.parse(page("75,05% Foo Fund; 24,95% Bar"))          # 5 + 95 = 100: the sum would not show it
    # a holder that starts with a digit stops the parse too (the price: a "3i" would have to be allowed by hand)
    with pytest.raises(ValueError, match="a holder that starts with a digit, '3i Group', in the share cell of 'Foo Bank'"):
        ce.parse(page("60% Foo Fund; 40% 3i Group"))
    with pytest.raises(ValueError, match="the shares of 'Foo Bank' add up to 90: has the layout changed"):
        ce.parse(page("60% Foo Fund; 30% Bar"))
    with pytest.raises(ValueError, match="add up to 100.6"):
        ce.parse(page("50.3% Foo Fund; 50.3% Bar"))
    for cell in ("50.25% Foo Fund; 50.25% Bar", "60% Foo Fund; Bar"):    # within SHARE_SUM_PP; a share not given
        assert set(ce.parse(page(cell))["farm"]) == {"Gunfleet Sands I", "Foo Bank"}
    # a decimal comma after the name: "Ørsted 75,05%" leaves "75," before the share
    with pytest.raises(ValueError, match="a share with a decimal comma"):
        ce.parse(page("Foo Fund 75,05%; Bar 24,95%"))
    # one farm in two rows of a section: its shares add up to 200, not two farms of 100
    twice = PAGE_2023.replace(FOO_ROW, "<tr><td><p>Foo Bank</p></td><td><p>Foo</p></td><td><p>60% Foo; 40% Bar</p></td>"
                                       "</tr><tr><td><p>Foo Bank</p></td><td><p>Foo</p></td><td><p>60% Foo; 40% Bar</p>"
                                       "</td></tr>")
    with pytest.raises(ValueError, match="the shares of 'Foo Bank' add up to 200"):
        ce.parse(twice)


# ---------------------------------------------------------------------------- pulling
def test_a_pull_names_the_snapshot_by_its_as_at_date_and_never_overwrites_it(tmp_path, monkeypatch, capsys):
    pages = {"live": PAGE_2024.encode("utf-8")}
    monkeypatch.setattr(cfg, "raw_dir", lambda: tmp_path)
    monkeypatch.setattr(ce, "download", lambda url: PAGE_2023.encode("utf-8") if "web.archive.org" in url
                        else pages["live"])
    path = ce.pull()[0]
    assert path == tmp_path / "crown_estate" / "wind_farm_ownership_20241231.html"
    assert path.read_bytes() == PAGE_2024.encode("utf-8")
    pages["live"] = PAGE_2024.replace("50.1% &Oslash;rsted", "50.2% &Oslash;rsted").encode("utf-8")
    ce.pull()
    assert path.read_bytes() == PAGE_2024.encode("utf-8")                 # immutable, with a warning
    assert "differs" in capsys.readouterr().out
    paths = ce.pull(archived=True)
    assert [p.name for p in paths] == ["wind_farm_ownership_20241231.html", "wind_farm_ownership_20231231.html",
                                       "wind_farm_ownership_20231231.html"]
    t = ce.table()
    assert set(t["source"]) == {"wind_farm_ownership_20231231.html", "wind_farm_ownership_20241231.html"}
    foo = t[t["farm"] == "Foo Bank"].set_index("holder")["share_pct"].to_dict()
    assert foo == {"Foo Fund": 15.0, "Bar": 85.0}                         # one row per holder, shares summed
    assert not t.duplicated(["as_at", "farm", "holder"]).any()


def test_a_page_that_cannot_be_pulled_does_not_stop_the_others(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cfg, "raw_dir", lambda: tmp_path)
    monkeypatch.setattr(ce, "ARCHIVED", {"20240621132923": "end-2023", "20260408080732": "end-2024"})
    down, error_page = ce.archived_url("20240621132923"), ce.archived_url("20260408080732")

    def download(url):
        if url == down:
            raise requests.ConnectionError("retries exhausted")
        if url == error_page:              # served, but no table: the archive's own error page
            return b"<html><body><h1>Hrm.</h1><p>This page is not available on the web.</p></body></html>"
        return PAGE_2024.encode("utf-8")

    monkeypatch.setattr(ce, "download", download)
    failed = []
    paths = ce.pull(archived=True, failed=failed)
    assert [p.name for p in paths] == ["wind_farm_ownership_20241231.html"] and failed == [down, error_page]
    out = capsys.readouterr().out
    assert f"WARNING: {down} not pulled (ConnectionError" in out
    assert f"WARNING: {error_page} not pulled (ValueError" in out
    assert not (tmp_path / "crown_estate" / "wind_farm_ownership_20231231.html").exists()
    assert ce.main(["--archived"]) == 1 and ce.main([]) == 0
    monkeypatch.setattr(ce, "download", lambda url: b"<html><body>Service unavailable</body></html>")
    with pytest.raises(ValueError):
        ce.pull()                       # nothing obtained: the error is raised, as for the live page alone
    assert ce.main([]) == 1


def test_archived_captures_are_fetched_raw():
    assert all(re.fullmatch(r"\d{14}", s) for s in ce.ARCHIVED)
    assert ce.archived_url("20240621132923") == f"https://web.archive.org/web/20240621132923id_/{ce.PAGE}"


# ---------------------------------------------------------------------------- comparing
@pytest.fixture
def owners(tmp_path, monkeypatch):
    """A synthetic company_owners.csv (and an empty company_groups.csv) in place of the real ones."""
    pd.DataFrame(columns=["name", "group", "same_as", "note", "source"]).to_csv(tmp_path / co.GROUPS_FILE, index=False)
    rows = [
        ("Alpha Wind Ltd", "Orsted", "50", "yes", "", ""), ("Alpha Wind Ltd", "Beta Fund", "50", "no", "", ""),
        ("Gamma Wind Ltd", "SSE", "60", "yes", "", ""), ("Gamma Wind Ltd", "Equinor", "40", "no", "", ""),
        ("Delta Wind Ltd", "SSE", "100", "yes", "", ""),
        ("Epsilon Wind Ltd", "Equinor", "100", "yes", "", ""),
        ("Zeta Wind Ltd", "Orsted", "50", "yes", "", ""), ("Zeta Wind Ltd", "Kappa", "50", "no", "", ""),
        ("Eta Wind Ltd", "Ocean Winds", "95", "yes", "", ""), ("Eta Wind Ltd", "Ignitis", "5", "no", "", ""),
        ("Theta Wind Ltd", "RWE", "50.1", "yes", "", ""), ("Theta Wind Ltd", "Greencoat UK Wind", "49.9", "no", "", ""),
        ("Iota Wind Ltd", "SSE", "100", "yes", "", "2023-06-30"),
        ("Iota Wind Ltd", "SSE", "50", "yes", "2023-07-01", ""),
        ("Iota Wind Ltd", "TRIG", "50", "no", "2023-07-01", ""),
        ("Kappa Wind Ltd", "SSE", "60", "yes", "", ""),
        # Moray East's owners as company_owners.csv names them: the three behind Diamond Green Ltd one by one
        ("Mu Wind Ltd", "Ocean Winds", "40", "yes", "", ""), ("Mu Wind Ltd", "INPEX", "16.7", "no", "", ""),
        ("Mu Wind Ltd", "Kansai Electric", "10.02", "no", "", ""),
        ("Mu Wind Ltd", "Mitsubishi HC Capital", "6.68", "no", "", ""),
        ("Mu Wind Ltd", "Equitix", "26.6", "no", "", ""),
        ("Nu Wind Ltd", "SSE", "100", "yes", "2024-01-01", ""),             # rows from 2024 only
    ]
    pd.DataFrame([{"entity": f"company:{e}", "owner": o, "share_pct": s, "operator": op, "valid_from": f,
                   "valid_to": t} for e, o, s, op, f, t in rows]).assign(
        sources="test-src", evidence="test", status="verified", checked="2026-10-06").to_csv(
        tmp_path / co.OWNERS_FILE, index=False)
    monkeypatch.setattr(cfg, "reference_dir", lambda: tmp_path)
    co.clear_caches()
    yield tmp_path
    co.clear_caches()


_NAMES = ("Alpha", "Gamma", "Delta", "Epsilon", "Zeta", "Eta", "Theta", "Iota", "Kappa", "Mu", "Nu")
FARMS = pd.DataFrame({"farm": list(_NAMES), "entity": [f"{n} Wind Ltd" for n in _NAMES], "note": ""})


def _snapshot(rows, as_at="2024-12-31"):
    """(farm, operator, share cell) -> the parsed table's rows."""
    out = [{"as_at": T(as_at), "section": "operational", "farm": f, "operator": op, "holder": h, "share_pct": s}
           for f, op, cell in rows for h, s in ce.split_shares(cell)]
    return pd.DataFrame(out).assign(source="test.html")


def test_agreement_passes_and_each_kind_of_difference_is_flagged(owners):
    snap = _snapshot([
        ("Alpha", "Ørsted", "50% Ørsted; 50% Beta Fund"),                                  # agrees
        ("Gamma", "SSE Renewables", "50% SSE; 50% Equinor"),                                # two shares off
        ("Delta", "SSE", "50% SSE; 50% Masdar"),                                            # a group missing here
        ("Epsilon", "SSE Renewables", "100% Equinor"),                                      # another operator
        ("Eta", "Moray Offshore Windfarm (West) Ltd", "47.5% EDP Renewables; 47.5% ENGIE; 5% Ignitis"),  # vehicle
        ("Theta", "RWE", "50.5% RWE; 49.5% Greencoat UK Wind"),                             # within 0.5 points
        ("Iota", "SSE", "50% SSE; 50% TRIG (The Renewables Infrastructure Group)"),          # rows by date
        ("Kappa", "SSE", "60% SSE; 40% Foo Fund"),                                          # unresolved is no group
        ("Omega", "Vattenfall", "100% Vattenfall"),                                         # not in the farm map
    ])
    d = B.compare(snap, FARMS, known={})
    got = {(r.farm, r.kind, r.group, r.company_owners, r.crown_estate) for r in d.itertuples()}
    assert got == {
        ("Gamma", "share", "SSE", "60", "50"), ("Gamma", "share", "Equinor", "40", "50"),
        ("Delta", "group", "Masdar", "", "50"), ("Delta", "share", "SSE", "100", "50"),
        ("Epsilon", "operator", "", "Equinor", "SSE"),
        ("Eta", "operator", "", "Ocean Winds", "Moray Offshore Windfarm (West)"),
        ("Kappa", "group", "Foo Fund", "", "40"),
    }
    assert not d["known"].any() and d.attrs["compared"] == 8 and d.attrs["unmapped"] == ["Omega"]
    earlier = B.compare(_snapshot([("Iota", "SSE", "100% SSE")], as_at="2022-12-31"), FARMS, known={})
    assert earlier.empty and earlier.attrs["compared"] == 1


def test_a_vehicle_the_table_names_takes_the_shares_of_the_owners_company_owners_names(owners):
    snap = _snapshot([("Mu", "Ocean Winds", "40% Ocean Winds; 33.4% Diamond Green Ltd; 26.6% Equitix")])
    d = B.compare(snap, FARMS, known={})
    assert d.empty and d.attrs["compared"] == 1        # INPEX 16.7 + Kansai 10.02 + Mitsubishi HC 6.68 = 33.4


def test_a_farm_without_rows_on_the_table_date_is_one_no_rows_difference(owners):
    snap = _snapshot([("Nu", "SSE", "60% SSE; 40% Equinor")], as_at="2023-12-31")
    d = B.compare(snap, FARMS, known={})
    assert d[["farm", "entity", "kind", "group", "company_owners", "crown_estate"]].values.tolist() == [
        ["Nu", "Nu Wind Ltd", "no_rows", "", "no rows on this date", "60% SSE; 40% Equinor"]]
    assert "no_rows" in B.KINDS and "no rows in company_owners.csv for Nu Wind Ltd on this date" in B.describe(d)
    assert B.compare(_snapshot([("Nu", "SSE", "100% SSE")]), FARMS, known={}).empty     # 2024: rows, and agreed
    known = {("2023-12-31", "Nu", "no_rows", ""): ("no rows on this date", "60% SSE; 40% Equinor", "rows from 2024")}
    assert B.compare(snap, FARMS, known=known)["known"].all()


def test_a_known_difference_is_reported_with_its_reason_not_failed(owners):
    snap = _snapshot([("Zeta", "Ørsted", "50% Ørsted; 50% Lambda"), ("Epsilon", "SSE", "100% Equinor")])
    known = {("2024-12-31", "Zeta", "group", "Kappa"): B.Known("50", "", "Lambda is Kappa's fund"),
             ("2024-12-31", "Zeta", "group", "Lambda"): B.Known("", "50", "Lambda is Kappa's fund"),
             ("2023-12-31", "Epsilon", "operator", ""): B.Known("Equinor", "SSE", "another year only")}
    d = B.compare(snap, FARMS, known=known)
    zeta = d[d["farm"] == "Zeta"]
    assert set(zeta["group"]) == {"Kappa", "Lambda"} and zeta["known"].all()
    assert set(zeta["reason"]) == {"Lambda is Kappa's fund"}
    assert not d.loc[d["farm"] == "Epsilon", "known"].any()                  # a known difference holds on its date
    any_date = B.compare(snap, FARMS, known={("", "epsilon", "operator", ""): ("Equinor", "SSE", "every date")})
    assert any_date.loc[any_date["farm"] == "Epsilon", "known"].all()        # "" = every date; names match loosely


def test_a_known_difference_explains_only_the_difference_it_names(owners):
    snap = _snapshot([("Zeta", "Ørsted", "50% Ørsted; 50% Lambda")])
    d = B.compare(snap, FARMS, known={("2024-12-31", "Zeta", "group", "Kappa"): ("50", "", "Kappa's stake")})
    assert d.set_index("group")["known"].to_dict() == {"Kappa": True, "Lambda": False}   # the unrelated one flagged
    assert d.set_index("group")["reason"].to_dict() == {"Kappa": "Kappa's stake", "Lambda": ""}
    gamma = _snapshot([("Gamma", "SSE", "50% SSE; 50% Equinor")])
    d = B.compare(gamma, FARMS, known={("", "Gamma", "share", "SSE"): ("60", "55", "the table said 55 once")})
    assert not d["known"].any()                         # same farm, kind and group, other values: not this one
    d = B.compare(gamma, FARMS, known={("", "Gamma", "share", "SSE"): ("60", "50", "every date")})
    assert d.set_index("group")["known"].to_dict() == {"SSE": True, "Equinor": False}


def test_a_known_difference_that_matches_nothing_is_reported_as_unused(owners):
    snap = _snapshot([("Gamma", "SSE", "50% SSE; 50% Equinor"), ("Alpha", "Ørsted", "50% Ørsted; 50% Beta Fund")])
    known = {("2024-12-31", "Gamma", "share", "SSE"): ("60", "50", "used"),
             ("2024-12-31", "Gamma", "share", "Equinor"): ("40", "45", "the table now says 50"),
             ("", "Alpha", "operator", ""): ("Orsted", "Beta Fund", "of no date: checked on every date"),
             ("2018-12-31", "Gamma", "group", "Masdar"): ("", "10", "of a date not compared: not reported")}
    d = B.compare(snap, FARMS, known=known)
    assert d.attrs["unused_known"] == [("2024-12-31", "Gamma", "share", "Equinor"), ("", "Alpha", "operator", "")]
    text = B.summary(snap, d)
    assert "2 known differences unused" in text
    assert "UNUSED: the KNOWN_DIFFERENCES entry (every date, Alpha, operator)" in text and "Masdar" not in text


def test_the_report_tables_join_the_web_tables_where_transcribed(owners, tmp_path, monkeypatch):
    raw = tmp_path / "raw"
    monkeypatch.setattr(cfg, "raw_dir", lambda: raw)
    (raw / "crown_estate").mkdir(parents=True)
    (raw / "crown_estate" / "wind_farm_ownership_20241231.html").write_text(PAGE_2024, encoding="utf-8")
    web = B.snapshots()
    assert set(web["source"]) == {"wind_farm_ownership_20241231.html"}       # no reports file: silently web only
    report = {"as_at": "2018-12-31", "section": "operational", "farm": "Gunfleet Sands I", "operator": "Ørsted",
              "holder": "Marubeni Corporation", "holder_printed": "Marubeni...3", "share_pct": "24.95",
              "source_id": "ce-2018", "page": "14"}
    pd.DataFrame([report]).to_csv(tmp_path / B.REPORTS_FILE, index=False)
    both = B.snapshots()
    report = both[both["source"] == "ce-2018"]
    assert len(report) == 1 and report["as_at"].iloc[0] == T("2018-12-31") and report["share_pct"].iloc[0] == 24.95
    assert report["holder"].iloc[0] == "Marubeni Corporation"                # holder; holder_printed is not read
    assert "holder_printed" not in both.columns and B.holder_group(report["holder"].iloc[0]) == "Marubeni"


def test_the_report_tables_are_read_as_text_with_sections_and_shares_normalised(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "reference_dir", lambda: tmp_path)
    row = {"as_at": "2020-12-31", "section": "Fully operational projects", "farm": "Lincs", "operator": "Ørsted",
           "holder": "Ørsted", "holder_printed": "Ørsted", "share_pct": "25", "source_id": "ce-2020", "page": "24-25"}
    rows = [{**row, "section": "Under construction projects", "farm": "Foo Bank", "holder": "NA",
             "holder_printed": "N...1", "share_pct": "24.95%"},
            {**row, "share_pct": " 44 % "},
            {**row, "holder": "None", "share_pct": ""}]
    pd.DataFrame(rows).to_csv(tmp_path / B.REPORTS_FILE, index=False)
    t = B.reports()
    assert t.columns.tolist() == ce.COLUMNS + ["source", "page"]             # holder_printed is not read
    assert t["section"].tolist() == ["under_construction", "operational", "operational"]
    assert t["share_pct"].iloc[:2].tolist() == [24.95, 44.0] and np.isnan(t["share_pct"].iloc[2])
    assert t["holder"].tolist() == ["NA", "Ørsted", "None"]                  # text, never a missing value
    assert t["page"].tolist() == ["24-25"] * 3 and t["source"].tolist() == ["ce-2020"] * 3
    pd.DataFrame([{**row, "share_pct": "24.95.5"}]).to_csv(tmp_path / B.REPORTS_FILE, index=False)
    with pytest.raises(ValueError, match="no number"):
        B.reports()
    pd.DataFrame([{k: v for k, v in row.items() if k != "holder"}]).to_csv(tmp_path / B.REPORTS_FILE, index=False)
    with pytest.raises(ValueError, match="no column holder"):
        B.reports()


def test_a_report_row_without_a_farm_operator_or_holder_or_of_no_known_section_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "reference_dir", lambda: tmp_path)
    row = {"as_at": "2020-12-31", "section": "operational", "farm": "Lincs", "operator": "Ørsted", "holder": "Ørsted",
           "holder_printed": "Ørsted", "share_pct": "100", "source_id": "ce-2020", "page": "24"}
    for column, value, message in (("farm", " ", r"rows with a blank farm \(lines 3\)"),
                                   ("operator", "", r"rows with a blank operator \(lines 3\)"),
                                   ("holder", "*", r"rows with a blank holder \(lines 3\)"),   # a footnote star only
                                   ("section", "Decommissioned projects", "neither operational nor under construction"),
                                   ("section", "", "neither operational nor under construction")):
        pd.DataFrame([row, {**row, column: value}]).to_csv(tmp_path / B.REPORTS_FILE, index=False)
        with pytest.raises(ValueError, match=message):
            B.reports()
    both = pd.DataFrame([row, {**row, "section": "Under construction projects"}])
    both.to_csv(tmp_path / B.REPORTS_FILE, index=False)
    assert B.reports()["section"].tolist() == ["operational", "under_construction"]


def test_strict_fails_only_on_an_unexplained_difference(owners, tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "processed_dir", lambda: tmp_path)
    monkeypatch.setattr(B, "KNOWN_DIFFERENCES", {})
    FARMS.to_csv(tmp_path / B.FARMS_FILE, index=False)
    snap = _snapshot([("Alpha", "Ørsted", "50% Ørsted; 50% Beta Fund")])
    monkeypatch.setattr(B, "snapshots", lambda: snap)
    assert B.main(["--strict"]) == 0
    written = pd.read_csv(tmp_path / B.OUT_FILE)
    assert written.columns.tolist() == B.OUT_COLUMNS and set(written["group"]) == {"Orsted", "Beta Fund"}
    snap2 = _snapshot([("Gamma", "SSE", "50% SSE; 50% Equinor")])
    monkeypatch.setattr(B, "snapshots", lambda: snap2)
    assert B.main(["--strict"]) == 1 and B.main([]) == 0


def test_strict_fails_on_a_farm_not_mapped_and_on_a_known_difference_unused(owners, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cfg, "processed_dir", lambda: tmp_path)
    monkeypatch.setattr(B, "KNOWN_DIFFERENCES", {})
    FARMS.to_csv(tmp_path / B.FARMS_FILE, index=False)
    snap = _snapshot([("Alpha", "Ørsted", "50% Ørsted; 50% Beta Fund"), ("Barrow", "Ørsted", "100% Ørsted")])
    monkeypatch.setattr(B, "snapshots", lambda: snap)
    assert B.main(["--strict"]) == 0                     # Barrow is left out on purpose (NOT_COMPARED)
    out = capsys.readouterr().out
    assert f"  not compared: Barrow -- {B.NOT_COMPARED['Barrow'].reason}\n" in out              # with its reason
    assert "NOT MAPPED" not in out and "NOT_COMPARED CHANGED" not in out
    with_omega = pd.concat([snap, _snapshot([("Omega", "Vattenfall", "100% Vattenfall")])], ignore_index=True)
    monkeypatch.setattr(B, "snapshots", lambda: with_omega)
    assert B.main(["--strict"]) == 1 and B.main([]) == 0
    assert "NOT MAPPED: Omega" in capsys.readouterr().out
    d = B.compare(with_omega, FARMS, known={})
    assert d.attrs["unmapped"] == ["Omega"] and d.attrs["not_compared"] == {"Barrow": B.NOT_COMPARED["Barrow"].reason}
    assert d.attrs["not_compared_changed"] == []
    monkeypatch.setattr(B, "snapshots", lambda: snap)
    monkeypatch.setattr(B, "KNOWN_DIFFERENCES", {("", "Alpha", "operator", ""): B.Known("Orsted", "Beta Fund", "gone")})
    assert B.main(["--strict"]) == 1 and B.main([]) == 0
    assert "UNUSED: the KNOWN_DIFFERENCES entry (every date, Alpha, operator)" in capsys.readouterr().out


def test_strict_fails_on_a_farm_not_compared_whose_holdings_changed(owners, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cfg, "processed_dir", lambda: tmp_path)
    monkeypatch.setattr(B, "KNOWN_DIFFERENCES", {})
    FARMS.to_csv(tmp_path / B.FARMS_FILE, index=False)
    sold = _snapshot([("Alpha", "Ørsted", "50% Ørsted; 50% Beta Fund"), ("Barrow", "Ørsted", "50% Ørsted; 50% Foo")])
    monkeypatch.setattr(B, "snapshots", lambda: sold)
    assert B.main(["--strict"]) == 1 and B.main([]) == 0           # NOT_COMPARED expects "100% Orsted" of Barrow
    out = capsys.readouterr().out
    assert "  NOT_COMPARED CHANGED: Barrow 2024-12-31 50% Orsted; 50% Foo (expected: 100% Orsted)\n" in out
    assert "1 farm-dates of NOT_COMPARED changed" in out
    d = B.compare(sold, FARMS, known={})
    assert d.empty and d.attrs["not_compared_changed"] == [
        ("Barrow", "2024-12-31", "50% Orsted; 50% Foo", "100% Orsted")]


def test_a_farm_not_compared_is_checked_against_the_holdings_its_entry_expects(owners):
    expects = {"Rhyl Flats": B.LeftOut("50.1% RWE; 24.95% Greencoat UK Wind; 24.95% Macquarie", "no rows yet"),
               "Kincardine": B.LeftOut(None, "one holder at a time")}

    def changed(farm, cell):
        d = B.compare(_snapshot([(farm, "", cell)]), FARMS, known={}, not_compared=expects)
        assert d.empty and d.attrs["compared"] == 0 and list(d.attrs["not_compared"]) == [farm]
        return [c[:3] for c in d.attrs["not_compared_changed"]]

    assert changed("Rhyl Flats", "24.95% UK GIG OWF; 50.1% Innogy; 24.95% Greencoat UK Wind Plc") == []  # any order
    assert changed("Rhyl Flats", "50% RWE; 25% Greencoat UK Wind; 25% GIG Renewable Energy Fund") == []   # tolerance
    assert changed("Rhyl Flats", "RWE; Greencoat UK Wind; GIG Renewable Energy Fund") == []    # shares not given
    assert changed("Rhyl Flats", "50.1% RWE; 49.9% Greencoat UK Wind") == [
        ("Rhyl Flats", "2024-12-31", "50.1% RWE; 49.9% Greencoat UK Wind")]                     # a group gone
    assert changed("Rhyl Flats", "50.1% RWE; 24.95% Greencoat UK Wind; 24.95% Foo Fund") != []  # another group
    assert changed("Rhyl Flats", "60.1% RWE; 14.95% Greencoat UK Wind; 24.95% Macquarie") != []  # a share sold
    assert changed("Kincardine", "100% Atkins") == [] and changed("Kincardine", "Pilot Offshore Renewables") == []
    assert changed("Kincardine", "60% Pilot Offshore Renewables; 40% Foo") == [
        ("Kincardine", "2024-12-31", "60% Pilot Offshore Renewables; 40% Foo")]                 # no longer one holder
    snap = _snapshot([("Kincardine", "", "60% Pilot Offshore Renewables; 40% Foo")])
    text = B.summary(snap, B.compare(snap, FARMS, known={}, not_compared=expects))
    assert ("NOT_COMPARED CHANGED: Kincardine 2024-12-31 60% Pilot Offshore Renewables; 40% Foo (expected: any one "
            "holder)") in text and "  not compared: Kincardine -- one holder at a time" in text


def test_holders_take_the_groups_company_owners_uses():
    cases = {
        "Ørsted": "Orsted", "Iberdrola (ScottishPower)": "ScottishPower", "ScottishPower Renewables": "ScottishPower",
        "Legal & General NTR Fund and Dev Bank of Japan": "NTR and DBJ", "Dev Bank of Japan": "DBJ",
        "Equitix and TRIG (The Renewables Infrastructure Group)": "Equitix and TRIG", "Equitix": "Equitix",
        "TRIG (The Renewables Infrastructure Group)": "TRIG", "GIG Renewable Energy Fund": "Macquarie",
        "MIRA (Macquarie Infrastructure and Real Assets)": "Macquarie", "UK GIG OWF": "Macquarie",
        "Greencoat London Array Limited": "Schroders Greencoat", "Greencoat UK Wind": "Greencoat UK Wind",
        "Caisse dépôt & placement Québec": "CDPQ",
        "GLIL Infrastructure and Octopus (on behalf of NEST)": "GLIL and Octopus",
        "Octopus Renewables Funds": "Octopus", "Vårgrønn": "Vargronn", "Mitsubishi UFG": "Mitsubishi HC Capital",
        "Diamond Green Ltd": "Diamond Green", "Kansai": "Kansai Electric", "Engie": "ENGIE", "EDF Renewables": "EDF",
        "Innogy": "RWE", "PGGM & Ampère Equity Fund": "PGGM and Ampere Equity Fund", "PGGM & AEF": "PGGM and Ampere "
        "Equity Fund", "Xceco": "XceCo", "Some New Fund Ltd": "Some New Fund", "": "",
    }
    assert {k: B.holder_group(k) for k in cases} == cases
    # every group a rule gives is one company_owners.csv uses, a vehicle, or the owner of a farm without rows there
    used = set(_real(co.OWNERS_FILE)["owner"]) | set(B.VEHICLES) | {"Pilot Offshore Renewables", "ORE Catapult"}
    assert {g for _, g in B.HOLDER_GROUPS} <= used, {g for _, g in B.HOLDER_GROUPS} - used
    for vehicle, members in B.VEHICLES.items():
        assert vehicle not in members and len(members) >= 2


# ---------------------------------------------------------------------------- the reference tables
def _real(name: str) -> pd.DataFrame:
    return pd.read_csv(REAL_REFERENCE / name, dtype=str, keep_default_na=False)


def test_the_farm_map_is_well_formed_and_points_at_rows_of_company_owners():
    t = _real(B.FARMS_FILE)
    assert t.columns.tolist() == ["farm", "entity", "note"]
    assert not t["farm"].duplicated().any() and not t["farm"].map(B.farm_key).duplicated().any()
    assert (t["farm"].str.strip() != "").all() and (t["entity"].str.strip() != "").all()
    entities = set(_real(co.OWNERS_FILE)["entity"])
    missing = {e for e in t["entity"] if f"company:{e}" not in entities}
    assert not missing, f"entities without rows in company_owners.csv: {missing}"


def test_known_differences_name_a_mapped_farm_a_kind_a_group_both_values_and_a_reason():
    mapped = set(_real(B.FARMS_FILE)["farm"].map(B.farm_key))
    keys = [(when, B.farm_key(farm), kind, group) for when, farm, kind, group in B.KNOWN_DIFFERENCES]
    assert len(set(keys)) == len(keys)                                       # no two entries for one difference
    for (when, farm, kind, group), entry in B.KNOWN_DIFFERENCES.items():
        assert isinstance(entry, B.Known) and entry.reason.strip(), (farm, kind, group)
        assert when == "" or when in TABLE_DATES, when                       # a date some table has, or every date
        assert B.farm_key(farm) in mapped, farm
        assert kind in B.KINDS
        if kind in ("group", "share"):
            assert group.strip(), (farm, kind)
            values = [v for v in (entry.company_owners, entry.crown_estate) if v != ""]
            assert all(re.fullmatch(r"\d+(\.\d+)?", v) for v in values), entry      # shares as _pct writes them
            assert len(values) == (2 if kind == "share" else 1), entry               # a group is on one side only
        else:
            assert group == "" and entry.company_owners and entry.crown_estate, (farm, kind)
            if kind == "no_rows":
                assert entry.company_owners == B.NO_ROWS, entry                      # as compare() reports it


def test_not_compared_names_farms_the_map_leaves_out_each_with_its_holdings_and_a_reason():
    mapped = set(_real(B.FARMS_FILE)["farm"].map(B.farm_key))
    keys = [B.farm_key(f) for f in B.NOT_COMPARED]
    assert len(set(keys)) == len(keys) and not set(keys) & mapped, set(keys) & mapped
    for farm, entry in B.NOT_COMPARED.items():
        assert isinstance(entry, B.LeftOut) and entry.reason.strip(), farm
        if entry.holdings is not None:             # as _holdings writes a table's, in groups that a rule gives
            shares = B._holdings_of(entry.holdings)
            assert B._holdings(shares) == entry.holdings, (farm, entry.holdings)
            assert all(B.holder_group(g) == g for g in shares), (farm, entry.holdings)
            assert abs(sum(shares.values()) - 100.0) <= B.TOLERANCE_PP, (farm, entry.holdings)
    assert {"Barrow", "Rhyl Flats", "Thanet"} <= set(B.NOT_COMPARED)
    assert B.NOT_COMPARED["Barrow"].holdings == "100% Orsted" and B.NOT_COMPARED["Kincardine"].holdings is None
