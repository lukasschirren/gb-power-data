"""Ownership tables (gbpowerdata.common.companies, gbpowerdata.build.build_ownership) on synthetic data: names
reduce to groups in the documented order; joint ventures resolve by date, with the shares no source gives left
blank and the uncovered part unresolved; Capacity Market agreements count in every delivery year they cover, until
the year they are terminated in, and secondary trades do not count; CfD contracts count once contracted and until
terminated or their term is over; a wind farm takes the holder of the RO stations its name
matches; the curated reference tables are well formed, every
share cites sources that exist and the reference document is up to date; the CM puller never writes the contact
columns; Ofgem's certificate counts are read with their thousands separators; a CM unit without a fuel type is
classed by its technology; DUKES records without a site code get ids of their own; a station left out of the
year's lists while it runs takes the latest list that has it; a group no rule places takes one spelling; the
records' traders are the BM-unit table's, and a proxy whose snapshot year is not built stays unchecked."""

from pathlib import Path

import pandas as pd
import pytest

from gbpowerdata import config as cfg
from gbpowerdata.build import bm_units as B
from gbpowerdata.build import build_ownership as O
from gbpowerdata.common import companies as co
from gbpowerdata.pull import cm_register_pull, dukes_pull

T = pd.Timestamp
REAL_REFERENCE = cfg.reference_dir()


@pytest.fixture
def reference(tmp_path, monkeypatch):
    pd.DataFrame([
        {"name": "RWE Npower", "group": "RWE", "same_as": "", "note": "", "source": "DUKES"},
        {"name": "Triton Knoll Offshore Wind Farm Limited", "group": "RWE", "same_as": "", "note": "", "source": "x"},
        {"name": "Foo JV (BM)", "group": "Alpha", "same_as": "Foo JV Ltd", "note": "BM name", "source": "x"},
    ]).to_csv(tmp_path / co.GROUPS_FILE, index=False)
    pd.DataFrame([
        {"entity": "station:Saltend", "owner": "Energy Capital Partners", "share_pct": "100", "operator": "no",
         "valid_from": "", "valid_to": "2022-08-31"},
        {"entity": "station:Saltend", "owner": "SSE", "share_pct": "50", "operator": "no", "valid_from": "2022-09-01", "valid_to": ""},
        {"entity": "station:Saltend", "owner": "Equinor", "share_pct": "50", "operator": "no", "valid_from": "2022-09-01", "valid_to": ""},
        {"entity": "station:Saltend", "owner": "Triton Power", "share_pct": "", "operator": "yes", "valid_from": "", "valid_to": ""},
        {"entity": "company:Foo JV Ltd", "owner": "Alpha", "share_pct": "50", "operator": "yes", "valid_from": "", "valid_to": ""},
        {"entity": "company:Foo JV Ltd", "owner": "Beta", "share_pct": "25", "operator": "no", "valid_from": "", "valid_to": ""},
        {"entity": "company:NoShares Ltd", "owner": "Gamma", "share_pct": "", "operator": "yes", "valid_from": "", "valid_to": ""},
        {"entity": "company:NoShares Ltd", "owner": "Delta", "share_pct": "", "operator": "no", "valid_from": "", "valid_to": ""},
    ]).assign(sources="test-src", evidence="test", status="verified", checked="2026-10-06").to_csv(
        tmp_path / co.OWNERS_FILE, index=False)
    pd.DataFrame([
        {"station": "Saltend", "tech_class": "gas", "dukes_pattern": "^Saltend", "bmu_ids": "T_SCCL-1;T_SCCL-2", "note": ""},
        {"station": "Sutton Bridge", "tech_class": "gas", "dukes_pattern": "^Sutton Bridge", "bmu_ids": "T_SUTB-1", "note": ""},
    ]).to_csv(tmp_path / co.STATIONS_FILE, index=False)
    monkeypatch.setattr(cfg, "reference_dir", lambda: tmp_path)
    co.clear_caches()
    yield tmp_path
    co.clear_caches()


def test_names_are_reduced_for_matching_and_cleaned_for_tables():
    assert co.norm("Seabank Power Limited") == "SEABANK POWER"
    assert co.norm(None) == "" and co.norm(float("nan")) == ""
    assert co.clean("RWE Generation UK plc") == "RWE Generation UK"
    assert co.postcode("Windmill Hill Business Park, Whitehill Way, Swindon, Wiltshire SN5 6PB") == "SN5 6PB"


def test_a_name_finds_its_group_in_the_documented_order(reference):
    assert co.group_of("RWE Npower") == ("RWE", "alias")
    assert co.group_of("Triton Knoll Offshore Wind") == ("RWE", "alias")                   # Elexon's cut name
    assert co.group_of("SSE Generation Ltd") == ("SSE", "name")
    assert co.group_of("Foo Wind Ltd", address="c/o Orsted Wind Power A/S, Nesa Alle 1") == ("Orsted", "address")
    assert co.group_of("Bar Wind Ltd", address="Inveralmond House, 200 Dunkeld Road, Perth PH1 3AQ") == ("SSE", "site")
    assert co.group_of("EP Lynemouth Power Ltd", address="Epsilon, Windmill Hill, Swindon SN5 6PB") == ("EPUKi", "name")
    assert co.group_of("Keadby Gen Ltd", {co.norm("Keadby Gen Ltd"): "SSE plc"}) == ("SSE", "cm_parent")
    assert co.group_of("Unknown Energy Limited") == ("Unknown Energy", "self")
    assert co.group_of("Foo Ltd", address="Kraftvaerksvej, Esbjerg, Denmark") == ("Foo", "self")    # not ESB
    assert co.group_of(None) == ("", "")


def test_joint_ventures_resolve_by_date_with_unknown_shares_kept_blank(reference):
    owners, operator, basis = co.resolve("Energy Capital Partners", T("2021-12-31"), station="Saltend")
    assert owners == [{"group": "Energy Capital Partners", "share": 1.0}] and operator == "Triton Power"
    owners, operator, basis = co.resolve("Energy Capital Partners", T("2023-12-31"), station="Saltend")
    assert {o["group"]: o["share"] for o in owners} == {"SSE": 0.5, "Equinor": 0.5}
    assert operator == "Triton Power" and basis == "curated"
    owners, operator, _ = co.resolve("Foo JV Ltd", T("2023-12-31"))
    assert {o["group"]: o["share"] for o in owners} == {"Alpha": 0.5, "Beta": 0.25, co.UNRESOLVED: 0.25}
    assert operator == "Alpha"
    owners, operator, _ = co.resolve("NoShares Ltd", T("2023-12-31"))
    assert [o["group"] for o in owners] == ["Gamma", "Delta"] and all(pd.isna(o["share"]) for o in owners)
    assert operator == "Gamma"
    assert co.resolve("Plain Co Ltd", T("2023-12-31")) == ([{"group": "Plain Co", "share": 1.0}], "Plain Co", "self")


def test_a_registers_other_name_for_a_venture_takes_its_rows(reference):
    owners, operator, basis = co.resolve("Foo JV (BM)", T("2023-12-31"))
    assert operator == "Alpha" and basis == "curated" and len(owners) == 3
    assert co.trader_group("Foo JV (BM)", T("2023-12-31")) == ("Alpha", "jv_operator")


def test_capacity_market_agreements_count_in_every_delivery_year_they_cover():
    units = pd.DataFrame({
        "Delivery Years for which Agreement Valid": ["2024/2025, 2025/2026, 2026/2027", "2025/2026", "2025/2026", "2023/2024"],
        "Capacity Agreement Awarded": ["Yes", "Yes", "No", "Yes"],
        "Capacity Agreement has been Terminated": ["No", "Yes", "No", "No"],
    })
    assert list(O.cm_in_force(units, 2025).index) == [0]
    assert list(O.cm_in_force(units, 2023).index) == [3]


def test_a_cm_agreement_counts_until_the_year_it_is_terminated_in_and_secondary_trades_do_not_count():
    units = pd.DataFrame({
        "Type": ["T-4", "T-4", "T-1", "ST", "T-4"],
        "Delivery Years for which Agreement Valid": ["2023/2024, 2024/2025, 2025/2026"] * 5,
        "Capacity Agreement Awarded": ["Yes"] * 5,
        "Capacity Agreement has been Terminated": ["Yes", "Yes", "No", "No", "Yes"],
        "Date of Termination of Capacity Agreement": ["15/02/2025", "01/10/2024", "", "", ""],
    })
    # terminated in February 2025: in force for 2023/24 and 2024/25, not 2025/26; terminated on 1 October 2024,
    # the day 2024/25 began: in force that year; a secondary trade never; a termination without a date: never
    assert list(O.cm_in_force(units, 2023).index) == [0, 1, 2]
    assert list(O.cm_in_force(units, 2024).index) == [0, 1, 2]
    assert list(O.cm_in_force(units, 2025).index) == [2]


def test_a_cfd_contract_stops_counting_once_its_term_is_over():
    # past dates only: as_of caps a year at today, so a future expiry cannot be tested on a fixed answer
    t = pd.DataFrame({
        "record_id": ["ended", "running"],
        "start": [T("2009-01-01"), T("2019-06-01")],
        "round_date": [T("2008-04-30"), T("2015-02-26")],
        "terminated": [pd.NaT, pd.NaT],
        "lccc_status": ["Live (Post-FIC)", "Live (Post-FIC)"],
        "expiry": [T("2024-04-01"), T("2034-06-01")],
    })
    assert set(O.cfd_in_year(t, 2023)["record_id"]) == {"ended", "running"}
    assert set(O.cfd_in_year(t, 2024)["record_id"]) == {"running"}


def test_cfd_contracts_count_once_contracted_and_until_terminated():
    t = pd.DataFrame({
        "record_id": ["live", "signed", "later", "gone", "gone_later", "undated"],
        "start": [T("2019-06-01"), pd.NaT, pd.NaT, pd.NaT, T("2020-01-01"), pd.NaT],
        "round_date": [T("2017-09-11"), T("2022-07-07"), T("2026-01-14"), T("2019-09-20"), T("2017-09-11"), T("2019-09-20")],
        "terminated": [pd.NaT, pd.NaT, pd.NaT, T("2021-05-01"), T("2024-03-01"), pd.NaT],
        "lccc_status": ["Live (Post-FIC)", "Pre-Start Date", "Pre-MDD", "Terminated", "Terminated", "Terminated"],
    })
    y2022 = O.cfd_in_year(t, 2022).set_index("record_id")["status"].to_dict()
    assert y2022 == {"live": "operating", "signed": "contracted", "gone_later": "operating"}
    assert set(O.cfd_in_year(t, 2025)["record_id"]) == {"live", "signed"}


def test_every_register_vocabulary_maps_to_one_set_of_classes():
    assert O.dukes_class("Fossil Fuel / Single cycle / Diesel/Gas Oil") == "oil"
    assert O.dukes_class("Fossil Fuel / CCGT / Natural Gas") == "gas"
    assert O.dukes_class("Wind / Offshore / Wind") == "offshore_wind"
    assert O.dukes_class("Hydro / pumped storage / Hydro / pumped storage") == "pumped_storage"
    assert O.dukes_class("Coal/oil / Conventional steam") == "coal"
    assert O.ro_class("Landfill gas") == "bioenergy" and O.ro_class("Offshore wind - floating turbines") == "offshore_wind"
    for table in (O.CFD_CLASS, O.CM_CLASS, O.BM_CLASS):
        assert set(table.values()) <= set(O.TECH_CLASSES)


def test_a_dukes_record_joins_a_station_only_within_its_class(reference):
    stations = co.dukes_bmu_map()
    assert O._station_of(pd.Series({"site": "Sutton Bridge", "tech_class": "gas"}), stations) == "Sutton Bridge"
    assert O._station_of(pd.Series({"site": "Sutton Bridge Solar Farm", "tech_class": "solar"}), stations) == ""


def test_a_farm_takes_the_holder_of_the_ro_stations_its_name_matches(tmp_path, monkeypatch):
    pd.DataFrame([
        {"station": "Sheringham Shoals Windfarm ", "elexon_bmu_id": "T_SHRSW-1", "is_offshore": True},   # trailing space
        {"station": "Clyde Central Windfarm, Clyde North Windfarm, Clyde South Windfarm", "elexon_bmu_id": "T_CLDCW-1",
         "is_offshore": False},
        {"station": "Foo Hill Wind Farm", "elexon_bmu_id": "T_FOOW-1", "is_offshore": False},
    ]).to_csv(tmp_path / "wind_farm_map.csv", index=False)
    monkeypatch.setattr(cfg, "reference_dir", lambda: tmp_path)
    monkeypatch.setattr(O, "ro_or_none", lambda: pd.DataFrame({
        "record_id": ["R1", "R2", "R3", "R4"], "tech_class": ["offshore_wind"] + ["onshore_wind"] * 3,
        "station": ["Sheringham Shoal", "Clyde Windfarm (North)", "Clyde Windfarm (South)", "Foo Wind Farm"],
        "company": ["Scira Offshore Energy Limited"] + ["Clyde Windfarm (Scotland) Limited"] * 2 + ["Foo Ltd"],
        "capacity_mw": [315.0, 192.0, 126.0, 10.0], "address": ["a", "b", "b", "c"]}))
    O.farm_ro_links.cache_clear()
    try:
        links = O.farm_ro_links().set_index("station")
    finally:
        O.farm_ro_links.cache_clear()
    assert links.loc["Sheringham Shoals Windfarm", "holder"] == "Scira Offshore Energy Limited"
    assert links.loc["Clyde Central Windfarm, Clyde North Windfarm, Clyde South Windfarm", "ro_ids"] == ["R2", "R3"]
    assert links.loc["Foo Hill Wind Farm", "holder"] == ""                   # "hill" is not in the RO station's name


def test_cm_components_link_by_elexons_or_national_grids_unit_id(monkeypatch):
    monkeypatch.setattr(O, "bm_register", lambda year: pd.DataFrame({"unit_id": ["T_SUTB-1", "E_PILLB-1"],
                                                                     "ngc_id": ["SUTB-1", "PILLB-1"]}))
    monkeypatch.setattr(O, "cm_components", lambda: pd.DataFrame({
        "Auction Name": ["a", "a", "b"], "CMU ID": ["X1", "X2", "X3"], "Component ID": ["SUTB-1", "E_PILLB-1", "SITE01"]}))
    assert O.component_units(2025)["unit_id"].tolist() == ["T_SUTB-1", "E_PILLB-1"]


def test_a_storage_unit_takes_the_agreement_in_force_else_the_latest_before_else_the_earliest():
    c = pd.DataFrame({"unit_id": ["A", "A", "A", "B"], "cmu_id": ["a18", "a20", "a27", "b27"],
                      "first_delivery_year": ["2018", "2020", "2027", "2027"],
                      "last_delivery_year": ["2018", "2034", "2027", "2041"]})
    pick = lambda y: dict(zip(*O.pick_agreement(c, y)[["unit_id", "cmu_id"]].T.values))   # noqa: E731
    assert pick(2025) == {"A": "a20", "B": "b27"}      # in force; B's only agreement starts later
    assert pick(2019) == {"A": "a18", "B": "b27"}      # none in force: the latest that started
    assert pick(2017)["A"] == "a18"                    # none started: the earliest
    assert pick(2027)["A"] == "a27"                    # two in force: the latest to start


def test_a_postcode_link_needs_one_owner_who_trades_the_unit_or_a_matching_name():
    # Zenobe's Blackhillock units carry codes for names, and Zenobe trades them; Tye Lane (traded by EDF) sits at the
    # postcode Thorpe Marsh's components give, another company's site
    assert O.postcode_accepts({"Zenobe"}, "Zenobe", "T_BLHLB-1", ["Blackhillock"]) == "Zenobe"
    assert O.postcode_accepts({"Foresight", co.UNRESOLVED}, "Tesla", "Chapel Farm BESS", ["CHAPELFARM"]) == "Foresight"
    assert O.postcode_accepts({"Thorpe Co"}, "EDF", "Tye Lane BESS", ["ThorpeMarsh"]) == ""
    assert O.postcode_accepts({"A", "B"}, "A", "Site", ["Site"]) == ""


def test_the_cm_puller_never_writes_the_contact_columns():
    csv = ("﻿CMU ID,Name of Applicant,Secondary Trading Contact_Telephone,Secondary Trading Contact_Email,Parent Company\n"
           "X1,Foo Ltd,0123,a@b.c,Foo plc\n").encode("utf-8")
    t = cm_register_pull.without_contacts(csv)
    assert t.columns.tolist() == ["CMU ID", "Name of Applicant", "Parent Company"]
    assert t.loc[0, "Name of Applicant"] == "Foo Ltd"


def test_the_dukes_edition_is_the_year_in_the_attachments_title():
    assert dukes_pull.edition_of("Power stations in the United Kingdom, May 2026 (DUKES 5.11)", "2026-07-30T09:30") == "2026"
    assert dukes_pull.edition_of("Power stations in the United Kingdom (DUKES 5.11)", "2027-07-29T09:30") == "2027"


# ---------------------------------------------------------------------------- the curated tables themselves
def _real(name: str) -> pd.DataFrame:
    return pd.read_csv(REAL_REFERENCE / name, dtype=str, keep_default_na=False)


def test_company_owners_rows_are_sourced_dated_and_add_up():
    t = _real(co.OWNERS_FILE)
    assert t.columns.tolist() == co.OWNERS_COLUMNS
    assert t["entity"].str.match(r"^(company|station):.+").all()
    stations = set(_real(co.STATIONS_FILE)["station"])
    assert set(t.loc[t["entity"].str.startswith("station:"), "entity"].str[8:]) <= stations
    assert t["operator"].isin(["yes", "no"]).all()
    assert t["status"].isin(co.STATUSES).all(), set(t["status"]) - set(co.STATUSES)
    assert (t["evidence"].str.strip() != "").all()
    pd.to_datetime(t["checked"], format="%Y-%m-%d", errors="raise")
    known = set(_real(co.SOURCES_FILE)["source_id"])
    cited = t["sources"].map(lambda s: [i.strip() for i in s.split(";") if i.strip()])
    assert cited.map(len).gt(0).all(), t[cited.map(len) == 0]
    assert set(i for ids in cited for i in ids) <= known, set(i for ids in cited for i in ids) - known
    share = pd.to_numeric(t["share_pct"].replace("", None), errors="raise")
    assert ((share > 0) & (share <= 100) | share.isna()).all()
    start = pd.to_datetime(t["valid_from"].replace("", None), errors="raise")
    end = pd.to_datetime(t["valid_to"].replace("", None), errors="raise")
    assert ((start <= end) | start.isna() | end.isna()).all()
    # on every date a row starts or ends, each key's shares add up to at most 100 and it has at most one operator
    for entity, rows in t.assign(share=share, start=start, end=end).groupby("entity"):
        dates = {T("2018-01-01"), T("2026-10-06")} | set(rows["start"].dropna()) | set(rows["end"].dropna())
        for d in dates:
            on = rows[(rows["start"].isna() | (rows["start"] <= d)) & (rows["end"].isna() | (rows["end"] >= d))]
            assert on["share"].sum() <= 100.0 + 1e-6, (entity, d)
            assert (on["operator"] == "yes").sum() <= 1, (entity, d)


def test_every_source_is_complete_unique_and_cited():
    s = _real(co.SOURCES_FILE)
    assert s.columns.tolist() == co.SOURCES_COLUMNS
    assert not s["source_id"].duplicated().any()
    assert s["url"].str.match(r"^https?://").all(), s.loc[~s["url"].str.match(r"^https?://"), "source_id"]
    assert (s[["publisher", "title", "kind"]].apply(lambda c: c.str.strip() != "")).all().all()
    pd.to_datetime(s["accessed"], format="%Y-%m-%d", errors="raise")
    assert s["published"].str.match(r"^(\d{4}(-\d{2}(-\d{2})?)?)?$").all()     # a year, a month or a day, as the source gives it
    cited = {i.strip() for f in (co.OWNERS_FILE, co.LEADS_FILE, B.LEFT_REGISTER) for ids in _real(f)["sources"]
             for i in ids.split(";") if i.strip()}
    assert set(s["source_id"]) <= cited, set(s["source_id"]) - cited


def test_the_units_that_left_the_register_are_sourced_linked_and_traded():
    t = _real(B.LEFT_REGISTER)
    assert t.columns.tolist() == B.LEFT_COLUMNS
    assert not t["unit_id"].duplicated().any() and t["unit_id"].str.match(r"^[TE]_").all()
    assert not t["ngc_id"].duplicated().any() and (t["ngc_id"].str.strip() != "").all()
    assert (pd.to_numeric(t["capacity_mw"], errors="raise") > 0).all()
    pd.to_datetime(t["closed"], format="%Y-%m-%d", errors="raise")
    pd.to_datetime(t["checked"], format="%Y-%m-%d", errors="raise")
    known = set(_real(co.SOURCES_FILE)["source_id"])
    for ids in t["sources"]:
        assert ids.strip() and {i.strip() for i in ids.split(";")} <= known, ids
    # owners through DUKES' station rows, traders from the documented lead parties
    linked = {u for s in _real(co.STATIONS_FILE)["bmu_ids"] for u in s.split(";") if u}
    assert set(t["unit_id"]) <= linked, set(t["unit_id"]) - linked
    assert set(t["unit_id"]) <= set(_real(co.LEADS_FILE)["unit_id"])


def test_documented_lead_party_changes_are_sourced_and_do_not_overlap():
    t = _real(co.LEADS_FILE)
    assert t.columns.tolist() == co.LEADS_COLUMNS
    known = set(_real(co.SOURCES_FILE)["source_id"])
    for ids in t["sources"]:
        assert ids.strip() and {i.strip() for i in ids.split(";")} <= known
    assert t["status"].isin(co.STATUSES).all()
    start = pd.to_datetime(t["valid_from"].replace("", None), errors="raise")
    end = pd.to_datetime(t["valid_to"].replace("", None), errors="raise")
    for unit, rows in t.assign(start=start, end=end).groupby("unit_id"):
        rows = rows.sort_values("start", na_position="first")
        for a, b in zip(rows.itertuples(), list(rows.itertuples())[1:]):
            assert pd.notna(a.end) and pd.notna(b.start) and a.end < b.start, unit


def test_a_documented_lead_party_holds_only_in_its_period(reference):
    pd.DataFrame([{"unit_id": "T_X-1", "lead_party": "Old Trader Ltd", "valid_from": "", "valid_to": "2020-12-31",
                   "sources": "s", "evidence": "e", "status": "verified", "checked": "2026-10-06"}]).to_csv(
        reference / co.LEADS_FILE, index=False)
    co.clear_caches()
    assert co.lead_party_at("T_X-1", T("2019-12-31")) == "Old Trader Ltd"
    assert co.lead_party_at("T_X-1", T("2021-12-31")) == ""
    assert co.lead_party_at("T_Y-1", T("2019-12-31")) == ""


def test_the_reference_document_is_up_to_date():
    doc = cfg.REPO_ROOT / co.REFERENCES_DOC
    co.clear_caches()
    assert doc.read_text(encoding="utf-8") == co.references_markdown(), (
        "docs/ownership_references.md is stale: run python -m gbpowerdata.common.companies --references")


def test_company_groups_give_each_company_one_group_and_point_same_as_at_known_rows():
    t = _real(co.GROUPS_FILE)
    assert t.columns.tolist() == ["name", "group", "same_as", "note", "source"]
    groups = t.groupby(t["name"].map(co.norm))["group"].nunique()     # spellings of one name ("Ltd"/"Limited") agree
    assert (groups == 1).all(), groups[groups > 1]
    assert (t["group"].str.strip() != "").all()
    owners = set(_real(co.OWNERS_FILE)["entity"].str.partition(":")[2].map(co.norm))
    linked = t.loc[t["same_as"].str.strip() != "", "same_as"].map(co.norm)
    assert set(linked) <= owners, set(linked) - owners


def test_the_station_map_is_well_formed():
    import re
    t = _real(co.STATIONS_FILE)
    assert t.columns.tolist() == ["station", "tech_class", "dukes_pattern", "bmu_ids", "note"]
    assert not t["station"].duplicated().any()
    assert set(t["tech_class"]) <= set(O.TECH_CLASSES)
    for p in t["dukes_pattern"]:
        re.compile(p)
    units = [u for s in t["bmu_ids"] for u in s.split(";") if u]
    assert all(re.match(r"^[TE]_", u) for u in units) and len(units) == len(set(units))


def test_todays_lead_party_stands_for_a_past_year_unless_a_dated_source_shows_a_change_of_hands(monkeypatch):
    owners = {  # year -> unit -> (owner/operator rows, operator)
        2019: {"T_SOLD-1": ([{"role": "operator", "basis": "curated", "register": "dukes"}], "EDF"),
               "T_KEPT-1": ([{"role": "operator", "basis": "alias", "register": "dukes"}], "SSE"),
               "T_SPELL-1": ([{"role": "operator", "basis": "self", "register": "cm"}], "ESSO PETROLEUM COMPANY")},
        2026: {"T_SOLD-1": ([], "EIG"), "T_KEPT-1": ([], "SSE"), "T_SPELL-1": ([], "Esso Petroleum Company Ltd")},
    }
    monkeypatch.setattr(O, "_unit_owners", lambda year: owners[year])
    monkeypatch.setattr(co, "lead_party_at", lambda unit, when: "")
    monkeypatch.setattr(co, "trader_group", lambda party, when, cm=None: (party, "alias"))

    def unit(u, party):
        return pd.Series({"unit_id": u, "party_name": party, "party_basis": "proxy", "register_date": "2026-06-05"})

    sold = O._trader(unit("T_SOLD-1", "EIG Trading"), 2019, {})
    assert (sold["group"], sold["register"]) == ("EDF", "operator_at_date")          # changed hands since
    kept = O._trader(unit("T_KEPT-1", "SSE Trading"), 2019, {})
    assert (kept["group"], kept["register"]) == ("SSE Trading", "bm_proxy")          # same operator: proxy kept
    spelt = O._trader(unit("T_SPELL-1", "Esso"), 2019, {})
    assert spelt["register"] == "bm_proxy"                                             # no dated source: kept


def test_a_joint_ventures_own_company_trading_a_unit_gives_its_owners(reference, monkeypatch):
    # Gunfleet Sands: the RO register names a group company that holds other farms too; the lead party is the venture
    monkeypatch.setattr(O, "bm_register", lambda year: pd.DataFrame([
        {"unit_id": "T_JV-1", "party_name": "Foo JV Ltd", "tech": "wind", "active": True},
        {"unit_id": "T_RWE-1", "party_name": "Bar Trading Ltd", "tech": "wind", "active": True}]))
    monkeypatch.setattr(O, "bmu_links", lambda year: {"T_JV-1": {"ro": {"company": "RWE Npower", "record_id": "R1"}},
                                                      "T_RWE-1": {"ro": {"company": "RWE Npower", "record_id": "R2"}}})
    monkeypatch.setattr(O, "cm_parents", lambda: {})
    O._unit_owners.cache_clear()
    try:
        owners = O._unit_owners(2023)
    finally:
        O._unit_owners.cache_clear()
    rows, operator = owners["T_JV-1"]
    assert {x["group"]: x["share"] for x in rows if x["role"] == "owner"} == {"Alpha": 0.5, "Beta": 0.25,
                                                                              co.UNRESOLVED: 0.25}
    assert operator == "Alpha" and {(x["register"], x["basis"]) for x in rows} == {("bm", "curated")}
    rows, operator = owners["T_RWE-1"]
    assert operator == "RWE" and rows[0]["register"] == "ro"            # a lead party without dated rows changes nothing


REGISTER = pd.DataFrame({
    "contract_id": ["AAA-1", "AAA-2", "AAA-3"], "project_name": ["Glendye", "Sanquhar II", "No Number"],
    "counterparty_name": ["GLENDYE WIND FARM LIMITED", "SANQUHAR II COMMUNITY WIND CO LTD", "SOME CO LIMITED"],
    "counterparty_registration_no": ["9171944", "SC449688", None], "counterparty_address": ["", "", ""],
    "technology_type": ["Onshore Wind"] * 3, "current_installed_capacity": [124.8, 269.4, 10.0],
    "initial_installed_capacity": [124.8, 269.4, 10.0], "allocation_round": ["Allocation Round 7"] * 3,
    "start_date": [None] * 3, "termination_date": [None] * 3})


def _register(tmp_path, monkeypatch):
    lccc = tmp_path / "lccc"
    lccc.mkdir()
    pd.DataFrame({"CFD_ID": ["AAA-1", "AAA-2", "AAA-3"], "Status": ["Contracted"] * 3}).to_csv(
        lccc / "cfd_contract_portfolio_status.csv", index=False)
    pd.DataFrame({"Auction": ["AR7"], "Publication_Date": ["2026-01-14T00:00:00"]}).to_csv(
        lccc / "cfd_auction_outcomes.csv", index=False)
    monkeypatch.setattr(cfg, "raw_dir", lambda: tmp_path)
    monkeypatch.setattr(O.pd, "read_excel", lambda *a, **k: REGISTER.copy())
    O.cfd_register.cache_clear()


def test_the_cfd_registers_company_numbers_keep_their_leading_zeros(tmp_path, monkeypatch):
    _register(tmp_path, monkeypatch)
    try:
        assert O.cfd_register()["company_number"].tolist() == ["09171944", "SC449688", ""]
    finally:
        O.cfd_register.cache_clear()


def _registers_empty(monkeypatch, cfd: bool = True) -> None:
    """Every register empty (the CfD register too unless `cfd` is False) and no spellings to read, so records()
    runs only the loops a test fills."""
    monkeypatch.setattr(O, "cm_parents", lambda: {})
    monkeypatch.setattr(O, "dukes_with_stations", lambda year: pd.DataFrame(
        columns=["site", "company", "technology", "capacity_mw", "record_id", "tech_class", "station"]))
    monkeypatch.setattr(co, "dukes_bmu_map", lambda: pd.DataFrame(columns=["bmus"]))
    monkeypatch.setattr(O, "ro_or_none", lambda: None)
    monkeypatch.setattr(O, "farm_ro_links", lambda: pd.DataFrame(columns=["holder", "bmu_ids", "ro_ids", "address"]))
    monkeypatch.setattr(O, "cm_units", lambda: pd.DataFrame(columns=O.CM_COLUMNS))
    monkeypatch.setattr(O, "component_units", lambda year: pd.DataFrame(columns=["Auction Name", "CMU ID", "unit_id"]))
    monkeypatch.setattr(O, "cm_bmu_links", lambda year: pd.DataFrame(columns=["unit_id", "applicant", "cmu_id", "parent"]))
    monkeypatch.setattr(O, "bm_register", lambda year: pd.DataFrame(
        {"active": pd.Series(dtype=bool), "party_name": [], "unit_id": [], "unit_name": [], "tech": [],
         "capacity_mw": []}))
    monkeypatch.setattr(O, "_spellings", lambda: {})
    if cfd:
        monkeypatch.setattr(O, "cfd_bmus", lambda year: {})
        monkeypatch.setattr(O, "cfd_register", lambda: pd.DataFrame(
            columns=["record_id", "lccc_status", "terminated", "start", "round_date"]))


def test_each_cfd_contract_hands_its_number_to_resolve(tmp_path, monkeypatch):
    _register(tmp_path, monkeypatch)
    seen = []

    def resolve(company, when, station="", cm_parents=None, address=None, company_number=""):
        seen.append((company, company_number))
        return [{"group": "X", "share": 1.0}], "X", "self"
    monkeypatch.setattr(co, "resolve", resolve)
    _registers_empty(monkeypatch, cfd=False)
    monkeypatch.setattr(O, "cfd_bmus", lambda year: {"AAA-1": ["T_GLDYE-1"]})
    try:
        rec = O.records(2026)
        assert ("GLENDYE WIND FARM LIMITED", "09171944") in seen and ("SOME CO LIMITED", "") in seen
        assert set(rec.loc[rec["register"] == "cfd", "company_number"]) == {"09171944", "SC449688", ""}
        assert O.bmu_links(2026)["T_GLDYE-1"]["cfd"]["company_number"] == "09171944"   # the BM-unit link too
    finally:
        O.cfd_register.cache_clear()


def test_an_empty_owners_table_reads_as_no_rows(reference):
    pd.DataFrame(columns=co.OWNERS_COLUMNS).to_csv(reference / co.OWNERS_FILE, index=False)
    co.clear_caches()
    assert co.company_owners().empty
    assert co.resolve("Plain Co Ltd", T("2023-12-31")) == ([{"group": "Plain Co", "share": 1.0}], "Plain Co", "self")


def test_ro_certificate_counts_are_read_with_their_thousands_separators(tmp_path, monkeypatch):
    (tmp_path / "ofgem").mkdir()
    pd.DataFrame({"Accreditation reference": ["R1", "R1", "R2", "R3"],
                  "Country": ["England", "England", "Scotland", "Northern Ireland"],
                  "Output period": ["Jan 2019", "Feb 2020", "Mar 2021", "Jan 2019"],
                  "Number of certificates": ["22,608", "0", "512", "1,000"]}).to_csv(
        tmp_path / "ofgem" / "RO_Certificates_01-10-2026_10-00.csv", index=False)
    monkeypatch.setattr(cfg, "raw_dir", lambda: tmp_path)
    O.ro_output_years.cache_clear()
    try:
        assert O.ro_output_years() == {"R1": frozenset({2019}), "R2": frozenset({2021})}   # not R1's zero, not NI
    finally:
        O.ro_output_years.cache_clear()


def test_a_cm_unit_without_a_fuel_type_is_classed_by_its_technology():
    assert O.cm_class("Gas", "Storage (Duration 2h)") == "gas"                     # the fuel type decides first
    assert O.cm_class("", "Combined Cycle Gas Turbine (CCGT)", "South Humber Bank", "Centrica") == "gas"
    assert O.cm_class(None, "IFA (France)", "IFA_16", "National Grid Interconnectors") == "interconnector"
    assert O.cm_class(float("nan"), "Storage", "Dinorwig Unit 1", "First Hydro Company") == "pumped_storage"
    assert O.cm_class("", "Storage (Duration 2h)", "Cleator Storage", "CLEATOR BATTERY STORAGE LIMITED") == "battery"
    assert O.cm_class("", "Coal/biomass", "Cottam Power Station CMU 1", "EDF Energy Limited") == "coal"
    assert O.cm_class("", "Coal/biomass", "Kirklees EfW", "SUEZ RECYCLING AND RECOVERY KIRKLEES LTD") == "bioenergy"
    assert O.cm_class("", "Coal/biomass", "DRAX02", "DRAX POWER LIMITED") == "bioenergy"     # Drax's biomass units
    assert O.cm_class("", "Coal/biomass", "DRAX05", "DRAX POWER LIMITED") == "coal"
    assert O.cm_class("", "OCGT and Reciprocating Engines (Fuel Type - Diesel)", "X", "Y") == "oil"
    assert O.cm_class("", "DSR", "X", "Y") == "dsr" and O.cm_class("", "Nuclear", "X", "Y") == "nuclear"


def test_dukes_records_without_a_site_code_get_ids_of_their_own(monkeypatch):
    sheet = pd.DataFrame([
        ["Company Name", "Site Name", "Type", "Installed Capacity (MW)", "Location"],
        ["SSE", "Keadby", "CCGT", 735, "Yorkshire and the Humber"],
        ["SSE", "Keadby", "Wind", 68, "Yorkshire and the Humber"],
        ["Alpha Ltd", "Sites with capacity < 20 MW", "Wind", 30, "Scotland"],
        ["Beta Ltd", "Sites with capacity < 20 MW", "Wind", 12, "Scotland"],
        ["Gamma Ltd", "Elsewhere", "Coal", 500, "Northern Ireland"]])

    def read_excel(path, sheet_name=None, header=None):
        if header is None:
            return sheet
        t = sheet.iloc[header + 1:].copy()
        t.columns = sheet.iloc[header].tolist()
        return t.reset_index(drop=True)
    monkeypatch.setattr(O, "_dukes_book", lambda: (Path("DUKES_5.11_2026.xlsx"), ("DUKES 2019",)))
    monkeypatch.setattr(O.pd, "read_excel", read_excel)
    O.dukes_stations.cache_clear()
    try:
        ids = O.dukes_stations(2018)["record_id"].tolist()
    finally:
        O.dukes_stations.cache_clear()
    assert ids == ["Keadby | CCGT", "Keadby | Wind", "Sites with capacity < 20 MW | Alpha Ltd | Wind",
                   "Sites with capacity < 20 MW | Beta Ltd | Wind"]


def test_a_station_left_out_of_the_years_lists_while_it_runs_takes_the_latest_list_that_has_it(reference, monkeypatch):
    lists = {2021: [("Calon Energy", "Sutton Bridge", 803.0)], 2022: [], 2023: [], 2024: []}

    def with_stations(year):
        if year not in lists:
            raise ValueError(year)
        return pd.DataFrame([{"company": c, "record_id": f"{s} | CCGT", "station": s, "capacity_mw": mw}
                             for c, s, mw in lists[year]], columns=["company", "record_id", "station", "capacity_mw"])
    monkeypatch.setattr(O, "dukes_with_stations", with_stations)
    running = {2022: True, 2023: True, 2024: False}
    monkeypatch.setattr(O, "bm_register", lambda year: pd.DataFrame({"unit_id": ["T_SUTB-1"], "active": [running[year]]}))
    assert O.dukes_company("Sutton Bridge", 2022) == ("Calon Energy", "Sutton Bridge | CCGT")    # the edition before
    assert O.dukes_company("Sutton Bridge", 2023) == ("Calon Energy", "Sutton Bridge | CCGT")    # ran: an older list
    assert O.dukes_company("Sutton Bridge", 2024) == ("", "")                                     # closed: none


def test_a_group_no_rule_places_takes_one_spelling(reference):
    assert O.preferred_spelling({"CLEVE HILL SOLAR PARK", "Cleve Hill Solar Park"}) == "Cleve Hill Solar Park"
    assert O.preferred_spelling({"AMP Projects FinCo", "Amp Projects Finco"}) == "AMP Projects FinCo"
    spellings = {co.norm("Cleve Hill Solar Park Ltd"): "Cleve Hill Solar Park", "RWE": "Rwe"}
    t = pd.DataFrame({"group": ["CLEVE HILL SOLAR PARK", "Cleve Hill Solar Park", "RWE", co.UNRESOLVED, None]})
    groups = O.one_spelling(t, spellings)["group"].tolist()
    assert groups[:4] == ["Cleve Hill Solar Park", "Cleve Hill Solar Park", "RWE", co.UNRESOLVED]   # a rule's name kept
    assert groups[4] is None


def test_the_records_traders_are_the_bm_unit_tables(monkeypatch):
    _registers_empty(monkeypatch)
    monkeypatch.setattr(O, "bm_register", lambda year: pd.DataFrame({
        "active": [True], "party_name": ["EIG Trading Ltd"], "unit_id": ["T_WBURB-1"], "unit_name": ["West Burton B 1"],
        "tech": ["ccgt"], "capacity_mw": [440.0], "connection": ["transmission"]}))
    monkeypatch.setattr(O, "_trader", lambda r, year, cm: {"role": "trader", "group": "EDF", "share": 1.0,
                                                            "company": "EIG Trading Ltd", "basis": "operator_at_date",
                                                            "register": "operator_at_date", "record_id": r.unit_id})
    bm = O.records(2019).query("register == 'bm'")
    assert bm[["role", "group", "basis", "company"]].values.tolist() == [["trader", "EDF", "operator_at_date",
                                                                         "EIG Trading"]]


def test_a_proxy_stays_unchecked_with_a_warning_where_its_snapshots_year_is_not_built(monkeypatch, capsys):
    def owners(year):
        if year == 2026:
            raise FileNotFoundError("bm_unit_register_2026.csv is missing")
        return {"T_X-1": ([{"role": "operator", "basis": "curated", "register": "dukes"}], "EDF")}
    monkeypatch.setattr(O, "_unit_owners", owners)
    monkeypatch.setattr(O, "_WARNED", set())
    monkeypatch.setattr(co, "lead_party_at", lambda unit, when: "")
    monkeypatch.setattr(co, "trader_group", lambda party, when, cm=None: (party, "alias"))
    r = pd.Series({"unit_id": "T_X-1", "party_name": "EIG Trading", "party_basis": "proxy", "register_date": "2026-06-05"})
    t = O._trader(r, 2019, {})
    assert (t["group"], t["register"]) == ("EIG Trading", "bm_proxy")
    assert "bm_unit_register_2026.csv is not built" in capsys.readouterr().out
