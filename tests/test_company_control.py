"""Companies House persons with significant control (gbpowerdata.pull.companies_house_pull,
gbpowerdata.common.company_control, gbpowerdata.build.build_company_control) on synthetic API answers and temporary
folders, without the network, the real data or the real curated tables: the puller writes no individual's name,
address, birth date, nationality or residence, keeps corporate PSCs whole, and keeps any entry with a person's
details or title as a person's whatever its kind, unless its name ends in a legal form; it pages through a
company's list, with or without total_results, and writes nothing for a list it cannot read whole; it follows
UK-registered parents only (the country decides; Gibraltar, the Crown Dependencies, Ireland and the overseas
territories never count), up to N levels, and not beyond a parent whose name is not the one its PSC entries give,
judging a level only once all of it is fetched and always following a company it was asked for; it never overwrites
a snapshot, and a second run the same day judges a parent afresh without touching its file; pull dates are
YYYYMMDD; company numbers are eight characters of text with Companies House's prefixes only and ASCII digits, in the
curated list too, and are read from a registration text prefix first; the natures of control give the ownership and
voting bands; the table names no individual, dates every row by its snapshot and blanks a controller number that
leads to a company of another name; a stamped build writes its own file; the majority corporate controller on a
date follows a sale and ignores individuals and minority holders, from the table however it was read; a company's
group follows its controllers up the chain, typing the table once, from the processed table where there is one
(with a warning when the snapshots show it is out of date) and the snapshots otherwise, answers a known group only
when asked to, remembers its answers from the default table and costs nothing without either. Every person here is
invented."""
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
import requests

from gbpowerdata import config as cfg
from gbpowerdata.build import build_company_control as B
from gbpowerdata.common import companies as co
from gbpowerdata.common import company_control as C
from gbpowerdata.pull import companies_house_pull as ch

T = pd.Timestamp
REAL_REFERENCE = cfg.reference_dir()

# an individual as Companies House lists one, with every personal field it can carry (all invented)
INDIVIDUAL = {
    "kind": "individual-person-with-significant-control",
    "name": "Mr Testy Mc Testface",
    "name_elements": {"title": "Mr", "forename": "Testy", "middle_name": "Mc", "surname": "Testface"},
    "address": {"premises": "1", "address_line_1": "Example Street", "locality": "Exampleton",
                "postal_code": "ZZ1 1ZZ", "country": "England"},
    "date_of_birth": {"month": 2, "year": 1961},
    "nationality": "Ruritanian",
    "country_of_residence": "Ruritania",
    "natures_of_control": ["ownership-of-shares-75-to-100-percent", "voting-rights-75-to-100-percent"],
    "notified_on": "2016-04-06",
    "ceased_on": "2019-05-01",
    "links": {"self": "/company/09171944/persons-with-significant-control/individual/AbCdEf123"},
    "etag": "e1",
    "identity_verification_details": {"preferred_name": "Testy"},
}
PERSONAL = ("Testy", "Testface", "Example Street", "Exampleton", "ZZ1 1ZZ", "1961", "Ruritania", "AbCdEf123")
PARENT = {
    "kind": "corporate-entity-person-with-significant-control",
    "name": "Glen Holdings Limited",
    "identification": {"legal_form": "Private Company Limited By Shares", "legal_authority": "Companies Act 2006",
                       "place_registered": "Companies House", "country_registered": "England",
                       "registration_number": "12345678", "something_new": "dropped"},
    "address": {"premises": "2", "address_line_1": "Office Road", "postal_code": "ZZ2 2ZZ"},
    "natures_of_control": ["ownership-of-shares-75-to-100-percent", "voting-rights-75-to-100-percent"],
    "notified_on": "2019-05-01",
    "links": {"self": "/company/09171944/persons-with-significant-control/corporate-entity/XyZ1"},
    "etag": "e2",
}
FOREIGN = {
    "kind": "corporate-entity-person-with-significant-control",
    "name": "Vind Holding A/S",
    "identification": {"legal_form": "Aktieselskab", "legal_authority": "Danish Companies Act",
                       "place_registered": "Danish Business Authority", "country_registered": "Denmark",
                       "registration_number": "87654321"},
    "natures_of_control": ["ownership-of-shares-25-to-50-percent"],
    "notified_on": "2019-05-01",
    "links": {"self": "/company/09171944/persons-with-significant-control/corporate-entity/XyZ2"},
}
SUPER_SECURE = {"kind": "super-secure-person-with-significant-control", "ceased": False,
                "description": "super-secure-persons-with-significant-control",
                "links": {"self": "/company/09171944/persons-with-significant-control/super-secure/QwE"}}


def corporate(name, number, **extra):
    """A UK-registered corporate PSC like PARENT, with its own name and registration number."""
    return {**PARENT, "name": name, "identification": {**PARENT["identification"], "registration_number": number},
            "links": {"self": f"/psc/{number}"}, **extra}


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    """Empty raw, processed and reference folders under tmp_path, the reference one with a company_groups.csv of
    one alias (so group_of answers by alias, by name or self) and a company_owners.csv of one unrelated station
    (companies.company_owners cannot read a table without rows), so nothing reads the real data or curated tables."""
    d = SimpleNamespace(raw=tmp_path / "raw", processed=tmp_path / "processed", reference=tmp_path / "reference")
    for folder in vars(d).values():
        folder.mkdir()
    pd.DataFrame([{"name": "Alpha Energy Holdings Ltd", "group": "Alpha", "same_as": "", "note": "", "source": "x"}]
                 ).to_csv(d.reference / co.GROUPS_FILE, index=False)
    pd.DataFrame([{"entity": "station:Elsewhere", "owner": "Beta", "share_pct": "100", "operator": "yes",
                   "valid_from": "", "valid_to": "", "sources": "x", "evidence": "x", "status": "verified",
                   "checked": "2026-10-06"}], columns=co.OWNERS_COLUMNS).to_csv(d.reference / co.OWNERS_FILE,
                                                                               index=False)
    monkeypatch.setattr(cfg, "raw_dir", lambda: d.raw)
    monkeypatch.setattr(cfg, "processed_dir", lambda: d.processed)
    monkeypatch.setattr(cfg, "reference_dir", lambda: d.reference)
    co.clear_caches()
    C.clear_cache()
    yield d
    co.clear_caches()
    C.clear_cache()


# ---------------------------------------------------------------------------- personal data
def test_the_puller_keeps_corporate_pscs_whole_and_of_anyone_else_only_kind_control_and_dates():
    assert ch.filter_psc(INDIVIDUAL) == {
        "kind": "individual-person-with-significant-control",
        "natures_of_control": ["ownership-of-shares-75-to-100-percent", "voting-rights-75-to-100-percent"],
        "notified_on": "2016-04-06", "ceased_on": "2019-05-01"}
    parent = ch.filter_psc(PARENT)
    assert set(parent) == {"name", "kind", "identification", "natures_of_control", "notified_on"}
    assert parent["name"] == "Glen Holdings Limited"
    assert set(parent["identification"]) == set(ch.IDENTIFICATION_FIELDS)        # its five fields, nothing new
    assert ch.filter_psc(SUPER_SECURE) == {"kind": "super-secure-person-with-significant-control"}
    # a kind Companies House adds later is treated as a person, as is a beneficial owner of an overseas entity
    for kind in ("some-new-kind", "individual-beneficial-owner", None):
        assert set(ch.filter_psc({**INDIVIDUAL, "kind": kind})) <= set(ch.NATURAL_FIELDS)
    written = json.dumps([ch.filter_psc(i) for i in (INDIVIDUAL, PARENT, FOREIGN, SUPER_SECURE)])
    for text in PERSONAL:
        assert text not in written, text


@pytest.mark.parametrize("extra", [
    {"date_of_birth": {"month": 2, "year": 1961}}, {"name_elements": {"surname": "Testface"}},
    {"nationality": "Ruritanian"}, {"country_of_residence": "Ruritania"},
    *[{"name": f"{title} Testy Testface"}
      for title in ("Mr", "MRS", "Ms.", "Miss", "Mx", "Dr", "Prof.", "Professor", "Rev", "Revd", "Reverend", "Sir",
                    "Dame", "Lord", "Lady", "Baron", "Baroness", "Hon", "Hon.", "Honourable", "The Hon", "The Rt Hon",
                    "The Rt. Hon.", "Rt Hon", "The Right Honourable")],
])
def test_an_entry_with_a_persons_details_or_title_is_a_persons_whatever_its_kind(extra):
    entry = {**PARENT, **extra}                   # filed under a corporate kind, with a UK registration
    assert C.looks_personal(entry)
    kept = ch.filter_psc(entry)
    assert set(kept) <= set(ch.NATURAL_FIELDS)
    assert not any(text in json.dumps(kept) for text in ("Testy", "Testface", "1961", "Ruritania", "Glen"))
    assert C.uk_number(entry) == "" and ch.parents({"persons_with_significant_control": {"items": [entry]}}) == []
    # neither the unfiltered entry nor the kept one is named, numbered or counted as a controller in the table
    for item in (entry, kept):
        row = C.rows({"company_number": "09171944", "persons_with_significant_control": {"items": [item]}})[0]
        assert (row["controller_kind"], row["controller_name"], row["controller_number"]) == ("other", "", "")


def test_a_company_whose_name_begins_like_a_title_or_ends_in_a_legal_form_stays_a_company():
    for name in ("Drax Power Limited", "Ladybird Wind Ltd", "Sirius Energy Ltd", "Mission Solar Ltd",
                 "Lordship Farm Ltd", "MSC Holdings Limited", "The Lord Mayor Trust", "Honda Motor Europe",
                 "Profit Holdings", "Revolution Energy", "Baronsmead Wind",
                 # a title, then a legal form at the end, which no person's name has
                 "Sir Galahad Holdings Limited", "Lord Energy Ltd.", "Dr. Foster Energy plc", "Baron Wind P.L.C.",
                 "Lady Grey LLP", "Lord Partners LP", "Mr Testy Company", "Hon Energy Corporation", "Mrs Testy Inc",
                 "The Honourable Artillery Company"):
        entry = {**PARENT, "name": name}
        assert not C.looks_personal(entry), name
        assert ch.filter_psc(entry)["name"] == name and C.uk_number(entry) == "12345678"
    for form in C.LEGAL_FORMS:
        assert not C.looks_personal({"name": f"Lord Testy {form}"}), form
    # what the title test still catches: no legal form, a foreign one, or words after it (kept nameless)
    for name in ("Lord Holdings", "Dr Foster Energy", "Baron Holding GmbH", "Lord Holdings Limited (in liquidation)"):
        assert C.looks_personal({"name": name}), name
    # a person's details make an entry a person's, whatever its name ends in
    assert C.looks_personal({**PARENT, "name": "Sir Testy Testface Limited", "date_of_birth": {"year": 1961}})
    # so does a sole trader's trading name, legal form or not
    for name in ("Mr Testy t/a Testface Energy Limited", "Mrs Testy T / A Wind Ltd", "Dr Testy trading as Foo Company"):
        assert C.looks_personal({**PARENT, "name": name}), name


def test_the_profile_keeps_its_five_fields_only():
    profile = {"company_number": "09171944", "company_name": "GLENDYE WIND FARM LIMITED", "company_status": "active",
               "date_of_creation": "2014-08-12", "previous_company_names": [{"name": "OLD NAME LIMITED",
               "effective_from": "2014-08-12", "ceased_on": "2015-01-01"}],
               "registered_office_address": {"postal_code": "ZZ3 3ZZ"}, "sic_codes": ["35110"], "type": "ltd"}
    assert set(ch.filter_profile(profile)) == set(ch.PROFILE_FIELDS)


# ---------------------------------------------------------------------------- numbers and registrations
def _digits(script_zero: int, digits: str) -> str:
    """`digits` written in another script's digits (0x0660 Arabic-Indic, 0xFF10 full-width), kept ASCII here."""
    return "".join(chr(script_zero + int(d)) for d in digits)


def test_company_numbers_are_eight_characters_of_text():
    assert C.company_number("9171944") == "09171944"           # as a spreadsheet keeps it
    assert C.company_number(9171944) == "09171944"
    assert C.company_number("9171944.0") == "09171944"
    assert C.company_number(" sc449688 ") == "SC449688"
    assert C.company_number("SC 12345") == "SC012345"
    assert C.company_number("OC428012") == "OC428012"
    assert C.company_number("R0000123") == "R0000123"          # Northern Ireland, before partition: prefix R0
    # a separator between the prefix and the digits is dropped
    for written in ("SC-123456", "SC 123456", "SC.123456", "sc - 123456", " SC.123456 "):
        assert C.company_number(written) == "SC123456", written
    assert C.company_number("sc-12345") == "SC012345" and C.company_number("R-0000123") == "R0000123"
    for written in ("SC/123456", "SC:123456", "SC#123456", "SC: 123456"):      # any of the separators filings use
        assert C.company_number(written) == "SC123456", written
    assert C.company_number("R0-000123") == "R0000123" and C.company_number("R0/000123") == "R0000123"
    # Companies House's prefixes, those added since its 2012 guide included; a society keeps its FCA letters
    for number in ("NI012345", "SO301234", "NC000123", "LP012345", "SL012345", "FC012345", "ZC000123", "SE000123",
                   "GE000123", "NO123456", "BR012345", "OE001234", "SG000123", "CE001234", "CS000123", "IP00525R",
                   "SP0218RS"):
        assert C.company_number(number) == number, number
    assert C.company_number("ip525r") == "IP00525R" and C.company_number("SP218RS") == "SP0218RS"
    assert {"SC", "NI", "R0", "OC", "SO", "NC", "IP", "SP", "NP", "OE", "BR"} <= set(C.PREFIXES)
    assert all(len(p) == 2 for p in C.PREFIXES) and set(C.SOCIETIES) <= set(C.PREFIXES)
    for blank in ("", None, float("nan"), "N/A", "123456789",
                  "XY123456", "XY-123456", "ABCDEFGH", "12AB34CD",     # an unknown prefix or form, eight characters
                  "SC12345R", "IP12345RS", "525R", "R123", "12-345678",
                  "0", "00000000", "SC000000", "R0000000", "IP00000R",   # zeros only
                  _digits(0x0660, "09171944"), _digits(0xFF10, "09171944")):   # digits of other scripts
        assert C.company_number(blank) == "", blank
    assert ch.company_number is C.company_number               # one normaliser, everywhere


def test_a_registration_number_in_text_is_read_prefix_first_and_a_lone_run_only_without_a_prefix_joined_to_it():
    def corp(number):
        return {"kind": "corporate-entity-person-with-significant-control",
                "identification": {"country_registered": "England", "registration_number": number}}
    read = {"Company number SC-123456 (Scotland)": "SC123456", "Co. No. SC 449688": "SC449688",
            "SC - 123456": "SC123456", "Registered society IP00525R": "IP00525R",
            "Company number 07598482 (England And Wales)": "07598482", "Company No 09171944": "09171944",
            "No. 9171944": "09171944", "No.09171944": "09171944", "Number: 09171944": "09171944",
            "E&W 09171944": "09171944", "UK 09171944": "09171944", "Co 9171944": "09171944",
            # "No" and "Nr" with a separator are the word number; joined to the digits, the prefix
            "No 123456": "00123456", "Nr. 1234567": "01234567", "NO123456": "NO123456",
            "09171944 / SC123456": "SC123456",                       # the prefixed form first, wherever it stands
            # a known prefix joined by ":", "/" or "#" is its number, not the digits alone (an England and Wales one)
            "SC: 123456": "SC123456", "SC/123456": "SC123456", "SC#123456": "SC123456", "OC: 123456": "OC123456",
            # England and Wales, and Companies House, before the digits are words, not prefixes
            "E & W 09171944": "09171944", "EW 09171944": "09171944", "CH 09171944": "09171944"}
    for text, number in read.items():
        assert C.uk_number(corp(text)) == number, text
    # digits right after a prefix that is unknown, mistyped or given the wrong number of digits: no number
    for text in ("XY-123456", "Ref AB 123456", "SC-1234567", "(SC-1234567)", "B 123456", "00000000", "123 456 789",
                 "XY: 123456", "XY/123456", "XY#123456", "SC: 1234567", _digits(0x0660, "09171944")):
        assert C.uk_number(corp(text)) == "", text


def test_only_uk_registered_corporate_pscs_are_followed():
    assert C.uk_number(PARENT) == "12345678"
    assert C.uk_number(FOREIGN) == ""                           # a Danish CVR number has eight digits too
    assert C.uk_number(INDIVIDUAL) == ""

    def corp(**ident):
        return {"kind": "corporate-entity-person-with-significant-control", "identification": ident}
    assert C.uk_number(corp(country_registered="Uk", registration_number="9171944")) == "09171944"
    assert C.uk_number(corp(place_registered="Registrar Of Companies For Scotland",
                            registration_number="SC 449688")) == "SC449688"
    assert C.uk_number(corp(country_registered="England And Wales",
                            registration_number="Company number 07598482")) == "07598482"
    assert C.uk_number(corp(country_registered="New South Wales, Australia", registration_number="12345678")) == ""
    assert C.uk_number(corp(country_registered="Ireland", registration_number="123456")) == ""
    assert C.uk_number({"kind": "legal-person-person-with-significant-control",
                        "identification": {"country_registered": "England",
                                           "legal_authority": "Local Government Act"}}) == ""


def test_the_country_decides_and_a_foreign_country_beside_a_uk_sounding_place_is_foreign():
    def corp(country="", place=""):
        return {"kind": "corporate-entity-person-with-significant-control",
                "identification": {"country_registered": country, "place_registered": place,
                                   "registration_number": "9171944"}}
    uk = [("England", "Companies House"), ("United Kingdom", ""), ("", "Companies House"),
          ("", "Registrar of Companies for England and Wales"), ("Northern Ireland", ""),
          ("N. Ireland", "Companies House"), ("United Kingdom (Northern Ireland)", ""),
          # the common spellings of the UK, now that the exclusions below come first
          ("U.K.", ""), ("UK", ""), ("England, UK", ""), ("Great Britain", ""), ("Britain", ""), ("GB", ""),
          ("", "Companies House (U.K.)"),
          # white space and hyphens collapsed before the tests
          ("United  Kingdom", ""), ("England,\tUK", ""), ("Northern-Ireland", ""), ("", "Companies\nHouse")]
    for country, place in uk:
        assert C.uk_number(corp(country, place)) == "09171944", (country, place)
    foreign = [
        ("Luxembourg", "Companies House"),                       # the country decides; the place only when it is blank
        ("Delaware, United States", "Registrar of Companies for England and Wales"),
        ("", "Companies House Gibraltar"), ("Gibraltar", ""),    # Gibraltar's registry is called Companies House too
        ("Jersey", "Companies House"), ("Guernsey", ""), ("Isle Of Man", ""), ("Channel Islands", ""),
        ("United Kingdom", "Isle of Man Companies Registry"),   # in either field
        ("IOM", ""), ("I.O.M.", ""), ("Isle  of\tMan", ""), ("Isle-of-Man", ""), ("UK", "Manx companies registry"),
        ("England", "Ireland"), ("Ireland", ""), ("Republic of Ireland", "Companies Registration Office"),
        ("Eire", ""), (chr(0xC9) + "ire", ""), ("Irish Republic", ""), ("", "CRO"),
        ("United Kingdom", "Companies Registration Office"),
        # the overseas territories with registries of their own, "UK" beside them or not
        ("Cayman Islands", ""), ("Grand Cayman (UK)", ""), ("Bermuda", "Registrar of Companies"), ("BVI", ""),
        ("Virgin Islands, British", ""), ("British Virgin Islands", "United Kingdom"), ("United Kingdom", "Anguilla"),
        ("Montserrat", ""), ("Turks & Caicos Islands", ""), ("Turks and Caicos", ""), ("Falkland Islands", ""),
        ("Falklands", ""), ("St Helena", ""), ("St. Helena", ""), ("Saint Helena, Ascension and Tristan da Cunha", ""),
        ("Ascension Island", ""), ("Tristan da Cunha", ""), ("Pitcairn Islands", ""),
        # New England, New South Wales, New Britain and New Scotland, however they are spaced
        ("New England, USA", ""), ("New  England", ""), ("New-England", ""), ("New\nSouth Wales", ""),
        ("New Britain", ""), ("New Britain, Papua New Guinea", ""), ("New Scotland, New York", ""),
        ("New Jersey", ""), ("Ukraine", ""), ("British Virgin Islands", ""), ("GB Holdings, Delaware", ""), ("", "")]
    for country, place in foreign:
        assert C.uk_number(corp(country, place)) == "", (country, place)


def test_pull_dates_are_yyyymmdd(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cfg, "raw_dir", lambda: tmp_path / "raw")
    assert C.valid_stamp("20261006") == "20261006" and C.valid_stamp(20261006) == "20261006"
    assert B.stamp_arg("20261006") == "20261006"
    for bad in ("2026-10-06", "2026106", "202610066", "20261399", "20260230", "", "today", None, "20261006\n",
                _digits(0x0660, "20261006"), _digits(0xFF10, "20261006")):
        with pytest.raises(ValueError):
            C.valid_stamp(bad)
        if bad is not None:                                     # None is "every pull date"
            with pytest.raises(ValueError):
                C.snapshot_files(bad)
    assert C.snapshot_files(None) == {}
    with pytest.raises(SystemExit) as e:                        # the build's --stamp
        B.main(["--stamp", "2026-10-06"])
    assert e.value.code == 2 and "YYYYMMDD" in capsys.readouterr().err
    with pytest.raises(ValueError):                             # the puller would write a folder nothing reads
        ch.pull(["09171944"], stamp="2026-10-06", api=FakeApi({}, {}))
    assert not (tmp_path / "raw").exists()


# ---------------------------------------------------------------------------- the puller
class FakeApi:
    """Companies House as two dicts (number -> profile, number -> PSC list; missing = HTTP 404). The PSC list is
    served one entry per page, so the puller must page through it. `totals` overrides a list's total_results (a list
    that claims more than it serves); a number in `repeat` is served by a server that ignores start_index, one in
    `no_total` by one whose pages give no total_results."""

    def __init__(self, profiles: dict, pscs: dict, totals: dict | None = None, repeat=(), no_total=()):
        self.profiles, self.pscs, self.totals, self.repeat, self.paths = profiles, pscs, totals or {}, set(repeat), []
        self.no_total = set(no_total)

    @property
    def calls(self) -> int:
        return len(self.paths)

    def get(self, path, params=None):
        self.paths.append(path)
        number = path.split("/")[2]
        if not path.endswith("/persons-with-significant-control"):
            return self.profiles.get(number)
        items = self.pscs.get(number)
        if items is None:
            return None
        start = 0 if number in self.repeat else int(params["start_index"])
        page = {"items": items[start:start + 1], "items_per_page": 1, "start_index": start,
                "total_results": self.totals.get(number, len(items)),
                "active_count": sum("ceased_on" not in i for i in items),
                "ceased_count": sum("ceased_on" in i for i in items), "links": {"self": f"/company/{number}/psc"}}
        if number in self.no_total:
            del page["total_results"]
        return page


def _profile(number, name, previous=()):
    return {"company_number": number, "company_name": name, "company_status": "active",
            "date_of_creation": "2014-08-12",
            "previous_company_names": [{"name": p, "effective_from": "2014-08-12", "ceased_on": "2018-01-01"}
                                       for p in previous],
            "registered_office_address": {"address_line_1": "Example Street", "postal_code": "ZZ1 1ZZ"}}


def test_the_pull_pages_through_the_list_follows_uk_parents_and_never_overwrites(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "raw_dir", lambda: tmp_path / "raw")
    sse = corporate("SSE Renewables Holdings Limited", "SC123456")
    api = FakeApi({"09171944": _profile("09171944", "GLENDYE WIND FARM LIMITED"),
                   "12345678": _profile("12345678", "GLEN HOLDINGS LIMITED")},
                  {"09171944": [INDIVIDUAL, PARENT, FOREIGN, SUPER_SECURE], "12345678": [sse]})
    written = ch.pull(["9171944", "not a number"], follow=1, stamp="20261006", api=api)
    assert set(written) == {"09171944", "12345678"}                 # the UK parent, one level up; not the Danish one
    assert not any("87654321" in p or "SC123456" in p for p in api.paths)   # follow=1 stops at the parent
    record = json.loads((tmp_path / "raw" / "companies_house" / "20261006" / "09171944.json").read_text("utf-8"))
    psc = record["persons_with_significant_control"]
    assert psc["found"] and psc["total_results"] == 4 and len(psc["items"]) == 4 and psc["ceased_count"] == 1
    assert set(record) == set(ch.PROFILE_FIELDS) | {"persons_with_significant_control"}
    text = "".join(p.read_text("utf-8") for p in (tmp_path / "raw").rglob("*.json"))
    for personal in PERSONAL:
        assert personal not in text, personal
    assert ch.parents(record) == ["12345678"]
    assert ch.parent_links(record) == [("12345678", "Glen Holdings Limited")]
    parent = json.loads(Path(written["12345678"]).read_text("utf-8"))
    assert "not_followed" not in parent                              # its name is the one the entry gives
    # a second run the same day reads the snapshots back and asks Companies House nothing
    before = {p: p.read_bytes() for p in (tmp_path / "raw").rglob("*.json")}
    again = FakeApi({}, {})
    assert ch.pull(["09171944"], follow=1, stamp="20261006", api=again) == written
    assert again.calls == 0 and before == {p: p.read_bytes() for p in (tmp_path / "raw").rglob("*.json")}
    # a number Companies House does not know writes nothing; a company without a PSC list is kept as such
    ch.pull(["00000404", "00000405"], stamp="20261007",
            api=FakeApi({"00000405": _profile("00000405", "NO PSC LIMITED")}, {}))
    folder = tmp_path / "raw" / "companies_house" / "20261007"
    assert sorted(p.name for p in folder.iterdir()) == ["00000405.json"]
    empty = json.loads((folder / "00000405.json").read_text("utf-8"))["persons_with_significant_control"]
    assert empty == {"found": False, "total_results": None, "active_count": None, "ceased_count": None, "items": []}


def test_the_pull_log_counts_corporate_entries_kept_as_a_persons(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cfg, "raw_dir", lambda: tmp_path / "raw")
    miskinded = {**PARENT, "date_of_birth": {"month": 2, "year": 1961}, "links": {"self": "/psc/miskinded"}}
    ch.pull(["09171944"], stamp="20261006", api=FakeApi(
        {"09171944": _profile("09171944", "GLENDYE WIND FARM LIMITED")}, {"09171944": [PARENT, miskinded]}))
    assert "2 PSC entries (0 ceased, 1 corporate, 1 corporate kept as a person's)" in capsys.readouterr().out
    text = (tmp_path / "raw" / "companies_house" / "20261006" / "09171944.json").read_text("utf-8")
    assert "1961" not in text and text.count("Glen Holdings Limited") == 1


def test_follow_2_climbs_two_levels_and_no_further(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cfg, "raw_dir", lambda: tmp_path / "raw")
    monkeypatch.setenv(ch.KEY_ENV, "test-key")
    api = FakeApi({"09171944": _profile("09171944", "GLENDYE WIND FARM LIMITED"),
                   "12345678": _profile("12345678", "GLEN HOLDINGS LIMITED"),
                   "SC123456": _profile("SC123456", "SSE RENEWABLES HOLDINGS LIMITED"),
                   "11111111": _profile("11111111", "TOP CO LIMITED")},
                  {"09171944": [INDIVIDUAL, PARENT],
                   "12345678": [corporate("SSE Renewables Holdings Limited", "SC123456")],
                   "SC123456": [corporate("Top Co Limited", "11111111")], "11111111": []})
    monkeypatch.setattr(ch, "Api", lambda key: api)
    assert ch.main(["--numbers", "9171944", "--follow", "2"]) == 0      # the command line, as documented
    (folder,) = (tmp_path / "raw" / "companies_house").iterdir()        # today's pull date
    assert C.valid_stamp(folder.name) == folder.name
    assert sorted(p.stem for p in folder.glob("*.json")) == ["09171944", "12345678", "SC123456"]
    assert not any("11111111" in p for p in api.paths)                  # three levels up: never asked
    out = capsys.readouterr().out
    assert "level 1: 1 UK-registered" in out and "level 2: 1 UK-registered" in out and "level 3" not in out


def test_a_parent_whose_name_is_not_the_one_its_psc_entry_gives_is_written_but_not_climbed(tmp_path, monkeypatch,
                                                                                         capsys):
    monkeypatch.setattr(cfg, "raw_dir", lambda: tmp_path / "raw")
    pscs = {"09171944": [PARENT], "08904850": [corporate("Unrelated Trading Ltd", "12345678")],
            "12345678": [corporate("SSE Renewables Holdings Limited", "SC123456")], "SC123456": []}

    def api(parent_profile):
        return FakeApi({"09171944": _profile("09171944", "GLENDYE WIND FARM LIMITED"),
                        "08904850": _profile("08904850", "CLEVE HILL SOLAR PARK LIMITED"),
                        "12345678": parent_profile,
                        "SC123456": _profile("SC123456", "SSE RENEWABLES HOLDINGS LIMITED")}, pscs)
    # Glendye's entry names "Glen Holdings Limited", but Companies House gives 12345678 another name, today and before
    stranger = _profile("12345678", "UNRELATED TRADING LIMITED", previous=["OTHER OLD NAME LIMITED"])
    fake = api(stranger)
    written = ch.pull(["09171944"], follow=2, stamp="20261006", api=fake)
    assert set(written) == {"09171944", "12345678"}                     # written, so it can be looked at
    assert not any("SC123456" in p for p in fake.paths)                 # but its own PSCs are not followed
    why = json.loads(Path(written["12345678"]).read_text("utf-8"))["not_followed"]
    assert why["psc_of"] == ["09171944"] and why["psc_names"] == ["Glen Holdings Limited"] and why["reason"]
    assert "not followed further: ['12345678']" in capsys.readouterr().out
    # a previous name is the company's name too: renamed after its child filed, it is followed
    renamed = _profile("12345678", "NEW NAME LIMITED", previous=["GLEN HOLDINGS LIMITED"])
    written = ch.pull(["09171944"], follow=2, stamp="20261007", api=api(renamed))
    assert set(written) == {"09171944", "12345678", "SC123456"}
    assert "not_followed" not in json.loads(Path(written["12345678"]).read_text("utf-8"))
    # reached from two companies, one of which names it rightly: followed
    written = ch.pull(["09171944", "08904850"], follow=2, stamp="20261008", api=api(stranger))
    assert set(written) == {"09171944", "08904850", "12345678", "SC123456"}


GLEN = {"09171944": _profile("09171944", "GLENDYE WIND FARM LIMITED"),
        "12345678": _profile("12345678", "GLEN HOLDINGS LIMITED"),
        "22222222": _profile("22222222", "MID HOLDINGS LIMITED"),
        "08904850": _profile("08904850", "CLEVE HILL SOLAR PARK LIMITED"),
        "SC123456": _profile("SC123456", "SSE RENEWABLES HOLDINGS LIMITED")}


def test_a_level_is_judged_whole_so_a_parent_its_own_level_names_rightly_is_followed(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cfg, "raw_dir", lambda: tmp_path / "raw")
    # two paths to 12345678 in one level: Glendye's own entry gives it a wrong name and comes first; Glendye's other
    # parent, 22222222, of the same level, names it rightly
    pscs = {"09171944": [corporate("Wrong Name Limited", "12345678"), corporate("Mid Holdings Limited", "22222222")],
            "22222222": [corporate("Glen Holdings Limited", "12345678")],
            "12345678": [corporate("SSE Renewables Holdings Limited", "SC123456")], "SC123456": []}
    fake = FakeApi(GLEN, pscs)
    written = ch.pull(["09171944"], follow=2, stamp="20261006", api=fake)
    assert set(written) == {"09171944", "12345678", "22222222", "SC123456"}     # its own PSCs followed
    assert "not_followed" not in json.loads(Path(written["12345678"]).read_text("utf-8"))
    assert "not followed further" not in capsys.readouterr().out
    # a company asked for is followed whatever another company's entry calls it
    pscs = {"09171944": [corporate("Wrong Name Limited", "12345678")],
            "12345678": [corporate("SSE Renewables Holdings Limited", "SC123456")], "SC123456": []}
    written = ch.pull(["09171944", "12345678"], follow=1, stamp="20261007", api=FakeApi(GLEN, pscs))
    assert set(written) == {"09171944", "12345678", "SC123456"}
    assert "not_followed" not in json.loads(Path(written["12345678"]).read_text("utf-8"))


def test_a_second_pull_the_same_day_judges_a_parent_afresh_and_leaves_its_file_as_it_was(tmp_path, monkeypatch,
                                                                                         capsys):
    monkeypatch.setattr(cfg, "raw_dir", lambda: tmp_path / "raw")
    folder = tmp_path / "raw" / "companies_house" / "20261006"
    pscs = {"08904850": [corporate("Unrelated Trading Ltd", "12345678")],
            "09171944": [PARENT], "12345678": [corporate("SSE Renewables Holdings Limited", "SC123456")],
            "SC123456": []}
    # first pull of the day: 12345678 asked for on its own, so written without not_followed
    ch.pull(["12345678"], stamp="20261006", api=FakeApi(GLEN, pscs))
    parent = folder / "12345678.json"
    before = parent.read_bytes()
    assert "not_followed" not in json.loads(before)
    capsys.readouterr()
    # second pull the same day: Cleve Hill's entry gives 12345678 another name. The snapshot on disk is read back,
    # named in the warning, its own PSCs not asked for, and its file left byte for byte
    fake = FakeApi(GLEN, pscs)
    written = ch.pull(["08904850"], follow=2, stamp="20261006", api=fake)
    assert set(written) == {"08904850", "12345678"}
    assert not any("12345678" in p or "SC123456" in p for p in fake.paths)
    assert parent.read_bytes() == before and not (folder / "SC123456.json").exists()
    assert "not followed further: ['12345678']" in capsys.readouterr().out
    # the other way round: written with not_followed by a run that reached it through the wrong name only, the
    # parent is followed by a later run the same day that reaches it rightly, and its file keeps that first view
    ch.pull(["08904850"], follow=2, stamp="20261007", api=FakeApi(GLEN, pscs))
    parent = tmp_path / "raw" / "companies_house" / "20261007" / "12345678.json"
    before = parent.read_bytes()
    assert json.loads(before)["not_followed"]["psc_of"] == ["08904850"]
    capsys.readouterr()
    written = ch.pull(["09171944"], follow=2, stamp="20261007", api=FakeApi(GLEN, pscs))
    assert set(written) == {"09171944", "12345678", "SC123456"} and parent.read_bytes() == before
    assert "not followed further" not in capsys.readouterr().out


def test_a_psc_list_that_ends_early_writes_nothing_for_that_company(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cfg, "raw_dir", lambda: tmp_path / "raw")
    pscs = {"00000777": [PARENT, FOREIGN], "00000778": [PARENT, FOREIGN], "09171944": [PARENT]}
    profiles = {n: _profile(n, f"COMPANY {n} LIMITED") for n in pscs}
    # one list claims three entries and serves two; another's server ignores start_index (the first page twice)
    api = FakeApi(profiles, pscs, totals={"00000777": 3}, repeat={"00000778"})
    for number in ("00000777", "00000778"):
        with pytest.raises(ch.IncompleteList):
            ch.psc_list(api, number)
    written = ch.pull(["00000777", "00000778", "09171944"], stamp="20261006", api=api)
    assert set(written) == {"09171944"}                                  # the run goes on with the others
    folder = tmp_path / "raw" / "companies_house" / "20261006"
    assert sorted(p.name for p in folder.iterdir()) == ["09171944.json"]
    out = capsys.readouterr().out
    assert "ended before their total_results" in out and "['00000777', '00000778']" in out
    # no snapshot was written that day, so a second run retries them
    assert set(ch.pull(["00000777"], stamp="20261006", api=FakeApi(profiles, pscs))) == {"00000777"}
    assert (folder / "00000777.json").exists()


def test_a_psc_list_without_total_results_is_read_until_a_page_brings_nothing_new(tmp_path, monkeypatch, capsys):
    pscs = {"00000779": [PARENT, FOREIGN, SUPER_SECURE]}
    api = FakeApi({}, pscs, no_total={"00000779"})
    listed = ch.psc_list(api, "00000779")
    assert listed["found"] and len(listed["items"]) == 3 and listed["total_results"] is None
    assert len(api.paths) == 4                          # one entry a page, then a page that brings nothing new
    api = FakeApi({}, pscs)                             # with total_results, the page that completes it is the last
    assert len(ch.psc_list(api, "00000779")["items"]) == 3 and len(api.paths) == 3
    # pages that still bring new entries when MAX_PAGES runs out: not known to be whole, so nothing is written
    monkeypatch.setattr(ch, "MAX_PAGES", 2)
    with pytest.raises(ch.IncompleteList):
        ch.psc_list(FakeApi({}, pscs, no_total={"00000779"}), "00000779")
    monkeypatch.setattr(cfg, "raw_dir", lambda: tmp_path / "raw")
    assert ch.pull(["00000779"], stamp="20261006", api=FakeApi(
        {"00000779": _profile("00000779", "COMPANY 00000779 LIMITED")}, pscs, no_total={"00000779"})) == {}
    assert not (tmp_path / "raw" / "companies_house" / "20261006").exists()
    assert "could not be read whole" in capsys.readouterr().out


def test_the_key_comes_from_the_environment_then_the_token_file(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cfg, "reference_dir", lambda: tmp_path)
    monkeypatch.setattr(cfg, "raw_dir", lambda: tmp_path / "raw")
    monkeypatch.delenv(ch.KEY_ENV, raising=False)
    with pytest.raises(ch.KeyMissing) as e:
        ch.api_key()
    assert ch.KEY_ENV in str(e.value) and ch.TOKEN_FILE in str(e.value)
    assert ch.main(["--numbers", "09171944"]) == 2                 # the CLI says so instead of a traceback
    assert ch.KEY_ENV in capsys.readouterr().err
    assert not (tmp_path / "raw" / "companies_house").exists()      # and leaves no empty snapshot folder
    (tmp_path / ch.TOKEN_FILE).write_text(chr(0xFEFF) + "file-key\r\n", encoding="utf-8")
    assert ch.api_key() == "file-key"                               # a byte-order mark (Notepad) and CRLF removed
    monkeypatch.setenv(ch.KEY_ENV, " env-key ")
    assert ch.api_key() == "env-key"


class _Response:
    def __init__(self, status, payload=None, headers=None):
        self.status_code, self._payload, self.headers = status, payload, headers or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


def test_the_api_sends_the_key_as_user_name_waits_out_the_rate_limit_and_reads_404_as_absent(monkeypatch):
    slept = []
    monkeypatch.setattr(ch.time, "sleep", slept.append)
    api = ch.Api("secret-key", interval=0)
    assert api.session.auth == ("secret-key", "")                   # HTTP basic: the key, an empty password
    answers = iter([_Response(429, headers={"X-Ratelimit-Reset": "30"}), _Response(503),
                    _Response(200, {"company_name": "X LIMITED"}), _Response(404)])
    monkeypatch.setattr(api.session, "get", lambda *a, **k: next(answers))
    assert api.get("/company/00000001") == {"company_name": "X LIMITED"}
    assert slept == [30.0, 2]                                        # the rest of the window, then a back-off
    assert api.get("/company/00000002") is None
    monkeypatch.setattr(api.session, "get", lambda *a, **k: _Response(401))
    with pytest.raises(ch.KeyMissing) as e:
        api.get("/company/00000003")
    assert "secret-key" not in str(e.value)


# ---------------------------------------------------------------------------- the table
@pytest.mark.parametrize("natures, ownership, voting", [
    (["ownership-of-shares-75-to-100-percent", "voting-rights-75-to-100-percent",
      "right-to-appoint-and-remove-directors"], "75-100", "75-100"),
    (["ownership-of-shares-50-to-75-percent-as-trust"], "50-75", ""),
    (["ownership-of-shares-75-to-100-percent-as-firm", "voting-rights-50-to-75-percent-as-firm"], "75-100", "50-75"),
    (["right-to-share-surplus-assets-50-to-75-percent-limited-liability-partnership",
      "voting-rights-75-to-100-percent-limited-liability-partnership"], "50-75", "75-100"),
    (["part-right-to-share-surplus-assets-25-to-50-percent"], "25-50", ""),
    (["voting-rights-25-to-50-percent"], "", "25-50"),
    (["ownership-of-shares-more-than-25-percent-registered-overseas-entity"], "", ""),
    (["significant-influence-or-control", "right-to-appoint-and-remove-members-limited-liability-partnership"], "", ""),
    ([], "", ""),
])
def test_the_bands_come_from_the_natures_of_control(natures, ownership, voting):
    assert (C.ownership_band(natures), C.voting_band(natures)) == (ownership, voting)


def test_the_table_names_no_individual_even_from_an_unfiltered_snapshot():
    record = {"company_number": "9171944", "company_name": "GLENDYE WIND FARM LIMITED",
              "persons_with_significant_control": {"items": [INDIVIDUAL, PARENT, FOREIGN, SUPER_SECURE]}}
    t = pd.DataFrame(C.rows(record, snapshot="20261006"))
    assert t.columns.tolist() == C.COLUMNS and set(t["company_number"]) == {"09171944"}
    assert set(t["snapshot"]) == {"20261006"}                        # every row dated by its pull
    assert t["controller_kind"].tolist() == ["individual", "corporate", "corporate", "other"]
    person = t.iloc[0]
    assert (person["controller_name"], person["controller_number"], person["ceased_on"]) == ("", "", "2019-05-01")
    assert t.loc[1, ["controller_name", "controller_number", "ownership_band"]].tolist() == [
        "Glen Holdings Limited", "12345678", "75-100"]
    assert t.loc[2, "controller_number"] == ""                       # registered abroad: no Companies House number
    for personal in PERSONAL:
        assert personal not in t.to_csv(), personal


def psc(company, kind="corporate", name="", number="", own="", vote="", on="2016-04-06", off="", held=""):
    return {"company_number": company, "company_name": f"COMPANY {company}", "controller_kind": kind,
            "controller_name": name, "controller_number": number, "ownership_band": own, "voting_band": vote,
            "held_as": held, "notified_on": on, "ceased_on": off}


SALES = pd.DataFrame([
    # sold on 15 March 2021 to a buyer of a smaller band, so only the cessation can hand control over
    psc("00000001", name="Old Parent Limited", number="00000010", own="75-100", vote="75-100", off="2021-03-15"),
    psc("00000001", name="New Parent Limited", number="00000020", own="50-75", vote="50-75", on="2021-03-15"),
    psc("00000001", kind="individual", own="75-100", vote="75-100"),       # the person at the top: never the answer
    psc("00000001", name="Minority Investor Limited", own="25-50", vote="25-50", on="2018-01-01"),
    psc("00000002", kind="individual", own="75-100", vote="75-100"),       # only an individual
    psc("00000003", name="Half Owner A Limited", own="25-50", vote="25-50"),   # a 50:50 joint venture
    psc("00000003", name="Half Owner B Limited", own="25-50", vote="25-50"),
    psc("00000004", kind="legal_person", name="Some Council", vote="50-75"),   # a majority of the votes only
    psc("00000005", name="Seller Limited", own="75-100"),                   # a sale whose cessation was never filed
    psc("00000005", name="Buyer Limited", own="75-100", on="2022-06-30"),
    psc("00000006", name="Gone Parent Limited", own="75-100", off="2020-01-01"),   # bought out by a person
    psc("00000006", kind="individual", own="75-100", on="2020-01-01"),
])


def _name(number, when, table=SALES):
    found = C.controller_at(number, when, table)
    return found["controller_name"] if found else None


def test_the_controller_on_a_date_follows_a_sale_and_ignores_individuals_and_minorities():
    assert _name("00000001", "2015-12-31") is None                    # before the registers began
    assert _name("00000001", "2020-12-31") == "Old Parent Limited"
    assert _name("00000001", "2021-03-14") == "Old Parent Limited"
    assert _name("00000001", "2021-03-15") == "New Parent Limited"    # the old one ceased that day
    assert _name("00000001", T("2026-10-06")) == "New Parent Limited"
    assert _name(1, "2020-12-31") == "Old Parent Limited"             # the number as a spreadsheet keeps it
    assert _name("00000002", "2023-12-31") is None                    # only an individual
    assert _name("00000003", "2023-12-31") is None                    # two holders of 25-50: no majority
    assert _name("00000004", "2023-12-31") == "Some Council"
    assert _name("00000005", "2021-12-31") == "Seller Limited"
    assert _name("00000005", "2023-12-31") == "Buyer Limited"         # both in force: the later notification
    assert _name("00000006", "2019-12-31") == "Gone Parent Limited"
    assert _name("00000006", "2020-01-01") is None                    # ceased; an individual since
    assert _name("00000099", "2023-12-31") is None                    # not in the table
    found = C.controller_at("00000001", "2020-12-31", SALES)
    assert found["controller_number"] == "00000010" and found["ceased_on"] == T("2021-03-15")
    # the CSV read back without dtypes (numbers as integers, dates as text) answers the same
    back = pd.read_csv(io.StringIO(SALES.to_csv(index=False)))
    assert _name("00000001", "2021-03-15", back) == "New Parent Limited"


def test_the_controller_on_a_date_from_the_csv_read_as_text():
    # company_control.csv as most readers read it: every column text, blanks as "", no snapshot column in old files
    text = pd.read_csv(io.StringIO(SALES.to_csv(index=False)), dtype=str, keep_default_na=False)
    assert (text["ceased_on"] == "").any()
    assert _name("00000001", "2021-03-14", text) == "Old Parent Limited"
    assert _name("00000001", "2021-03-15", text) == "New Parent Limited"
    assert _name("1", "2021-03-15", text) == "New Parent Limited"
    assert _name("00000005", "2023-12-31", text) == "Buyer Limited"
    assert _name("00000006", "2020-01-01", text) is None
    found = C.controller_at("00000001", "2020-12-31", text)
    assert found["ceased_on"] == T("2021-03-15") and found["snapshot"] == ""
    assert pd.isna(C.controller_at("00000001", "2022-12-31", text)["ceased_on"])    # "" read as no date


CHAIN = pd.DataFrame([
    # a project company sold in mid-2021 by a developer to a holding company whose parent is SSE's
    psc("00000100", name="Glen Developments Limited", number="00000200", own="75-100", off="2021-06-30"),
    psc("00000100", name="Glen Holdings Limited", number="00000300", own="75-100", on="2021-06-30"),
    psc("00000300", name="SSE Renewables Holdings Limited", number="SC000001", own="75-100", on="2019-01-01"),
    psc("00000200", kind="individual", own="75-100"),
    # a group known by an alias, two levels up, through a 50-75 holding
    psc("00000400", name="Mid Co Limited", number="00000500", own="50-75"),
    psc("00000500", name="Alpha Energy Holdings Ltd", own="75-100"),
    # a loop in the filings ends
    psc("00000600", name="Loop A Limited", number="00000700", own="75-100"),
    psc("00000700", name="Loop B Limited", number="00000600", own="75-100"),
    # a chain longer than MAX_LEVELS: the group five levels up is not reached
    *[psc(f"0000080{i}", name=f"Level {i + 1} Limited", number=f"0000080{i + 1}", own="75-100") for i in range(4)],
    psc("00000804", name="SSE plc", own="75-100"),
])


def test_a_companys_group_follows_its_controllers_up_the_chain(dirs):
    assert C.group_by_control("00000100", "2022-12-31", CHAIN) == ("SSE", "ch_psc")             # by name, two up
    assert C.group_by_control("00000100", "2020-12-31", CHAIN) == ("Glen Developments", "ch_psc")  # the last name
    assert C.group_by_control("00000400", "2022-12-31", CHAIN) == ("Alpha", "ch_psc")           # by alias
    assert C.group_by_control("00000600", "2022-12-31", CHAIN) == ("Loop B", "ch_psc")
    assert C.MAX_LEVELS == 4
    assert C.group_by_control("00000800", "2022-12-31", CHAIN) == ("Level 4", "ch_psc")
    assert C.group_by_control("00000801", "2022-12-31", CHAIN) == ("SSE", "ch_psc")
    assert C.group_by_control("00000200", "2022-12-31", CHAIN) == ("", "")                    # an individual only
    assert C.group_by_control("00000999", "2022-12-31", CHAIN) == ("", "")
    assert C.group_by_control("", "2022-12-31", CHAIN) == ("", "")
    assert C.group_by_control("00000100", None, CHAIN) == ("", "")                            # no date, no answer


def test_known_only_answers_a_group_only_where_the_chain_reaches_one_known_by_alias_or_name(dirs):
    for known_only in (False, True):                  # SSE two up by name, Alpha two up by alias: the same either way
        assert C.group_by_control("00000100", "2022-12-31", CHAIN, known_only=known_only) == ("SSE", "ch_psc")
        assert C.group_by_control("00000400", "2022-12-31", CHAIN, known_only=known_only) == ("Alpha", "ch_psc")
    # no known group up the chain: the last controller's name, or nothing with known_only
    assert C.group_by_control("00000100", "2020-12-31", CHAIN) == ("Glen Developments", "ch_psc")
    assert C.group_by_control(company_number="100", when="2020-12-31", table=CHAIN, known_only=True) == ("", "")
    assert C.group_by_control("00000600", "2022-12-31", CHAIN, known_only=True) == ("", "")      # a loop
    assert C.group_by_control("00000800", "2022-12-31", CHAIN, known_only=True) == ("", "")      # beyond MAX_LEVELS
    assert C.group_by_control("00000200", "2022-12-31", CHAIN, known_only=True) == ("", "")      # an individual

    # the intended order in companies.group_of: known_only before the CM parent, the last name after it
    def group_of(number, when, cm_group):
        return (C.group_by_control(number, when, CHAIN, known_only=True)[0] or cm_group
                or C.group_by_control(number, when, CHAIN)[0] or "self")
    assert group_of("00000100", "2020-12-31", "RWE") == "RWE"     # an unknown holding company never beats it
    assert group_of("00000100", "2022-12-31", "RWE") == "SSE"     # a known group on the date does
    assert group_of("00000100", "2020-12-31", "") == "Glen Developments"
    assert group_of("00000999", "2020-12-31", "") == "self"


def test_lookups_on_the_default_table_are_remembered_per_company_and_day_until_clear_cache(dirs, monkeypatch):
    CHAIN.assign(snapshot="20261006").to_csv(dirs.processed / C.OUTPUT, index=False)
    walked = []
    real = C._controller
    monkeypatch.setattr(C, "_controller", lambda t, when: walked.append(when) or real(t, when))
    assert C.group_by_control("00000801", "2022-12-31") == ("SSE", "ch_psc")
    assert len(walked) == 4                                          # four controllers up
    # the same company and day in either mode, the number and the date written otherwise: remembered
    assert C.group_by_control(801, T("2022-12-31 15:30")) == ("SSE", "ch_psc")
    assert C.group_by_control("00000801", "2022-12-31", known_only=True) == ("SSE", "ch_psc")
    assert len(walked) == 4
    assert C.group_by_control("00000801", "2022-12-31", CHAIN) == ("SSE", "ch_psc")   # a table given: walked again
    assert len(walked) == 8
    C.clear_cache()
    assert C.group_by_control("00000801", "2022-12-31") == ("SSE", "ch_psc")
    assert len(walked) == 12


def test_the_table_is_typed_once_per_chain_and_not_at_all_with_an_index(dirs, monkeypatch):
    calls = []
    typed = C._typed
    monkeypatch.setattr(C, "_typed", lambda t: calls.append(len(t)) or typed(t))
    assert C.group_by_control("00000801", "2022-12-31", CHAIN) == ("SSE", "ch_psc")    # four controllers up
    assert len(calls) == 1
    index = C.index_table(CHAIN)
    calls.clear()
    assert C.group_by_control("00000800", "2022-12-31", index) == ("Level 4", "ch_psc")
    assert C.controller_at("00000100", "2022-12-31", index)["controller_name"] == "Glen Holdings Limited"
    assert calls == []


def _snapshot(root, stamp, number, items, name="SOME COMPANY LIMITED", previous=()):
    folder = root / "companies_house" / stamp
    folder.mkdir(parents=True, exist_ok=True)
    record = {"company_number": number, "company_name": name,
              "previous_company_names": [{"name": p, "effective_from": "2014-01-01", "ceased_on": "2018-01-01"}
                                         for p in previous],
              "persons_with_significant_control": {"found": True, "items": [ch.filter_psc(i) for i in items]}}
    path = folder / f"{number}.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    return path


def test_the_table_reads_the_newest_snapshot_of_each_company_dates_its_rows_and_writes_numbers_as_text(dirs):
    empty = C.control_table()
    assert empty.empty and empty.columns.tolist() == C.COLUMNS
    assert C.controller_at("09171944", "2026-10-06") is None
    sold = {**PARENT, "ceased_on": "2025-01-31"}
    buyer = corporate("Buyer Holdings Limited", "7598482", notified_on="2025-01-31")
    _snapshot(dirs.raw, "20261001", "09171944", [PARENT], name="GLENDYE WIND FARM LIMITED")
    _snapshot(dirs.raw, "20261001", "SC449688", [INDIVIDUAL])
    _snapshot(dirs.raw, "20261006", "09171944", [sold, buyer], name="GLENDYE WIND FARM LIMITED")
    t = C.control_table()                                            # no processed table yet: the snapshots
    assert set(t["company_number"]) == {"09171944", "SC449688"}     # a later pull of one company adds to the rest
    glendye = t[t["company_number"] == "09171944"]
    assert glendye["controller_name"].tolist() == ["Glen Holdings Limited", "Buyer Holdings Limited"]
    assert set(glendye["snapshot"]) == {"20261006"}                  # "still holds" as of that pull
    assert set(t.loc[t["company_number"] == "SC449688", "snapshot"]) == {"20261001"}
    assert len(C.control_table(stamp="20261001")) == 2               # as pulled on 1 October
    C.clear_cache()
    assert C.controller_at("9171944", "2026-10-06")["controller_number"] == "07598482"   # the snapshots on disk
    assert C.controller_at("09171944", "2024-12-31")["controller_name"] == "Glen Holdings Limited"
    assert B.main([]) == 0                                            # data/processed/company_control.csv
    path = dirs.processed / C.OUTPUT
    back = pd.read_csv(path, dtype=str, keep_default_na=False)
    assert back.columns.tolist() == C.COLUMNS
    assert back["company_number"].str.len().eq(8).all() and "07598482" in set(back["controller_number"])
    assert set(back["ceased_on"]) == {"", "2025-01-31", "2019-05-01"}
    assert set(back["notified_on"]) == {"2016-04-06", "2019-05-01", "2025-01-31"}
    assert set(back["snapshot"]) == {"20261001", "20261006"}
    for personal in PERSONAL:
        assert personal not in path.read_text("utf-8"), personal
    assert [p.name for p in dirs.processed.iterdir()] == [C.OUTPUT]   # written whole, no part file left
    before = path.read_bytes()
    assert B.main(["--stamp", "20261001"]) == 0                       # as pulled on 1 October, in a file of its own
    assert len(pd.read_csv(dirs.processed / "company_control_20261001.csv", dtype=str)) == 2
    assert path.read_bytes() == before                                # the lookups' table is still every pull's
    assert B.output_path(stamp="20261001") == dirs.processed / "company_control_20261001.csv"


def test_a_controller_number_that_leads_to_a_company_of_another_name_is_blanked(dirs, capsys):
    sse = corporate("SSE Renewables Holdings Limited", "SC123456")
    _snapshot(dirs.raw, "20261006", "09171944", [PARENT], name="GLENDYE WIND FARM LIMITED")
    _snapshot(dirs.raw, "20261006", "12345678", [sse], name="UNRELATED TRADING LIMITED",
              previous=["OTHER OLD NAME LIMITED"])
    _snapshot(dirs.raw, "20261006", "08904850", [corporate("Never Pulled Holdings Limited", "7598482")])
    t = C.snapshot_table()
    glendye = t[t["company_number"] == "09171944"].iloc[0]
    assert (glendye["controller_name"], glendye["controller_number"]) == ("Glen Holdings Limited", "")
    out = capsys.readouterr().out
    assert "WARNING" in out and "12345678" in out and "UNRELATED TRADING LIMITED" in out
    # a controller that was never pulled cannot be checked: its number stays
    assert t.loc[t["company_number"] == "08904850", "controller_number"].tolist() == ["07598482"]
    assert C.group_by_control("09171944", "2026-10-06") == ("Glen Holdings", "ch_psc")    # the chain stops there
    assert "WARNING" in capsys.readouterr().out                       # the lookup read the snapshots: same check
    # a previous name is the company's too (renamed after the filing): the number stays and the chain goes on
    _snapshot(dirs.raw, "20261007", "12345678", [sse], name="NEW NAME LIMITED", previous=["GLEN HOLDINGS LIMITED"])
    t = C.snapshot_table()
    assert t.loc[t["company_number"] == "09171944", "controller_number"].tolist() == ["12345678"]
    assert "WARNING" not in capsys.readouterr().out
    C.clear_cache()
    assert C.group_by_control("09171944", "2026-10-06") == ("SSE", "ch_psc")


def test_lookups_read_the_processed_table_where_it_exists_and_warn_when_a_snapshot_is_newer(dirs, capsys):
    _snapshot(dirs.raw, "20261001", "09171944", [PARENT], name="GLENDYE WIND FARM LIMITED")
    path = B.write()
    assert C.group_by_control("09171944", "2026-10-06") == ("Glen Holdings", "ch_psc")
    # lookups read the table, not the snapshots: change the table and the answer follows it
    table = pd.read_csv(path, dtype=str, keep_default_na=False)
    table.loc[0, "controller_name"] = "Alpha Energy Holdings Ltd"
    table.to_csv(path, index=False)
    C.clear_cache()
    assert C.group_by_control("09171944", "2026-10-06") == ("Alpha", "ch_psc")    # by alias, from the file
    assert "WARNING" not in capsys.readouterr().out
    # a snapshot written after the table: the table is still read, with a warning to rebuild it
    newer = _snapshot(dirs.raw, "20261006", "SC449688", [INDIVIDUAL])
    later = path.stat().st_mtime + 60
    os.utime(newer, (later, later))
    C.clear_cache()
    assert C.group_by_control("09171944", "2026-10-06") == ("Alpha", "ch_psc")
    out = capsys.readouterr().out
    assert "WARNING" in out and "20261006" in out and "build_company_control" in out


def test_lookups_warn_when_a_later_pull_with_entries_is_missing_from_the_table_whatever_the_file_times(dirs, capsys):
    _snapshot(dirs.raw, "20261001", "09171944", [PARENT], name="GLENDYE WIND FARM LIMITED")
    path = B.write()
    built = path.stat().st_mtime
    # a later pull whose files are older than the table (restored from a backup, say): only its date shows it
    later = _snapshot(dirs.raw, "20261006", "SC449688", [corporate("Buyer Holdings Limited", "7598482")])
    os.utime(later, (built - 60, built - 60))
    capsys.readouterr()
    C.clear_cache()
    assert C.group_by_control("09171944", "2026-10-06") == ("Glen Holdings", "ch_psc")    # read as it is
    out = capsys.readouterr().out
    assert "WARNING" in out and "20261006" in out and "20261001" in out and "build_company_control" in out
    # a stamped build leaves it as it is (it writes its own file), so the warning stays
    assert B.main(["--stamp", "20261001"]) == 0
    C.clear_cache()
    C.group_by_control("09171944", "2026-10-06")
    assert "20261006" in capsys.readouterr().out
    # rebuilt from every pull, then a later pull of a company without PSC entries, which adds no rows: no warning
    B.write()
    empty = _snapshot(dirs.raw, "20261007", "00000405", [])
    os.utime(empty, (path.stat().st_mtime - 60,) * 2)
    capsys.readouterr()
    C.clear_cache()
    assert C.group_by_control("09171944", "2026-10-06") == ("Glen Holdings", "ch_psc")
    assert "WARNING" not in capsys.readouterr().out
    # a later pull of a company the table holds, now without entries, takes its rows away: that shows
    gone = _snapshot(dirs.raw, "20261008", "09171944", [], name="GLENDYE WIND FARM LIMITED")
    os.utime(gone, (path.stat().st_mtime - 60,) * 2)
    C.clear_cache()
    C.group_by_control("09171944", "2026-10-06")
    out = capsys.readouterr().out
    assert "WARNING" in out and "20261008" in out


def test_a_lookup_without_snapshots_or_table_is_cheap_and_empty(dirs, monkeypatch):
    reads = []
    real = C.control_table
    monkeypatch.setattr(C, "control_table", lambda stamp=None: reads.append(stamp) or real(stamp))
    for _ in range(3):
        assert C.group_by_control("09171944", "2026-10-06") == ("", "")
        assert C.controller_at("9171944", T("2026-10-06")) is None
    assert reads == [None]                                            # read once, then remembered
    assert not any(dirs.raw.iterdir()) and not any(dirs.processed.iterdir())    # and nothing written
    assert C.number_of("Glendye Wind Farm Limited") == ""             # no curated list in this folder


def test_a_company_without_a_number_takes_the_one_the_curated_list_gives_its_name(dirs):
    pd.DataFrame([{"company_number": "9171944", "name": "GLENDYE WIND FARM LIMITED", "why": "x"},
                  {"company_number": "SC1", "name": "Twin Name Ltd", "why": "x"},
                  {"company_number": "SC2", "name": "TWIN NAME LIMITED", "why": "x"}]).to_csv(
        dirs.reference / C.NUMBERS_FILE, index=False)
    assert C.number_of("Glendye Wind Farm Ltd") == "09171944"         # by normalised name, the number normalised
    assert C.number_of("Twin Name Limited") == ""                      # a name two numbers share names neither
    assert C.number_of("Unknown Ltd") == "" and C.number_of(None) == ""


# gbpowerdata.common.companies with the Companies House basis wired in (resolve and group_of taking company_number
# and the date)
def test_a_project_company_resolves_to_its_controllers_group_on_the_date(dirs):
    pd.DataFrame([
        psc("09171944", name="Glen Developments Limited", number="00000200", own="75-100", off="2021-06-30"),
        psc("09171944", name="SSE Renewables Holdings Limited", number="SC000001", own="75-100", on="2021-06-30"),
    ]).assign(snapshot="20261006").to_csv(dirs.processed / C.OUTPUT, index=False)
    pd.DataFrame([{"company_number": "09171944", "name": "GLENDYE WIND FARM LIMITED", "why": "test"}]).to_csv(
        dirs.reference / C.NUMBERS_FILE, index=False)
    sold, before = T("2022-12-31"), T("2020-12-31")
    # the register's number, as the CfD register keeps it (without its leading zero)
    assert co.resolve("Glendye Wind Farm Limited", sold, company_number="9171944") == (
        [{"group": "SSE", "share": 1.0}], "SSE", "ch_psc")
    assert co.resolve("Glendye Wind Farm Limited", before, company_number="9171944") == (
        [{"group": "Glen Developments", "share": 1.0}], "Glen Developments", "ch_psc")
    # no number given: the curated list gives it by the company's name
    assert co.resolve("GLENDYE WIND FARM LTD", sold)[1:] == ("SSE", "ch_psc")
    # dated, so tried before the Capacity Market parent, which is today's
    cm = {co.norm("Glendye Wind Farm Limited"): "RWE plc"}
    assert co.group_of("Glendye Wind Farm Limited", cm, when=sold) == ("SSE", "ch_psc")
    assert co.resolve("Glendye Wind Farm Limited", sold, cm_parents=cm)[2] == "ch_psc"
    # without a date there is no lookup: the CM parent, else the company itself
    assert co.group_of("Glendye Wind Farm Limited", cm) == ("RWE", "cm_parent")
    assert co.group_of("Glendye Wind Farm Limited") == ("Glendye Wind Farm", "self")
    # the same company trading its own units is placed as it is as an owner (trader_group passes the date)
    assert co.trader_group("Glendye Wind Farm Limited", sold) == ("SSE", "ch_psc")
    assert co.trader_group("Glendye Wind Farm Limited", before) == ("Glen Developments", "ch_psc")
    # a company the table does not place falls through to the rules after it
    assert co.resolve("Other Wind Limited", sold, company_number="00000999")[1:] == ("Other Wind", "self")
    assert co.resolve("Other Wind Limited", sold, cm_parents={co.norm("Other Wind Limited"): "RWE plc"},
                      company_number="00000999")[1:] == ("RWE", "cm_parent")


# ---------------------------------------------------------------------------- the curated list
def test_the_seeded_list_of_company_numbers_is_well_formed():
    t = pd.read_csv(REAL_REFERENCE / C.NUMBERS_FILE, dtype=str, keep_default_na=False)
    assert t.columns.tolist() == C.NUMBERS_COLUMNS
    # eight digits, a prefix (R0 included) and six digits, or a registered society's IP00525R / SP0218RS
    shape = r"[0-9]{8}|[A-Z][A-Z0-9][0-9]{6}|[A-Z]{2}[0-9]{4,5}[A-Z]{1,2}"
    assert t["company_number"].str.fullmatch(shape).all(), t.loc[
        ~t["company_number"].str.fullmatch(shape), "company_number"]
    assert t["company_number"].map(C.company_number).eq(t["company_number"]).all()    # canonical, leading zeros kept
    assert not t["company_number"].duplicated().any()
    assert not t["name"].map(co.norm).duplicated().any()               # number_of finds each by its name
    assert (t["name"].str.strip() != "").all() and (t["why"].str.strip() != "").all()


def test_a_trustee_is_never_the_controller():
    # Glendye and Blarghour: shares and votes filed as held as a trustee; MeyGen: a corporate trustee by its name
    as_trust = ["ownership-of-shares-50-to-75-percent-as-trust", "voting-rights-75-to-100-percent-as-trust"]
    assert C.held_as(as_trust) == "trust"
    assert C.held_as(["ownership-of-shares-75-to-100-percent", "ownership-of-shares-75-to-100-percent-as-trust"]) == ""
    assert C.held_as(["ownership-of-shares-75-to-100-percent-as-firm"]) == ""      # a fund's partnership holds
    assert C.held_as(["significant-influence-or-control"]) == ""
    record = {"company_number": "09171723", "company_name": "BLARGHOUR WIND FARM LIMITED",
              "persons_with_significant_control": {"items": [
                  {**PARENT, "name": "Womble Bond Dickinson (Trust Corporation) Limited", "natures_of_control": as_trust}]}}
    assert C.rows(record)[0]["held_as"] == "trust"
    table = pd.DataFrame([
        psc("09171723", name="Womble Bond Dickinson (Trust Corporation) Limited", own="50-75", vote="75-100", held="trust"),
        psc("SC347501", name="HSBC Corporate Trustee Company (UK) Limited", own="75-100"),
        psc("00000111", name="Example Nominees Limited", own="75-100"),
        psc("00000222", name="Harmony Energy Income Trust plc", own="75-100"),                # a trust, not a trustee
        psc("00000333", name="Example Nominees Limited", own="75-100"),
        psc("00000333", name="Real Parent Limited", own="50-75")])
    for company in ("09171723", "SC347501", "00000111"):
        assert C.controller_at(company, "2025-12-31", table) is None
        assert C.group_by_control(company, "2025-12-31", table) == ("", "")
    assert C.controller_at("00000222", "2025-12-31", table)["controller_name"] == "Harmony Energy Income Trust plc"
    assert C.controller_at("00000333", "2025-12-31", table)["controller_name"] == "Real Parent Limited"


def test_a_lender_is_never_the_controller():
    # Kilbraur Wind Energy: Falck's (Renantis') entries ceased on 22 Dec 2022 and Intesa Sanpaolo holds the shares as
    # security from 11 Jul 2023 (Scots law gives the lender the title); Broken Cross: National Westminster Bank
    table = pd.DataFrame([
        psc("SC254430", name="Falck Renewables Wind Limited", own="50-75", vote="50-75", on="2016-06-30", off="2022-12-22"),
        psc("SC254430", name="Mufg Bank, Ltd", own="25-50", on="2022-04-19", off="2022-12-22"),
        psc("SC254430", name="Intesa Sanpaolo S.P.A", own="75-100", on="2023-07-11"),
        psc("SC579904", name="National Westminster Bank Plc", own="75-100", on="2023-12-20", off="2025-09-15"),
        psc("02267400", name="Banks Group Holdings Limited", own="75-100", vote="75-100", on="2018-07-27")])
    assert C.controller_at("SC254430", "2021-12-31", table)["controller_name"] == "Falck Renewables Wind Limited"
    assert C.group_by_control("SC254430", "2021-12-31", table) == ("Renantis", "ch_psc")
    for when in ("2023-12-31", "2025-12-31"):
        assert C.controller_at("SC254430", when, table) is None
        assert C.group_by_control("SC254430", when, table) == ("", "")
    assert C.controller_at("SC579904", "2024-12-31", table) is None
    assert C.controller_at("02267400", "2025-12-31", table)["controller_name"] == "Banks Group Holdings Limited"
    assert C.LENDER.search("The Banks Group Limited") is None and C.LENDER.search("Riverbank Energy") is None
