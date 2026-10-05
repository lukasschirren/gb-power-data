"""Extract the headline default tariff cap: unit rate (p/kWh) + standing charge (p/day).

The cap DECOMPOSITION (wholesale/network/policy/...) is what a bill is *made of*;
this is what a capped customer actually *pays* — the two-part regulated tariff, by
GSP region and payment method. Most GB households are on a capped or cap-tracking
tariff, so this is the consumer tariff, and it is the natural counterpart to the
Octopus standard-variable tariff (which tracks the cap) already pulled.

Source: Ofgem's "pre-levelised rates model", tab `1a Default tariff cap`, which
gives, per region and payment method, two figures for single-rate electricity:
  Nil consumption £/yr        = standing charge x 365
  Benchmark £/yr (at TDCV)    = standing charge x 365 + unit rate x TDCV
from which:
  standing_charge_p_day = Nil / 365 * 100
  unit_rate_p_kwh       = (Benchmark - Nil) / TDCV * 100

Why it matters (verified): the standing-charge regional spread (~£91/yr,
London -> N Wales & Mersey) reproduces the DUoS regional spread (build_duos_tariffs,
~£82/yr) almost exactly — post-TCR the residual network cost sits in the standing
charge. The unit rate is nearly flat across regions (mostly national wholesale +
policy). So this cross-validates the DUoS work and locates the regional signal.

Output (data/processed/):
  cap_tariff_by_region.csv   per (period, payment_method, gsp_group):
                             standing_charge_p_day, unit_rate_p_kwh, total_gbp_yr

Usage:
  python -m gbpowerdata.build.build_cap_tariff
"""

from __future__ import annotations

import sys
import warnings

import pandas as pd

from gbpowerdata import config as cfg

warnings.filterwarnings("ignore")

OFGEM = cfg.raw_dir() / "ofgem"
TDCV_KWH = 2700.0
SHEET = "1a Default tariff cap"

REGION_TO_GSP = {
    "Eastern": "_A", "East Midlands": "_B", "London": "_C", "N Wales and Mersey": "_D",
    "Midlands": "_E", "Northern": "_F", "North West": "_G", "Southern": "_H",
    "South East": "_J", "South Wales": "_K", "Southern Western": "_L",
    "Yorkshire": "_M", "Southern Scotland": "_N", "Northern Scotland": "_P",
}
# The three region blocks appear in this order down the tab.
PAYMENT_ORDER = ["Direct Debit", "Standard Credit", "Prepayment Meter"]


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


def main() -> None:
    path = _latest_model()
    d = pd.read_excel(path, sheet_name=SHEET, header=None)

    # The period label sits near the top of the tab (e.g. "July 2026 - September 2026").
    period = "unknown"
    for i in range(min(12, len(d))):
        for c in range(d.shape[1]):
            v = str(d.at[i, c])
            if any(m in v for m in ("2024", "2025", "2026")) and " - " in v:
                period = v.strip()
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
                unit_rate_p_kwh=round((bench - nil) / TDCV_KWH * 100, 3),
                nil_gbp_yr=round(float(nil), 2), total_gbp_yr=round(float(bench), 2)))
    out = pd.DataFrame(rows)
    if out.empty:
        sys.exit(f"Parsed zero rows from {path.name} tab '{SHEET}' — layout changed.")

    dest = cfg.processed_dir() / "cap_tariff_by_region.csv"
    out.to_csv(dest, index=False)
    print(f"Default tariff cap ({period}) from {path.name}")
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
