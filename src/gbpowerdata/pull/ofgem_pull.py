"""Pull the Ofgem default tariff cap annexes from the PRIMARY source.

Ofgem publishes the full cap decomposition as versioned .xlsx annexes on the
"Energy price cap (default tariff) levels" page. The page is static HTML (no JS,
no auth), and every historical version is still linked, so the annex URLs can be
discovered by scraping rather than hardcoded per quarter.

  Annex 2  wholesale cost allowance  -> CfD allowance (tab 7a), Capacity Market (4a)
  Annex 3  network cost allowance    -> TNUoS, BSUoS, DUoS (electricity)
  Annex 4  policy cost allowance     -> RO, FiT, ECO, WHD, AAHEDC, GGL, NCC, nRAB

Why the primary source and not a third-party aggregation: an aggregation cannot be
cited as provenance, and where a component is genuinely unavailable openly we want
that recorded as a gap rather than silently filled with someone's estimate.

⚠️ These are the cap ALLOWANCE - what suppliers were permitted to charge, set ~2
months ahead on a forecast. It is NOT what a component actually cost. For CfDs the
settled cost comes from LCCC (`lccc_pull.py --levy`), and the two differ by up to
£9/MWh in some years. Do not treat the allowance as an outturn.

Usage:
  python -m gbpowerdata.pull.ofgem_pull                 # discover + download latest annexes
  python -m gbpowerdata.pull.ofgem_pull --list          # show discovered annex versions, exit
  python -m gbpowerdata.pull.ofgem_pull --extract-cfd   # + tidy the CfD allowance to CSV
"""

from __future__ import annotations

import argparse
import re
import sys
from urllib.parse import urljoin, unquote

import pandas as pd
import requests

from gbpowerdata import config as cfg

BASE = "https://www.ofgem.gov.uk"
LEVELS_PAGE = (f"{BASE}/energy-regulation/domestic-and-non-domestic/energy-pricing-rules/"
               "energy-price-cap/energy-price-cap-default-tariff-levels")
OUT_DIR = cfg.raw_dir() / "ofgem"
UA = {"User-Agent": "Mozilla/5.0 (research; GB electricity ABM)"}

# Which annex we want -> a regex matching its filename on the levels page.
ANNEXES = {
    # ORDER MATTERS: the first pattern to match wins. The supplementary workbook is
    # named "supplementary_workbook_to_annex_2_3_and_4_-_demand_and_losses", so it
    # must be tested before the annex-2/3/4 patterns or it is misfiled as annex 2.
    "supplementary_demand_losses": re.compile(r"supplementary.*(demand|loss)", re.I),
    # Headline cap TARIFF (unit rate + standing charge) build-up; before annex-2.
    "cap_tariff_model": re.compile(r"pre-?levelised.*rates.*model", re.I),
    "annex2_wholesale": re.compile(r"(annex[-_ ]?2\b|Wholesale-cost-allowance)", re.I),
    "annex3_network_elec": re.compile(r"(annex[-_ ]?3\b|Network-cost-allowance).*elec", re.I),
    "annex4_policy": re.compile(r"(annex[-_ ]?4\b|Policy-cost-allowance)", re.I),
}

# The 14 Ofgem charge restriction regions, in the sheet's own order, mapped onto the
# GSP groups the rest of the pipeline uses (gbpowerdata.common.gsp).
REGION_TO_GSP = {
    "Eastern": "_A", "East Midlands": "_B", "London": "_C", "N Wales and Mersey": "_D",
    "Midlands": "_E", "Northern": "_F", "North West": "_G", "Southern": "_H",
    "South East": "_J", "South Wales": "_K", "Southern Western": "_L",
    "Yorkshire": "_M", "Southern Scotland": "_N", "Northern Scotland": "_P",
}


def discover() -> pd.DataFrame:
    """Every annex .xlsx linked on the levels page, with its publication folder."""
    r = requests.get(LEVELS_PAGE, headers=UA, timeout=120)
    r.raise_for_status()
    hrefs = sorted(set(re.findall(r'href="([^"]*\.xlsx)"', r.text)))
    rows = []
    for h in hrefs:
        name = unquote(h.rsplit("/", 1)[-1])
        # publication folder is /sites/default/files/YYYY-MM/...
        m = re.search(r"/files/(\d{4})-(\d{2})/", h)
        pub = f"{m.group(1)}-{m.group(2)}" if m else ""
        for key, pat in ANNEXES.items():
            if pat.search(name):
                rows.append(dict(annex=key, published=pub, filename=name,
                                 url=urljoin(BASE, h)))
                break
    return pd.DataFrame(rows).sort_values(["annex", "published"])


def download(df: pd.DataFrame) -> dict[str, "object"]:
    """Download the most recently published version of each annex."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    paths = {}
    for annex, g in df.groupby("annex"):
        row = g.iloc[-1]                      # highest publication folder
        dest = OUT_DIR / f"{annex}_{row['published']}.xlsx"
        if dest.exists():
            print(f"  cached  {dest.name}")
        else:
            resp = requests.get(row["url"], headers=UA, timeout=300)
            resp.raise_for_status()
            dest.write_bytes(resp.content)
            print(f"  saved   {dest.name}  ({len(resp.content) / 1e6:.1f} MB)")
        paths[annex] = dest
    return paths


def extract_cfd_allowance(path) -> pd.DataFrame:
    """Tidy tab '7a CFD allowance' -> one row per (region, charge restriction period).

    The sheet is a wide matrix: period labels on one header row, 14 regions down the
    side, repeated per metering arrangement. We take the single-rate block only.
    """
    d = pd.read_excel(path, sheet_name="7a CFD allowance", header=None)
    # Locate the header rows by content rather than position (they move between versions).
    hdr = d.index[d[4].astype(str).str.contains("Charge Restriction Period", na=False)]
    fy_row = d.index[d[4].astype(str).str.contains("Fiscal year", na=False)]
    if not len(hdr) or not len(fy_row):
        raise ValueError("could not locate the period header rows in tab 7a")
    hdr, fy_row = hdr[0], fy_row[0]

    periods = {c: str(d.at[hdr, c]).strip() for c in d.columns
               if pd.notna(d.at[hdr, c]) and str(d.at[hdr, c]).strip() not in ("", "nan")}
    fys = {c: str(d.at[fy_row, c]).strip() for c in periods}

    # Single-rate block: starts at the row labelled so in col 1, ends before the next label.
    starts = d.index[d[1].astype(str).str.contains("Single-Rate", na=False)]
    if not len(starts):
        raise ValueError("could not locate the single-rate block in tab 7a")
    start = starts[0]
    rows = []
    for i in range(start, start + 14):
        region = str(d.at[i, 2]).strip()
        if region not in REGION_TO_GSP:
            continue
        for c, per in periods.items():
            v = d.at[i, c]
            if pd.isna(v) or isinstance(v, str):
                continue
            rows.append(dict(region=region, gsp_group=REGION_TO_GSP[region],
                             charge_restriction_period=per, fiscal_year=fys.get(c, ""),
                             cfd_allowance_gbp_per_customer_yr=float(v)))
    out = pd.DataFrame(rows)
    if out.empty:
        raise ValueError("tab 7a parsed to zero rows — sheet layout has changed")
    return out


def _find_row(d: pd.DataFrame, text: str) -> int | None:
    """First row index containing `text` in ANY column (label columns move between
    annex versions, so never assume a fixed column)."""
    hit = d.index[d.apply(
        lambda r: r.astype(str).str.contains(text, na=False, regex=False).any(), axis=1)]
    return int(hit[0]) if len(hit) else None


_MONTHS = {m: i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July", "August",
     "September", "October", "November", "December"], start=1)}


def _period_bounds(label: str) -> tuple[pd.Timestamp, pd.Timestamp] | tuple[None, None]:
    """'April 2015 - September 2015' -> (2015-04-01, 2015-09-30). Handles en/em dashes."""
    parts = re.split(r"[-–—]", label.replace("–", "-").replace("—", "-"))
    if len(parts) != 2:
        return None, None
    try:
        a_m, a_y = parts[0].strip().split()
        b_m, b_y = parts[1].strip().split()
        start = pd.Timestamp(int(a_y), _MONTHS[a_m.capitalize()], 1)
        end = (pd.Timestamp(int(b_y), _MONTHS[b_m.capitalize()], 1)
               + pd.offsets.MonthEnd(1))
        return start, end
    except (ValueError, KeyError):
        return None, None


def extract_cfd_allowance_per_mwh(path) -> pd.DataFrame:
    """Tab '7b CFD calculation' -> the single-rate CfD allowance in GBP/MWh.

    Row '1. Summary of CfD scheme before losses multiplier applied' carries the
    allowance in "£/MWh at transmission system", which is the same basis as the
    LCCC levy (per MWh of eligible demand) - so no benchmark-consumption or TDCV
    conversion is needed, and the TDCV changes (3.1 -> 2.7 -> 2.5 MWh) cannot
    contaminate the comparison.
    """
    d = pd.read_excel(path, sheet_name="7b CFD calculation", header=None)
    hdr = _find_row(d, "Charge Restriction Period")
    if hdr is None:
        raise ValueError("could not locate the period header row in tab 7b")
    # The £/MWh summary row: single-rate arrangement, unit stated in £/MWh. The unit
    # column moves between annex versions, so match on the row's whole contents.
    mask = (d.apply(lambda r: r.astype(str).str.contains("Single-Rate", na=False).any(), axis=1)
            & d.apply(lambda r: r.astype(str).str.contains("/MWh", na=False).any(), axis=1))
    rows = d.index[mask]
    if not len(rows):
        raise ValueError("could not locate the single-rate GBP/MWh row in tab 7b")
    row = rows[0]

    out = []
    for c in d.columns:
        lab = d.at[hdr, c]
        v = d.at[row, c]
        if pd.isna(lab) or pd.isna(v) or isinstance(v, str):
            continue
        start, end = _period_bounds(str(lab).strip())
        if start is None:
            continue
        out.append(dict(charge_restriction_period=str(lab).strip(),
                        period_start=start, period_end=end,
                        cfd_allowance_gbp_mwh=float(v)))
    df = pd.DataFrame(out).drop_duplicates("charge_restriction_period")
    if df.empty:
        raise ValueError("tab 7b parsed to zero rows - sheet layout has changed")
    return df.sort_values("period_start").reset_index(drop=True)


def extract_policy_costs_per_mwh(path) -> pd.DataFrame:
    """Annex 4 tab '2a Aggregate costs' -> every policy scheme in GBP/MWh.

    One row per (scheme, charge restriction period) for the single-rate electricity
    block: RO, FiT, ECO, WHD, AAHEDC, NCC (network charging compensation) and nRAB
    (nuclear RAB / Sizewell C). Note the units differ by scheme - WHD appears both
    per customer and per MWh, AAHEDC is at GSP level and NCC/nRAB at transmission
    level - so the unit is carried through rather than silently harmonised.
    """
    d = pd.read_excel(path, sheet_name="2a Aggregate costs", header=None)
    hdr = _find_row(d, "Charge Restriction Period")
    if hdr is None:
        raise ValueError("could not locate the period header row in Annex 4 tab 2a")
    start = _find_row(d, "Electricity - Single-Rate Metering Arrangement")
    if start is None:
        raise ValueError("could not locate the single-rate block in Annex 4 tab 2a")

    periods = {c: str(d.at[hdr, c]).strip() for c in d.columns
               if pd.notna(d.at[hdr, c]) and str(d.at[hdr, c]).strip() not in ("", "nan")}
    rows = []
    for i in range(start, min(start + 12, len(d))):
        # Stop at the next metering-arrangement block.
        if i > start and "Multi-Register" in str(d.at[i, 1]):
            break
        scheme, unit = str(d.at[i, 2]).strip(), str(d.at[i, 4]).strip()
        if scheme in ("nan", ""):
            continue
        for c, per in periods.items():
            v = d.at[i, c]
            if pd.isna(v) or isinstance(v, str):
                continue
            s, e = _period_bounds(per)
            if s is None:
                continue
            rows.append(dict(scheme=scheme, unit=unit, charge_restriction_period=per,
                             period_start=s, period_end=e, allowance=float(v)))
    df = pd.DataFrame(rows)
    if df.empty:
        raise ValueError("Annex 4 tab 2a parsed to zero rows - layout has changed")
    return df.sort_values(["scheme", "period_start"]).reset_index(drop=True)


def extract_duos_per_customer(path) -> pd.DataFrame:
    """Annex 3 tab '2b DUoS' -> DUoS £/customer/yr per (region, charge period).

    This is Ofgem's computation of the domestic DUoS bill from the FINAL published
    DNO charges (not a forecast), applying the half-hourly demand-share weighting
    that a naive red/amber/green blend cannot reproduce (the residual charge drifts
    between the red unit rate and the fixed charge across the DCP268/TCR reforms).
    Same wide (region x period) matrix layout as the CfD tab.
    """
    d = pd.read_excel(path, sheet_name="2b DUoS", header=None)
    hdr = _find_row(d, "Charge Restriction Period")
    start = _find_row(d, "Single-Rate Metering Arrangement")
    if hdr is None or start is None:
        raise ValueError("could not locate headers in Annex 3 tab 2b")

    periods = {c: str(d.at[hdr, c]).strip() for c in d.columns
               if pd.notna(d.at[hdr, c]) and str(d.at[hdr, c]).strip() not in ("", "nan")}
    rows = []
    for i in range(start, start + 14):
        region = str(d.at[i, 5]).strip()
        if region not in REGION_TO_GSP:
            continue
        for c, per in periods.items():
            v = d.at[i, c]
            if pd.isna(v) or isinstance(v, str):
                continue
            s, e = _period_bounds(per)
            if s is None:
                continue
            rows.append(dict(region=region, gsp_group=REGION_TO_GSP[region],
                             charge_restriction_period=per, period_start=s, period_end=e,
                             duos_gbp_per_customer_yr=float(v)))
    df = pd.DataFrame(rows)
    if df.empty:
        raise ValueError("Annex 3 tab 2b parsed to zero rows - layout has changed")
    return df.sort_values(["gsp_group", "period_start"]).reset_index(drop=True)


def main(argv: list[str]) -> None:
    p = argparse.ArgumentParser(description="Pull Ofgem default tariff cap annexes.")
    p.add_argument("--list", action="store_true", help="list discovered annexes and exit.")
    p.add_argument("--extract-cfd", action="store_true",
                   help="also tidy the Annex 2 CfD allowance into a CSV.")
    p.add_argument("--extract-policy", action="store_true",
                   help="also tidy the Annex 4 policy costs (RO/FiT/ECO/WHD/AAHEDC/NCC/nRAB).")
    p.add_argument("--extract-duos", action="store_true",
                   help="also tidy the Annex 3 DUoS £/customer/yr (weighted from DNO charges).")
    args = p.parse_args(argv[1:])

    print(f"Discovering annexes on {LEVELS_PAGE} ...")
    df = discover()
    print(f"  found {len(df)} annex files across {df['published'].nunique()} publications")
    if args.list:
        print(df.to_string(index=False))
        return

    paths = download(df)

    if args.extract_cfd:
        out = extract_cfd_allowance(paths["annex2_wholesale"])
        dest = OUT_DIR / "cfd_allowance_by_region.csv"
        out.to_csv(dest, index=False)
        print(f"\n  CfD allowance (£/customer/yr): {len(out):,} rows "
              f"({out['gsp_group'].nunique()} regions x "
              f"{out['charge_restriction_period'].nunique()} periods) -> {dest}")

        pm = extract_cfd_allowance_per_mwh(paths["annex2_wholesale"])
        dest2 = OUT_DIR / "cfd_allowance_gbp_mwh.csv"
        pm.to_csv(dest2, index=False)
        print(f"  CfD allowance (£/MWh):        {len(pm):,} periods, "
              f"{pm['period_start'].min():%Y-%m} to {pm['period_end'].max():%Y-%m} -> {dest2}")

    if args.extract_policy:
        pol = extract_policy_costs_per_mwh(paths["annex4_policy"])
        dest = OUT_DIR / "policy_cost_allowances.csv"
        pol.to_csv(dest, index=False)
        print(f"  Policy allowances: {len(pol):,} rows, schemes "
              f"{sorted(pol['scheme'].unique())} -> {dest}")

    if args.extract_duos:
        du = extract_duos_per_customer(paths["annex3_network_elec"])
        dest = OUT_DIR / "duos_per_customer.csv"
        du.to_csv(dest, index=False)
        print(f"  DUoS £/customer/yr: {len(du):,} rows "
              f"({du['gsp_group'].nunique()} regions x "
              f"{du['charge_restriction_period'].nunique()} periods) -> {dest}")


if __name__ == "__main__":
    sys.exit(main(sys.argv))
