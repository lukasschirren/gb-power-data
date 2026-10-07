"""Pull Companies House's persons with significant control (PSC) of chosen companies into data/raw/companies_house/.

The companies are those listed in data/reference/companies_house_numbers.csv, or named with --numbers.

Why: most CfD counterparties, many RO holders and some BM lead parties (a wind farm's own company that trades it,
"Kilbraur Wind Energy") are special-purpose project companies ("Glendye Wind Farm Limited") that no register links
to a group, so the ownership tables (gbpowerdata.build.build_ownership) resolve them to themselves (basis "self").
Companies House holds, for every UK company, the people and companies with
significant control over it, each with the date the control began and, once it ends, the date it ceased. A
corporate PSC with a majority of the shares or votes is the company's parent, and the dates show when control
changed hands. gbpowerdata.build.build_company_control turns the snapshots into a dated table, and
gbpowerdata.common.company_control reads it; that module also holds the rules this puller applies (company
numbers, UK registration, the name check, the personal-data test), so the puller and the table agree.

Source: Companies House Public Data API, https://api.company-information.service.gov.uk, with a free REST key from
the Companies House Developer Hub (https://developer.company-information.service.gov.uk), sent by HTTP basic auth as
the user name with an empty password. Two resources per company:
  GET /company/{number}                                   the profile; kept: company_number, company_name,
                                                          company_status, date_of_creation, previous_company_names
                                                          (each with effective_from and ceased_on)
  GET /company/{number}/persons-with-significant-control  the PSC list, paged by items_per_page and start_index;
                                                          the documentation gives no default or maximum, so pages
                                                          of PAGE_SIZE are asked for and read until total_results
                                                          (a page without it: until a page brings no new entry)
What the documentation says (developer-specs.company-information.service.gov.uk, read 6 Oct 2026): the list counts
active_count and ceased_count, so ceased PSCs are in it; register_view=true would show "only PSCs which are active or
were terminated during election period" and is left at its default, false. An entry has a kind
(individual-person-with-significant-control, corporate-entity-person-with-significant-control, legal-person-...,
super-secure-..., and the *-beneficial-owner kinds of the register of overseas entities; told apart here by their
first words), natures_of_control (codes such as
ownership-of-shares-75-to-100-percent, explained in Companies House's api-enumerations, psc_descriptions.yml),
notified_on, ceased_on and, for a corporate entity or legal person, identification (legal_form, legal_authority,
place_registered, country_registered, registration_number). A company without a PSC list answers 404 (kept as
"found": false). Rate limit: 600 requests per five minutes, then HTTP 429 for the rest of the window, so requests
are paced at one per INTERVAL_S and a 429 is waited out.
Licence: none is stated. Companies House "imposes no rules or requirements on how the information on the public
register is used" and requires credit where its guidance, website, publications or statistical tables are used
(gov.uk, "Our public task, copyright and Crown copyright",
https://www.gov.uk/government/publications/companies-house-accreditation-to-information-fair-traders-scheme/public-task-copyright-and-crown-copyright;
the register is public under the Companies Act 2006); its reusers are "responsible for complying with any
applicable data protection, copyright and other legislation and regulations" (gov.uk, "Companies House data
products", https://www.gov.uk/guidance/companies-house-data-products): hence the filter below.

Personal data: an individual PSC is listed with name, service address, month and year of birth, nationality and
country of residence. None of that is written. Every entry passes a whitelist of fields (filter_psc), so a field
Companies House adds later is dropped as well:
  corporate entity, legal person     name, kind, identification (its five fields), natures_of_control, notified_on,
                                     ceased_on
  anything else: an individual, a    kind, natures_of_control, notified_on, ceased_on only: no name, name_elements,
  super-secure entry, a kind not     address, date_of_birth, nationality, country_of_residence, links (whose ids
  known here                         lead back to the person) or identity-verification details
Defence in depth: whatever its kind says, an entry is kept as a person's (the second row) when it carries any of a
person's fields (date_of_birth, name_elements, nationality, country_of_residence) or its name starts with a personal
title (Mr, Mrs, Ms, Miss, Mx, Dr, Prof, Professor, Rev, Revd, Reverend, Sir, Dame, Lord, Lady, Baron, Baroness, Hon,
Honourable, The (Rt) Hon) and does not end in a legal form (Limited, Ltd, plc, LLP, LP, Company, Corporation, Inc,
Incorporated), which no person's name does: gbpowerdata.common.company_control.looks_personal. An individual filed
under a corporate kind is so never named, while "Sir Galahad Holdings Limited" is. The cost: a company or body whose
name starts with a title and does not end in such a form ("Lord Holdings", "Baron Holding GmbH", "Lord Holdings
Limited (in liquidation)") is kept nameless too, and its chain stops there.
The profile keeps its five fields only (no registered office: a small company's may be a home). Nothing personal is
printed, and the key is never printed.

--follow N also pulls the UK-registered corporate PSCs and theirs, up to N levels, ceased ones included, since the
parent before a sale dates the change. UK-registered (gbpowerdata.common.company_control.uk_number, whose module
docstring has the full rules): the identification's country_registered decides where it is filled,
place_registered only where it is blank, white space and hyphens collapsed; it must name England, Wales, Scotland,
Northern Ireland, the United Kingdom (UK, U.K.), Britain or Companies House (not New England, New South Wales, New
Scotland or New Britain), and neither field may name Gibraltar (whose registry is also called Companies House),
Jersey, Guernsey, Alderney, Sark, the Isle of Man (IOM, Manx), the Channel Islands, Ireland (Eire, Irish, its
Companies Registration Office or CRO; Northern Ireland is the UK's), or an overseas territory with a registry of
its own: the Cayman Islands, Bermuda, the (British) Virgin Islands (BVI), Anguilla, Montserrat, the Turks and Caicos
Islands, the Falkland Islands, St (Saint) Helena, Ascension, Tristan da Cunha, Pitcairn. A foreign parent is not on
the register and ends the chain.
Each followed parent is checked by name: where none of the PSC entries that led to it gives the name Companies
House gives it, today's or a previous one (compared by gbpowerdata.common.companies.norm), a mistyped registration
number has most likely led to a stranger, so the parent's snapshot is still written, with "not_followed" saying
why, and its own PSCs are not followed. A level is judged only once all of it has been fetched, by every entry that
names the parent in the companies followed so far, its own level's included, so one entry with a wrong name does
not stop a parent that another company of the same level names rightly (a snapshot whose judgement is certain is
written at once; one that waits is written when its level is done). A company listed or named with --numbers is
always followed. A parent stopped at its level stays stopped for the rest of the run, even where a company of a
later level names it rightly (its snapshot keeps the view of the run that wrote it). build_company_control makes the
same check and blanks such a number in the table.
"not_followed" records the judgement of the run that wrote the snapshot, by the entries that reached it in that
run: a later run the same day reads the snapshot back, judges the company afresh by its own entries and never
rewrites the file, so a snapshot without the field may be stopped in that run, and one with it followed.

Gotchas:
- notified_on is the date the company gives for when the PSC became registrable (form PSC01: "Date that individual
  became a registrable person"); the API documents it as the date Companies House was notified. Registers began on
  6 April 2016, so control held before then shows as 6 April 2016. Companies House does not check the dates.
- A corporate PSC is a "relevant legal entity": the first company up the chain that keeps its own PSC register or
  has shares traded on a regulated market (Companies Act 2006, Part 21A). An unlisted foreign holding company is
  skipped, and whoever is above it is recorded instead.
- Company numbers are eight characters, kept as text: digits zero-padded (the CfD register's "9171944" is
  09171944), one of Companies House's prefixes (SC Scotland, NI Northern Ireland, OC/SO/NC limited liability
  partnerships, ...; company_control.PREFIXES, from its URI Customer Guide and forum, and BR) with six digits, a registered
  society's IP/SP/NP with its FCA number's digits and letters (IP00525R): gbpowerdata.common.company_control.
  company_number, the one normaliser used everywhere. An unknown prefix is no number, so it is never pulled.
- A company with only statements ("no registrable person", "PSC exists but not identified") has no entries; the
  statements are not pulled.
- A PSC list that ends before its total_results (a page missing or served twice), or that gives no total_results
  and still brings new entries after MAX_PAGES pages, raises IncompleteList, and no snapshot of that company is
  written that day: snapshots are never overwritten, so a partial list would hide a controller for good, while a
  second run retries the company. The run goes on with the other companies and names the incomplete ones in a
  WARNING at the end. Without total_results nothing can tell a page served twice from the end of the list; the
  documentation lists total_results in every list, so this is a fallback.
- A snapshot folder is named by its pull date, YYYYMMDD (today's; pull(stamp=...) takes another, checked, since
  the build reads only folders so named).
- The key file may start with a byte-order mark (Notepad writes one): it is read as utf-8-sig and stripped.

Output (one folder per pull date, never overwritten; a company already pulled that day is read back, not pulled
again): data/raw/companies_house/{YYYYMMDD}/{number}.json with the profile's fields,
"persons_with_significant_control": {found, total_results, active_count, ceased_count, items} (the counts of the
first page; None where it gave none) and, for a followed parent whose name matched none of the PSC entries that led
to it in the run that wrote it, "not_followed": {reason, psc_of (those companies' numbers), psc_names (the corporate
names those entries give)}.

Usage (the key from CH_API_KEY, else data/reference/companies_house_token.txt, gitignored):
  python -m gbpowerdata.pull.companies_house_pull                               # every company in the reference list
  python -m gbpowerdata.pull.companies_house_pull --follow 2                    # and their UK parents, two levels up
  python -m gbpowerdata.pull.companies_house_pull --numbers 09171944 SC449688   # only these
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
from pathlib import Path

import pandas as pd
import requests

from gbpowerdata import config as cfg
from gbpowerdata.common.company_control import (NUMBERS_FILE, RAW_FOLDER, company_number, is_corporate,
                                                looks_personal, name_mismatch, uk_number, valid_stamp)

API = "https://api.company-information.service.gov.uk"
KEY_ENV = "CH_API_KEY"
TOKEN_FILE = "companies_house_token.txt"
PAGE_SIZE = 100
MAX_PAGES = 100          # 10,000 entries: far beyond any company, a stop should paging ever misbehave
INTERVAL_S = 0.55       # 600 requests per five minutes is one per 0.5 s; the margin absorbs clock jitter
WINDOW_S = 300
PROFILE_FIELDS = ("company_number", "company_name", "company_status", "date_of_creation", "previous_company_names")
CORPORATE_FIELDS = ("name", "kind", "identification", "natures_of_control", "notified_on", "ceased_on")
NATURAL_FIELDS = ("kind", "natures_of_control", "notified_on", "ceased_on")
IDENTIFICATION_FIELDS = ("country_registered", "legal_authority", "legal_form", "place_registered",
                         "registration_number")


class KeyMissing(RuntimeError):
    """No Companies House API key in the environment or in data/reference/."""


class IncompleteList(RuntimeError):
    """A PSC list that could not be read whole (it ended before its total_results, or still brought new entries
    after MAX_PAGES pages): nothing is written for that company that day."""


def out_dir() -> Path:
    return cfg.raw_dir() / RAW_FOLDER


def listed_numbers() -> list[str]:
    """The companies to pull: data/reference/companies_house_numbers.csv, numbers normalised, in file order."""
    path = cfg.reference_dir() / NUMBERS_FILE
    if not path.exists():
        raise FileNotFoundError(f"{path} is missing: list the companies there, or name them with --numbers")
    table = pd.read_csv(path, dtype=str, keep_default_na=False)
    numbers = [company_number(n) for n in table["company_number"]]
    if bad := [raw for raw, n in zip(table["company_number"], numbers) if not n]:
        print(f"  WARNING: not company numbers, skipped: {bad}")
    return list(dict.fromkeys(n for n in numbers if n))


# ---------------------------------------------------------------------------- personal data
def filter_psc(item: dict) -> dict:
    """One PSC entry as it is written: a corporate entity or legal person with CORPORATE_FIELDS (identification
    with its five fields); anything else, an individual above all, with NATURAL_FIELDS only, and so is any entry
    that carries a person's details or title whatever its kind (looks_personal)."""
    if not is_corporate(item.get("kind")) or looks_personal(item):
        return {k: item[k] for k in NATURAL_FIELDS if k in item}
    out = {k: item[k] for k in CORPORATE_FIELDS if k in item and k != "identification"}
    if isinstance(ident := item.get("identification"), dict):
        out["identification"] = {k: ident[k] for k in IDENTIFICATION_FIELDS if k in ident}
    return out


def filter_profile(profile: dict) -> dict:
    """The company profile's PROFILE_FIELDS (no address, officers or anything else)."""
    return {k: profile[k] for k in PROFILE_FIELDS if k in profile}


# ---------------------------------------------------------------------------- the API
def api_key() -> str:
    """The key from CH_API_KEY, else data/reference/companies_house_token.txt (a byte-order mark and surrounding
    white space removed)."""
    key = os.environ.get(KEY_ENV, "").strip()
    if key:
        return key
    path = cfg.reference_dir() / TOKEN_FILE
    if path.exists() and (key := path.read_text(encoding="utf-8-sig").strip()):
        return key
    raise KeyMissing(f"No Companies House API key: set {KEY_ENV} or put the key in {path} (gitignored). A free REST "
                     "key comes from https://developer.company-information.service.gov.uk")


class Api:
    """A paced Companies House session: at most one request per `interval` seconds, a 429 waited out (Companies
    House refuses every request for the rest of its five-minute window), connection errors and 5xx retried.
    get() returns the JSON, or None for a 404."""

    def __init__(self, key: str, interval: float = INTERVAL_S):
        self.session = requests.Session()
        self.session.auth = (key, "")          # the key is the user name, the password is empty
        self.interval = interval
        self.last = 0.0
        self.calls = 0

    def _pace(self) -> None:
        wait = self.last + self.interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self.last = time.monotonic()

    @staticmethod
    def _window_left(r: requests.Response) -> float:
        """Seconds to the end of the rate-limit window: the X-Ratelimit-Reset header where sent (undocumented, so
        read as a Unix time if it looks like one, else as seconds), else a minute; between 1 s and the window."""
        try:
            reset = float(r.headers["X-Ratelimit-Reset"])
        except (KeyError, ValueError):
            return 60.0
        return min(max(reset - time.time() if reset > 1e9 else reset, 1.0), WINDOW_S)

    def get(self, path: str, params: dict | None = None, tries: int = 7) -> dict | None:
        for i in range(tries):
            self._pace()
            self.calls += 1
            try:
                r = self.session.get(API + path, params=params, timeout=60)
            except (requests.ConnectionError, requests.Timeout):
                if i == tries - 1:
                    raise
                time.sleep(2 ** i)
                continue
            if r.status_code == 404:
                return None
            if r.status_code == 401:
                raise KeyMissing(f"Companies House refused the key (HTTP 401): check {KEY_ENV} or "
                                 f"data/reference/{TOKEN_FILE} (a REST key, not a streaming key)")
            if r.status_code == 429 or (r.status_code >= 500 and i < tries - 1):
                time.sleep(self._window_left(r) if r.status_code == 429 else 2 ** i)
                continue
            r.raise_for_status()
            return r.json()
        raise RuntimeError(f"companies_house_pull: {path} still refused after {tries} tries")


def _total(page: dict) -> int | None:
    """A page's total_results as a number; None where it gives none (or not a number)."""
    try:
        return int(page["total_results"])
    except (KeyError, TypeError, ValueError):
        return None


def psc_list(api, number: str) -> dict:
    """A company's whole PSC list, ceased entries included, page by page, unfiltered: {found, total_results,
    active_count, ceased_count, items} (the counts as the first page gives them). found is False where Companies
    House has no list (404). The pages are read until the entries read reach total_results (the largest any page
    gives), or, while no page gives one, until a page brings no new entry or no page comes. IncompleteList when
    fewer entries were read than a total_results says there are, or when MAX_PAGES pages still bring new entries."""
    items: list[dict] = []
    first = None
    total = None
    seen: set[str] = set()
    for _ in range(MAX_PAGES):
        page = api.get(f"/company/{number}/persons-with-significant-control",
                       {"items_per_page": PAGE_SIZE, "start_index": len(items)})
        if page is None:
            break
        if first is None:
            first = page
        new = []
        for item in page.get("items") or []:
            # an entry's own URL identifies it; a page served twice adds nothing
            ident = (item.get("links") or {}).get("self") or json.dumps(item, sort_keys=True)
            if ident not in seen:
                seen.add(ident)
                new.append(item)
        items += new
        if (count := _total(page)) is not None:
            total = count if total is None else max(total, count)
        if not new or (total is not None and len(items) >= total):
            break
    else:                                    # every page brought new entries, and the list is not known to be whole
        raise IncompleteList(f"{number}: the PSC list still brought new entries after {MAX_PAGES} pages "
                             f"({len(items)} entries)")
    if total is not None and len(items) < total:
        raise IncompleteList(f"{number}: the PSC list ended after {len(items)} of its {total} entries")
    counts = {k: (first or {}).get(k) for k in ("total_results", "active_count", "ceased_count")}
    return {"found": first is not None, **counts, "items": items}


def snapshot(api, number: str) -> dict | None:
    """One company as it is written (profile fields, filtered PSC list); None if Companies House does not know
    the number. IncompleteList (from psc_list) when its PSC list could not be read whole."""
    profile = api.get(f"/company/{number}")
    if profile is None:
        return None
    out = filter_profile(profile)
    out["company_number"] = company_number(out.get("company_number")) or number
    psc = psc_list(api, number)
    psc["items"] = [filter_psc(i) for i in psc["items"]]
    out["persons_with_significant_control"] = psc
    return out


def parent_links(record: dict) -> list[tuple[str, str]]:
    """(Companies House number, the name the entry gives) of a written record's UK-registered corporate PSCs,
    ceased ones included."""
    items = (record.get("persons_with_significant_control") or {}).get("items") or []
    return list(dict.fromkeys((n, str(i.get("name") or "").strip()) for i in items if (n := uk_number(i))))


def parents(record: dict) -> list[str]:
    """The Companies House numbers of a written record's UK-registered corporate PSCs, ceased ones included."""
    return list(dict.fromkeys(n for n, _ in parent_links(record)))


def not_followed(via: list[tuple[str, str]], record: dict) -> dict | None:
    """Why a parent reached through `via` [(the company whose PSC it is, the name that entry gives)] is not
    followed further: none of those names is its name or a previous one (name_mismatch). None where one is, where
    Companies House gives it no name to check, or where nothing reached it (`via` empty)."""
    if not via or not all(name_mismatch(name, record) for _, name in via):
        return None
    return {"reason": "no PSC entry that leads here gives this company's name, today's or a previous one, so its "
                      "registration number may be mistyped; its own PSCs are not followed",
            "psc_of": list(dict.fromkeys(c for c, _ in via)), "psc_names": list(dict.fromkeys(n for _, n in via))}


def judge(records: dict[str, dict], via: dict[str, list[tuple[str, str]]], listed=()) -> set[str]:
    """The companies of one level whose own PSCs are followed, once the whole level has been fetched (`records`:
    number -> snapshot). A listed company always is; a reached one unless not_followed finds that none of the
    entries naming it gives its name, counting the entries of every company followed so far, its own level's
    included. `via` (parent -> [(the company whose PSC it is, the name given)]) gains the entries of the companies
    followed here, so the next level is judged by them too. A followed company's entries can only clear another (a
    reached company has an entry already, so one more can make a match but never take one away), so the loop
    ends."""
    followed: set[str] = set()
    while True:
        now = {n for n, record in records.items() if n in listed or not_followed(via.get(n, []), record) is None}
        if now == followed:
            return followed
        for n in now - followed:
            for parent, name in parent_links(records[n]):
                via.setdefault(parent, []).append((n, name))
        followed = now


def _write(path: Path, record: dict) -> None:
    # written whole, then renamed, so an interrupted pull leaves no half file that "exists" on the next run
    part = path.with_name(path.name + ".part")
    part.write_text(json.dumps(record, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    os.replace(part, path)


def _save(path: Path, record: dict) -> None:
    """Write a new snapshot and log it. The folder is made only now, so a run without a key leaves none behind."""
    path.parent.mkdir(parents=True, exist_ok=True)
    _write(path, record)
    psc = record["persons_with_significant_control"]
    corporate = sum(is_corporate(i.get("kind")) and "name" in i for i in psc["items"])
    # a corporate kind written without its name was kept as a person's (looks_personal): counted, so that a change
    # at Companies House that made every corporate entry look personal shows at once
    as_person = sum(is_corporate(i.get("kind")) and "name" not in i for i in psc["items"])
    listed = f"{len(psc['items'])} PSC entries" if psc["found"] else "no PSC list"
    print(f"  {path.stem} {record.get('company_name', '')}: {listed} "
          f"({psc.get('ceased_count') or 0} ceased, {corporate} corporate"
          + (f", {as_person} corporate kept as a person's" if as_person else "") + f") -> {path}", flush=True)


def pull(numbers: list[str] | None = None, follow: int = 0, stamp: str | None = None, api=None) -> dict[str, str]:
    """Pull `numbers` (default: the reference list) and, with follow N, their UK corporate PSCs up to N levels,
    into the folder of pull date `stamp` (YYYYMMDD, default today); returns company number -> written (or
    existing) path. Each level is fetched whole before it is judged (judge): a followed parent whose name matches
    none of the entries that led to it is written, with not_followed, but not followed further; a company whose
    PSC list cannot be read whole is not written (see the module docstring)."""
    stamp = dt.date.today().strftime("%Y%m%d") if stamp is None else valid_stamp(stamp)
    asked = listed_numbers() if numbers is None else list(numbers)
    wanted = [company_number(n) for n in asked]
    if bad := [raw for raw, n in zip(asked, wanted) if not n]:
        print(f"  WARNING: not company numbers, skipped: {bad}")
    level = list(dict.fromkeys(n for n in wanted if n))
    listed = set(level)                             # asked for: always followed, whatever names them
    folder = out_dir() / stamp
    written: dict[str, str] = {}
    unknown: list[str] = []
    incomplete: list[str] = []
    stopped: list[str] = []
    via: dict[str, list[tuple[str, str]]] = {}     # parent -> [(the company whose PSC it is, the name given)]
    done: set[str] = set()
    for depth in range(max(follow, 0) + 1):
        records: dict[str, dict] = {}               # this level, fetched or read back, in its order
        held: dict[str, Path] = {}                  # new snapshots whose judgement waits for the whole level
        for number in level:
            done.add(number)
            path = folder / f"{number}.json"
            if path.exists():                       # raw snapshots are immutable: read back, never re-pulled
                records[number] = json.loads(path.read_text(encoding="utf-8"))
                written[number] = str(path)
                continue
            api = api or Api(api_key())
            try:
                record = snapshot(api, number)
            except IncompleteList as e:
                incomplete.append(number)
                print(f"  WARNING: {e}; nothing written for {number}", flush=True)
                continue
            if record is None:
                unknown.append(number)
                continue
            records[number] = record
            if number in listed or not_followed(via.get(number, []), record) is None:
                _save(path, record)                 # followed whatever the rest of the level shows: written now
                written[number] = str(path)
            else:
                held[number] = path                 # another company of this level may yet name it rightly
        followed = judge(records, via, listed)
        for number, path in held.items():
            if number not in followed:              # a stranger, most likely: written, but its chain not climbed
                records[number]["not_followed"] = not_followed(via.get(number, []), records[number])
            _save(path, records[number])
            written[number] = str(path)
        stopped += [n for n in records if n not in followed]
        found = [parent for n in records if n in followed for parent, _ in parent_links(records[n])]
        level = [n for n in dict.fromkeys(found) if n not in done]
        if depth < max(follow, 0) and level:
            print(f"  level {depth + 1}: {len(level)} UK-registered corporate PSC(s) to follow", flush=True)
    if unknown:
        print(f"  WARNING: not known to Companies House (HTTP 404), nothing written: {unknown}")
    if incomplete:
        print(f"  WARNING: PSC lists that could not be read whole (they ended before their total_results, or still "
              f"brought new entries after {MAX_PAGES} pages), nothing written (pull them again): {incomplete}")
    if stopped:
        print(f"  WARNING: parents whose name matches none of the PSC entries judged at their level (a company of a "
              f"later level naming one rightly does not reopen it in this run), not followed further: {stopped}")
    calls = getattr(api, "calls", 0)
    print(f"  {len(written)} companies in {folder} ({calls} requests)")
    return written


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--numbers", nargs="+", metavar="NUMBER",
                    help=f"company numbers to pull instead of data/reference/{NUMBERS_FILE}")
    ap.add_argument("--follow", type=int, default=0, metavar="N",
                    help="also pull the UK-registered corporate PSCs and theirs, up to N levels")
    a = ap.parse_args(argv)
    try:
        pull(a.numbers, follow=a.follow)
    except KeyMissing as e:
        print(f"companies_house_pull: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
