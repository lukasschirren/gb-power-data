"""Run and down times of GB thermal units: how long each BM unit generates once started and stays off once stopped, in
its metered output and in its own notifications, beside the minimum non-zero and zero times it declared to NESO
-> data/processed/unit_spells_{year}.csv (one row per spell) and data/processed/unit_run_times.csv (one row per unit,
year and source).

WHY
    Unit-commitment models give each plant a minimum up and down time. The GB defaults of
    data/reference/thermal_parameters.csv take 6 h for a CCGT from the declared values (bm_dynamic_by_tech.csv,
    gbpowerdata.build.bm_dynamic), and a model with one default holds every CCGT to it. The declarations limit NESO's
    instructions, not the unit's own schedule: the Grid Code (BC1) defines the minimum non-zero time (MNZT) as "the
    minimum time that a BM Unit can operate at a non-zero level as a result of a Bid-Offer Acceptance" and the minimum
    zero time (MZT) as the minimum time a BM unit that has been exporting must operate at zero or import before it
    exports again, "as a result of a Bid-Offer Acceptance" (as Elexon's BSC glossary and NESO's note "Interpretation of
    MZT and MNZT for bi-directional units" quote them: https://www.elexon.co.uk/bsc/glossary/minimum-non-zero-time/,
    https://neso.energy/document/274201/download). What each unit does is in its output: this stage measures the
    spells it ran and was off, unit by unit.

SOURCES (Elexon Insights, BMRS data under Elexon's BMRS data licence: datapack SOURCES["elexon"])
    data/raw/b1610/{unit}.csv   metered output per half-hour (B1610, gbpowerdata.pull.b1610_pull): the register's
                                thermal T_ units and, named with --units, the embedded CCGTs; from 1 February 2019
    data/raw/fpn/{unit}.csv     final physical notifications (gbpowerdata.pull.fpn_pull), from March 2016
    data/raw/bm_dynamic/submissions_{MNZT,MZT,NDZ}_{YYYY-MM}.csv   every declaration with its effective time
                                (gbpowerdata.pull.bm_dynamic_pull --submissions MNZT MZT NDZ), from September 2016
    data/raw/bm_units_*.csv     the register (gbpowerdata.build.bm_units.register): name, technology and capacity, and
                                the NGC ids of declarations that carry no Elexon id
    The units are those with a metering file; each is measured on both sources where it has both files.

METHOD
    Level. The mean MW of each half-hour, keyed on its UTC start: metered MWh x 2 (B1610 keys a half-hour on its end,
    in UTC), or the notified energy x 2 (gbpowerdata.common.elexon.fpn_energy: each segment's mean level x duration).
    On and off. A half-hour is on when its level is at least ON_SHARE (10%) of the unit's full output, taken as the 99th
    percentile of its positive half-hourly levels in the whole file (the register's capacity is zero or out of date
    for some units). 10% lies well under a CCGT's stable export limit (0.47 of capacity, bm_dynamic_by_tech.csv), so a
    run counts from the first half-hour of material output to the last; station load (a small import) and auxiliaries
    count as off.
    Spells. A spell is a maximal sequence of half-hours in one state. One that touches a missing half-hour or either
    end of the file is censored (its length is a lower bound): it stays in the spell table, flagged, and out of the
    statistics. A spell belongs to the UTC year of its first half-hour, 2018 to the current year.
    Per unit, year and source (unit_run_times.csv): hours observed and on, starts (off -> on with both half-hours
    observed), the runs' and downs' count and percentiles (p10, p25, median, p90) in hours, the share under SHORT_H
    (6 h, the GB default), and the two-shift share: the runs under 24 h after which the unit is off for less than 24 h
    (it starts again within a day), as a share of the runs.
    Declared (same values on both sources' rows): the time-weighted mean over the year of the MNZT, MZT and NDZ in
    force, in hours. A declaration holds from its effective time to the next one; the one in force on 1 January counts
    from then, and a unit that first declares during the year counts from its first. 999, the top of the range
    (bm_dynamic.SENTINEL, typically a unit that will not start at notice), is left out of the mean and its share of the
    year given (*_share_999).

READING THE NUMBERS
    The notified spells (source fpn) are the unit's own schedule after the day-ahead and intraday markets; the metered
    ones (b1610) add NESO's instructions in the Balancing Mechanism, which keep units on or bring them on. A market
    model's commitment compares with the notified spells, the system's operation with the metered ones. The lower
    decile of a unit's run lengths is the shortest run it makes as a matter of course; the single shortest runs include
    trips and tests (an inference: the data do not say why a unit stopped).
    In 2023-2025 the median CCGT unit's lower decile of runs was 5.5-6 h in its notifications and 6 h metered, and of
    downs 6.5 h and 6 h, as its declared MNZT and MZT of 6 h (units with ten runs or more in the year). The exceptions:
    Killingholme (declared MNZT 1.3-2 h), Peterborough and Corby (0.5-1.1 h) run a few hours at a time, 86-100% of
    Killingholme's runs under 6 h; Enfield's own schedule had a tenth of its runs at 2.5 h or less in 2024-2025; West
    Burton B, Marchwood and Carrington were off for under 6 h in 16-38% of their metered downs (declared MZT 3-4.7 h)
    against 4-26% of their notified ones, so NESO's instructions brought them back sooner than their own schedules.

OUTPUTS
    data/processed/unit_spells_{year}.csv  year, unit_id, source, state (run/down), start, end (UTC), hours, censored
    data/processed/unit_run_times.csv      year, unit_id, ngc_id, unit_name, tech, capacity_mw, source, full_mw, on_mw,
                                           hours_observed, hours_on, starts, n_runs, run_h_p10/p25/p50/p90,
                                           run_share_under_6h, n_downs, down_h_p10/p25/p50/p90, down_share_under_6h,
                                           two_shift_share, mnzt_h, mnzt_share_999, mzt_h, mzt_share_999, ndz_h,
                                           ndz_share_999
    Read them with gbpowerdata.processed.read_unit_run_times() and read_unit_spells(year).

Usage:  python -m gbpowerdata.build.unit_runs        (all units with a metering file; about five minutes)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from gbpowerdata import config as cfg
from gbpowerdata.build import bm_units as B
from gbpowerdata.build.bm_dynamic import SENTINEL
from gbpowerdata.common.elexon import fpn_energy

ON_SHARE = 0.10                    # on: a level at least this share of the unit's full output
FULL_QUANTILE = 0.99               # the unit's full output: this quantile of its positive levels
SHORT_H = 6.0                      # the GB default minimum up and down time of a CCGT (thermal_parameters.csv)
DAY_H = 24.0                       # two-shift: a run and the down after it both shorter than this
HALF_HOUR = pd.Timedelta("30min")
SOURCES = ("fpn", "b1610")
DECLARED = {"MNZT": "periodMin", "MZT": "periodMin", "NDZ": "notice"}    # dataset -> its value column, minutes
YEARS = B.YEARS
SPELL_COLUMNS = ["year", "unit_id", "source", "state", "start", "end", "hours", "censored"]
PERCENTILES = {"p10": 0.10, "p25": 0.25, "p50": 0.50, "p90": 0.90}
COLUMNS = (["year", "unit_id", "ngc_id", "unit_name", "tech", "capacity_mw", "source", "full_mw", "on_mw",
            "hours_observed", "hours_on", "starts", "n_runs"]
           + [f"run_h_{p}" for p in PERCENTILES] + ["run_share_under_6h", "n_downs"]
           + [f"down_h_{p}" for p in PERCENTILES] + ["down_share_under_6h", "two_shift_share"]
           + [f"{d.lower()}{suffix}" for d in DECLARED for suffix in ("_h", "_share_999")])


# ---------------------------------------------------------------------------- levels
def b1610_levels(path: Path) -> pd.Series:
    """A unit's metered output as mean MW per half-hour, keyed on the half-hour's UTC start."""
    d = pd.read_csv(path, usecols=["halfHourEndTime", "quantity"])
    start = pd.to_datetime(d["halfHourEndTime"], utc=True) - HALF_HOUR
    mw = pd.Series(d["quantity"].astype(float).values * 2.0, index=start)
    return mw[~mw.index.duplicated(keep="last")].sort_index()


def fpn_levels(path: Path) -> pd.Series:
    """A unit's notified level as mean MW per half-hour, keyed on the half-hour's UTC start."""
    return (fpn_energy(path) * 2.0).sort_index()


def states(levels: pd.Series, on_share: float = ON_SHARE) -> tuple[pd.Series, float]:
    """(on/off per half-hour on a complete half-hourly grid: 1.0 on, 0.0 off, NaN missing; the unit's full output)."""
    if levels.empty:
        return pd.Series(dtype=float), np.nan
    positive = levels[levels > 0]
    full = float(positive.quantile(FULL_QUANTILE)) if len(positive) else np.nan
    grid = pd.date_range(levels.index[0], levels.index[-1], freq=HALF_HOUR)
    lv = levels.reindex(grid)
    on = (lv >= on_share * full).astype(float) if np.isfinite(full) else pd.Series(0.0, index=grid)
    return on.where(lv.notna()), full


def spells(state: pd.Series) -> pd.DataFrame:
    """The maximal spells of one state (start, end, hours, state "run" or "down", censored when next to a missing
    half-hour or an end of the series)."""
    if state.empty:
        return pd.DataFrame(columns=["state", "start", "end", "hours", "censored"])
    key = state.fillna(-1.0)
    block = key.ne(key.shift()).cumsum()
    g = pd.DataFrame({"v": key.values, "t": state.index, "block": block.values}).groupby("block", sort=True)
    s = g.agg(v=("v", "first"), start=("t", "first"), last=("t", "last"), n=("v", "size")).reset_index(drop=True)
    before, after = s["v"].shift(1), s["v"].shift(-1)
    s["censored"] = before.isna() | after.isna() | before.eq(-1.0) | after.eq(-1.0)
    s = s[s["v"] >= 0].copy()
    s["state"] = np.where(s["v"] == 1.0, "run", "down")
    s["end"] = s["last"] + HALF_HOUR
    s["hours"] = s["n"] / 2.0
    return s[["state", "start", "end", "hours", "censored"]].reset_index(drop=True)


def two_shift(s: pd.DataFrame) -> pd.Series:
    """Whether each spell is a two-shift run: an uncensored run under DAY_H followed by an uncensored down under DAY_H
    (the spells of one unit and source, in time order)."""
    censored = s["censored"].astype(bool)
    after_state = s["state"].shift(-1, fill_value="")
    after_censored = censored.shift(-1, fill_value=True)
    after_hours = s["hours"].shift(-1, fill_value=np.inf)
    return ((s["state"] == "run") & ~censored & (s["hours"] < DAY_H) & (after_state == "down") & ~after_censored
            & (after_hours < DAY_H))


def by_year(state: pd.Series) -> pd.DataFrame:
    """Hours observed and on, and starts (off -> on, both half-hours observed), per UTC year."""
    year = state.index.year
    started = (state == 1.0) & (state.shift() == 0.0)
    return pd.DataFrame({"hours_observed": state.notna().groupby(year).sum() / 2.0,
                         "hours_on": (state == 1.0).groupby(year).sum() / 2.0,
                         "starts": started.groupby(year).sum().astype(int)}).rename_axis("year")


def spell_stats(s: pd.DataFrame) -> dict:
    """Counts, percentiles and shares of one unit's uncensored spells in one year and source."""
    out = {}
    for state, name in (("run", "run"), ("down", "down")):
        h = s.loc[(s["state"] == state) & ~s["censored"], "hours"]
        out["n_runs" if state == "run" else "n_downs"] = len(h)
        for p, q in PERCENTILES.items():
            out[f"{name}_h_{p}"] = float(h.quantile(q)) if len(h) else np.nan
        out[f"{name}_share_under_6h"] = float((h < SHORT_H).mean()) if len(h) else np.nan
    runs = (s["state"] == "run") & ~s["censored"]
    out["two_shift_share"] = float(s.loc[runs, "two_shift"].mean()) if runs.any() else np.nan
    return out


def measure(levels: pd.Series, years=YEARS) -> tuple[pd.DataFrame, pd.DataFrame, float]:
    """(spells with year and two_shift, per-year rows with the statistics, the unit's full output) of one unit's
    levels from one source."""
    state, full = states(levels)
    s = spells(state)
    s["year"] = pd.DatetimeIndex(s["start"]).year if len(s) else pd.Series(dtype=int)
    s["two_shift"] = two_shift(s) if len(s) else pd.Series(dtype=bool)
    s = s[s["year"].isin(years)]
    hours = by_year(state) if len(state) else pd.DataFrame(columns=["hours_observed", "hours_on", "starts"])
    rows = []
    for y in years:
        if y not in hours.index or hours.at[y, "hours_observed"] == 0:
            continue
        rows.append({"year": y, **hours.loc[y].to_dict(), **spell_stats(s[s["year"] == y])})
    return s.reset_index(drop=True), pd.DataFrame(rows), full


# ---------------------------------------------------------------------------- declarations
def ngc_to_elexon(raw: Path | None = None) -> dict[str, str]:
    """NGC id -> Elexon id over every kept register snapshot (the newest wins)."""
    raw = cfg.raw_dir() if raw is None else Path(raw)
    out = {}
    for f in sorted(raw.glob("bm_units_*.csv")):
        r = pd.read_csv(f, usecols=["nationalGridBmUnit", "elexonBmUnit"]).dropna()
        out.update(dict(zip(r["nationalGridBmUnit"].astype(str), r["elexonBmUnit"].astype(str))))
    return out


def declarations(raw: Path | None = None, units: set[str] | None = None) -> pd.DataFrame:
    """Every MNZT, MZT and NDZ declaration (unit_id, dataset, time UTC, minutes) from the submissions files."""
    raw = cfg.raw_dir() if raw is None else Path(raw)
    folder = raw / "bm_dynamic"
    ngc = None
    parts = []
    for ds, col in DECLARED.items():
        for f in sorted(folder.glob(f"submissions_{ds}_*.csv")):
            try:
                d = pd.read_csv(f, usecols=lambda c: c in ("time", col, "bmUnit", "nationalGridBmUnit"))
            except pd.errors.EmptyDataError:
                continue
            if d.empty or col not in d:
                continue
            if "bmUnit" not in d:
                d["bmUnit"] = np.nan
            if d["bmUnit"].isna().any():
                ngc = ngc_to_elexon(raw) if ngc is None else ngc
                d["bmUnit"] = d["bmUnit"].fillna(d["nationalGridBmUnit"].astype(str).map(ngc))
            d = d.dropna(subset=["bmUnit", col])
            parts.append(pd.DataFrame({"unit_id": d["bmUnit"].astype(str), "dataset": ds,
                                       "time": pd.to_datetime(d["time"], utc=True), "minutes": d[col].astype(float)}))
    if not parts:
        return pd.DataFrame(columns=["unit_id", "dataset", "time", "minutes"])
    out = pd.concat(parts, ignore_index=True)
    if units is not None:
        out = out[out["unit_id"].isin(units)]
    return (out.sort_values(["unit_id", "dataset", "time"])
            .drop_duplicates(["unit_id", "dataset", "time"], keep="last").reset_index(drop=True))


def in_force(d: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> tuple[float, float]:
    """(time-weighted mean in hours without the sentinel, the sentinel's share of the time) of one unit's declarations
    of one dataset (time-sorted) between start and end."""
    before = d[d["time"] <= start].tail(1).assign(time=start)
    seg = pd.concat([before, d[(d["time"] > start) & (d["time"] < end)]], ignore_index=True)
    if seg.empty:
        return np.nan, np.nan
    seconds = (seg["time"].shift(-1).fillna(end) - seg["time"]).dt.total_seconds()
    sentinel = seg["minutes"] >= SENTINEL
    total = seconds.sum()
    if total <= 0:
        return np.nan, np.nan
    kept = seconds[~sentinel]
    mean = float(np.average(seg.loc[~sentinel, "minutes"], weights=kept) / 60.0) if kept.sum() > 0 else np.nan
    return mean, float(seconds[sentinel].sum() / total)


def declared_by_year(decl: pd.DataFrame, years=YEARS, now: pd.Timestamp | None = None) -> pd.DataFrame:
    """Per unit and year: the time-weighted MNZT, MZT and NDZ in hours and the share of the year at the sentinel."""
    now = pd.Timestamp.now(tz="UTC") if now is None else now
    rows = []
    for (unit, ds), d in decl.groupby(["unit_id", "dataset"], sort=True):
        for y in years:
            start = pd.Timestamp(f"{y}-01-01", tz="UTC")
            end = min(pd.Timestamp(f"{y + 1}-01-01", tz="UTC"), now)
            if end <= start:
                continue
            mean, share = in_force(d, start, end)
            if np.isnan(mean) and np.isnan(share):
                continue
            rows.append({"unit_id": unit, "year": y, f"{ds.lower()}_h": mean, f"{ds.lower()}_share_999": share})
    if not rows:
        return pd.DataFrame(columns=["unit_id", "year"])
    return pd.DataFrame(rows).groupby(["unit_id", "year"], as_index=False).first()


# ---------------------------------------------------------------------------- build
def metered_units(raw: Path | None = None) -> list[str]:
    """The units with a metering file (data/raw/b1610/{unit}.csv)."""
    raw = cfg.raw_dir() if raw is None else Path(raw)
    return sorted(p.stem for p in (raw / "b1610").glob("*.csv") if not p.stem.startswith("_"))


def build(units: list[str] | None = None, raw: Path | None = None,
          register: pd.DataFrame | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(unit_run_times, spells) for `units` (default: every unit with a metering file)."""
    raw = cfg.raw_dir() if raw is None else Path(raw)
    units = metered_units(raw) if units is None else units
    reg = B.register() if register is None else register
    reg = reg.drop_duplicates("unit_id").set_index("unit_id")
    rows, all_spells = [], []
    for i, unit in enumerate(units, 1):
        for source, reader in (("fpn", fpn_levels), ("b1610", b1610_levels)):
            path = raw / source / f"{unit}.csv"
            if not path.exists():
                continue
            s, per_year, full = measure(reader(path))
            if len(s):
                all_spells.append(s.assign(unit_id=unit, source=source))
            if len(per_year):
                rows.append(per_year.assign(unit_id=unit, source=source, full_mw=full, on_mw=ON_SHARE * full))
        if i % 20 == 0:
            print(f"  {i}/{len(units)} units", flush=True)
    times = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=["unit_id", "year", "source"])
    info = reg.reindex(times["unit_id"])
    for col in ("ngc_id", "unit_name", "tech", "capacity_mw"):
        times[col] = info[col].values if col in info else np.nan
    decl = declared_by_year(declarations(raw, set(units)))
    times = times.merge(decl, on=["unit_id", "year"], how="left")
    times = times.reindex(columns=COLUMNS).sort_values(["unit_id", "year", "source"]).reset_index(drop=True)
    spell_table = (pd.concat(all_spells, ignore_index=True)[SPELL_COLUMNS] if all_spells
                   else pd.DataFrame(columns=SPELL_COLUMNS))
    return times, spell_table


def write(times: pd.DataFrame, spell_table: pd.DataFrame, out_dir: Path | None = None) -> None:
    out_dir = cfg.processed_dir() if out_dir is None else Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    times.round(4).to_csv(out_dir / "unit_run_times.csv", index=False)
    for y, s in spell_table.groupby("year"):
        s.sort_values(["unit_id", "source", "start"]).to_csv(out_dir / f"unit_spells_{y}.csv", index=False)
    print(f"  unit_run_times.csv: {len(times):,} rows ({times['unit_id'].nunique()} units); "
          f"unit_spells_{{year}}.csv: {len(spell_table):,} spells in {spell_table['year'].nunique()} years")


def summary(times: pd.DataFrame, years=(2023, 2024, 2025), tech: str = "ccgt") -> pd.DataFrame:
    """The CCGTs' notified and metered run and down times in `years`: medians over units of each unit's statistics."""
    t = times[(times["tech"] == tech) & times["year"].isin(years) & (times["n_runs"] >= 10)]
    cols = ["run_h_p10", "run_h_p50", "run_share_under_6h", "down_h_p10", "down_h_p50", "down_share_under_6h",
            "two_shift_share", "mnzt_h", "mzt_h"]
    return t.groupby(["source", "year"])[cols].median().round(2)


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description="Run and down times of the thermal BM units (see the module docstring).") \
        .parse_args(argv)
    times, spell_table = build()
    write(times, spell_table)
    print(summary(times).to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
