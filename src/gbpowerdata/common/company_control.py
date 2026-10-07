"""Who controls a company, and from when: Companies House's persons with significant control (PSC), read and
interpreted in one place.

Why: the ownership tables (gbpowerdata.build.build_ownership) reduce every company a register names to a group,
and a project company that no rule places resolves to itself (basis "self"): 6.9 GW of the CfD contracts counted
in 2025 and 12.4 GW in 2026, in the tables built on 6 Oct 2026. Companies House's register of persons with
significant control names each company's parent, the date it became one and the date it ceased to be, so it
places such a company in a group on a given date and dates the changes of control. Everything that interprets that
register lives here, so its three users agree: the puller (gbpowerdata.pull.companies_house_pull) takes the company
numbers, the test of a UK registration, the name check and the personal-data test from this module; the build
(gbpowerdata.build.build_company_control) writes snapshot_table() to data/processed/company_control.csv; and
gbpowerdata.common.companies asks group_by_control() for a company's group on a date (basis "ch_psc").

Intended use, by gbpowerdata.common.companies.group_of when it is given a date and a company number, in this order:
  1. group_by_control(number, when, known_only=True) before the Capacity Market parent: a controller on the date
     that leads to a group known by alias or name wins over NESO's parent, which is today's;
  2. group_by_control(number, when) after the CM parent and before "self": the name of a holding company that no
     rule places is better than the company's own, but it never overrides a CM parent that names a real group.

Layering: common is the lowest layer of the package. This module imports gbpowerdata.config only;
gbpowerdata.common.companies (norm, clean, group_of) is imported inside the functions that use it, because
companies imports this module the same way. Nothing here imports gbpowerdata.build or gbpowerdata.pull.

Source: Companies House Public Data API, https://api.company-information.service.gov.uk, through the puller's
snapshots (its docstring lists the resources and fields, and what the API documentation says about them).
Licence: none is stated. Companies House "imposes no rules or requirements on how the information on the public
register is used" and requires credit where its guidance, website, publications or statistical tables are used
(gov.uk, "Our public task, copyright and Crown copyright",
https://www.gov.uk/government/publications/companies-house-accreditation-to-information-fair-traders-scheme/public-task-copyright-and-crown-copyright);
its reusers are "responsible for complying with any applicable data protection, copyright and other legislation
and regulations" (gov.uk, "Companies House data products", https://www.gov.uk/guidance/companies-house-data-products).

Where the table comes from (control_table, which every lookup reads unless it is handed a table):
  1. data/processed/company_control.csv where it exists: the fast path, the table of every pull as
     build_company_control last wrote it (its --stamp writes company_control_{YYYYMMDD}.csv instead, which no lookup
     reads). It is read as it is, with a WARNING to rebuild it, where a snapshot on disk was written after it, or
     where a pull date later than its newest snapshot value changes the table (it holds PSC entries, or a newer
     snapshot of a company in the table; a pull of new companies without entries adds no rows, so its date never
     reaches the table and is not counted).
  2. Otherwise the snapshots themselves, data/raw/companies_house/{YYYYMMDD}/{number}.json, the newest of each
     company (the latest pull-date folder that holds it, so a later pull of a few numbers adds to an earlier full
     pull instead of replacing it): snapshot_table(), the rows the build writes, name check included.
  With neither, the table is empty and every lookup answers None or ("", ""), for the cost of two file checks.
  Nothing is written, but looking for the processed table goes through gbpowerdata.config.processed_dir(), which
  creates data/processed/ where it is missing (as it does for every caller).
  control_table(stamp) with a pull date always reads the snapshots, up to that date. The default table is read
  once per process and group_by_control's answers from it are remembered per company and day: clear_cache() after
  a new pull or build (and after editing data/reference/company_groups.csv, whose groups those answers name).

The table, one row per company and PSC, ceased ones included:
  company_number     the company's Companies House number, eight characters, as text (company_number)
  company_name       its name in the snapshot (the profile's)
  controller_kind    corporate (a company), legal_person (a body that is not a company, such as a local
                     authority), individual, or other: a super-secure entry, a kind not known here, or a corporate
                     or legal-person entry with no name or with a person's details or title (Personal data below)
  controller_name    the controller's name, for corporate and legal persons only: blank for anyone else, so the
                     table never names a person
  controller_number  the controller's Companies House number where it is registered in the UK (uk_number) and,
                     where that company was pulled too, Companies House gives it the controller's name, today's or
                     a previous one (name_mismatch). Blank otherwise, with a WARNING where the name does not match:
                     a mistyped registration number in a filing would chain the company to a stranger. A foreign
                     registration number stays in the raw snapshot.
  ownership_band     the shares the controller holds (of an LLP or a partnership: the right to its surplus assets)
                     in the bands of the PSC forms: "25-50" more than 25% but not more than 50%, "50-75" more than
                     50% but less than 75%, "75-100" 75% or more; from natures_of_control such as
                     ownership-of-shares-75-to-100-percent and its -as-trust and -as-firm variants (held as a
                     trustee, or through a firm such as a fund's limited partnership). Blank where it holds none: it
                     appoints the directors or has significant influence only, or it is a beneficial owner of an
                     overseas entity, whose codes say no more than "more than 25 percent"
  voting_band        the same for voting rights
  held_as            "trust" where every band the controller has is filed as held as a trustee (natures ending
                     -as-trust), else blank: a trustee is never a controller (Gotchas)
  notified_on        the date the controller became registrable, as the company gives it (6 April 2016 at the
                     earliest)
  ceased_on          the date it ceased to be one; blank while it holds
  snapshot           the pull date (YYYYMMDD) of the snapshot the row comes from: a blank ceased_on means the
                     controller still held on that date. Nothing is known of later dates; a lookup after it
                     assumes nothing changed.

Numbers (company_number): eight characters, as Companies House writes them, ASCII digits only. Digits alone are a
company of England and Wales, zero-padded ("9171944", as a spreadsheet keeps it, is 09171944). Otherwise a known
two-character prefix and six digits, zero-padded ("SC12345" is SC012345), a separator after the prefix dropped
("SC-123456", "SC 123456", "SC.123456", "SC/123456" and "SC:123456" are SC123456; "R0-000123" is R0000123). The prefixes (PREFIXES, with what each registers) are
those of Companies House's "Uniform Resource Identifiers (URI) Customer Guide", version 1.1, May 2012,
https://assets.publishing.service.gov.uk/government/uploads/system/uploads/attachment_data/file/426891/uniformResourceIdentifiersCustomerGuide.pdf
(for England and Wales, Scotland and Northern Ireland in turn where there are three):
  SC Scottish company; NI Northern Ireland company; R0 Northern Ireland company from before partition
  OC SO NC  limited liability partnerships        LP SL NL  limited partnerships
  AC SA NA  assurance companies                   ZC SZ NZ  unregistered companies (not under the Companies Acts)
  GE GS GN  European Economic Interest Groupings  SE ES EN  European companies (Societas Europaea)
  IC SI NV  investment companies with variable capital  RC SR NR  Royal Charter companies
  IP SP NP  industrial and provident (now registered) societies, NP also credit unions; NO credit unions (NI)
  FC overseas company; SF and NF overseas companies registered in Scotland or Northern Ireland before 1 Oct 2009
and those added since, which the guide lacks (Companies House forum, "Missing prefixes in Companies House
document", November 2024, https://forum.companieshouse.gov.uk/t/missing-prefixes-in-companies-house-document/10257):
OE registered overseas entity, CE and CS charitable incorporated organisations (England and Wales, Scotland), FE
further education or sixth form college corporation, PC protected cell company, SG Scottish qualifying partnership;
and BR, the number Companies House gives a UK establishment of an overseas company, which neither list has. A registered society keeps the letters of its FCA number after
its IP, SP or NP and digits, eight characters in all: Co-operative Group is IP00525R, a Scottish society SP0218RS.
Anything else is "": an unknown prefix ("XY123456"), a society's FCA number without its prefix ("525R"), a number
of zeros only, digits other than 0-9.

UK registrations (uk_number): the identification's country_registered decides where it is filled, place_registered
only where it is blank, each with its white space and hyphens collapsed and accents dropped. It must name England,
Wales, Scotland, Northern Ireland (N. Ireland), the United Kingdom (UK, U.K.), Britain or Companies House ("GB" only
as the whole field), not New England, New South Wales, New Scotland or New Britain. Neither field may name, whatever
stands beside it: Gibraltar (whose registry is also called Companies House); a Crown Dependency (Jersey, Guernsey,
Alderney, Sark, the Isle of Man or IOM or Manx, the Channel Islands); Ireland (Eire, Irish, its Companies
Registration Office or CRO; Northern Ireland is taken out first); or an overseas territory with a registry of its
own: the Cayman Islands, Bermuda, the (British) Virgin Islands or BVI, Anguilla, Montserrat, the Turks and Caicos
Islands, the Falkland Islands, St (Saint) Helena, Ascension, Tristan da Cunha, Pitcairn. The number is the
registration_number as company_number reads it; failing that, it is looked for in the text ("Company number SC
449688", "No. 9171944 (England and Wales)"): first a known prefix joined to its six digits (a society's to its
digits and letters) by at most one separator (".", "-", ":", "/" or "#", with or without spaces); then a run of
six to eight digits on its own, passed over where a word of one or two letters stands right before it with any
separator ("XY-123456" and "XY: 123456" are not 00123456 but an unknown or mistyped prefix; "SC-1234567" is not
01234567), unless that word is No, Nr, Co, UK, GB, EW or CH, which are read here as words, not prefixes ("E & W"
before the digits is England and Wales).
"No" and "Nr" followed by a separator are the word number, not the prefixes NO and NR: "No 123456" is 00123456,
"NO123456" a credit union.

Functions:
  company_number(value)                  a Companies House number as eight characters of text ("" if it is none):
                                         the one normaliser for every register's numbers (Numbers above)
  uk_number(item)                        the Companies House number of a UK-registered corporate PSC entry, else ""
                                         (UK registrations above)
  looks_personal(item)                   True for an entry with a person's details or title, whatever its kind
  name_mismatch(psc_name, record)        True when a pulled company has a name and none of its names is psc_name
  valid_stamp(stamp)                     a pull date as YYYYMMDD (a real date); ValueError otherwise
  snapshot_files(stamp), snapshot_table(stamp)
                                         the newest snapshot of each company, and their rows (what the build writes)
  control_table(stamp)                   the table (see above), dates parsed
  index_table(table)                     a table typed once and split by company number, for many lookups
  controller_at(number, when, table)     the corporate or legal-person PSC with a majority (ownership or votes
                                         50-75 or 75-100) in force on the day of `when` (notified_on <= day <
                                         ceased_on), as a dict; None if there is none, or only individuals,
                                         trustees or lenders (Gotchas). Two at once (a sale whose cessation was
                                         filed late): the larger band, then the later notification.
  group_by_control(company_number, when, table, known_only)
                                         (group, "ch_psc"): the majority controller followed up the chain within
                                         the table (MAX_LEVELS controllers at most) to the first controller that
                                         gbpowerdata.common.companies.group_of places by alias or name; failing
                                         that, the last controller's name without its legal form, or ("", "") with
                                         known_only=True; ("", "") without a majority corporate controller, without
                                         a date, or with no table at all
  number_of(name)                        the number data/reference/companies_house_numbers.csv lists for a company
                                         name (compared by companies.norm), "" if none
  clear_cache()                          forget the default table, the answers read from it and the list of numbers
`table` is control_table() by default, company_control.csv read any way (with or without dtype=str), or
index_table() of either. A DataFrame is typed and indexed once per call (group_by_control walks the whole chain on
that one index); an index is used as it is, so pass one for many lookups.

Gotchas:
- A majority is more than 50%: the owners of a 50:50 joint venture hold "25-50" each, so the venture company has
  no majority controller; its shares belong in data/reference/company_owners.csv.
- The dates are the company's own, and Companies House does not check them. Control held before 6 April 2016
  shows from that date, so the table says nothing about earlier dates; a change filed late leaves two majority
  controllers overlapping (see controller_at). Lookups are by day: the time of `when` is dropped.
- The chain stops at a controller that was not pulled (companies_house_pull --follow N pulls the UK parents), that
  is registered abroad, or whose number Companies House gives to a company of another name. A corporate PSC is the
  first "relevant legal entity" up the chain, so an unlisted foreign holding company is skipped (see the puller).
- Only the PSC entries are read: a company with only statements has no rows, and the right to appoint the
  directors or significant influence alone does not make a majority.
- A trustee is never a controller: one whose bands are all filed as held as a trustee (held_as "trust"), or whose
  name says trustee, trust corporation, nominee or custodian (TRUSTEE), holds the shares for someone else and names
  no owner's group. Found in the first pull (7 Oct 2026): Womble Bond Dickinson (Trust Corporation) Limited for
  Glendye and Blarghour, two Grace Dieu Corporate Trustee companies for Oakley Solar, HSBC Corporate Trustee
  Company (UK) Limited for MeyGen. Such a company has no majority controller unless another one holds; a fund's
  general partner filed as holding "-as-firm" stays a controller.
- A lender is never a controller either: Scots law transfers the title of pledged shares to the lender, which then
  files as the PSC. A name with bank, banking, banca, banco, banque or Sanpaolo as a word (LENDER) is taken for one.
  Found in the pull of BM lead parties (7 Oct 2026): MUFG Bank, Ltd (2022) and Intesa Sanpaolo S.p.A (from 11 Jul
  2023) for Kilbraur and Millennium Wind Energy, whose owners' entries ceased on 22 Dec 2022; National Westminster
  Bank Plc for Broken Cross Wind Farm (Dec 2023 to Sep 2025). The owner before the pledge is not inferred, so such a
  company has no majority controller while the lender holds; "The Banks Group Limited" is not a lender.
- The group is a name, not owners with shares: a controller that is itself a joint venture resolves by its name
  only (company_owners.csv is not read here).
- Numbers are matched as company_number() writes them, so "9171944" (as a spreadsheet keeps it) finds 09171944.

Personal data: the snapshots hold no individual's name, address or birth date (the puller's filter), and the table
names no individual either, whatever a snapshot holds: controller_name and controller_number are filled only for a
corporate or legal-person entry that has a name, carries none of a person's fields (date_of_birth, name_elements,
nationality, country_of_residence) and whose name does not start with a personal title (TITLES: Mr, Mrs, Ms, Miss,
Mx, Dr, Prof, Professor, Rev, Revd, Reverend, Sir, Dame, Lord, Lady, Baron, Baroness, Hon, Honourable, and The
(Rt) Hon or Rt Hon before a name) unless the name ends in a legal form (LEGAL_FORMS: Limited, Ltd, plc or P.L.C.,
LLP or L.L.P., LP, Company, Corporation, Inc, Incorporated), which no person's name does: "Sir Galahad Holdings
Limited" stays a company; a sole trader's trading name ("Mr X t/a Y Limited", "trading as") stays a person's. The title test still catches a company or body whose name starts with a title and does
not end in one of those forms: "Lord Holdings", "Dr Foster Energy" without a legal form, a foreign form ("Baron
Holding GmbH"), a body ("The Honourable Society of ..."), or a name with words after its legal form ("Lord Holdings
Limited (in liquidation)"). Such an entry is kept nameless and its chain stops there, the price of never naming a
person by mistake. Warnings print company names and numbers only.

Usage (lookups; the puller and the build have their own command lines):
  from gbpowerdata.common import company_control as cc
  cc.group_by_control("09171944", "2024-12-31")                    # (group, "ch_psc"), or ("", "")
  cc.group_by_control("09171944", "2024-12-31", known_only=True)   # only a group known by alias or name
  cc.controller_at("9171944", "2024-12-31")                         # the majority controller's row, or None
  cc.company_number("SC-12345")                                     # "SC012345"
"""
from __future__ import annotations

import datetime as dt
import json
import math
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

import pandas as pd

from gbpowerdata import config as cfg

RAW_FOLDER = "companies_house"                 # data/raw/companies_house/{YYYYMMDD}/{number}.json
OUTPUT = "company_control.csv"                 # data/processed/: the table of every pull, read by the lookups
OUTPUT_STAMPED = "company_control_{stamp}.csv"     # data/processed/: build_company_control --stamp; read by no lookup
NUMBERS_FILE = "companies_house_numbers.csv"   # data/reference/: the companies to pull, hand-curated
NUMBERS_COLUMNS = ["company_number", "name", "why"]
COLUMNS = ["company_number", "company_name", "controller_kind", "controller_name", "controller_number",
           "ownership_band", "voting_band", "held_as", "notified_on", "ceased_on", "snapshot"]
DATES = ("notified_on", "ceased_on")
KINDS = ("corporate", "legal_person", "individual", "other")
CORPORATE = ("corporate", "legal_person")
CORPORATE_KINDS = ("corporate-entity", "legal-person")     # the PSC kinds' prefixes; every other kind is a person
PERSONAL_FIELDS = ("date_of_birth", "name_elements", "nationality", "country_of_residence")
TITLES = ("Mr", "Mrs", "Ms", "Miss", "Mx", "Dr", "Prof", "Professor", "Rev", "Revd", "Reverend", "Sir", "Dame",
          "Lord", "Lady", "Baron", "Baroness", "Hon", "Honourable")
LEGAL_FORMS = ("Limited", "Ltd", "plc", "P.L.C.", "LLP", "L.L.P.", "LP", "Company", "Corporation", "Inc",
               "Incorporated")
BANDS = ("25-50", "50-75", "75-100")
MAJORITY = ("50-75", "75-100")
MAX_LEVELS = 4
BASIS = "ch_psc"

# Companies House's number prefixes and what each registers (the module docstring gives the sources)
PREFIXES = {
    "SC": "Scottish company", "NI": "Northern Ireland company",
    "R0": "Northern Ireland company from before partition",
    "OC": "limited liability partnership, England and Wales", "SO": "limited liability partnership, Scotland",
    "NC": "limited liability partnership, Northern Ireland",
    "LP": "limited partnership, England and Wales", "SL": "limited partnership, Scotland",
    "NL": "limited partnership, Northern Ireland", "SG": "Scottish qualifying partnership",
    "FC": "overseas company", "SF": "overseas company registered in Scotland before 1 October 2009",
    "NF": "overseas company registered in Northern Ireland before 1 October 2009",
    "BR": "UK establishment of an overseas company", "OE": "registered overseas entity",
    "AC": "assurance company, England and Wales", "SA": "assurance company, Scotland",
    "NA": "assurance company, Northern Ireland",
    "ZC": "unregistered company (not formed under the Companies Acts), England and Wales",
    "SZ": "unregistered company, Scotland", "NZ": "unregistered company, Northern Ireland",
    "GE": "European Economic Interest Grouping, England and Wales",
    "GS": "European Economic Interest Grouping, Scotland",
    "GN": "European Economic Interest Grouping, Northern Ireland",
    "SE": "European company (Societas Europaea), England and Wales", "ES": "European company, Scotland",
    "EN": "European company, Northern Ireland",
    "IP": "industrial and provident (registered) society, England and Wales",
    "SP": "industrial and provident (registered) society, Scotland",
    "NP": "industrial and provident society or credit union, Northern Ireland", "NO": "credit union, Northern Ireland",
    "IC": "investment company with variable capital, England and Wales",
    "SI": "investment company with variable capital, Scotland",
    "NV": "investment company with variable capital, Northern Ireland",
    "RC": "Royal Charter company, England and Wales", "SR": "Royal Charter company, Scotland",
    "NR": "Royal Charter company, Northern Ireland",
    "CE": "charitable incorporated organisation, England and Wales",
    "CS": "Scottish charitable incorporated organisation",
    "FE": "further education or sixth form college corporation", "PC": "protected cell company",
}
SOCIETIES = ("IP", "SP", "NP")                 # whose numbers keep their FCA letters: IP00525R, SP0218RS
NUMBER_WORDS = ("NO", "NR")                    # "No." and "Nr." before a number in a filing: the word number
# one- or two-letter words before a number that are no prefix (EW: England and Wales; CH: Companies House)
NOT_PREFIXES = NUMBER_WORDS + ("CO", "UK", "GB", "EW", "CH")

# every digit class is [0-9]: \d would take other scripts' digits too (Arabic-Indic, full-width), which no register
# writes and which would then be zero-padded into a "number"
_STAMP = re.compile(r"[0-9]{8}")                                    # fullmatch
_FLOAT = re.compile(r"[0-9]+\.0")                                   # a number read as a float, "9171944.0"
_SEPARATED = re.compile(r"(R0|[A-Z]{1,2})[.\-:/#]+(?=[0-9])")      # "SC-", "SC/", "R0-" at the start, before digits
_DIGITS = re.compile(r"[0-9]{1,8}")
_PREFIX = "|".join(PREFIXES)
_PREFIXED = re.compile(r"(" + _PREFIX + r")([0-9]{1,6})")
_SOCIETY = re.compile(r"(" + "|".join(SOCIETIES) + r")([0-9]{1,5})([A-Z]{1,2})")
# in text (upper case, white space collapsed): a known prefix joined to its digits by at most one separator
_PREFIXED_IN_TEXT = re.compile(r"(?<![A-Z0-9])(" + _PREFIX + r")(\s?[.\-:/#]?\s?)"
                               r"([0-9]{6}|[0-9]{5}[A-Z]|[0-9]{4}[A-Z]{2})(?![A-Z0-9])")
_RUN_IN_TEXT = re.compile(r"(?<![A-Z0-9])[0-9]{6,8}(?![A-Z0-9])")
# "XY-", "SC: " or "AB/" right before a run of digits: any separator; not "E & W" (England and Wales)
_JOINED = re.compile(r"(?<![A-Z0-9&])(?<!&\s)([A-Z]{1,2})[^A-Z0-9]+\Z")
_NUMBER_WORD = re.compile(r"(?:" + "|".join(NUMBER_WORDS) + r")\b\W")   # "No 123456", "No.123456" at the start
# a title as a whole word at the start: "Mr", "MRS.", "Dr ", "The Rt Hon"; not "Drax", "Ladybird", "Sirius", "Honda"
_HON = r"(?:(?:rt|right)\.?\s+)?hon(?:ourable)?"
_TITLE = re.compile(r"^\W*(?:the\s+" + _HON + "|" + _HON + "|" + "|".join(TITLES) + r")\b", re.I)
# a sole trader's trading name ("Mr X t/a Y Ltd") is a person's whatever it ends in
_TRADING_AS = re.compile(r"\b(?:t\s*/\s*a|trading\s+as)\b", re.I)
# a legal form as the last word: "Limited", "Ltd.", "PLC", "p.l.c.", "L.L.P."; not "LP" spelt with full stops
_LEGAL_FORM = re.compile(r"\b(?:limited|ltd|p\.?l\.?c|l\.?l\.?p|lp|company|corporation|inc|incorporated)\W*\Z",
                         re.I)
# Northern Ireland, however it is abbreviated, is the UK's: it is taken out before Ireland is looked for
_NORTHERN_IRELAND = re.compile(r"\b(?:northern|n\.?)[\s-]*ireland\b", re.I)
# a UK registration: a nation, the state, Companies House; not New England, New South Wales, New Scotland or New
# Britain (the text is collapsed first, so "New  England" is caught too); "GB" only alone
_UK = re.compile(_NORTHERN_IRELAND.pattern + r"|(?<!new )\bengland\b|(?<!new south )\bwales\b|(?<!new )\bscotland\b"
                 r"|\bunited kingdom\b|(?<!new )\bbritain\b|\bcompanies house\b|\buk\b|(?<![a-z])u\.k\b\.?"
                 r"|^\s*gb\s*$", re.I)
# never the UK, whatever sits beside it: Gibraltar (whose registry is also called Companies House), the Crown
# Dependencies, Ireland and its registry, and the overseas territories with registries of their own
_NOT_UK = re.compile(r"\b(?:gibraltar|jersey|guernsey|alderney|sark|isle of man|i\.?o\.?m|manx|channel islands?"
                     r"|ireland|eire|irish|cro|companies registration office"
                     r"|caymans?|bermuda|virgin islands|bvi|anguilla|montserrat|caicos|falklands?"
                     r"|(?:st|saint)\W*helena|ascension|tristan da cunha|pitcairn)\b", re.I)
_BAND = r"-(25-to-50|50-to-75|75-to-100)-percent"
# shares; an LLP's or a partnership's right to share in the surplus assets is its equivalent
_OWNERSHIP = re.compile(r"^(?:ownership-of-shares|right-to-share-surplus-assets|part-right-to-share-surplus-assets)"
                        + _BAND)
_VOTING = re.compile(r"^voting-rights" + _BAND)
# a controller holding for someone else, by its name ("Womble Bond Dickinson (Trust Corporation) Limited", "HSBC
# Corporate Trustee Company (UK) Limited"); "Harmony Energy Income Trust" is not one
TRUSTEE = re.compile(r"\b(?:trustees?|trust corporation|nominees?|custodians?)\b", re.I)
# a lender holding the shares as security, by its name ("MUFG Bank, Ltd", "Intesa Sanpaolo S.p.A", "National
# Westminster Bank Plc"); "The Banks Group Limited" is not one
LENDER = re.compile(r"\b(?:bank|banking|banca|banco|banque|sanpaolo)\b", re.I)


# ---------------------------------------------------------------------------- numbers and dates
def company_number(value) -> str:
    """A Companies House number as the register writes it, eight characters of text (Numbers in the module
    docstring): digits zero-padded ("9171944", as a spreadsheet keeps it, is "09171944"); a known prefix (PREFIXES)
    with six digits, zero-padded, a separator after it dropped ("SC12345" is "SC012345", "SC-123456" "SC123456");
    a registered society's IP, SP or NP with the digits and letters of its FCA number, padded to eight characters
    ("IP525R" is "IP00525R"). "" for a blank, NaN, a number of zeros only, or anything else."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    s = re.sub(r"\s+", "", str(value)).strip("'\"").upper()
    if _FLOAT.fullmatch(s):
        s = s[:-2]
    if m := _SEPARATED.match(s):                 # "SC-123456", "SC.123456" (white space is gone already)
        s = m[1] + s[m.end():]
    if _DIGITS.fullmatch(s):
        prefix, digits, suffix = "", s.zfill(8), ""
    elif m := _PREFIXED.fullmatch(s):
        prefix, digits, suffix = m[1], m[2].zfill(6), ""
    elif (m := _SOCIETY.fullmatch(s)) and len(m[2]) + len(m[3]) <= 6:
        prefix, digits, suffix = m[1], m[2].zfill(6 - len(m[3])), m[3]
    else:
        return ""
    return prefix + digits + suffix if digits.strip("0") else ""     # a number of zeros only is none


# group_by_control's first parameter is named company_number, which hides the function in its body
_normal = company_number


def valid_stamp(stamp) -> str:
    """A pull date as its folder is named, YYYYMMDD and a real date; ValueError otherwise (a folder named any other
    way would never be read)."""
    s = str(stamp)
    try:
        if not _STAMP.fullmatch(s):
            raise ValueError
        dt.datetime.strptime(s, "%Y%m%d")
    except ValueError:
        raise ValueError(f"a pull date is YYYYMMDD, such as 20261006, not {stamp!r}") from None
    return s


# ---------------------------------------------------------------------------- one PSC entry
def is_corporate(kind) -> bool:
    """A corporate entity or legal person (never a natural person), by its PSC kind."""
    return str(kind or "").startswith(CORPORATE_KINDS)


def looks_personal(item: dict) -> bool:
    """True for an entry that carries an individual's details, whatever its kind says: any of PERSONAL_FIELDS, or
    a name that starts with a personal title (TITLES, The (Rt) Hon) and does not end in a legal form (LEGAL_FORMS),
    or does but names a sole trader's trading name ("t/a", "trading as").
    Such an entry is kept and read as a person's (Personal data in the module docstring)."""
    if any(k in item for k in PERSONAL_FIELDS):
        return True
    name = str(item.get("name") or "")
    return bool(_TITLE.match(name)) and (not _LEGAL_FORM.search(name) or bool(_TRADING_AS.search(name)))


def _flat(value) -> str:
    """A place or country as the tests read it: accents dropped (Eire with its acute accent is "Eire"), white space
    and hyphens collapsed to single spaces ("New  England" is "New England", "Isle-of-Man" "Isle of Man")."""
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[\s\-]+", " ", text).strip()


def _not_uk(text: str) -> bool:
    return bool(_NOT_UK.search(_NORTHERN_IRELAND.sub(" ", text)))


def _number_in_text(text: str) -> str:
    """A Companies House number in a registration text (upper case, white space collapsed): a known prefix joined to
    its digits first, then a run of six to eight digits with no prefix joined to it ("" if neither)."""
    for m in _PREFIXED_IN_TEXT.finditer(text):
        if m[2] and m[1] in NUMBER_WORDS:      # "No. 123456": the word number, not the prefix NO
            continue
        if number := company_number(m[1] + m[3]):
            return number
    for m in _RUN_IN_TEXT.finditer(text):
        joined = _JOINED.search(text, 0, m.start())
        if joined and joined[1] not in NOT_PREFIXES:   # "XY-123456": an unknown or mistyped prefix, not 00123456
            continue
        if number := company_number(m[0]):
            return number
    return ""


def uk_number(item: dict) -> str:
    """The Companies House number of a corporate PSC registered in the UK; "" for any other entry.

    The identification's country_registered decides where it is filled, place_registered only where it is blank;
    it must name a UK nation, the United Kingdom, Britain or Companies House, and neither field may name Gibraltar,
    a Crown Dependency, Ireland or an overseas territory with a registry of its own, whatever stands beside it:
    "Companies House" with a foreign country is not the UK's register (UK registrations in the module docstring
    lists every name). The number is registration_number as company_number reads it, else the one its text gives
    ("Company number SC 449688"). An entry with a person's details (looks_personal) has no number."""
    if not is_corporate(item.get("kind")) or looks_personal(item):
        return ""
    ident = item.get("identification")
    if not isinstance(ident, dict):
        return ""
    country = _flat(ident.get("country_registered"))
    place = _flat(ident.get("place_registered"))
    if _not_uk(country) or _not_uk(place) or not _UK.search(country or place):
        return ""
    raw = " ".join(str(ident.get("registration_number") or "").upper().split())
    if not _NUMBER_WORD.match(raw) and (number := company_number(raw)):
        return number
    return _number_in_text(raw)          # "Company number 09171944 (England And Wales)"


def controller_kind(kind) -> str:
    """corporate, legal_person, individual or other, from a PSC kind (the -beneficial-owner kinds of overseas
    entities included)."""
    k = str(kind or "")
    if k.startswith("corporate-entity"):
        return "corporate"
    if k.startswith("legal-person"):
        return "legal_person"
    if k.startswith("individual"):
        return "individual"
    return "other"


def _band(natures, pattern: re.Pattern) -> str:
    found = [m[1].replace("-to-", "-") for n in (natures or []) if (m := pattern.match(str(n)))]
    return max(found, key=BANDS.index) if found else ""


def ownership_band(natures) -> str:
    """"25-50", "50-75" or "75-100" from a PSC's natures_of_control (shares, or an LLP's surplus assets); ""."""
    return _band(natures, _OWNERSHIP)


def voting_band(natures) -> str:
    """"25-50", "50-75" or "75-100" from a PSC's natures_of_control (voting rights); ""."""
    return _band(natures, _VOTING)


def held_as(natures) -> str:
    """"trust" where every nature of control that gives a share or vote band is held as a trustee (-as-trust); ""."""
    banded = [str(n) for n in natures or [] if _OWNERSHIP.match(str(n)) or _VOTING.match(str(n))]
    return "trust" if banded and all(n.endswith("-as-trust") for n in banded) else ""


# ---------------------------------------------------------------------------- one snapshot
def known_names(record: dict) -> list[str]:
    """A company snapshot's name and previous names (the profile's previous_company_names), as given."""
    names = [record.get("company_name")]
    names += [p.get("name") for p in record.get("previous_company_names") or [] if isinstance(p, dict)]
    return [str(n).strip() for n in names if str(n or "").strip()]


def name_mismatch(psc_name, record: dict) -> bool:
    """True when the snapshot `record` of a company has a company_name and neither it nor any previous name is
    `psc_name` (compared by gbpowerdata.common.companies.norm); False where there is no name to check against."""
    from gbpowerdata.common import companies as co    # lazily: companies imports this module the same way
    if not str(record.get("company_name") or "").strip():
        return False
    return co.norm(psc_name) not in {co.norm(n) for n in known_names(record)}


def rows(record: dict, snapshot: str = "") -> list[dict]:
    """The table's rows for one snapshot (dates as text; `snapshot` its pull date). A name and number only for a
    corporate or legal-person entry with a name and nothing of a person's (looks_personal); any other such entry
    is "other"."""
    number = company_number(record.get("company_number"))
    name = str(record.get("company_name") or "").strip()
    out = []
    for item in (record.get("persons_with_significant_control") or {}).get("items") or []:
        kind = controller_kind(item.get("kind"))
        controller = str(item.get("name") or "").strip()
        if kind in CORPORATE and (not controller or looks_personal(item)):
            kind = "other"                       # never named, never followed, never a controller
        named = kind in CORPORATE
        natures = item.get("natures_of_control") or []
        out.append({"company_number": number, "company_name": name, "controller_kind": kind,
                    "controller_name": controller if named else "",
                    "controller_number": uk_number(item) if named else "",
                    "ownership_band": ownership_band(natures), "voting_band": voting_band(natures),
                    "held_as": held_as(natures),
                    "notified_on": str(item.get("notified_on") or ""), "ceased_on": str(item.get("ceased_on") or ""),
                    "snapshot": snapshot})
    return out


# ---------------------------------------------------------------------------- the table
def raw_root() -> Path:
    """data/raw/companies_house/, where the puller writes its pull-date folders."""
    return cfg.raw_dir() / RAW_FOLDER


def snapshot_files(stamp: str | None = None) -> dict[str, Path]:
    """Company number -> its newest snapshot: the latest pull-date folder that holds it (up to `stamp`, YYYYMMDD,
    where given; ValueError for a stamp of another form)."""
    stamp = None if stamp is None else valid_stamp(stamp)
    root = raw_root()
    if not root.is_dir():
        return {}
    folders = sorted(p for p in root.iterdir()
                     if p.is_dir() and _STAMP.fullmatch(p.name) and (stamp is None or p.name <= stamp))
    files: dict[str, Path] = {}
    for folder in folders:                       # oldest first, so a later pull of a company replaces an earlier one
        for f in sorted(folder.glob("*.json")):
            if number := company_number(f.stem):
                files[number] = f
    return files


def _typed(table: pd.DataFrame) -> pd.DataFrame:
    """A control table however it was read (from control_table(), or the CSV with or without dtype=str): text
    columns as text with "" for blank, numbers as eight-character text, dates parsed."""
    t = table.reindex(columns=COLUMNS).copy()
    for c in COLUMNS:
        if c not in DATES:
            t[c] = t[c].fillna("").astype(str).str.strip()
    for c in ("company_number", "controller_number"):
        t[c] = t[c].map(company_number)
    t["snapshot"] = t["snapshot"].str.replace(r"\.0$", "", regex=True)     # read as a number without dtype=str
    for c in DATES:
        if not pd.api.types.is_datetime64_any_dtype(t[c]):
            t[c] = pd.to_datetime(t[c].astype("string").str.strip().str[:10], format="%Y-%m-%d", errors="coerce")
    return t


def _sorted(t: pd.DataFrame) -> pd.DataFrame:
    return t.sort_values(["company_number", "notified_on", "controller_kind", "controller_name"], kind="stable",
                         na_position="first").reset_index(drop=True)


def snapshot_table(stamp: str | None = None) -> pd.DataFrame:
    """One row per company and PSC from the newest snapshot of each company (up to `stamp`), dates parsed, with the
    name check: a controller_number whose own snapshot gives another name is blanked, with a WARNING. Empty, with
    the columns, when there is no snapshot. This is what build_company_control writes."""
    files = snapshot_files(stamp)
    records = {n: json.loads(p.read_text(encoding="utf-8")) for n, p in files.items()}
    out: list[dict] = []
    for n in sorted(records):
        out += rows(records[n], snapshot=files[n].parent.name)
    for r in out:
        n = r["controller_number"]
        if n and n in records and name_mismatch(r["controller_name"], records[n]):
            print(f"  WARNING: {r['company_number']} gives its controller {r['controller_name']!r} the number {n}, "
                  f"which Companies House gives to {records[n].get('company_name')!r} (previous names included): "
                  "the number is left blank, so the chain stops there", flush=True)
            r["controller_number"] = ""
    return _sorted(_typed(pd.DataFrame(out, columns=COLUMNS)))


def _pulls() -> dict[str, list[Path]]:
    """Pull date -> the snapshot files of its folder (folders named YYYYMMDD only)."""
    root = raw_root()
    if not root.is_dir():
        return {}
    pulls: dict[str, list[Path]] = {}
    for f in root.glob("*/*.json"):
        if _STAMP.fullmatch(f.parent.name):
            pulls.setdefault(f.parent.name, []).append(f)
    return pulls


def _has_entries(path: Path) -> bool:
    """True when a snapshot lists a PSC entry, so it adds rows to the table (also when it cannot be read: the
    build would stop on it, so a rebuild is the right advice)."""
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return True
    return bool((record.get("persons_with_significant_control") or {}).get("items"))


def _out_of_date(path: Path, table: pd.DataFrame) -> str:
    """Why the processed table at `path` (read as `table`) may lag the snapshots on disk; "" when nothing shows it.
    Two signs: a snapshot written after the file, and a pull date later than the table's newest snapshot value
    with a snapshot that changes the table: one with PSC entries, or a newer snapshot of a company the table holds
    (which replaces that company's rows, or takes them away). The second catches a table restored or copied after
    the pulls, or written up to an earlier pull date; it skips the other pulls (companies new to the table and
    without entries), which add no rows, so their dates never reach the table (counting them would warn for good,
    rebuild or not)."""
    pulls = _pulls()
    if not pulls:
        return ""
    why = []
    built = path.stat().st_mtime
    if written := sorted(d for d, files in pulls.items() if any(f.stat().st_mtime > built for f in files)):
        why.append(f"snapshots were written after it in the pull-date folders {', '.join(written)}")
    newest = max((s for s in table["snapshot"] if s), default="")
    held = set(table["company_number"])
    for d in sorted((d for d in pulls if d > newest), reverse=True):     # the latest first, and only the latest
        if any(company_number(f.stem) in held or _has_entries(f) for f in pulls[d]):
            why.append(f"the pull of {d} changes the table, whose newest snapshot value is {newest or 'none'}")
            break
    return "; ".join(why)


def control_table(stamp: str | None = None) -> pd.DataFrame:
    """The control table, dates parsed: data/processed/company_control.csv where it exists (with a WARNING where
    the snapshots on disk show it is out of date), else snapshot_table(); with a pull date, always the snapshots up
    to it. Looking for the processed table creates data/processed/ where it is missing (gbpowerdata.config.
    processed_dir does), and writes nothing."""
    if stamp is None:
        path = cfg.processed_dir() / OUTPUT
        if path.exists():
            table = _sorted(_typed(pd.read_csv(path, dtype=str, keep_default_na=False)))
            if why := _out_of_date(path, table):
                print(f"  WARNING: {path} may be out of date ({why}); it is read as it is: rebuild it with "
                      "python -m gbpowerdata.build.build_company_control", flush=True)
            return table
    return snapshot_table(stamp)


# ---------------------------------------------------------------------------- control on a date
def index_table(table: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """A control table (control_table(), or company_control.csv read any way) typed once and split by company
    number; pass it as `table` to answer many lookups without typing the table again."""
    t = _typed(table)
    return {n: g for n, g in t.groupby("company_number", sort=False) if n}


@lru_cache(maxsize=1)
def _default_index() -> dict[str, pd.DataFrame]:
    """control_table() indexed, read once per process (clear_cache() forgets it)."""
    return index_table(control_table())


def _indexed(table) -> dict[str, pd.DataFrame]:
    if table is None:
        return _default_index()
    if isinstance(table, dict):                  # index_table() already
        return table
    return index_table(table)


def _day(when) -> pd.Timestamp:
    """The day of `when`, its time and time zone dropped (the table's dates are days); NaT for None or a blank."""
    when = pd.Timestamp(when)
    if pd.isna(when):
        return pd.NaT
    return (when.tz_localize(None) if when.tzinfo is not None else when).normalize()


def trustee(t: pd.DataFrame) -> pd.Series:
    """Rows of a controller that holds for someone else (a typed table): its bands held as a trustee (held_as
    "trust"), or a trustee's, nominee's or custodian's name (TRUSTEE)."""
    return t["held_as"].eq("trust") | t["controller_name"].str.contains(TRUSTEE, na=False)


def lender(t: pd.DataFrame) -> pd.Series:
    """Rows of a controller that holds the shares as a lender's security (a typed table): a bank's name (LENDER)."""
    return t["controller_name"].str.contains(LENDER, na=False)


def in_force(t: pd.DataFrame, when: pd.Timestamp) -> pd.Series:
    """Corporate or legal-person PSCs with a majority of the shares or votes, notified by `when` and not ceased, that
    are neither trustees nor lenders (a typed table)."""
    return (t["controller_kind"].isin(CORPORATE)
            & (t["notified_on"] <= when) & (t["ceased_on"].isna() | (t["ceased_on"] > when))
            & (t["ownership_band"].isin(MAJORITY) | t["voting_band"].isin(MAJORITY))
            & ~trustee(t) & ~lender(t))


def _controller(t: pd.DataFrame | None, when: pd.Timestamp) -> dict | None:
    """The majority controller among one company's typed rows at `when` (see controller_at)."""
    if t is None or t.empty:
        return None
    live = t[in_force(t, when)]
    if live.empty:
        return None
    rank = [max(BANDS.index(b) if b in BANDS else -1 for b in pair)
            for pair in zip(live["ownership_band"], live["voting_band"])]
    best = live.assign(_rank=rank).sort_values(["_rank", "notified_on"], ascending=False, kind="stable").iloc[0]
    return best.drop("_rank").to_dict()


def controller_at(number, when, table=None) -> dict | None:
    """The majority corporate or legal-person controller of company `number` (any form company_number reads) on
    the day of `when` (a row of the table, as a dict); None if there is none, or only individuals, trustees or
    lenders. Two at once: the larger band, then the later notification."""
    key = company_number(number)
    if not key:
        return None
    return _controller(_indexed(table).get(key), _day(when))


def _walk(key: str, day: pd.Timestamp, index: dict[str, pd.DataFrame]) -> tuple[str, str]:
    """Company `key`'s majority controllers on `day`, followed up the chain within `index` (MAX_LEVELS at most; a
    parent abroad, not verified or not pulled, or a loop, ends it): (the group of the first controller that
    gbpowerdata.common.companies.group_of places by alias or name, else ""; that group again, else the last
    controller's name without its legal form, else "")."""
    if key not in index:                         # no rows, or no table at all: nothing to import or read
        return "", ""
    from gbpowerdata.common import companies as co    # lazily: companies imports this module the same way
    seen = {key}
    last = None
    for _ in range(MAX_LEVELS):
        found = _controller(index.get(key), day)
        if found is None:
            break
        last = found
        # group_of with the name alone (no date, no number), so it never comes back here
        group, basis = co.group_of(found["controller_name"])
        if basis in ("alias", "name"):
            return group, group
        key = found["controller_number"]
        if not key or key in seen:                # a parent abroad or not verified, or a loop in the filings
            break
        seen.add(key)
    return "", co.clean(last["controller_name"]) if last is not None else ""


@lru_cache(maxsize=2 ** 16)
def _default_walk(key: str, day: pd.Timestamp) -> tuple[str, str]:
    """_walk on the default table, remembered per company and day for both modes of group_by_control (clear_cache()
    forgets it): a register is resolved year by year, so the same company and day come back many times."""
    return _walk(key, day, _default_index())


def group_by_control(company_number, when, table=None, known_only: bool = False) -> tuple[str, str]:
    """(group, "ch_psc") of company `company_number` (any form company_number() reads) on the day of `when`: its
    majority controller followed up the chain within the table to the first controller
    gbpowerdata.common.companies.group_of places by alias or name. Where no controller up the chain is so placed,
    the last controller's name without its legal form, or, with known_only=True, ("", ""). ("", "") as well when the
    company has no majority corporate controller on that day, without a date, and without a table at all (cheaply:
    no snapshot and no processed table read as an empty index, once). Answers from the default table are remembered
    per company and day (clear_cache() forgets them). The module docstring gives the order in which
    gbpowerdata.common.companies.group_of is meant to call the two modes."""
    key = _normal(company_number)
    day = _day(when)
    if not key or pd.isna(day):
        return "", ""
    known, last = _default_walk(key, day) if table is None else _walk(key, day, _indexed(table))
    group = known or ("" if known_only else last)
    return (group, BASIS) if group else ("", "")


# ---------------------------------------------------------------------------- the curated list of numbers
@lru_cache(maxsize=1)
def _listed() -> dict[str, str]:
    """data/reference/companies_house_numbers.csv: normalised name -> number; a name that two numbers share is left
    out (it names neither); empty without the file."""
    from gbpowerdata.common import companies as co
    path = cfg.reference_dir() / NUMBERS_FILE
    if not path.exists():
        return {}
    table = pd.read_csv(path, dtype=str, keep_default_na=False)
    found: dict[str, set[str]] = {}
    for name, raw in zip(table["name"], table["company_number"]):
        if (key := co.norm(name)) and (number := company_number(raw)):
            found.setdefault(key, set()).add(number)
    return {k: next(iter(v)) for k, v in found.items() if len(v) == 1}


def number_of(name) -> str:
    """The Companies House number data/reference/companies_house_numbers.csv lists for a company name, compared by
    gbpowerdata.common.companies.norm ("" if none): the number of a company whose register gives none."""
    from gbpowerdata.common import companies as co
    return _listed().get(co.norm(name), "")


def clear_cache() -> None:
    """Forget the default table, group_by_control's answers from it and the list of numbers (after a new pull or
    build, after editing company_groups.csv, or in tests)."""
    _default_index.cache_clear()
    _default_walk.cache_clear()
    _listed.cache_clear()
