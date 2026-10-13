"""NESO's frequency response and reserve results by unit and delivery period, in one schema, by year
-> data/processed/ancillary_by_unit_{year}.csv.

Why: what the system operator buys from a unit, in MW and for how long, is both income (a battery's largest source
in 2021-2022) and capacity the unit cannot sell elsewhere in those hours (a model of the day-ahead market needs it
as an input: the MW a battery holds for response is not offered in the auction). NESO publishes it per unit, but in
four schemas over the years (gbpowerdata.pull.ancillary_pull); this table puts them into one.

Sources (data/raw/neso/ancillary/, gbpowerdata.pull.ancillary_pull; NESO Open Data Licence):
  dc_tender_2020_2021.csv          Dynamic Containment (low frequency) tenders, 2 Oct 2020 to 15 Sep 2021: accepted
                                   MW, availability fee (GBP/MW/h), service hours, NESO's total cost; times in UTC
  dc_dr_dm_by_unit_2021_2023.csv   DC, DM and DR day-ahead auctions, 16 Sep 2021 to 2 Nov 2023: cleared MW and
                                   clearing price per EFA block (4 hours); times in UK local time
  eac_by_unit_fy{yyyy}.csv, eac_by_unit_current_{date}.csv, eac_by_unit_daily_{date}.csv
                                   NESO's Enduring Auction Capability, from 2 Nov 2023: response (DC, DM, DR per EFA
                                   block), quick, slow and balancing reserve (per half-hour); times in UTC
  br_by_unit_{yyyy}_{yyyy}.csv     Balancing Reserve, 12 Mar 2024 to 29 Oct 2025 (then in the EAC files); UTC
  sffr_results_{date}.csv          Static Firm Frequency Response auctions, from 1 Apr 2023: accepted MW and the
                                   clearing price per EFA block; times in UK local time
  ffr_post_tender_tr{nnn}[_amended].{csv,xlsx,xlsm}   the monthly Firm Frequency Response tenders, rounds TR108 (for
                                   January 2019) to TR166 (for November 2023), every tender accepted or rejected: unit,
                                   technology, a service frame for working days, Saturdays and Sundays or bank
                                   holidays, the availability and nomination fees (GBP per hour, for the unit); the
                                   round's CSV where NESO published one, else its workbook, an amended version first
  ffr_auction_by_unit_{yyyy}_{yyyy}.csv   the weekly FFR auction trial ("Phase 2"), 7 Dec 2019 to 30 Nov 2021: static
                                   (LFS) and dynamic (DLH) FFR, cleared MW and clearing price per EFA block; UK local time
  stor_da_results_{date}.csv       the daily STOR auctions, from 1 Apr 2021: contracted MW and the market clearing
                                   price per unit and service day (05:00 to 05:00 UK local time); times in UTC
  stor_windows_{date}.csv          the committed STOR windows of each service day, two a day in UK local time
  data/raw/govuk/bank_holidays.json   gov.uk's bank holidays (OGL; England and Wales, from 2019), for the FFR frames
The time zone of each source is checked, not assumed: an EFA block starts at 23:00, 03:00, 07:00, 11:00, 15:00 or
19:00 UK local time, so a source's block starts are converted as declared (SOURCES) and must land on those hours
(check_efa_hours), which fails if a source is read in the wrong zone.

Method:
  revenue      MW x GBP/MW/h x hours of the delivery period (end - start in UTC, so a block over a clock change
               counts its 3 or 5 hours). The DC tenders' own total cost is checked against it.
  FFR tenders  one row per accepted tender and service day: the day's frame in UK local time (a frame from 23:00, or
               one that ends before it starts, begins the evening before, as EFA days do), Sunday's frame on a bank
               holiday; the service days run from the start date to the end date, except that a start on a month's
               last day before a later end (the evening start of a frame for the next month, as rounds from 2020 date
               it) begins the next day. mw is the largest response tendered (dynamic: primary, secondary and high
               frequency at 0.2-0.8 Hz; static: deliverable by 10 or 30 s) and price_gbp_per_mw_h the availability
               and nomination fees (GBP/h) over it, so revenue = fees x hours: NESO pays the availability fee for the
               hours a unit is available and the nomination fee for the hours it nominates, so this is the value of
               the accepted tender with the unit available and nominated throughout (nomination fees are under 0.1%
               of it). A long-term contract accepted before TR108 is missing; window initiation fees and response
               energy (BM prices) are left out. Against NESO's spend reports (licence condition C9, by month): dynamic
               FFR April-November 2023 within 6% of what NESO paid in every month (7.12 against 6.91 GBP m, response
               energy excluded); April 2022-March 2023 70% above it (63.3 against 37.2 GBP m; 43-124% by month), the
               gap of docs/AUDIT.md A10-5.
  STOR         one row per accepted day-ahead result and committed window of its service day: the contracted MW at
               the market clearing price over the window's hours (STOR pays availability within the windows only;
               utilisation is paid for energy delivered, which is not here). A service day the windows file does not
               yet cover is left out. Against NESO's spend reports (C9, monthly tables), the BM units' STOR comes
               within -10% to +18% of what NESO paid in every month of 2022/23 and 2023/24 (49.1 against 45.1 and
               6.9 against 6.6 GBP m); the non-BM units' falls far short of it (7.4 and 1.4 against 30.4 and 28.3
               GBP m), since most non-BM availability was paid on long-term STOR contracts (an inference: NESO
               publishes no unit-level table of them).
  service      DC, DM, DR (dynamic containment, moderation, regulation; product suffix L/H = low/high frequency),
               SFFR (static FFR: the monthly tenders' static product FFR-S, the weekly auctions' LFS, the day-ahead
               auctions' SFFR), DFFR (dynamic FFR: FFR-D, DLH), QR, SR, BR (quick, slow and balancing reserve; prefix
               P/N = positive/negative), STOR.
  unit         NESO's unit id as published: a BM unit's National Grid id (CHAPB-1, or AG-... for a supplier or virtual
               lead party unit) or a non-BM unit's own id (GSET-07). elexon_unit is the Elexon id of a National Grid
               id in any kept snapshot of Elexon's register, of any kind (T_ and E_ units, supplier units 2__ such
               as BP's 2__FBPGM001, virtual lead party units V__ such as Habitat's V__NHABI005), matched as spelled,
               else ignoring punctuation and spaces (NESO writes "AG -GEDF02", "GBND_2", "AFFR1"; id_key), else where
               NESO gives the Elexon id itself (E_ARNKB-2); blank for a non-BM unit. Of the GBP 158m paid to the
               batteries in 2025, 39% went to T_ and E_ units, 37% to supplier and virtual lead party units and 24%
               to non-BM units (docs/storage_revenues.md).
  participant  the company that bid the unit, as published; participant_group is its group by the rules of the
               ownership tables (gbpowerdata.common.companies.trader_group at the year's end), in the one spelling
               those tables give the name (gbpowerdata.build.build_ownership.one_spelling), so an optimiser and a BM
               trader of the same company have one name; a bidder no register names takes one spelling of its own
               ("ARENKO CLEANTECH" and "Arenko Cleantech" are one group).
  kept         accepted or executed rows with MW > 0; tenders rejected or withdrawn and cancelled results are
               dropped. Two accepted FFR tenders of one unit for one frame are two contracts (a monthly top-up on a
               long-term tender), both kept. The daily file repeats the running year's last day: a result is kept
               once, by NESO's unitResultID where the source has one, else by (unit, product, delivery start). The
               files follow on from each other (the 2021-23 auctions start the day after the last tender, the
               Balancing Reserve file ends at 22:30 UTC on 29 Oct 2025 and the EAC files carry it from 23:00), and
               the build fails if two different files hold a result for the same unit, product and start
               (check_no_overlap; not the FFR tender rounds, whose reports each hold their own contracts). Within one
               file a unit can have several results for one product and period (72 in FY2024, distinct
               unitResultIDs): all are kept.
Year: the UTC year of delivery_start.

Output columns: delivery_start, delivery_end (UTC), hours, service, product, unit, elexon_unit, participant,
participant_group, technology, mw, price_gbp_per_mw_h, revenue_gbp, source.
Read it with gbpowerdata.processed.read_ancillary_by_unit(year).

Usage: python -m gbpowerdata.build.ancillary_services [--years 2019 2026]
"""
from __future__ import annotations

import argparse
import csv
import functools
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from gbpowerdata import config as cfg

RAW = cfg.raw_dir() / "neso" / "ancillary"
BANK_HOLIDAYS = cfg.raw_dir() / "govuk" / "bank_holidays.json"
LOCAL = "Europe/London"
EFA_START_HOURS = {23, 3, 7, 11, 15, 19}
FIRST_YEAR = 2019                    # the first unit-level results: the FFR tenders for January 2019 (TR108)
COLUMNS = ["delivery_start", "delivery_end", "hours", "service", "product", "unit", "elexon_unit", "participant",
           "participant_group", "technology", "mw", "price_gbp_per_mw_h", "revenue_gbp", "source"]
# product -> service
SERVICE = {"DCL": "DC", "DCH": "DC", "DML": "DM", "DMH": "DM", "DRL": "DR", "DRH": "DR",
           "PBR": "BR", "NBR": "BR", "PQR": "QR", "NQR": "QR", "PSR": "SR", "NSR": "SR", "SFFR": "SFFR",
           "FFR-S": "SFFR", "LFS": "SFFR", "FFR-D": "DFFR", "DLH": "DFFR", "STOR": "STOR"}
TOTAL_COST_TOL = 0.01                # GBP: the DC tenders' total cost against MW x fee x hours
# FFR post-tender reports: columns by position, the same in every round's workbook and CSV (TR108-TR166), checked
# against the words of each file's header (FFR_HEADER)
FFR_WIDTH = 45
FFR_COLUMNS = {"ref": 0, "status": 1, "company": 3, "unit": 4, "technology": 6, "start": 7, "end": 8,
               "wd_from": 11, "wd_to": 12, "wd_h": 13, "sat_from": 14, "sat_to": 15, "sat_h": 16,
               "sun_from": 17, "sun_to": 18, "sun_h": 19, "availability": 20, "nomination": 21}
FFR_HEADER = {11: "from", 13: "duration", 14: "from", 17: "from", 20: "availability", 21: "nomination",
              28: "primary", 31: "secondary", 33: "high"}
FFR_DYNAMIC_MW = range(28, 35)       # primary, secondary and high frequency response at 0.2-0.8 Hz (dynamic)
FFR_STATIC_MW = (39, 40)             # response deliverable by 10 s and 30 s (non-dynamic providers)
CONTRACT_SOURCES = ("ffr_post_tender_",)   # each round's report holds its own contracts: overlaps are not repeats
EXCEL_EPOCH = pd.Timestamp("1899-12-30")


def _utc(s: pd.Series, zone: str) -> pd.Series:
    t = pd.to_datetime(s, errors="coerce")
    if zone == "UTC":
        return t.dt.tz_localize("UTC") if t.dt.tz is None else t.dt.tz_convert("UTC")
    return t.dt.tz_localize(zone, ambiguous="NaT", nonexistent="NaT").dt.tz_convert("UTC")


def check_efa_hours(starts: pd.Series, source: str, min_share: float = 0.99) -> None:
    """EFA blocks start at 23, 03, 07, 11, 15 or 19 h UK local time: a source read in the wrong zone fails."""
    local = starts.dt.tz_convert(LOCAL)
    share = float(local.dt.hour.isin(EFA_START_HOURS).mean()) if len(local) else 1.0
    if share < min_share:
        raise AssertionError(f"ancillary_services: {source}: only {share:.1%} of EFA blocks start on an EFA hour "
                             f"in UK local time; is the source's time zone right?")


def _frame(source: str, start, end, product, unit, participant, technology, mw, price,
           result_id=None) -> pd.DataFrame:
    d = pd.DataFrame({"delivery_start": start, "delivery_end": end, "product": product, "unit": unit,
                      "participant": participant, "technology": technology,
                      "mw": pd.to_numeric(mw, errors="coerce"), "price_gbp_per_mw_h": pd.to_numeric(price, errors="coerce"),
                      "result_id": result_id if result_id is not None else pd.NA})
    d["source"] = source
    d["unit"] = d["unit"].astype(str).str.strip().str.upper()
    d["product"] = d["product"].astype(str).str.strip().str.upper()
    return d


def dc_tender(t: pd.DataFrame, source: str) -> pd.DataFrame:
    """2020-21 DC tenders: accepted DC LF rows; fee GBP/MW/h over the service hours (UTC)."""
    t = t[(t["Market Name"] == "DC LF") & (t["Accepted/Rejected"] == "Accepted")]
    d = _frame(source, _utc(t["Delivery Start UTC"], "UTC"), _utc(t["Delivery End UTC"], "UTC"), "DCL",
               t["Response Unit"], t["Agent/Applicant"], t["Technology Type"], t["Volume Accepted"],
               t["Availability Fee"])
    hours = pd.to_numeric(t["Service Duration"], errors="coerce").to_numpy()
    span = ((d["delivery_end"] - d["delivery_start"]).dt.total_seconds() / 3600).to_numpy()
    if not np.allclose(hours, span, equal_nan=True):
        raise AssertionError(f"ancillary_services: {source}: service duration differs from delivery end - start")
    cost = pd.to_numeric(t["Total Cost"], errors="coerce").to_numpy()
    calc = d["mw"].to_numpy() * d["price_gbp_per_mw_h"].to_numpy() * span
    bad = np.abs(np.nan_to_num(cost) - calc) > TOTAL_COST_TOL * np.maximum(1.0, np.abs(calc))
    if bad.mean() > 0.001:
        raise AssertionError(f"ancillary_services: {source}: total cost disagrees with MW x fee x hours in "
                             f"{int(bad.sum())} rows")
    return d


def dc_dr_dm(t: pd.DataFrame, source: str) -> pd.DataFrame:
    """2021-23 DC/DM/DR auctions: cleared MW and clearing price per EFA block, UK local time."""
    t = t[t["Cancelled"].fillna("").astype(str).str.strip() == ""]
    d = _frame(source, _utc(t["Delivery Start"], LOCAL), _utc(t["Delivery End"], LOCAL), t["Service"],
               t["Unit Name"], t["Company"], t["Technology Type"], t["Cleared Volume"], t["Clearing Price"])
    check_efa_hours(d["delivery_start"].dropna(), source)
    return d


def eac(t: pd.DataFrame, source: str) -> pd.DataFrame:
    """EAC response and reserve results (and the Balancing Reserve file): executed MW, clearing price, UTC."""
    d = _frame(source, _utc(t["deliveryStart"], "UTC"), _utc(t["deliveryEnd"], "UTC"), t["auctionProduct"],
               t["auctionUnit"], t["registeredAuctionParticipant"], t["technologyType"], t["executedQuantity"],
               t["clearingPrice"], t["unitResultID"].astype(str))
    blocks = d[d["product"].str.match(r"^D[CMR][LH]$")]
    check_efa_hours(blocks["delivery_start"].dropna(), source)
    return d


def sffr(t: pd.DataFrame, source: str) -> pd.DataFrame:
    """Static FFR auctions: accepted MW at the clearing price per EFA block, UK local time."""
    t = t[t["Status"].astype(str).str.strip().str.lower() == "accepted"]
    d = _frame(source, _utc(t["Delivery Start"], LOCAL), _utc(t["Delivery End"], LOCAL), "SFFR", t["Unit"],
               t["Provider"], t["Technology Type"], t["Accepted Volume"], t["Clearing Price"])
    check_efa_hours(d["delivery_start"].dropna(), source)
    return d


def is_tender_ref(v) -> bool:
    """A tender's reference has a fraction (108.001); NESO's example rows carry the round alone (108)."""
    try:
        x = float(str(v).strip())
    except ValueError:
        return False
    return np.isfinite(x) and x != int(x)


def ffr_rows(path: Path) -> pd.DataFrame:
    """A post-tender report's tenders as published, by column position (FFR_COLUMNS), after checking the header's
    words (FFR_HEADER). Workbooks are read to FFR_WIDTH columns and stop after 50 empty rows: TR144's declares
    16,377 columns and 1,048,576 rows."""
    if path.suffix.lower() == ".csv":
        with open(path, encoding="latin-1", newline="") as f:     # NESO's CSVs are cp1252: GBP signs in the header
            rows = [r for r in csv.reader(f)]
    else:
        import openpyxl

        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        rows, empty = [], 0
        for r in wb.worksheets[0].iter_rows(max_col=FFR_WIDTH, values_only=True):
            empty = empty + 1 if all(v is None or str(v).strip() == "" for v in r) else 0
            if empty > 50:
                break
            rows.append(list(r))
        wb.close()
    first = next((i for i, r in enumerate(rows) if r and is_tender_ref(r[0])), None)
    if first is None:
        raise AssertionError(f"ancillary_services: {path.name}: no tenders")
    labels = [" ".join(str(r[j]) for r in rows[:first] if j < len(r) and r[j] is not None).lower()
              for j in range(FFR_WIDTH)]
    for j, word in FFR_HEADER.items():
        if word not in labels[j]:
            raise AssertionError(f"ancillary_services: {path.name}: column {j} reads {labels[j][:50]!r}, not "
                                 f"{word!r}: has NESO changed the report's layout?")
    data = [(list(r) + [None] * FFR_WIDTH)[:FFR_WIDTH] for r in rows[first:] if r and is_tender_ref(r[0])]
    return pd.DataFrame(data)


def report_date(v) -> pd.Timestamp:
    """A date as the reports give it: a date, an Excel serial (43861 = 31 Jan 2020, in TR121 and TR145) or text,
    day first (31/07/2021)."""
    if isinstance(v, (datetime, pd.Timestamp)):
        return pd.Timestamp(v).normalize()
    text = str(v).strip()
    if re.fullmatch(r"\d{5}(\.0+)?", text):
        return EXCEL_EPOCH + pd.Timedelta(days=int(float(text)))
    t = pd.to_datetime(text, dayfirst=not re.match(r"\d{4}-", text), errors="coerce")
    return t.normalize() if pd.notna(t) else pd.NaT


def hhmm(v) -> tuple[int, int] | None:
    """A frame time as the reports give it (2300, 700, "1500") -> (hour, minute); None where blank."""
    try:
        x = int(float(str(v).strip()))
    except ValueError:
        return None
    return (x // 100, x % 100) if 0 <= x <= 2400 and x % 100 < 60 else None


def fee(v) -> float:
    try:
        x = float(str(v).replace(",", "").replace("\xa3", "").strip())
    except ValueError:
        return 0.0
    return x if np.isfinite(x) else 0.0


@functools.lru_cache(maxsize=None)
def bank_holidays(path: Path | None = None) -> frozenset:
    """England and Wales bank holidays (gov.uk, from 2019; gbpowerdata.pull.ancillary_pull)."""
    path = BANK_HOLIDAYS if path is None else Path(path)
    if not path.exists():
        raise SystemExit(f"{path} is missing: run python -m gbpowerdata.pull.ancillary_pull")
    events = json.loads(path.read_text(encoding="utf-8"))["england-and-wales"]["events"]
    return frozenset(pd.Timestamp(e["date"]) for e in events)


def service_days(start: pd.Timestamp, end: pd.Timestamp) -> pd.DatetimeIndex:
    """The service days of a tender: from its start date to its end date, except that a start on a month's last day
    before a later end (the evening start of a frame for the next month, as rounds from 2020 date it) begins the
    next day."""
    nxt = start + pd.Timedelta(days=1)
    return pd.date_range(nxt if nxt.day == 1 and end >= nxt else start, end, freq="D")


def ffr_tender(t: pd.DataFrame, source: str) -> pd.DataFrame:
    """A round's accepted FFR tenders (ffr_rows), one row per tender and service day, UTC."""
    holidays = bank_holidays()
    t = t[t[FFR_COLUMNS["status"]].astype(str).str.strip().str.lower() == "accepted"]
    rows = []
    for r in t.itertuples(index=False):
        r = list(r)
        dynamic = max(fee(r[j]) for j in FFR_DYNAMIC_MW)
        static = max(fee(r[j]) for j in FFR_STATIC_MW)
        mw = dynamic if dynamic > 0 else static
        per_hour = fee(r[FFR_COLUMNS["availability"]]) + fee(r[FFR_COLUMNS["nomination"]])
        start, end = report_date(r[FFR_COLUMNS["start"]]), report_date(r[FFR_COLUMNS["end"]])
        if pd.isna(start) or pd.isna(end) or mw <= 0:
            continue
        for day in service_days(start, end):
            kind = "sun" if day.dayofweek == 6 or day in holidays else ("sat" if day.dayofweek == 5 else "wd")
            a, b = hhmm(r[FFR_COLUMNS[f"{kind}_from"]]), hhmm(r[FFR_COLUMNS[f"{kind}_to"]])
            if a is None or b is None or fee(r[FFR_COLUMNS[f"{kind}_h"]]) <= 0:
                continue
            begin = day + pd.Timedelta(hours=a[0], minutes=a[1]) - pd.Timedelta(days=int(a >= b))
            rows.append({"start": begin, "end": day + pd.Timedelta(hours=b[0], minutes=b[1]),
                         "product": "FFR-D" if dynamic > 0 else "FFR-S", "unit": r[FFR_COLUMNS["unit"]],
                         "participant": r[FFR_COLUMNS["company"]], "technology": r[FFR_COLUMNS["technology"]],
                         "mw": mw, "price": per_hour / mw,
                         "result_id": f"{source}:{fee(r[FFR_COLUMNS['ref']]):.3f}:{day:%Y%m%d}"})
    f = pd.DataFrame(rows, columns=["start", "end", "product", "unit", "participant", "technology", "mw", "price",
                                    "result_id"])
    return _frame(source, _utc(f["start"], LOCAL), _utc(f["end"], LOCAL), f["product"], f["unit"], f["participant"],
                  f["technology"], f["mw"], f["price"], f["result_id"])


def local_times(s: pd.Series) -> pd.Series:
    """Local times as NESO's files give them: ISO (the datastore's dump) or day first (07/12/2019 23:00)."""
    text = s.astype(str).str.strip()
    dayfirst = text.str.match(r"\d{2}/\d{2}/\d{4}")
    t = pd.to_datetime(text.where(~dayfirst), errors="coerce")
    return t.fillna(pd.to_datetime(text.where(dayfirst), format="%d/%m/%Y %H:%M", errors="coerce"))


def efa_times(start: pd.Series, end: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Naive times of EFA blocks to UTC, read as UK local time, except a row whose start is an EFA hour only when read
    as UTC: the weekly FFR auction files give EFA 1 at 22:00 from the clock change of 29 Mar 2020 into May 2020
    (2,879 rows), UTC, and local time otherwise (in winter the two agree)."""
    s_local, e_local = _utc(start, LOCAL), _utc(end, LOCAL)
    s_utc, e_utc = _utc(start, "UTC"), _utc(end, "UTC")
    utc = (~s_local.dt.tz_convert(LOCAL).dt.hour.isin(EFA_START_HOURS)
           & s_utc.dt.tz_convert(LOCAL).dt.hour.isin(EFA_START_HOURS))
    return s_local.where(~utc, s_utc), e_local.where(~utc, e_utc)


def ffr_auction(t: pd.DataFrame, source: str) -> pd.DataFrame:
    """The weekly FFR auction trial, 7 Dec 2019 to 30 Nov 2021: cleared MW at the clearing price per EFA block of the
    static (LFS) and dynamic (DLH) products, UK local time (UTC for some weeks of 2020: efa_times); no technology
    column."""
    t = t[t["Cancelled"].fillna("").astype(str).str.strip() == ""]
    start, end = efa_times(local_times(t["Delivery Start"]), local_times(t["Delivery End"]))
    d = _frame(source, start, end, t["Service"], t["Unit Name"], t["Company"], pd.NA, t["Cleared Volume"],
               t["Clearing Price"])
    check_efa_hours(d["delivery_start"].dropna(), source)
    return d


def clock_offset(s: pd.Series) -> pd.Series:
    """Times of day as NESO's files give them ("06:00", "17:30:00") -> offsets from midnight; NaT where blank."""
    text = s.astype(str).str.strip()
    text = text.where(~text.str.fullmatch(r"\d{1,2}:\d{2}"), text + ":00")
    return pd.to_timedelta(text.where(text.str.fullmatch(r"\d{1,2}:\d{2}:\d{2}")), errors="coerce")


def stor_windows(folder: Path | None = None) -> pd.DataFrame:
    """NESO's committed STOR windows (the newest stor_windows_{date}.csv): one row per service day and window, with
    its start and end as offsets from the day's local midnight (an end at or before the start runs past midnight)."""
    folder = RAW if folder is None else Path(folder)
    files = sorted(folder.glob("stor_windows_*.csv"))
    if not files:
        raise SystemExit(f"no stor_windows_*.csv in {folder}: run python -m gbpowerdata.pull.ancillary_pull")
    w = pd.read_csv(files[-1], encoding="utf-8-sig", dtype=str)
    text = w["Date"].astype(str).str.strip()
    dayfirst = text.str.match(r"\d{2}/\d{2}/\d{4}")
    day = pd.to_datetime(text.where(~dayfirst), errors="coerce").fillna(
        pd.to_datetime(text.where(dayfirst), format="%d/%m/%Y", errors="coerce")).dt.normalize()
    frames = []
    for k in (1, 2):
        start, end = clock_offset(w[f"Window {k} Start Time"]), clock_offset(w[f"Window {k} End Time"])
        end = end.where(end > start, end + pd.Timedelta(days=1))
        frames.append(pd.DataFrame({"day": day, "window": k, "start": start, "end": end}))
    return pd.concat(frames, ignore_index=True).dropna().sort_values(["day", "window"]).reset_index(drop=True)


def stor_da(t: pd.DataFrame, source: str) -> pd.DataFrame:
    """The daily STOR auctions, from 1 Apr 2021: an accepted result's contracted MW at the market clearing price over
    each committed window of its service day (stor_windows), UK local time."""
    t = t[t["Status"].astype(str).str.strip().str.lower() == "accepted"].copy()
    t["day"] = (pd.to_datetime(t["Service Delivery From"], utc=True).dt.tz_convert(LOCAL).dt.normalize()
                .dt.tz_localize(None))
    m = t.merge(stor_windows(), on="day", how="inner")
    return _frame(source, _utc(m["day"] + m["start"], LOCAL), _utc(m["day"] + m["end"], LOCAL), "STOR", m["Unit ID"],
                  m["Company Name"], m["Fuel Type"], m["Contracted MW"], m["Market Clearing Price"],
                  m["Tender Submission ID"].astype(str) + ":" + m["window"].astype(str))


# file-name pattern -> (reader, priority: lower wins where a result is in two files)
SOURCES = [
    (r"dc_tender_\d{4}_\d{4}", dc_tender, 0),
    (r"dc_dr_dm_by_unit_\d{4}_\d{4}", dc_dr_dm, 0),
    (r"eac_by_unit_fy\d{4}", eac, 0),
    (r"br_by_unit_\d{4}_\d{4}", eac, 1),
    (r"sffr_results_\d{8}", sffr, 2),
    (r"eac_by_unit_current_\d{8}", eac, 3),
    (r"br_by_unit_current_\d{8}", eac, 3),
    (r"eac_by_unit_daily_\d{8}", eac, 4),
    (r"ffr_post_tender_tr\d{3}(_amended)?", ffr_tender, 0),
    (r"ffr_auction_by_unit_\d{4}_\d{4}", ffr_auction, 0),
    (r"stor_da_results_\d{8}", stor_da, 2),
]
FILE_TYPES = (".csv", ".xlsx", ".xlsm")


def raw_files(folder: Path | None = None) -> list[tuple[Path, object, int]]:
    """The raw files to read: every archive, the newest file of each dated (running) resource, and one report per FFR
    tender round (amended before original, CSV before workbook)."""
    folder = RAW if folder is None else Path(folder)
    picked: dict[str, tuple] = {}
    for path in sorted(p for p in folder.iterdir() if p.suffix.lower() in FILE_TYPES):
        for pattern, reader, prio in SOURCES:
            if re.fullmatch(pattern, path.stem):
                if path.suffix.lower() != ".csv" and reader is not ffr_tender:
                    break
                key = re.sub(r"_(\d{8}|amended)$", "", path.stem)   # dated files (or versions) of one resource
                rank = (path.stem.endswith("_amended"), path.suffix.lower() == ".csv")
                if key not in picked or rank >= picked[key][3]:      # sorted by name: the newest date wins
                    picked[key] = (path, reader, prio, rank)
                break
    return sorted(((p, r, pr) for p, r, pr, _ in picked.values()), key=lambda x: (x[2], x[0].name))


def read_all(folder: Path | None = None) -> pd.DataFrame:
    frames = []
    for path, reader, prio in raw_files(folder):
        t = ffr_rows(path) if reader is ffr_tender else pd.read_csv(path, low_memory=False, encoding="utf-8-sig")
        d = reader(t, path.stem)
        d["priority"] = prio
        frames.append(d)
        print(f"  {path.name}: {len(t):,} rows -> {int((d['mw'] > 0).sum()):,} with MW", flush=True)
    if not frames:
        raise SystemExit(f"no ancillary results in {RAW}: run python -m gbpowerdata.pull.ancillary_pull")
    return pd.concat(frames, ignore_index=True)


def check_no_overlap(d: pd.DataFrame) -> None:
    """No two different files may hold a result for the same unit, product and delivery start (after the daily
    file's repeats are dropped by id): that would count a payment twice."""
    key = ["unit", "product", "delivery_start"]
    d = d[~d["source"].astype(str).str.startswith(CONTRACT_SOURCES)]
    n_src = d.groupby(key)["source"].nunique()
    both = n_src[n_src > 1]
    if len(both):
        ex = both.index[0]
        raise AssertionError(f"ancillary_services: {len(both)} results are in two files, e.g. {ex}: "
                             f"{sorted(d.set_index(key).loc[ex, 'source'].astype(str).unique())}")


def normalise(d: pd.DataFrame) -> pd.DataFrame:
    """Keep MW > 0, drop results counted twice, add service, hours and revenue."""
    d = d[(d["mw"] > 0) & d["delivery_start"].notna() & d["delivery_end"].notna()].copy()
    unknown = set(d["product"]) - set(SERVICE)
    if unknown:
        raise AssertionError(f"ancillary_services: products without a service {sorted(unknown)}")
    d = d.sort_values(["priority", "source"], kind="stable")
    has_id = d["result_id"].notna() & (d["result_id"].astype(str) != "nan")
    by_id = d[has_id].drop_duplicates("result_id")
    by_key = d[~has_id].drop_duplicates(["unit", "product", "delivery_start"])
    d = pd.concat([by_id, by_key], ignore_index=True)
    check_no_overlap(d)
    d["service"] = d["product"].map(SERVICE)
    d["hours"] = (d["delivery_end"] - d["delivery_start"]).dt.total_seconds() / 3600
    if (d["hours"] <= 0).any():
        raise AssertionError("ancillary_services: a delivery period that ends before it starts")
    d["revenue_gbp"] = d["mw"] * d["price_gbp_per_mw_h"] * d["hours"]
    return d.sort_values(["delivery_start", "unit", "product"]).reset_index(drop=True)


def id_key(unit) -> str:
    """A NESO unit id with its punctuation and spaces dropped: NESO spells one unit differently across its files
    (AFFR1 in the 2020-21 tenders, AFFR-1 in the auctions; GBND_2 and GBND-2; "AG -GEDF02" in FFR tenders)."""
    return re.sub(r"[^A-Z0-9]", "", str(unit).upper())


def map_elexon(units: pd.Series, ids: dict[str, str]) -> pd.Series:
    """Each NESO unit id's Elexon id (`ids`: National Grid id -> Elexon id): as spelled, else ignoring punctuation and
    spaces, else where NESO gives the Elexon id itself (E_ARNKB-2 for Hutton)."""
    keyed = {**{id_key(v): v for v in ids.values()}, **{id_key(k): v for k, v in ids.items()}}
    return units.map(ids).fillna(units.map(id_key).map(keyed))


def elexon_ids() -> dict[str, str]:
    """National Grid BM unit id -> Elexon id, over every kept snapshot of the register and every kind of unit
    (the newest snapshot wins)."""
    from gbpowerdata.build import bm_units as B

    out: dict[str, str] = {}
    for path in B.register_files().values():
        reg = pd.read_csv(path, usecols=["elexonBmUnit", "nationalGridBmUnit"]).dropna()
        out.update(dict(zip(reg["nationalGridBmUnit"].astype(str).str.strip().str.upper(),
                            reg["elexonBmUnit"].astype(str))))
    return out


def spellings() -> dict[str, str]:
    """Normalised name -> the spelling the ownership tables give it (gbpowerdata.build.build_ownership)."""
    from gbpowerdata.build import build_ownership as O
    return O._spellings()


def participant_groups(names: pd.Series, year: int, spelled: dict[str, str]) -> dict[str, str]:
    """Each participant's group by the ownership tables' rules at the year's end (or today in the current year), in
    the ownership tables' spelling (`spelled`, from spellings()); a group no register names takes the preferred
    spelling among its own variants."""
    from gbpowerdata.build import build_ownership as O
    from gbpowerdata.build.bm_units import as_of
    from gbpowerdata.common import companies as C

    when = as_of(year)
    raw = {n: C.trader_group(n, when)[0] for n in sorted(names.dropna().astype(str).unique())}
    own: dict[str, set] = {}
    for g in set(raw.values()):
        if isinstance(g, str) and (k := C.norm(g)):
            own.setdefault(k, set()).add(re.sub(r"\s+", " ", C.clean(g)))
    spelled = dict(spelled)
    for k, v in own.items():
        spelled.setdefault(k, O.preferred_spelling(v))
    groups = O.one_spelling(pd.DataFrame({"group": list(raw.values())}), spelled)["group"]
    return dict(zip(raw, groups))


def build(years) -> dict[int, pd.DataFrame]:
    d = normalise(read_all())
    d["elexon_unit"] = map_elexon(d["unit"], elexon_ids())
    d["year"] = d["delivery_start"].dt.year
    spelled = spellings()
    out = {}
    for y in years:
        t = d[d["year"] == y].copy()
        if t.empty:
            continue
        t["participant_group"] = t["participant"].astype(str).map(participant_groups(t["participant"], y, spelled))
        out[y] = t[COLUMNS].reset_index(drop=True)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--years", nargs=2, type=int, default=[FIRST_YEAR, pd.Timestamp.today().year])
    a = ap.parse_args(argv)
    tables = build(range(a.years[0], a.years[1] + 1))
    for y, t in tables.items():
        path = cfg.processed_dir() / f"ancillary_by_unit_{y}.csv"
        t.to_csv(path, index=False, date_format="%Y-%m-%dT%H:%M:%SZ")
        by = (t.groupby("service")["revenue_gbp"].sum() / 1e6).round(1).to_dict()
        mapped = float(t.loc[t["elexon_unit"].notna(), "revenue_gbp"].sum() / t["revenue_gbp"].sum())
        print(f"  ancillary_by_unit_{y}.csv: {len(t):,} rows, GBP m by service {by}, "
              f"{mapped:.0%} of revenue on BM units", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
