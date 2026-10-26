"""Operating limits of GB thermal plant, per BM unit and by technology, from the Balancing Mechanism
dynamic data -> data/processed/bm_dynamic_units.csv (one row per snapshot and active BM unit) and
data/reference/bm_dynamic_by_tech.csv (technology x metric x period: n, median, p10, p90).

WHY
    Unit-commitment and agent models need, per plant, a minimum stable level, ramp rates, a start-up
    notice and minimum up and down times. The generic values in data/reference/thermal_parameters.csv
    (DIW, Agora, the Danish Energy Agency, PyPSA-Eur) are German, Danish or US engineering estimates.
    The BM dynamic data are what each GB unit itself declares to NESO, under the Grid Code obligation
    that they "reasonably reflect the true current operating characteristics of the BM Unit"
    (BC2.5.3.1). gbpowerdata.pull.bm_dynamic_pull describes the datasets and fetches the snapshots.

METHOD
    Snapshots at settlement period 24 on the 15th of January, April, July and October 2018-2025 (the
    pull module's DEFAULT_DATES). For each unit and dataset, the value in force at the START of the
    period: the latest record at or before it, or, for a unit that first declared during the period, its
    first record. Units are matched to that year's register (data/processed/bm_unit_register_{year}.csv,
    gbpowerdata.build.bm_units) on the NGC id, because Elexon's own id is empty for units it no longer
    lists, and kept where the register has them active with an activity window covering the date.
    Derived per unit and snapshot:
      sel_share_capacity      SEL / register capacity, for an available unit (MEL > 0)
      sel_share_capacity_running  the same for a unit that is also running (FPN > 0): see THE CAVEAT;
                              a model's minimum stable level per MW of nameplate (PyPSA p_min_pu,
                              ASSUME min_power / max_power)
      sel_share_mel           SEL / MEL (MEL > 0)
      sel_share_mel_running   SEL / MEL for a unit that is also running
      run_up_share_per_min    (capacity - SEL) / minutes RURE takes from SEL to capacity, per MW of capacity
      run_down_share_per_min  the same, down RDRE from capacity to SEL
      time_zero_to_sel_min    minutes RURE takes from 0 to SEL, the run-up after synchronising
      time_sel_to_zero_min    minutes RDRE takes from SEL to 0
      ndz_min, mzt_min, mnzt_min as declared
    Rates with elbows (Grid Code BC1.A.1.5; NESO DVC&D rules V_RURE_5, V_RDRE_5): RURE rate1 applies
    from 0 MW up to elbow2, rate2 from elbow2 to elbow3, rate3 above; RDRE rate1 applies from the top
    down to elbow2, rate2 down to elbow3, rate3 below. A segment of 999 MW/min, the top of the valid
    range, is a step (an instantaneous synchronisation or desynchronisation block) and takes no time.
    The summary pools unit-snapshots with equal weight, per year and over 2018-2025. A value of 999 for
    NDZ, MZT or MNZT ("will not start at notice", typically a mothballed or unavailable unit) is kept in
    the unit table and left out of the summary, which reports how often it occurs (share_999).

THE CAVEAT, WHICH TRAVELS WITH THE NUMBERS
    Dynamic parameters are declared, not measured, and some have been declared commercially. Ofgem
    found SELs inflated to raise Balancing Mechanism payments (InterGen, 15 Apr 2020; EDF Energy West
    Burton B, 16 Dec 2020; ESB Carrington, 24 Aug 2021) and wrote on 29 Sep 2020 that a unit with a zero
    PN "should not submit a higher SEL than it would normally set". The pattern shows here: SEL / MEL is
    higher for units that are not running, so the *_running shares are the physical minimum stable level.
    MZT and MNZT are largely conventions (6 h for most CCGTs) that operators use to manage the start
    limits of their long-term service agreements (West Burton Energy's and RWE's responses to Ofgem's
    Inflexible Offers Licence Condition consultation, 2023): minimum up and down times as operated, not
    as engineered. Start-related values depend on the unit's thermal state, and a snapshot finds some
    units hot and some cold, so NDZ and the 0 -> SEL time mix start types; a CCGT's lowest NDZ in a year,
    about 60 min, is its hot-start notice. Nuclear units publish only SEL.

COVERAGE
    Only units the register holds are summarised. Elexon's 2026 unit list no longer carries Aberthaw B,
    Cottam or Eggborough (coal, closed 2018-2020) or Deeside's CCGT; since 14 Oct 2026 the register adds them
    from data/reference/bmu_left_register.csv (gbpowerdata.build.bm_units), with Aberthaw's three gas turbines.
    The build of 26 Oct 2026 takes them in: the coal rows of data/reference/bm_dynamic_by_tech.csv describe 25
    units (Aberthaw B, Cottam, Drax 5-6, Eggborough, Fiddler's Ferry, Ratcliffe-on-Soar, West Burton A), 14
    before, and the unit table holds 3,990 unit-snapshots (3,913 before). The coal medians of minimum stable
    level (0.46 of capacity) and minimum up and down time (6 h) stay as they were and the ramp rates move by 2%
    or less; the start-up notice rises from 6.0 to 6.3 h, and the 90th percentile of the minimum stable level
    from 0.56 to 0.70, because Aberthaw B declared an SEL of 380 MW on its 520 MW units. Eggborough appears in
    one snapshot (15 Jan 2018), before it stopped running in February and March 2018. No oil-fired BM unit is
    active in the register in 2018-2025. The register's "ocgt" class is mostly small open-cycle units of
    15-140 MW (the auxiliary gas turbines at coal and CCGT sites, Cowes, Indian Queens, Taylor's Lane)
    that run at or near full output, plus Spalding's 300 MW open-cycle unit.

Usage:  python -m gbpowerdata.build.bm_dynamic [--pull]     (--pull fetches missing snapshots first)
"""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from gbpowerdata import config as cfg
from gbpowerdata.pull import bm_dynamic_pull as pull

TECHS = ("ccgt", "ocgt", "coal", "oil", "biomass", "nuclear", "pumped_storage")
DYN = ("SEL", "SIL", "MZT", "MNZT", "MDV", "MDP", "NTB", "NTO", "NDZ")
RATES = ("RURE", "RDRE", "RURI", "RDRI")
RATE_COLS = ("rate1", "elbow2", "rate2", "elbow3", "rate3")
SENTINEL = 999.0
UNITS_FILE = "bm_dynamic_units.csv"
SUMMARY_FILE = "bm_dynamic_by_tech.csv"
PERIOD_ALL = "2018-2025"

# summary metrics: (column, unit, description)
METRICS = [
    ("sel_share_capacity", "fraction", "SEL / register capacity, available units (MEL > 0)"),
    ("sel_share_capacity_running", "fraction", "SEL / register capacity, units running (FPN > 0): p_min_pu on nameplate"),
    ("sel_share_mel", "fraction", "SEL / MEL, available units"),
    ("sel_share_mel_running", "fraction", "SEL / MEL, units running (FPN > 0): the physical minimum stable level"),
    ("run_up_share_per_min", "fraction/min", "run-up from SEL to capacity on RURE, share of capacity per minute"),
    ("run_down_share_per_min", "fraction/min", "run-down from capacity to SEL on RDRE, share of capacity per minute"),
    ("time_zero_to_sel_min", "min", "run-up from 0 MW to SEL on RURE"),
    ("time_sel_to_zero_min", "min", "run-down from SEL to 0 MW on RDRE"),
    ("ndz_min", "min", "notice to deviate from zero (start-up notice), 999 excluded"),
    ("mzt_min", "min", "minimum zero time (minimum down time), 999 excluded"),
    ("mnzt_min", "min", "minimum non-zero time (minimum up time), 999 excluded"),
]


def sp_start_utc(date: str, sp: int = pull.SP) -> pd.Timestamp:
    """Start of settlement period `sp` of the GB settlement day `date` (period 1 starts at local midnight)."""
    return (pd.Timestamp(date).tz_localize("Europe/London") + pd.Timedelta(minutes=30 * (sp - 1))).tz_convert("UTC")


def _read(path) -> pd.DataFrame:
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame(columns=["dataset", "nationalGridBmUnit", "bmUnit", "time"])


def _in_force(df: pd.DataFrame, start: pd.Timestamp) -> pd.DataFrame:
    """Per (dataset, NGC unit) the record in force at `start`: the latest at or before it, else the first after."""
    if df.empty:
        return df
    df = df.assign(time=pd.to_datetime(df["time"], utc=True)).sort_values("time")
    key = ["dataset", "nationalGridBmUnit"]
    before = df[df["time"] <= start].groupby(key).tail(1)
    after = df[df["time"] > start].groupby(key).head(1)
    after = after[~after.set_index(key).index.isin(before.set_index(key).index)]
    return pd.concat([before, after], ignore_index=True)


def _segments_up(r1, e2, r2, e3, r3):
    """RURE as (from MW, to MW, rate): rate1 from 0 to elbow2, rate2 to elbow3, rate3 above."""
    if pd.isna(e2):
        return [(0.0, np.inf, r1)]
    if pd.isna(e3):
        return [(0.0, e2, r1), (e2, np.inf, r2)]
    return [(0.0, e2, r1), (e2, e3, r2), (e3, np.inf, r3)]


def _segments_down(r1, e2, r2, e3, r3):
    """RDRE as (from MW, to MW, rate): rate1 from the top down to elbow2, rate2 to elbow3, rate3 below."""
    if pd.isna(e2):
        return [(0.0, np.inf, r1)]
    if pd.isna(e3):
        return [(e2, np.inf, r1), (0.0, e2, r2)]
    return [(e2, np.inf, r1), (e3, e2, r2), (0.0, e3, r3)]


def run_minutes(a: float, b: float, rates: tuple, up: bool) -> float:
    """Minutes to move between a and b MW on a unit's declared segments (999 MW/min = a step, no time)."""
    lo, hi = (a, b) if up else (b, a)
    if any(pd.isna(x) for x in (a, b, rates[0])) or hi <= lo:
        return np.nan
    t = 0.0
    for s_lo, s_hi, r in (_segments_up if up else _segments_down)(*rates):
        overlap = max(0.0, min(hi, s_hi) - max(lo, s_lo))
        if overlap <= 0:
            continue
        if pd.isna(r) or r <= 0:
            return np.nan
        if r < SENTINEL:
            t += overlap / r
    return t


def snapshot(date: str, sp: int = pull.SP) -> pd.DataFrame:
    """Every unit's declared values in force at the start of settlement period `sp` on `date`, wide."""
    start = sp_start_utc(date, sp)
    dyn = _in_force(_read(pull.path("dynamic", date, sp)), start)
    rat = _in_force(_read(pull.path("rates", date, sp)), start)
    parts = []
    if len(dyn):
        w = dyn.pivot(index="nationalGridBmUnit", columns="dataset", values="value")
        parts.append(w.rename(columns={c: f"{c.lower()}_{'mw' if c in ('SEL', 'SIL') else 'mwh' if c == 'MDV' else 'min'}"
                                       for c in w.columns}))
    for ds in RATES:
        s = rat[rat["dataset"] == ds] if len(rat) else rat
        if len(s):
            s = s.set_index("nationalGridBmUnit")[list(RATE_COLS)]
            parts.append(s.add_prefix(f"{ds.lower()}_"))
    for kind, col in (("mels", "mel_mw"), ("pn", "fpn_max_mw")):
        f = _read(pull.path(kind, date, sp))
        if len(f):
            parts.append(f.assign(lv=f[["levelFrom", "levelTo"]].max(axis=1))
                          .groupby("nationalGridBmUnit")["lv"].max().rename(col))
    u = pd.concat(parts, axis=1)
    u.index.name = "ngc_id"
    ids = pd.concat([_read(pull.path(k, date, sp))[["nationalGridBmUnit", "bmUnit"]] for k in pull.KINDS])
    ids = ids.dropna().drop_duplicates("nationalGridBmUnit").set_index("nationalGridBmUnit")["bmUnit"]
    u["elexon_id"] = u.index.map(ids)
    return u.reset_index()


def register(year: int, date: str) -> pd.DataFrame:
    """The year's register rows active on `date`, for the technologies in TECHS."""
    r = pd.read_csv(cfg.processed_dir() / f"bm_unit_register_{year}.csv")
    day = pd.Timestamp(date)
    a_from = pd.to_datetime(r["active_from"], errors="coerce")
    a_to = pd.to_datetime(r["active_to"], errors="coerce")
    live = (r["active"] == True) & (a_from.isna() | (a_from <= day)) & (a_to.isna() | (a_to >= day))  # noqa: E712
    keep = ["unit_id", "ngc_id", "unit_name", "party_name", "tech", "capacity_mw", "demand_capacity_mw"]
    return r.loc[live & r["tech"].isin(TECHS), keep].reset_index(drop=True)


def units_on(date: str, sp: int = pull.SP) -> pd.DataFrame:
    """The register's active thermal and storage units on `date` with their declared values and derived metrics."""
    year = int(date[:4])
    reg, snap = register(year, date), snapshot(date, sp)
    m = reg.merge(snap.drop(columns=["elexon_id"]), on="ngc_id", how="left")
    # a register row whose NGC id the snapshot does not carry: try Elexon's id
    miss = m["sel_mw"].isna() if "sel_mw" in m else pd.Series(True, index=m.index)
    by_elexon = snap.dropna(subset=["elexon_id"]).drop_duplicates("elexon_id").set_index("elexon_id")
    for i in m.index[miss & m["unit_id"].isin(by_elexon.index)]:
        for c in by_elexon.columns.drop("ngc_id"):
            m.at[i, c] = by_elexon.at[m.at[i, "unit_id"], c]
    for c in ["sel_mw", "mel_mw", "fpn_max_mw", "ndz_min", "mzt_min", "mnzt_min"] + \
             [f"{d.lower()}_{c}" for d in ("RURE", "RDRE") for c in RATE_COLS]:
        if c not in m:
            m[c] = np.nan
    m.insert(0, "date", date)
    m.insert(1, "sp", sp)
    m.insert(2, "year", year)
    return derive(m)


def derive(m: pd.DataFrame) -> pd.DataFrame:
    cap = m["capacity_mw"].where(m["capacity_mw"] > 0)
    sel = m["sel_mw"].where(m["sel_mw"] > 0)
    avail = m["mel_mw"] > 0
    m["running"] = m["fpn_max_mw"] > 0
    # a declared SEL above the register capacity (or MEL) by more than 5% says the denominator is stale
    cap = cap.where(~(sel > 1.05 * cap))
    m["sel_share_capacity"] = (sel / cap).where(avail)
    m["sel_share_capacity_running"] = m["sel_share_capacity"].where(m["running"])
    mel_ok = avail & ~(sel > 1.05 * m["mel_mw"])
    m["sel_share_mel"] = (sel / m["mel_mw"]).where(mel_ok)
    m["sel_share_mel_running"] = m["sel_share_mel"].where(m["running"])
    up = [tuple(r) for r in m[[f"rure_{c}" for c in RATE_COLS]].to_numpy(dtype=float)]
    dn = [tuple(r) for r in m[[f"rdre_{c}" for c in RATE_COLS]].to_numpy(dtype=float)]
    s, c = sel.to_numpy(dtype=float), cap.to_numpy(dtype=float)
    t_up = np.array([run_minutes(si, ci, r, True) for si, ci, r in zip(s, c, up)])
    t_dn = np.array([run_minutes(ci, si, r, False) for si, ci, r in zip(s, c, dn)])
    # a range crossed only by 999 MW/min steps takes no time: no rate to report, not an infinite one
    with np.errstate(divide="ignore", invalid="ignore"):
        m["run_up_share_per_min"] = np.where(t_up > 0, (c - s) / t_up / c, np.nan)
        m["run_down_share_per_min"] = np.where(t_dn > 0, (c - s) / t_dn / c, np.nan)
    m["time_zero_to_sel_min"] = [run_minutes(0.0, si, r, True) for si, r in zip(s, up)]
    m["time_sel_to_zero_min"] = [run_minutes(si, 0.0, r, False) for si, r in zip(s, dn)]
    return m


def summarise(units: pd.DataFrame) -> pd.DataFrame:
    """Technology x metric x period (each year and 2018-2025 pooled): n, median, p10, p90, share_999."""
    rows = []
    periods = [(str(y), units["year"] == y) for y in sorted(units["year"].unique())]
    periods.append((PERIOD_ALL, units["year"].between(2018, 2025)))
    for tech in TECHS:
        for period, in_period in periods:
            sub = units[(units["tech"] == tech) & in_period]
            for col, unit, desc in METRICS:
                x = pd.to_numeric(sub[col], errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
                n999 = int((x == SENTINEL).sum()) if col.endswith("_min") and col.startswith(("ndz", "mzt", "mnzt")) else 0
                share999 = n999 / len(x) if len(x) else np.nan
                x = x[x != SENTINEL] if n999 else x
                if not len(x):
                    continue
                rows.append(dict(tech=tech, period=period, metric=col, unit=unit,
                                 n_units=sub.loc[x.index, "unit_id"].nunique(), n_obs=len(x),
                                 median=round(x.median(), 4), p10=round(x.quantile(0.1), 4),
                                 p90=round(x.quantile(0.9), 4), share_999=round(share999, 4),
                                 description=desc))
    return pd.DataFrame(rows)


def build(dates: list[str] | None = None, sp: int = pull.SP, fetch: bool = False) -> tuple[pd.DataFrame, pd.DataFrame]:
    dates = sorted(set(dates or pull.DEFAULT_DATES))
    if fetch:
        pull.pull(dates, sp)
    units = pd.concat([units_on(d, sp) for d in dates], ignore_index=True)
    summary = summarise(units)
    out_u = cfg.processed_dir() / UNITS_FILE
    out_s = cfg.reference_dir() / SUMMARY_FILE
    units.to_csv(out_u, index=False)
    summary.to_csv(out_s, index=False)
    print(f"  {out_u.name}: {len(units)} unit-snapshots on {len(dates)} dates; {out_s.name}: {len(summary)} rows")
    return units, summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pull", action="store_true", help="fetch missing snapshots first")
    a = ap.parse_args()
    build(fetch=a.pull)
