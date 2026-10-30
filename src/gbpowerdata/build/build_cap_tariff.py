"""Extract the default tariff cap: the headline tariff by region (unit rate p/kWh + standing charge p/day), and what
the unit rate and standing charge are made of in every cap period, for electricity and gas.

The cap DECOMPOSITION (wholesale/network/policy/...) is what a bill is *made of*;
the headline is what a capped customer actually *pays* — the two-part regulated tariff, by
GSP region and payment method. Most GB households are on a capped or cap-tracking
tariff, so this is the consumer tariff, and it is the natural counterpart to the
Octopus standard-variable tariff (which tracks the cap) already pulled.

Source: Ofgem's "pre-levelised rates model" (the newest in data/raw/ofgem). Tab `1a Default tariff cap` gives, per
region and payment method, two figures for single-rate electricity:
  Nil consumption £/yr        = standing charge x 365
  Benchmark £/yr              = standing charge x 365 + unit rate x benchmark consumption
from which:
  standing_charge_p_day = Nil / 365 * 100
  unit_rate_p_kwh       = (Benchmark - Nil) / benchmark kWh * 100

THE BENCHMARK CONSUMPTION CHANGES BETWEEN PERIODS, and the model's calculation tabs do not say so reliably. The
history tab (1b) prices periods to December 2025 at 3,100 kWh of electricity and 12,000 kWh of gas, January-June 2026
at 2,700 and 11,500 (Ofgem's cap decision of 21 November 2025) and July 2026 on at 2,500 and 9,500 (its review of
typical domestic consumption values, decided 27 May 2026), while the calculation tabs of the May 2026 model still
read "2,700 kWh". So the benchmark is taken from the cap itself, per period and fuel: the policy cost allowance at the
benchmark less that at nil use is the per-MWh schemes of tab 3d times the benchmark MWh, so
  benchmark kWh = (PC at benchmark - PC at nil) / sum of tab 3d's GBP-per-MWh schemes x 1000,
which reproduces 3,100 / 12,000 to the kWh in every period from April 2017 to December 2025. It is rounded to
Ofgem's whole hundreds and must hold within 0.5%, or the build stops. (Before 23 Oct 2026 this module divided by a
fixed 2,700 kWh, which understated the July-September 2026 unit rate by 7%.)

Why the headline matters (verified): the standing-charge regional spread (~£91/yr,
London -> N Wales & Mersey) reproduces the DUoS regional spread (build_duos_tariffs,
~£82/yr) almost exactly — post-TCR the residual network cost sits in the standing
charge. The unit rate is nearly flat across regions (mostly national wholesale +
policy). So this cross-validates the DUoS work and locates the regional signal.

THE MAKE-UP PER PERIOD: the price of electricity against gas and the costs of government schemes in each.
Tab 1b gives each allowance of the cap at nil use and at the benchmark use, GBP a year excluding VAT, GB average, per
cap period since April 2017 (Ofgem's indicative levels before the cap began in January 2019), for each fuel and
payment method; here single-rate electricity and gas under the "Other Payment Method" (direct debit). An allowance's
per-kWh part is (benchmark - nil) / benchmark kWh, its per-customer part its value at nil. Grouped as:
  wholesale   the direct fuel allowance (DF) less the CfD allowance in it (tab 3a's "CFD allowance", the mean of the
              14 regions, as Ofgem's GB average is), electricity
  cfd         that CfD allowance (LCCC's levy as the cap passes it on; negative when the CfD paid back), electricity
  cm          the Capacity Market allowance, electricity
  policy      the policy cost allowance (PC); its schemes from tab 3d's "scheme by scheme estimates (GB average)":
              RO, FiT, ECO, WHD, AAHEDC, NCC (network charging compensation for energy-intensive industry) and nRAB
              (the nuclear RAB levy, Sizewell C) per MWh supplied on electricity; ECO and the WHD per MWh on gas;
              the WHD (and, on gas, the Green Gas Levy) per customer, which is the PC at nil use
  network     the network allowance (NC)
  other       everything else: operating costs, smart-meter costs, payment-method and headroom allowances, EBIT, ...
The components are checked to add up to the cap's total, the schemes to the policy allowance, both ways.

Outputs (data/processed/):
  cap_tariff_by_region.csv        per (period, payment_method, gsp_group) of the model's own period:
                                  standing_charge_p_day, unit_rate_p_kwh, nil_gbp_yr, total_gbp_yr
  cap_components_by_period.csv    per (period, fuel): start, end, benchmark_kwh, unit_rate_gbp_mwh and its parts
                                  wholesale/cfd/cm/policy/network/other_gbp_mwh, standing_charge_gbp_yr,
                                  policy_gbp_customer, and each scheme as <scheme>_gbp_mwh or <scheme>_gbp_customer
                                  (0 where a fuel does not carry it); all GBP excluding VAT

Usage:
  python -m gbpowerdata.build.build_cap_tariff
"""

from __future__ import annotations

import re
import sys
import warnings

import numpy as np
import pandas as pd

from gbpowerdata import config as cfg

warnings.filterwarnings("ignore")

OFGEM = cfg.raw_dir() / "ofgem"
SHEET = "1a Default tariff cap"
HISTORY_SHEET = "1b Historical level tables"
SCHEME_SHEET = "3d PC"
WHOLESALE_SHEET = "3a DF"

REGION_TO_GSP = {
    "Eastern": "_A", "East Midlands": "_B", "London": "_C", "N Wales and Mersey": "_D",
    "Midlands": "_E", "Northern": "_F", "North West": "_G", "Southern": "_H",
    "South East": "_J", "South Wales": "_K", "Southern Western": "_L",
    "Yorkshire": "_M", "Southern Scotland": "_N", "Northern Scotland": "_P",
}
# The three region blocks appear in this order down the tab.
PAYMENT_ORDER = ["Direct Debit", "Standard Credit", "Prepayment Meter"]

DIRECT_DEBIT = "other payment method"              # the cap model's name for direct debit
FUEL_BLOCKS = {"electricity": "electricity: single-rate metering arrangement", "gas": "gas"}     # tab 1b headings
SCHEME_FUELS = {"electricity": "electricity - single-rate metering arrangement", "gas": "gas"}  # tab 3d headings
NIL, BENCH = "nil consumption", "typical consumption"                          # tab 1b's two blocks per fuel
PERIOD_ROW = "28ad charge restriction period"      # tabs 3a/3d: the row of quarterly cap periods
CFD_TITLE = "cfd allowance"
TOTAL = "total_gb average"
GROUPS = {"df": "wholesale", "cm": "cm", "pc": "policy", "nc": "network"}      # tab 1b row -> component; rest "other"
MWH = 1000.0                                       # kWh per MWh
BENCHMARK_STEP_KWH = 100                           # Ofgem sets benchmark consumption in whole hundreds of kWh
BENCHMARK_TOL = 0.005                              # the identity holds to Ofgem's rounding; a misread layout fails it
SUM_TOL = 1e-6                                     # relative: tab 1b's components add up to its total


# A cap period label: 'Apr 2023 - June 2023', 'October 2015- March 2016', 'July 2026 - September 2026'.
CAP_PERIOD = re.compile(r"(?P<m0>[A-Za-z]{3})[a-z]* (?P<y0>\d{4})\s*[-–]\s*(?P<m1>[A-Za-z]{3})[a-z]* (?P<y1>\d{4})")


def period_dates(label) -> tuple[pd.Timestamp, pd.Timestamp] | None:
    """(first day, last day) of a cap period label such as 'Apr 2023 - June 2023' or 'October 2015- March 2016'."""
    m = CAP_PERIOD.fullmatch(str(label or "").strip())
    if not m:
        return None
    return (pd.Timestamp(f"1 {m['m0']} {m['y0']}"),
            pd.Timestamp(f"1 {m['m1']} {m['y1']}").to_period("M").end_time.normalize())


def _latest_model() -> "object":
    # Match both the puller's output (cap_tariff_model_*.xlsx from ofgem_pull) and a
    # hand-downloaded copy (cap_prelevelised_* / *pre-levelised*rates*model*).
    cands = (sorted(OFGEM.glob("cap_tariff_model_*.xlsx"))
             + sorted(OFGEM.glob("cap_prelevelised_*.xlsx"))
             + sorted(OFGEM.glob("*pre-levelised*rates*model*.xlsx")))
    if not cands:
        sys.exit("No cap pre-levelised rates model in data/raw/ofgem/. Run "
                 "`python -m gbpowerdata.pull.ofgem_pull` to download it.")
    return cands[-1]


# ------------------------------------------------------------------------------------------------ the make-up
def _s(v) -> str:
    """A cell as lower-case text with single spaces and plain hyphens; '' for a blank."""
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return ""
    return re.sub(r"\s+", " ", str(v).replace("–", "-").replace("\x96", "-")).strip().lower()


def _num(v) -> float:
    """A value cell; Ofgem's '-' (not applicable) and blanks are 0."""
    x = pd.to_numeric(v, errors="coerce")
    return 0.0 if pd.isna(x) else float(x)


def _row(g: pd.DataFrame, text: str, after: int = 0, startswith: bool = False) -> int:
    for i in range(after, len(g)):
        cells = g.iloc[i]
        if (cells.str.startswith(text) if startswith else cells == text).any():
            return i
    raise ValueError(f"no row reading {text!r} below row {after}")


def _periods(grid: pd.DataFrame, r: int, c0: int = -1) -> list[tuple[int, pd.Timestamp, pd.Timestamp, str]]:
    """(column, start, end, label) of the cap periods along row r right of column c0, up to the next label that is
    not a period (the next fuel's block in tab 1b)."""
    out = []
    for c in range(c0 + 1, grid.shape[1]):
        v = grid.iat[r, c]
        d = period_dates(v)
        if d is not None:
            out.append((c, d[0], d[1], str(v).strip()))
        elif _s(v) and c0 >= 0:
            break
    return out


def levels(grid: pd.DataFrame, fuel: str) -> pd.DataFrame:
    """Tab 1b, direct debit, one fuel: per cap period (index: its first day) the label, last day, and each allowance
    at nil use and at the benchmark use ('<row>_nil', '<row>_bench'), GBP a year excluding VAT, GB average."""
    g = grid.map(_s)
    head = _row(g, FUEL_BLOCKS[fuel], after=_row(g, DIRECT_DEBIT))
    c0 = int(np.flatnonzero(g.iloc[head] == FUEL_BLOCKS[fuel])[0])
    out = {}
    for block, tag in ((NIL, "nil"), (BENCH, "bench")):
        r0 = next(i for i in range(head, len(g)) if g.iat[i, c0] == block)
        for c, start, end, label in _periods(grid, r0, c0):
            row = out.setdefault(start, dict(period=label, end=end))
            r = r0 + 1
            while r < len(g) and g.iat[r, c0]:
                row[f"{g.iat[r, c0]}_{tag}"] = _num(grid.iat[r, c])
                r += 1
    t = pd.DataFrame.from_dict(out, orient="index").sort_index()
    t.index.name = "start"
    for tag in ("nil", "bench"):
        parts = [c for c in t.columns if c.endswith(f"_{tag}") and not c.startswith("total")]
        gap = (t[parts].sum(axis=1) - t[f"{TOTAL}_{tag}"]).abs()
        if (gap > SUM_TOL * t[f"{TOTAL}_{tag}"].abs().clip(lower=1.0)).any():
            raise ValueError(f"tab 1b {fuel} {tag}: the allowances do not add up to the total in "
                             f"{list(t.index[gap > SUM_TOL])}")
    return t


def scheme_column(name, unit) -> str:
    """'RO', 'GBP/MWh supplied' -> 'ro_gbp_mwh'; 'WHD', 'GBP/customer' -> 'whd_gbp_customer'."""
    base = re.sub(r"\W+", "_", _s(name).split("(")[0].strip()).strip("_")
    return f"{base}_gbp_mwh" if "mwh" in _s(unit) else f"{base}_gbp_customer"


def schemes(grid: pd.DataFrame, fuel: str) -> pd.DataFrame:
    """Tab 3d's 'scheme by scheme estimates (GB average)' for one fuel: per cap period (index: its first day) each
    scheme in GBP per MWh supplied or per customer a year, excluding VAT (columns from scheme_column)."""
    g = grid.map(_s)
    hi = _row(g, "scheme")
    js, ju = (int(np.flatnonzero(g.iloc[hi] == k)[0]) for k in ("scheme", "unit"))
    pr = _row(g, PERIOD_ROW, after=hi, startswith=True)
    cols = _periods(grid, pr)
    out, now = {}, None
    for r in range(pr + 1, len(g)):
        if g.iat[r, js - 1]:
            now = g.iat[r, js - 1]
        if now != SCHEME_FUELS[fuel] or not g.iat[r, js]:
            continue
        name = scheme_column(grid.iat[r, js], grid.iat[r, ju])
        for c, start, _, _ in cols:
            v = pd.to_numeric(grid.iat[r, c], errors="coerce")
            if pd.notna(v):
                out.setdefault(start, {})[name] = float(v)
    t = pd.DataFrame.from_dict(out, orient="index").sort_index().fillna(0.0)
    t.index.name = "start"
    return t


def cfd_allowance(grid: pd.DataFrame) -> pd.Series:
    """Tab 3a's CfD allowance for single-rate electricity, GBP per customer a year at the benchmark use, the mean of
    the 14 regions (as Ofgem's GB average is), per cap period (index: its first day)."""
    g = grid.map(_s)
    title = _row(g, CFD_TITLE)
    pr = max(i for i in range(title) if g.iloc[i].str.startswith(PERIOD_ROW).any())
    rc = int(np.flatnonzero(g.iloc[title + 1] == _s(next(iter(REGION_TO_GSP))))[0])
    rows = list(range(title + 1, title + 1 + len(REGION_TO_GSP)))
    if sorted(str(grid.iat[r, rc]).strip() for r in rows) != sorted(REGION_TO_GSP):
        raise ValueError("tab 3a: the CfD allowance's first rows are not the 14 single-rate regions")
    out = {}
    for c, start, _, _ in _periods(grid, pr):
        v = pd.to_numeric(grid.iloc[rows, c], errors="coerce")
        if v.notna().all():
            out[start] = float(v.mean())
    return pd.Series(out, name="cfd_gbp_customer").sort_index()


def benchmark_kwh(lv: pd.DataFrame, sc: pd.DataFrame, fuel: str) -> pd.Series:
    """Each period's benchmark use from the policy identity (module docstring), rounded to whole hundreds of kWh."""
    per_mwh = sc[[c for c in sc.columns if c.endswith("_gbp_mwh")]].sum(axis=1)
    kwh = (lv["pc_bench"] - lv["pc_nil"]) * MWH / per_mwh
    rounded = (kwh / BENCHMARK_STEP_KWH).round() * BENCHMARK_STEP_KWH
    bad = ~((kwh / rounded - 1).abs() <= BENCHMARK_TOL)
    if bad.any():
        raise ValueError(f"{fuel}: the policy allowance and tab 3d's schemes imply no whole benchmark use in "
                         + ", ".join(f"{lv.loc[s, 'period']} ({kwh[s]:,.0f} kWh)" for s in lv.index[bad]))
    return rounded


def history(hist: pd.DataFrame, pc: pd.DataFrame, df: pd.DataFrame) -> pd.DataFrame:
    """The make-up of the direct-debit cap per period and fuel from tabs 1b, 3d and 3a (module docstring)."""
    cfd = cfd_allowance(df)
    out = []
    for fuel in FUEL_BLOCKS:
        lv = levels(hist, fuel)
        sc = schemes(pc, fuel).reindex(lv.index)
        if sc.isna().all(axis=1).any():
            raise ValueError(f"{fuel}: tab 3d has no schemes for {list(lv.loc[sc.isna().all(axis=1), 'period'])}")
        sc = sc.fillna(0.0)
        kwh = benchmark_kwh(lv, sc, fuel)
        per = lambda row: (lv[f"{row}_bench"] - lv[f"{row}_nil"]) * MWH / kwh            # noqa: E731
        rows = sorted({c[:-len("_bench")] for c in lv.columns if c.endswith("_bench") and not c.startswith("total")})
        t = pd.DataFrame(index=lv.index)
        t["period"], t["end"], t["fuel"], t["benchmark_kwh"] = lv["period"], lv["end"], fuel, kwh
        t["unit_rate_gbp_mwh"] = per(TOTAL)
        c = (cfd.reindex(lv.index) * MWH / kwh) if fuel == "electricity" else pd.Series(0.0, index=lv.index)
        if c.isna().any():
            raise ValueError(f"tab 3a has no CfD allowance for {list(lv.loc[c.isna(), 'period'])}")
        for row, name in GROUPS.items():
            t[f"{name}_gbp_mwh"] = per(row) if row in rows else 0.0
        t["wholesale_gbp_mwh"] -= c
        t["cfd_gbp_mwh"] = c
        t["other_gbp_mwh"] = sum(per(r) for r in rows if r not in GROUPS)
        t["standing_charge_gbp_yr"] = lv[f"{TOTAL}_nil"]
        t["policy_gbp_customer"] = lv["pc_nil"]
        for name in ("policy_gbp_mwh", "policy_gbp_customer"):
            unit = name.split("policy")[1]
            gap = sc[[k for k in sc.columns if k.endswith(unit)]].sum(axis=1) - t[name]
            if (gap.abs() > BENCHMARK_TOL * t[name].abs().clip(lower=1.0)).any():
                raise ValueError(f"{fuel}: tab 3d's schemes do not add up to the policy allowance ({name})")
        out.append(pd.concat([t, sc], axis=1))
    t = pd.concat(out).reset_index()
    schemes_cols = sorted(c for c in t.columns if c.endswith(("_gbp_customer", "_gbp_mwh")) and c not in
                          {"policy_gbp_customer", *(f"{v}_gbp_mwh" for v in (*GROUPS.values(), "cfd", "other",
                                                                            "unit_rate"))})
    t[schemes_cols] = t[schemes_cols].fillna(0.0)
    parts = [f"{v}_gbp_mwh" for v in ("wholesale", "cfd", "cm", "policy", "network", "other")]
    gap = (t[parts].sum(axis=1) - t["unit_rate_gbp_mwh"]).abs()
    if (gap > SUM_TOL * t["unit_rate_gbp_mwh"].abs()).any():
        raise ValueError("the unit rate's parts do not add up to it")
    head = ["period", "start", "end", "fuel", "benchmark_kwh", "unit_rate_gbp_mwh", *parts, "standing_charge_gbp_yr",
            "policy_gbp_customer"]
    return t[head + schemes_cols].sort_values(["fuel", "start"]).reset_index(drop=True)


# ------------------------------------------------------------------------------------------------ the headline
def headline(d: pd.DataFrame, kwh: float) -> tuple[str, pd.DataFrame]:
    """Tab 1a: the model's own period and, per region and payment method, single-rate electricity's standing charge
    and unit rate at `kwh`, the benchmark use of that period."""
    # The period label sits near the top of the tab (e.g. "July 2026 - September 2026").
    period = "unknown"
    for i in range(min(12, len(d))):
        for c in range(d.shape[1]):
            if period_dates(d.at[i, c]) is not None:
                period = str(d.at[i, c]).strip()
                break
        if period != "unknown":
            break

    # Each payment block is 14 region rows; blocks start where "North West" recurs
    # in the region column (col 1). Nil = col 2, Benchmark = col 3 (single-rate elec).
    starts = [i for i in range(len(d)) if str(d.at[i, 1]).strip() == "North West"]
    rows = []
    for bi, start in enumerate(starts[:3]):
        pay = PAYMENT_ORDER[bi] if bi < len(PAYMENT_ORDER) else f"block{bi}"
        for i in range(start, start + 14):
            region = str(d.at[i, 1]).strip()
            if region not in REGION_TO_GSP:
                continue
            nil = pd.to_numeric(d.at[i, 2], errors="coerce")
            bench = pd.to_numeric(d.at[i, 3], errors="coerce")
            if pd.isna(nil) or pd.isna(bench):
                continue
            rows.append(dict(
                period=period, payment_method=pay, region=region,
                gsp_group=REGION_TO_GSP[region],
                standing_charge_p_day=round(nil / 365 * 100, 3),
                unit_rate_p_kwh=round((bench - nil) / kwh * 100, 3),
                nil_gbp_yr=round(float(nil), 2), total_gbp_yr=round(float(bench), 2)))
    return period, pd.DataFrame(rows)


def main() -> None:
    path = _latest_model()
    grids = {s: pd.read_excel(path, sheet_name=s, header=None)
             for s in (SHEET, HISTORY_SHEET, SCHEME_SHEET, WHOLESALE_SHEET)}
    comp = history(grids[HISTORY_SHEET], grids[SCHEME_SHEET], grids[WHOLESALE_SHEET])
    dest = cfg.processed_dir() / "cap_components_by_period.csv"
    comp.to_csv(dest, index=False)
    print(f"Cap make-up per period from {path.name}: {comp['period'].nunique()} periods x "
          f"{comp['fuel'].nunique()} fuels -> {dest}")
    for (fuel, kwh), g in comp.groupby(["fuel", "benchmark_kwh"], sort=False):
        print(f"  {fuel:<11} benchmark {kwh:>6,.0f} kWh: {g['period'].iloc[0]} .. {g['period'].iloc[-1]}")

    first = period_dates(next((v for v in grids[SHEET].iloc[:12].to_numpy().ravel() if period_dates(v) is not None),
                              None))
    elec = comp[comp["fuel"] == "electricity"].set_index("start")
    if first is None or first[0] not in elec.index:
        sys.exit(f"tab '{SHEET}' of {path.name}: its period is not in the history tab, so its benchmark is unknown")
    period, out = headline(grids[SHEET], float(elec.loc[first[0], "benchmark_kwh"]))
    if out.empty:
        sys.exit(f"Parsed zero rows from {path.name} tab '{SHEET}' — layout changed.")

    dest = cfg.processed_dir() / "cap_tariff_by_region.csv"
    out.to_csv(dest, index=False)
    print(f"Default tariff cap ({period}, benchmark {elec.loc[first[0], 'benchmark_kwh']:,.0f} kWh) from {path.name}")
    print(f"  {len(out)} rows = {out['gsp_group'].nunique()} regions x "
          f"{out['payment_method'].nunique()} payment methods -> {dest}\n")

    dd = out[out["payment_method"] == "Direct Debit"].sort_values("standing_charge_p_day")
    print("Direct Debit, single-rate electricity (exc VAT):")
    print(dd[["gsp_group", "region", "standing_charge_p_day", "unit_rate_p_kwh",
              "total_gbp_yr"]].to_string(index=False))
    sc = dd["standing_charge_p_day"]
    print(f"\n  standing charge spread £{(sc.max() - sc.min()) * 365 / 100:.0f}/yr "
          f"(mostly regional NETWORK cost); unit rate near-flat "
          f"{dd['unit_rate_p_kwh'].min():.1f}-{dd['unit_rate_p_kwh'].max():.1f} p/kWh")


if __name__ == "__main__":
    main()
