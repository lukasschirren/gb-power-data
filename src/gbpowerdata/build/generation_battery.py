"""GB batteries' discharge and charge per half-hour, metered and notified, the frequency response NESO contracted from
them, and where they are, with yearly and monthly totals -> data/processed/generation_battery_{year}.csv,
data/processed/generation_battery_summary.csv and data/processed/generation_battery_units.csv.

Why: the generation mix (gbpowerdata.build.generation_mix) has no battery column: FUELHH reports no battery fuel type,
so how much the batteries discharged and charged, when, where, how it grew year by year, and how much of the fleet
NESO held for frequency response instead was in no table. Per unit and month the notified energy and the response
payments are in storage_revenue_{y}; this stage adds the fleet's half-hours, its metered energy, the response MW and
the units' regions.

SOURCES
  data/raw/b1610/{unit}.csv   Elexon B1610 (gbpowerdata.pull.b1610_pull --storage-fleet, BMRS data licence): each
      unit's metered output, MWh per settlement period, signed (negative while charging), from 1 February 2019
      (Elexon's archive starts then). Elexon publishes it for every kind of battery unit, the supplier (2__) and
      virtual lead party (V__) ones included: 238 of storage_fleet's 239 BM storage units (b1610_pull). It carries
      no location.
  data/raw/fpn/{unit}.csv   Elexon's final physical notifications (gbpowerdata.pull.fpn_pull --storage-fleet): the
      position the unit notified before gate closure, read with gbpowerdata.common.elexon.fpn_energy as
      gbpowerdata.build.storage_revenues reads it.
  ancillary_by_unit_{y}.csv   NESO's frequency response results by unit and delivery period
      (gbpowerdata.build.ancillary_services, NESO Open Data Licence): the MW accepted for dynamic containment,
      moderation and regulation (DC, DM, DR; low and high frequency products), static FFR (the monthly tenders, the
      weekly auctions, the day-ahead auctions) and dynamic FFR, from January 2019 (the first unit-level results);
      the previous year's file for the blocks that run into the year. Reserve (quick, slow, balancing, STOR) is left
      out: it is not frequency response.
  The units are gbpowerdata.build.storage_revenues.units(year) with tech "battery": the register's T_ and E_ battery
  units active in the year (gbpowerdata.build.bm_units: active_from, active_to, capacity_mw), and storage_fleet's
  supplier and virtual lead party batteries from their entry_date to their last_seen, capacity_mw the largest MW NESO
  accepted them for (a lower bound); for response also storage_fleet's non-BM batteries (NESO's own unit ids), dated
  and sized the same way. Pumped storage is left out: it is in the generation mix (FUELHH's PS).
  generation_mix_{y}.csv (generation_mw) for the share of generation, where built.

LOCATION (B1610 carries none):
  gsp_group   the unit's GSP group (one of the 14 distribution areas) as Elexon's register gives it
      (gbpowerdata.build.bm_units' gsp_group, else storage_fleet's, in one spelling: gsp_group_name). The register
      gives it for every embedded, supplier and virtual lead party unit and for none of the transmission (T_) units or
      the non-BM ones, whose gsp_group is "unknown".
  postcode   the unit's postcode in NESO's Enduring Auction Capability results (gbpowerdata.build.storage_fleet.
      eac_postcodes: by its National Grid id, the most frequent where its rows differ; without the space, "AB555PE"),
      from November 2023: empty for a unit that never bid there (186 of the 264 units of 2025 have one). In the units
      table only: no source in the pipeline places a postcode in a GSP group or at coordinates.

THE HALF-HOURLY TABLE (MW, mean over the half-hour, UTC startTime on the year's spine)
  {flow}_{basis}_mw, {flow}_{basis}_{group}_mw   flow discharge or charge (both positive), basis metered (B1610) or
      notified (FPN), group transmission (T_), embedded (E_), supplier (2__) or vlp (V__); without a group the whole
      fleet. Each unit's output is split into discharge and charge before it is summed, so two units moving
      opposite ways in a half-hour are not netted against each other.
  net_{basis}_mw   discharge minus charge of the fleet.
  response_{product}_mw, response_{product}_{group}_mw   the MW NESO accepted from the batteries in the half-hour for
      each frequency response product, as ancillary_services names them: dcl, dch, dml, dmh, drl, drh (DC, DM and DR;
      L and H are NESO's low and high frequency products), sffr (static FFR) and dffr (dynamic FFR); group as above or
      non_bm; without a group the whole fleet, non-BM batteries included. Each product is kept as published: none is
      added to another. Empty before 2019 and after the last delivery the year's ancillary file holds.
  units_active, units_metered, units_notified   the BM battery units inside their activity in the half-hour, and
      those with a metered value and a notification in it. A unit without a value adds nothing: a group's column is
      0 where it has no active unit and empty where it has active units but none with a value.
  generation_mw   generation_mix's generation in the half-hour (empty without that table), for the share.

THE SUMMARY (generation_battery_summary.csv, long): one row per resolution ("year" or "month"), period (YYYY or
  YYYY-MM), basis (metered, notified, response), group ("all", one of the four, or non_bm for response), gsp_group
  ("all", or a GSP group with group "all") and flow (discharge, charge, net; for response the product):
  energy_gwh (MW x 0.5 h over the period's half-hours with a value; empty for response, which holds MW, not energy),
  mean_mw (energy over the hours with a value; for response the MW accepted, averaged over the half-hours NESO's
  results cover), share_of_generation (discharge only, group rows: its energy over generation_mix's generation in
  the half-hours both hold), units (units with any discharge or charge, or with MW accepted for the product, in the
  period), capacity_mw (the capacity_mw of the units in the row
  weighted by the share of the period each was active: the mean capacity in place; a lower bound for supplier, vlp
  and non_bm), coverage (energy: the active unit half-hours with a value over all active unit half-hours, what is
  missing from energy_gwh, which is not scaled up, and empty where it is 0; response: the share of the period
  NESO's results cover). A
  region's energy and MW are summed from its units' half-hours, so the regions add up to the fleet.

THE UNITS (generation_battery_units.csv): one row per unit and year: unit_id, unit_name, group, gsp_group, postcode,
  capacity_mw, capacity_source, active_from, active_to, discharge_metered_mwh, charge_metered_mwh, coverage_metered,
  discharge_notified_mwh, charge_notified_mwh, coverage_notified (empty for non-BM units), and response_{product}_mw
  (the MW NESO accepted from the unit, averaged over the year's half-hours its results cover).
  A rerun replaces the summary's and the units' rows of the years it builds and keeps the others.

GOTCHAS
  - Metered and notified differ: the notified position leaves out what the unit did in the Balancing Mechanism and
    any imbalance, the metered output includes both. The notified discharge exceeds the notified charge for T_/E_
    batteries in four of the five years 2021-2025 (docs/AUDIT.md A9-11), which no battery can sustain over a year;
    the metered energy is what the units' meters recorded, the notified what storage_revenue values.
  - Of the 118 T_/E_ batteries, 40 are registered with fuelType OTHER and 78 with none (register of 5 Jun 2026);
    whether FUELHH counts their output in OTHER (and so in generation_mix's generation) Elexon does not document.
    The data do not settle it: with each day's mean taken out, FUELHH's OTHER rises by 1.4 MW per MW the OTHER
    batteries discharge and by 1.2-1.5 MW per MW the batteries without a fuel type discharge (2024, 2025), and not
    with their charging (OTHER is never negative), so either OTHER holds battery discharge of both kinds or the other
    peaking units in it run at the same hours. share_of_generation divides by generation_mix's generation as built.
  - B1610 and FUELHH agree where both meter the same plant: the pumped storage units' B1610 output against FUELHH's
    PS (generation minus pumping) in 2024, correlation 1.000, slope 0.99, means -70 and -68 MW.
  - A supplier or virtual lead party unit may hold several sites, and its metered volume all the assets assigned to
    it; storage_fleet names it a battery from NESO's results (gbpowerdata.build.storage_fleet). Some units classed as
    batteries meter more out than in over a year, which no battery can (docs/AUDIT.md A9-14): 38 of 474 unit-years
    in 2019-2025, 27-73 GWh a year in excess, 37 of 2019's 66 GWh of metered discharge (E_RDFRB-1 "Redfield Road B",
    20 MW: 19.2 GWh out, 0.45 in). From 2022 the fleet meters 0.82-0.90 MWh out per MWh in.
  - The fleet's capacity in December, non-BM units included, against DESNZ's grid-scale battery capacity at the
    year's end (DUKES 2026 Table 5.16, UK; data/reference/official_statistics.csv): 473 against 879 MW (2019), 2,254
    against 2,319 (2022), 4,927 against 5,210 (2024), 7,832 against 7,512 (2025).
  - The register dates a battery by its files (gbpowerdata.build.bm_units), so a unit registered but silent before it
    trades is active and lowers coverage only where it publishes nothing; capacity_mw counts it from active_from.
  - No metered value before February 2019 (the 2018 rows of the metered basis are empty), and the notifications miss
    whole days for every unit (storage_revenues.notified_share lists them). A year's notified basis covers what
    fpn_pull has pulled: coverage says how much.
  - Response is the MW NESO accepted, not what was delivered; FFR contracts of rounds before TR108 (for January 2019)
    are missing, and so are the Enhanced Frequency Response contracts of 2016 (ancillary_services).
  - The units are bm_units' batteries, which include every unit named "Storage" (Statkraft's Keith and Lister units,
    at most 1 MW registered, may not be batteries).

Output: data/processed/generation_battery_{year}.csv (half-hourly), generation_battery_summary.csv,
generation_battery_units.csv. Read them with gbpowerdata.processed.read_generation_battery(year),
read_generation_battery(summary=True) and read_generation_battery(units=True).

Usage: python -m gbpowerdata.build.generation_battery [--years 2018 2025]
       (after b1610_pull --storage-fleet and fpn_pull --storage-fleet, storage_fleet, bm_units and
       ancillary_services; generation_mix for the share)
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from gbpowerdata import config as cfg
from gbpowerdata.build.generation_mix import settlement_start, spine
from gbpowerdata.common.elexon import fpn_energy

GROUPS = ("transmission", "embedded", "supplier", "vlp")       # the BM units, metered and notified
RESPONSE_GROUPS = GROUPS + ("non_bm",)
BASES = ("metered", "notified")
FLOWS = ("discharge", "charge")
RESPONSE_SERVICES = ("DC", "DM", "DR", "SFFR", "DFFR")         # ancillary_services' frequency response services
PRODUCTS = ("dcl", "dch", "dml", "dmh", "drl", "drh", "sffr", "dffr")
ANCILLARY_FROM = pd.Timestamp("2019-01-01", tz="UTC")          # the first unit-level results (FFR tender TR108)
GSP_GROUPS = ("Eastern", "East Midlands", "London", "Merseyside North Wales", "Midlands", "Northern", "North Western",
              "Southern", "South Eastern", "South Wales", "South Western", "Yorkshire", "South Scotland",
              "North Scotland")
UNKNOWN = "unknown"
UNIT_COLUMNS = (["year", "unit_id", "unit_name", "group", "gsp_group", "postcode", "capacity_mw", "capacity_source", "active_from",
                 "active_to", "discharge_metered_mwh", "charge_metered_mwh", "coverage_metered",
                 "discharge_notified_mwh", "charge_notified_mwh", "coverage_notified"]
                + [f"response_{p}_mw" for p in PRODUCTS])


def _gsp_key(name: str) -> str:
    words = re.sub(r"^_[A-P]\s*-\s*", "", str(name)).lower().split()
    return " ".join(w for w in words if w not in ("gsp", "group", "of"))


GSP_KEYS = {_gsp_key(g): g for g in GSP_GROUPS}


def gsp_group_name(name) -> str | None:
    """A GSP group in one spelling ("Eastern GSP Group", "_F - Northern", "SOUTH of SCOTLAND GSP" as the register and
    storage_fleet have them); None for a blank or a name that is not one of the 14."""
    return GSP_KEYS.get(_gsp_key(name)) if pd.notna(name) and str(name).strip() else None


def group_of(unit_id: str, kind: str) -> str:
    """T_ transmission, E_ embedded, and storage_fleet's supplier, vlp and non_bm kinds."""
    if kind == "bm":
        return "transmission" if str(unit_id).startswith("T_") else "embedded"
    return kind


def metered_energy(path: Path) -> pd.Series:
    """A unit's B1610 metered output per half-hour (MWh, signed: export positive), by UTC start of the period."""
    d = pd.read_csv(path, usecols=["settlementDate", "settlementPeriod", "quantity"])
    d["startTime"] = settlement_start(d["settlementDate"], d["settlementPeriod"])
    return d.drop_duplicates("startTime", keep="last").set_index("startTime")["quantity"].astype(float)


def active(idx: pd.DatetimeIndex, active_from, active_to) -> np.ndarray:
    """Whether each half-hour lies within [active_from, active_to] (whole UTC days; blank = open)."""
    ok = np.ones(len(idx), bool)
    if pd.notna(active_from) and str(active_from) != "":
        ok &= idx >= pd.Timestamp(active_from).normalize().tz_localize("UTC")
    if pd.notna(active_to) and str(active_to) != "":
        ok &= idx < pd.Timestamp(active_to).normalize().tz_localize("UTC") + pd.Timedelta(days=1)
    return ok


# ---------------------------------------------------------------------------- energy
def assemble(year: int, units: pd.DataFrame, energy: dict[str, dict[str, pd.Series]],
             generation: pd.Series | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The half-hourly energy columns of `year` and per BM unit, basis and month the figures the summary needs
    (discharge_mwh, charge_mwh, active_hh, covered_hh). `units` holds unit_id, group, active_from and active_to (units
    outside GROUPS are left out); `energy` maps a basis to each unit's signed MWh per half-hour."""
    idx = spine(year)
    month = idx.strftime("%Y-%m")
    units = units[units["group"].isin(GROUPS)]
    out = pd.DataFrame(index=idx)
    n_active = {g: np.zeros(len(idx)) for g in GROUPS}
    rows = []
    for basis in BASES:
        sums = {(f, g): np.zeros(len(idx)) for f in FLOWS for g in GROUPS}
        n_value = {g: np.zeros(len(idx)) for g in GROUPS}
        for u in units.itertuples(index=False):
            on = active(idx, u.active_from, u.active_to)
            if basis == BASES[0]:
                n_active[u.group] += on
            e = energy.get(basis, {}).get(u.unit_id)
            mwh = e.reindex(idx).to_numpy(float) if e is not None else np.full(len(idx), np.nan)
            has = ~np.isnan(mwh)
            dis, ch = np.clip(np.nan_to_num(mwh), 0, None), -np.clip(np.nan_to_num(mwh), None, 0)
            sums["discharge", u.group] += dis * 2
            sums["charge", u.group] += ch * 2
            n_value[u.group] += has & on
            m = pd.DataFrame({"discharge_mwh": dis, "charge_mwh": ch, "active_hh": on, "covered_hh": has & on})
            rows.append(m.groupby(month).sum().rename_axis("month").reset_index()
                        .assign(unit_id=u.unit_id, group=u.group, basis=basis))
        # a unit's energy outside its activity counts (it flowed), its coverage only inside; a column is 0 where no
        # unit is active and empty where units are active but none has a value
        n_act, n_val = sum(n_active.values()), sum(n_value.values())
        for f in FLOWS:
            for g in GROUPS:
                v = sums[f, g]
                out[f"{f}_{basis}_{g}_mw"] = np.where((n_active[g] > 0) & (n_value[g] == 0) & (v == 0), np.nan, v)
            v = sum(sums[f, g] for g in GROUPS)
            out[f"{f}_{basis}_mw"] = np.where((n_act > 0) & (n_val == 0) & (v == 0), np.nan, v)
        out[f"net_{basis}_mw"] = out[f"discharge_{basis}_mw"] - out[f"charge_{basis}_mw"]
        out[f"units_{basis}"] = sum(n_value.values()).astype(int)
    out["units_active"] = sum(n_active.values()).astype(int)
    out["generation_mw"] = generation.reindex(idx) if generation is not None else np.nan
    cols = ["unit_id", "group", "basis", "month", "discharge_mwh", "charge_mwh", "active_hh", "covered_hh"]
    unit_months = pd.concat(rows, ignore_index=True)[cols] if rows else pd.DataFrame(columns=cols)
    return out, unit_months


# ---------------------------------------------------------------------------- response
def response_rows(anc: pd.DataFrame, fleet: pd.Series) -> pd.DataFrame:
    """ancillary_by_unit's frequency response rows of the fleet's batteries: delivery_start, delivery_end (UTC),
    unit_id, group, product (PRODUCTS) and mw. `fleet` maps a battery's id to its group: the Elexon id of a BM unit,
    NESO's own id of a non-BM one (matched where the row has no Elexon id)."""
    a = anc[anc["service"].isin(RESPONSE_SERVICES) & (anc["mw"] > 0)]
    bm = fleet[fleet != "non_bm"]
    uid = a["elexon_unit"].where(a["elexon_unit"].isin(bm.index))
    nb = a["unit"].where(a["elexon_unit"].isna() & a["unit"].isin(fleet[fleet == "non_bm"].index))
    uid = uid.fillna(nb)
    product = a["service"].where(a["service"].isin(["SFFR", "DFFR"]), a["product"]).str.lower()
    out = pd.DataFrame({"delivery_start": pd.to_datetime(a["delivery_start"], utc=True),
                        "delivery_end": pd.to_datetime(a["delivery_end"], utc=True),
                        "unit_id": uid, "product": product, "mw": a["mw"].astype(float)}).dropna(subset=["unit_id"])
    out["group"] = out["unit_id"].map(fleet)
    return out.reset_index(drop=True)


def response_held(rows: pd.DataFrame, idx: pd.DatetimeIndex,
                  published_to: pd.Timestamp | None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The MW accepted per half-hour of `idx` by product, for the fleet and by group, and per unit, group, product and
    month the MWh it was held for (MW x 0.5 h over the month's half-hours, so a block over midnight at a month's end
    is split between the months). The half-hourly columns are empty before ANCILLARY_FROM and from `published_to`
    (None: no results at all)."""
    i0 = idx.searchsorted(rows["delivery_start"].to_numpy())
    i1 = idx.searchsorted(rows["delivery_end"].to_numpy())
    mw = rows["mw"].to_numpy(float)
    months = idx.strftime("%Y-%m")
    codes, labels = pd.factorize(months)
    zero = np.zeros(len(idx))
    held, unit_rows = {}, []
    for (uid, g, p), k in rows.groupby(["unit_id", "group", "product"]).indices.items():
        d = np.zeros(len(idx) + 1)
        np.add.at(d, i0[k], mw[k])
        np.add.at(d, i1[k], -mw[k])
        v = np.cumsum(d)[:-1]
        held[p, g] = held.get((p, g), zero) + v
        mwh = np.bincount(codes, weights=v * 0.5, minlength=len(labels))
        unit_rows.append(pd.DataFrame({"unit_id": uid, "group": g, "product": p, "month": labels, "mwh_held": mwh}))
    out = pd.DataFrame(index=idx)
    for p in PRODUCTS:
        out[f"response_{p}_mw"] = sum((held.get((p, g), zero) for g in RESPONSE_GROUPS), zero)
    for p in PRODUCTS:
        for g in RESPONSE_GROUPS:
            out[f"response_{p}_{g}_mw"] = held.get((p, g), zero)
    unpublished = (idx < ANCILLARY_FROM) | (True if published_to is None else idx >= published_to)
    out.loc[unpublished] = np.nan
    cols = ["unit_id", "group", "product", "month", "mwh_held"]
    um = pd.concat(unit_rows, ignore_index=True) if unit_rows else pd.DataFrame(columns=cols)
    return out.round(3), um[um["mwh_held"] > 0].reset_index(drop=True)


# ---------------------------------------------------------------------------- summary
def capacity(units: pd.DataFrame, idx: pd.DatetimeIndex, key, by: str) -> pd.DataFrame:
    """The mean capacity in place per period (`key` of each half-hour) and value of `by`: each unit's capacity_mw over
    the half-hours inside its activity, averaged over the period's half-hours."""
    parts = {}
    for value, u in units.groupby(by):
        mw = np.zeros(len(idx))
        for r in u.itertuples(index=False):
            mw += np.where(active(idx, r.active_from, r.active_to), np.nan_to_num(float(r.capacity_mw)), 0.0)
        parts[value] = pd.Series(mw, index=idx).groupby(key).mean()
    return pd.DataFrame(parts)


def summarise(t: pd.DataFrame, unit_months: pd.DataFrame, units: pd.DataFrame,
              resp_months: pd.DataFrame | None = None, regions: pd.Series | None = None) -> pd.DataFrame:
    """Energy (GWh), mean MW, share of generation, units, capacity and coverage by year and by month, basis, group or
    GSP group, and flow (long), from one year's half-hourly table, assemble()'s unit months, the units (with group,
    gsp_group, capacity_mw and their activity) and response_held()'s unit months; `regions` (unit -> GSP group) adds the
    regions of units paid for response outside the year's units."""
    region = units.drop_duplicates("unit_id").set_index("unit_id")["gsp_group"]
    if regions is not None:
        region = region.combine_first(regions)
    um = unit_months.assign(year=unit_months["month"].str[:4], gsp_group=unit_months["unit_id"].map(region),
                            moved=(unit_months["discharge_mwh"] + unit_months["charge_mwh"]) > 0)
    rm = (resp_months if resp_months is not None else
          pd.DataFrame(columns=["unit_id", "group", "product", "month", "mwh_held"]))
    rm = rm.assign(year=rm["month"].str[:4], gsp_group=rm["unit_id"].map(region).fillna(UNKNOWN))
    bm_units = units[units["group"].isin(GROUPS)]
    gen = t["generation_mw"]
    rows = []

    def row(**k):
        rows.append(dict(resolution=k["resolution"], period=k["period"], basis=k["basis"], group=k.get("group", "all"),
                         gsp_group=k.get("gsp_group", "all"), flow=k["flow"], energy_gwh=k.get("energy_gwh", np.nan),
                         mean_mw=k["mean_mw"], share_of_generation=k.get("share", np.nan), units=int(k["units"]),
                         capacity_mw=round(float(k["capacity_mw"]), 1), coverage=k["coverage"]))

    for resolution, key in (("year", t.index.strftime("%Y")), ("month", t.index.strftime("%Y-%m"))):
        periods = sorted(set(key))
        cap = capacity(units, t.index, key, "group").reindex(columns=list(RESPONSE_GROUPS), fill_value=0.0)
        cap_bm = cap[list(GROUPS)].sum(axis=1)
        cap_region = capacity(bm_units, t.index, key, "gsp_group")
        cap_region_all = capacity(units, t.index, key, "gsp_group")
        n_hh = pd.Series(1, index=t.index).groupby(key).sum()
        u_key = "year" if resolution == "year" else "month"
        for basis in BASES:
            ub = um[um["basis"] == basis]
            for group in ("all",) + GROUPS:
                sfx = "" if group == "all" else f"_{group}"
                u = ub if group == "all" else ub[ub["group"] == group]
                moved = u.groupby([u_key, "unit_id"])["moved"].any().groupby(level=0).sum()
                cov = u.groupby(u_key)["covered_hh"].sum() / u.groupby(u_key)["active_hh"].sum().replace(0, np.nan)
                dis, ch = t[f"discharge_{basis}{sfx}_mw"], t[f"charge_{basis}{sfx}_mw"]
                both = dis.notna() & gen.notna()
                share = dis.where(both).groupby(key).sum(min_count=1) / gen.where(both).groupby(key).sum(min_count=1)
                c = cap_bm if group == "all" else cap[group]
                for flow, mw in (("discharge", dis), ("charge", ch), ("net", dis - ch)):
                    e, m = (mw * 0.5 / 1000).groupby(key).sum(min_count=1), mw.groupby(key).mean()
                    for p in periods:
                        known = cov.get(p, np.nan) != 0      # units active but none with a value: unknown, not 0
                        row(resolution=resolution, period=p, basis=basis, group=group, flow=flow,
                            energy_gwh=round(e.get(p, np.nan), 3) if known else np.nan,
                            mean_mw=round(m.get(p, np.nan), 2) if known else np.nan,
                            share=round(share.get(p, np.nan), 6) if flow == "discharge" and known else np.nan,
                            units=moved.get(p, 0), capacity_mw=c.get(p, 0.0), coverage=round(cov.get(p, np.nan), 5))
            # by GSP group: summed from the units' months, so the regions add up to the fleet
            reg = ub.assign(gsp_group=ub["gsp_group"].fillna(UNKNOWN))
            sums = reg.groupby([u_key, "gsp_group"])[["discharge_mwh", "charge_mwh", "covered_hh", "active_hh"]].sum()
            moved = reg.groupby([u_key, "gsp_group", "unit_id"])["moved"].any().groupby(level=[0, 1]).sum()
            for (p, g), r in sums.iterrows():
                hours = n_hh[p] * 0.5
                cov = r["covered_hh"] / r["active_hh"] if r["active_hh"] else np.nan
                for flow, mwh in (("discharge", r["discharge_mwh"]), ("charge", r["charge_mwh"]),
                                  ("net", r["discharge_mwh"] - r["charge_mwh"])):
                    mwh = mwh if cov != 0 else np.nan
                    row(resolution=resolution, period=p, basis=basis, gsp_group=g, flow=flow,
                        energy_gwh=round(mwh / 1000, 3), mean_mw=round(mwh / hours, 2), units=moved.get((p, g), 0),
                        capacity_mw=cap_region.get(g, pd.Series(dtype=float)).get(p, 0.0),
                        coverage=round(cov, 5))
        # response: the MW accepted, averaged over the half-hours NESO's results cover, from the units' MWh held
        # (so the groups and the regions add up to the fleet)
        published = t[f"response_{PRODUCTS[0]}_mw"].notna().groupby(key).sum()
        hours = published * 0.5
        cov = (published / n_hh).round(5)
        cap_all = cap.sum(axis=1)
        for by, values in (("group", ("all",) + RESPONSE_GROUPS), ("gsp_group", None)):
            values = values or sorted(set(rm["gsp_group"]))
            for v in values:
                r = rm if v == "all" else rm[rm[by] == v]
                mwh = r.groupby([u_key, "product"])["mwh_held"].sum()
                held = r.groupby([u_key, "product"])["unit_id"].nunique()
                if by == "group":
                    c = cap_all if v == "all" else cap[v]
                else:
                    c = cap_region_all.get(v, pd.Series(dtype=float))
                for p in periods:
                    if by == "gsp_group" and p not in mwh.index.get_level_values(0):
                        continue
                    for prod in PRODUCTS:
                        h = hours.get(p, 0)
                        row(resolution=resolution, period=p, basis="response", flow=prod,
                            **({"group": v} if by == "group" else {"gsp_group": v}),
                            mean_mw=round(mwh.get((p, prod), 0.0) / h, 2) if h else np.nan,
                            units=held.get((p, prod), 0), capacity_mw=c.get(p, 0.0), coverage=cov.get(p, 0.0))
    return pd.DataFrame(rows)
    return pd.DataFrame(rows)


def unit_table(year: int, units: pd.DataFrame, unit_months: pd.DataFrame, resp_months: pd.DataFrame,
               published_hours: float, fleet: pd.DataFrame | None = None,
               postcodes: pd.Series | None = None) -> pd.DataFrame:
    """One row per unit of the year: its group, GSP group, capacity, activity, metered and notified energy with their
    coverage, and the MW NESO accepted from it per response product, averaged over the half-hours its results
    cover; a unit paid for response but outside the
    year's units is added from `fleet` (storage_fleet's batteries); postcode from `postcodes` (id_key(National Grid
    id) -> postcode, storage_fleet.eac_postcodes)."""
    if fleet is not None:
        extra = fleet[fleet["unit_id"].isin(resp_months["unit_id"]) & ~fleet["unit_id"].isin(units["unit_id"])]
        units = pd.concat([units, extra.assign(gsp_group=extra["gsp_group"].fillna(UNKNOWN))], ignore_index=True)
    out = units.drop_duplicates("unit_id").set_index("unit_id").copy()
    if postcodes is not None and "ngc_id" in out:
        from gbpowerdata.build.storage_fleet import id_key
        out["postcode"] = out["ngc_id"].map(lambda x: postcodes.get(id_key(x)) if pd.notna(x) else None)
    for basis in BASES:
        u = unit_months[unit_months["basis"] == basis].groupby("unit_id")[
            ["discharge_mwh", "charge_mwh", "covered_hh", "active_hh"]].sum()
        out[f"discharge_{basis}_mwh"] = u["discharge_mwh"].round(3)
        out[f"charge_{basis}_mwh"] = u["charge_mwh"].round(3)
        out[f"coverage_{basis}"] = (u["covered_hh"] / u["active_hh"].replace(0, np.nan)).round(5)
    held = resp_months.pivot_table(index="unit_id", columns="product", values="mwh_held", aggfunc="sum")
    for p in PRODUCTS:
        v = held[p] if p in held else pd.Series(dtype=float)
        out[f"response_{p}_mw"] = ((v.reindex(out.index).fillna(0.0) / published_hours).round(3)
                                   if published_hours else np.nan)
    return out.reset_index().assign(year=year).reindex(columns=UNIT_COLUMNS)


# ---------------------------------------------------------------------------- inputs
def load_energy(units: pd.DataFrame, raw: Path) -> dict[str, dict[str, pd.Series]]:
    """Each BM unit's metered (B1610) and notified (FPN) energy, from the files there are."""
    energy = {b: {} for b in BASES}
    for uid in units.loc[units["group"].isin(GROUPS), "unit_id"].unique():
        name = f"{str(uid).replace('/', '_')}.csv"
        if (raw / "b1610" / name).exists():
            energy["metered"][uid] = metered_energy(raw / "b1610" / name)
        if (raw / "fpn" / name).exists():
            energy["notified"][uid] = fpn_energy(raw / "fpn" / name)
    return energy


def fleet_batteries(processed: Path | None = None) -> pd.DataFrame:
    """storage_fleet's batteries: unit_id (the Elexon id, NESO's for a non-BM unit), ngc_id, unit_name, group,
    gsp_group, capacity_mw, capacity_source, active_from (entry_date) and active_to (last_seen)."""
    f = pd.read_csv((cfg.processed_dir() if processed is None else Path(processed)) / "storage_fleet.csv")
    f = f[f["tech"].eq("battery")]
    return pd.DataFrame({"unit_id": f["unit_id"], "ngc_id": f["ngc_id"], "unit_name": f["unit_name"],
                         "group": [group_of(i, k) for i, k in zip(f["unit_id"], f["kind"])],
                         "gsp_group": f["gsp_group"].map(gsp_group_name), "capacity_mw": f["capacity_mw"],
                         "capacity_source": f["capacity_source"], "active_from": f["entry_date"],
                         "active_to": f["last_seen"]}).reset_index(drop=True)


def battery_units(year: int, fleet: pd.DataFrame) -> pd.DataFrame:
    """The year's battery units: storage_revenues.units (the register's T_ and E_ units, storage_fleet's supplier and
    virtual lead party ones) and storage_fleet's non-BM ones active in the year, with group and gsp_group."""
    from gbpowerdata.build import storage_revenues as SR

    u = SR.units(year)
    u = u[u["tech"].eq("battery")].copy()
    u["group"] = [group_of(i, k) for i, k in zip(u["unit_id"], u["kind"])]
    region = fleet.drop_duplicates("unit_id").set_index("unit_id")["gsp_group"]
    reg = u["gsp_group"].map(gsp_group_name) if "gsp_group" in u else pd.Series(None, index=u.index)
    u["gsp_group"] = reg.fillna(u["unit_id"].map(region))
    nb = fleet[fleet["group"].eq("non_bm")]
    start, end = pd.to_datetime(nb["active_from"]), pd.to_datetime(nb["active_to"])
    nb = nb[(start <= pd.Timestamp(f"{year}-12-31")) & (end >= pd.Timestamp(f"{year}-01-01"))]
    cols = ["unit_id", "ngc_id", "unit_name", "group", "gsp_group", "capacity_mw", "capacity_source", "active_from",
            "active_to"]
    out = pd.concat([u[cols], nb[cols]], ignore_index=True)
    out["gsp_group"] = out["gsp_group"].fillna(UNKNOWN)
    return out


def ancillary(year: int, processed: Path) -> tuple[pd.DataFrame, pd.Timestamp | None]:
    """The year's ancillary_by_unit rows, with the previous year's that run into it, and the end of the last delivery
    the year's file holds (None without it)."""
    cols = ["delivery_start", "delivery_end", "service", "product", "unit", "elexon_unit", "mw"]
    path = processed / f"ancillary_by_unit_{year}.csv"
    if year < ANCILLARY_FROM.year or not path.exists():
        return pd.DataFrame(columns=cols), None
    a = pd.read_csv(path, usecols=cols)
    published_to = pd.to_datetime(a["delivery_end"], utc=True).max()
    prev = processed / f"ancillary_by_unit_{year - 1}.csv"
    if prev.exists():
        p = pd.read_csv(prev, usecols=cols)
        a = pd.concat([p[pd.to_datetime(p["delivery_end"], utc=True) > pd.Timestamp(f"{year}-01-01", tz="UTC")], a])
    return a, published_to


def _merge(path: Path, new: pd.DataFrame, years: list[int], year_of) -> pd.DataFrame:
    """`new` with the rows of the file at `path` whose year (year_of) was not rebuilt."""
    if not path.exists():
        return new
    old = pd.read_csv(path, dtype={"period": str})
    return pd.concat([old[~year_of(old).isin([str(y) for y in years])], new], ignore_index=True)


def build(years: list[int]) -> None:
    raw, proc = cfg.raw_dir(), cfg.processed_dir()
    if not (proc / "storage_fleet.csv").exists():
        raise SystemExit("storage_fleet.csv is missing: run python -m gbpowerdata.build.storage_fleet")
    fleet = fleet_batteries(proc)
    fleet_group = fleet.drop_duplicates("unit_id").set_index("unit_id")["group"]
    from gbpowerdata.build.storage_fleet import eac_postcodes
    postcodes = eac_postcodes(raw)
    summaries, unit_rows = [], []
    for y in years:
        u = battery_units(y, fleet)
        energy = load_energy(u, raw)
        mix = proc / f"generation_mix_{y}.csv"
        gen = (pd.read_csv(mix, usecols=["startTime", "generation_mw"], index_col="startTime",
                           parse_dates=["startTime"])["generation_mw"] if mix.exists() else None)
        t, um = assemble(y, u, energy, gen)
        anc, published_to = ancillary(y, proc)
        rows = response_rows(anc, fleet_group)
        resp, rm = response_held(rows, t.index, published_to)
        t = t.join(resp)
        order = ([f"{f}_{b}_mw" for b in BASES for f in FLOWS] + [f"net_{b}_mw" for b in BASES]
                 + [f"{f}_{b}_{g}_mw" for b in BASES for f in FLOWS for g in GROUPS]
                 + [f"response_{p}_mw" for p in PRODUCTS]
                 + [f"response_{p}_{g}_mw" for p in PRODUCTS for g in RESPONSE_GROUPS]
                 + ["units_active", "units_metered", "units_notified", "generation_mw"])
        t = t[order]
        t.to_csv(proc / f"generation_battery_{y}.csv", float_format="%.6g")
        s = summarise(t, um, u, rm, fleet.drop_duplicates("unit_id").set_index("unit_id")["gsp_group"])
        summaries.append(s)
        unit_rows.append(unit_table(y, u, um, rm, float(t[f"response_{PRODUCTS[0]}_mw"].notna().sum()) * 0.5, fleet, postcodes))
        yr = s[(s["resolution"] == "year") & (s["group"] == "all") & (s["gsp_group"] == "all")]
        yr = yr.set_index(["basis", "flow"])
        print(f"[{y}] -> generation_battery_{y}.csv  {len(u)} units ({len(energy['metered'])} metered, "
              f"{len(energy['notified'])} notified files, {rows['unit_id'].nunique()} in response)  GWh metered "
              f"discharge {yr.at[('metered', 'discharge'), 'energy_gwh']} charge "
              f"{yr.at[('metered', 'charge'), 'energy_gwh']}, notified discharge "
              f"{yr.at[('notified', 'discharge'), 'energy_gwh']} charge {yr.at[('notified', 'charge'), 'energy_gwh']}; "
              f"response MW dcl {yr.at[('response', 'dcl'), 'mean_mw']} dch {yr.at[('response', 'dch'), 'mean_mw']}",
              flush=True)
    path = proc / "generation_battery_summary.csv"
    s = _merge(path, pd.concat(summaries, ignore_index=True), years, lambda d: d["period"].str[:4])
    s = s.sort_values(["resolution", "period"], kind="stable", ascending=[False, True]).reset_index(drop=True)
    s.to_csv(path, index=False)
    path_u = proc / "generation_battery_units.csv"
    u = _merge(path_u, pd.concat(unit_rows, ignore_index=True), years, lambda d: d["year"].astype(str))
    u.sort_values(["year", "group", "unit_id"]).to_csv(path_u, index=False)
    print(f"  generation_battery_summary.csv: {len(s)} rows, years {sorted(set(s.loc[s.resolution == 'year', 'period']))}"
          f"; generation_battery_units.csv: {len(u)} rows")


def main(argv: list[str]) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--years", nargs=2, type=int, default=[2018, 2025])
    a = p.parse_args(argv)
    build(list(range(a.years[0], a.years[1] + 1)))


if __name__ == "__main__":
    main(sys.argv[1:])
