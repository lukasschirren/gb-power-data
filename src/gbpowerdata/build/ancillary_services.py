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
The time zone of each source is checked, not assumed: an EFA block starts at 23:00, 03:00, 07:00, 11:00, 15:00 or
19:00 UK local time, so a source's block starts are converted as declared (SOURCES) and must land on those hours
(check_efa_hours), which fails if a source is read in the wrong zone.

Method:
  revenue      MW x GBP/MW/h x hours of the delivery period (end - start in UTC, so a block over a clock change
               counts its 3 or 5 hours). The DC tenders' own total cost is checked against it.
  service      DC, DM, DR (dynamic containment, moderation, regulation; product suffix L/H = low/high frequency),
               SFFR (static FFR), QR, SR, BR (quick, slow and balancing reserve; prefix P/N = positive/negative).
  unit         NESO's unit id as published: a BM unit's National Grid id (CHAPB-1, or AG-... for a supplier or virtual
               lead party unit) or a non-BM unit's own id (GSET-07). elexon_unit is the Elexon id of a National Grid
               id in any kept snapshot of Elexon's register, of any kind (T_ and E_ units, supplier units 2__ such
               as BP's 2__FBPGM001, virtual lead party units V__ such as Habitat's V__NHABI005); blank for a non-BM
               unit. Of the GBP 157m paid to batteries in 2025, 39% went to T_ and E_ units, 37% to supplier and
               virtual lead party units and 24% to non-BM units (docs/storage_revenues.md).
  participant  the company that bid the unit, as published; participant_group is its group by the rules of the
               ownership tables (gbpowerdata.common.companies.trader_group at the year's end), in the one spelling
               those tables give the name (gbpowerdata.build.build_ownership.one_spelling), so an optimiser and a BM
               trader of the same company have one name; a bidder no register names takes one spelling of its own
               ("ARENKO CLEANTECH" and "Arenko Cleantech" are one group).
  kept         accepted or executed rows with MW > 0; tenders rejected or withdrawn and cancelled results are
               dropped. The daily file repeats the running year's last day: a result is kept once, by NESO's
               unitResultID where the source has one, else by (unit, product, delivery start). The files follow
               on from each other (the 2021-23 auctions start the day after the last tender, the Balancing
               Reserve file ends at 22:30 UTC on 29 Oct 2025 and the EAC files carry it from 23:00), and the build
               fails if two different files hold a result for the same unit, product and start
               (check_no_overlap). Within one file a unit can have several results for one product and period
               (72 in FY2024, distinct unitResultIDs): all are kept.
Year: the UTC year of delivery_start.

Output columns: delivery_start, delivery_end (UTC), hours, service, product, unit, elexon_unit, participant,
participant_group, technology, mw, price_gbp_per_mw_h, revenue_gbp, source.
Read it with gbpowerdata.processed.read_ancillary_by_unit(year).

Usage: python -m gbpowerdata.build.ancillary_services [--years 2020 2026]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from gbpowerdata import config as cfg

RAW = cfg.raw_dir() / "neso" / "ancillary"
LOCAL = "Europe/London"
EFA_START_HOURS = {23, 3, 7, 11, 15, 19}
FIRST_YEAR = 2020                    # the first unit-level results: 2 Oct 2020
COLUMNS = ["delivery_start", "delivery_end", "hours", "service", "product", "unit", "elexon_unit", "participant",
           "participant_group", "technology", "mw", "price_gbp_per_mw_h", "revenue_gbp", "source"]
# product -> service
SERVICE = {"DCL": "DC", "DCH": "DC", "DML": "DM", "DMH": "DM", "DRL": "DR", "DRH": "DR",
           "PBR": "BR", "NBR": "BR", "PQR": "QR", "NQR": "QR", "PSR": "SR", "NSR": "SR", "SFFR": "SFFR"}
TOTAL_COST_TOL = 0.01                # GBP: the DC tenders' total cost against MW x fee x hours


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
]


def raw_files(folder: Path | None = None) -> list[tuple[Path, object, int]]:
    """The raw files to read: every archive, and the newest file of each dated (running) resource."""
    folder = RAW if folder is None else Path(folder)
    picked: dict[str, tuple[Path, object, int]] = {}
    for path in sorted(folder.glob("*.csv")):
        for pattern, reader, prio in SOURCES:
            if re.fullmatch(pattern, path.stem):
                key = re.sub(r"_\d{8}$", "", path.stem)       # dated files of one resource share a key
                picked[key] = (path, reader, prio)           # sorted by name: the newest date wins
                break
    return sorted(picked.values(), key=lambda x: (x[2], x[0].name))


def read_all(folder: Path | None = None) -> pd.DataFrame:
    frames = []
    for path, reader, prio in raw_files(folder):
        t = pd.read_csv(path, low_memory=False, encoding="utf-8-sig")
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
    d["elexon_unit"] = d["unit"].map(elexon_ids())
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
