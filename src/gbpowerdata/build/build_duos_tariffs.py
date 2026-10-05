"""Parse domestic DUoS tariffs from the 14 DNO charging statements.

Distribution Use of System is the one network component with no API - each DNO
publishes an annual "Schedule of charges and other tables" workbook, and the
domestic tariff lives in the `Annex 1 LV...` sheet as a red/amber/green (RAG) unit
charge in p/kWh plus a fixed charge in p/MPAN/day.

This reads every workbook under data/raw/manual/dno_duos/, identifies the licence
area and charging year from the file *contents* (filenames are unreliable - some
DNOs ship numeric names), extracts the "Domestic ... with Residual" row, and maps
it to the pipeline's gsp_group.

This produces the RAW published tariff components. Collapsing red/amber/green to a
single £/household is deliberately NOT done here: the residual charge drifts between
the red unit rate and the fixed charge across the DCP268 (2018) and TCR (April 2022)
reforms, so a fixed red/amber/green demand split gives wrong, volatile totals
(verified: a naive 6/28/66 blend disagrees with Ofgem's weighting by ~2x and
reorders the regions). The correctly demand-weighted £/customer/yr, computed by
Ofgem from these SAME final published DNO charges, is pulled separately as
`data/raw/ofgem/duos_per_customer.csv` (`ofgem_pull --extract-duos`) and joined
here for cross-reference. Use that column for any household-cost figure; use the
raw rates here when the time-of-use structure itself is the point.

Output (data/processed/):
  duos_domestic_tariffs.csv   per (gsp_group, charging_year): raw red/amber/green
                              p/kWh + fixed p/day (this parse), plus the Ofgem-
                              weighted duos_gbp_per_customer_yr where the years align

Usage:
  python -m gbpowerdata.build.build_duos_tariffs
"""

from __future__ import annotations

import argparse
import re
import sys
import warnings

import pandas as pd

from gbpowerdata import config as cfg

warnings.filterwarnings("ignore")

DUOS_DIR = cfg.raw_dir() / "manual" / "dno_duos"
OFGEM_DUOS = cfg.raw_dir() / "ofgem" / "duos_per_customer.csv"

# Licence-name / filename fragment -> gsp_group. Order matters: more specific first
# (so "south eastern" beats "eastern"). Applied to the file's internal text.
LICENCE_TO_GSP = [
    ("south eastern", "_J"), ("south-eastern", "_J"), ("eastern power", "_A"),
    ("london", "_C"), ("east midlands", "_B"), ("west midlands", "_E"),
    ("midlands electricity", "_E"), ("south wales", "_K"), ("south west", "_L"),
    ("sweb", "_L"), ("swae", "_K"), ("north east", "_F"), ("northeast", "_F"),
    ("yorkshire", "_M"), ("electricity north west", "_G"), ("enwl", "_G"),
    ("sp distribution", "_N"), ("spd", "_N"), ("manweb", "_D"), ("spm", "_D"),
    ("hydro", "_P"), ("shepd", "_P"), ("southern electric", "_H"), ("sepd", "_H"),
]


def _header_blob(path) -> str:
    """First ~25 rows of the first sheet, flattened - carries the licence name
    and charging year even when the filename is a numeric id."""
    try:
        d = pd.read_excel(path, sheet_name=0, header=None, nrows=25)
    except Exception:
        return ""
    return " ".join(str(c) for c in d.values.ravel() if pd.notna(c))


def identify(path) -> tuple[str | None, int | None]:
    blob = _header_blob(path)
    text = (blob + " " + path.name).lower()
    gsp = next((g for frag, g in LICENCE_TO_GSP if frag in text), None)
    # Charging year: prefer a YYYY/YY inside the workbook, else a year in the name.
    m = re.search(r"20(\d{2})\s*[/-]\s*\d{2}", blob) or re.search(r"20\d{2}", path.name)
    year = None
    if m:
        year = int("20" + m.group(1)) if "/" in m.group(0) or "-" in m.group(0) else int(m.group(0))
    return gsp, year


def _find(df: pd.DataFrame, text: str) -> int | None:
    hit = df.index[df.apply(
        lambda r: r.astype(str).str.contains(text, case=False, na=False).any(), axis=1)]
    return int(hit[0]) if len(hit) else None


def parse_domestic(path) -> dict | None:
    """Extract the 'Domestic ... with Residual' RAG + fixed charges from Annex 1."""
    xl = pd.ExcelFile(path)
    sheet = next((s for s in xl.sheet_names if s.lower().startswith("annex 1")), None)
    if sheet is None:
        return None
    df = pd.read_excel(path, sheet_name=sheet, header=None)
    hdr = _find(df, "Tariff name")
    if hdr is None:
        return None
    # Column roles from the header row: RAG unit charges + fixed charge. Header
    # wording varies ("Red/black..." vs "Unit charge 1 (NHH) or red..."), so match
    # on keyword within the header cell.
    cols = {}
    for c in df.columns:
        h = str(df.at[hdr, c]).lower()
        if "red" in h or ("unit charge 1" in h):
            cols["red"] = c
        elif "amber" in h or ("unit charge 2" in h):
            cols["amber"] = c
        elif "green" in h:
            cols["green"] = c
        elif "fixed" in h:
            cols["fixed"] = c
    if not {"red", "amber", "green", "fixed"} <= cols.keys():
        return None
    # The residual-bearing domestic aggregate row (what a normal metered home pays).
    name_col = min(cols.values()) - 100  # tariff name is left of the numeric cols
    dom = None
    for i in range(hdr + 1, len(df)):
        nm = str(df.iat[i, [c for c in df.columns][0]]) if False else ""
        row_txt = " ".join(str(df.at[i, c]) for c in df.columns[:3])
        if "domestic" in row_txt.lower() and "residual" in row_txt.lower():
            dom = i
            break
    if dom is None:  # fall back to the first row starting "Domestic"
        for i in range(hdr + 1, len(df)):
            if str(df.at[i, df.columns[0]]).strip().lower().startswith("domestic"):
                dom = i
                break
    if dom is None:
        return None

    def num(role):
        v = pd.to_numeric(df.at[dom, cols[role]], errors="coerce")
        return float(v) if pd.notna(v) else None

    return {"red_p_kwh": num("red"), "amber_p_kwh": num("amber"),
            "green_p_kwh": num("green"), "fixed_p_day": num("fixed")}


def main(argv: list[str]) -> None:
    argparse.ArgumentParser(description="Parse domestic DUoS tariffs from DNO statements.").parse_args(argv[1:])

    files = [f for f in DUOS_DIR.rglob("*.xls*")
             if not any(k in f.name.lower() for k in ("embedded", "idno", "~$"))]
    rows, skipped = [], []
    for f in sorted(files):
        gsp, year = identify(f)
        if gsp is None or year is None:
            skipped.append((f.name, "unidentified"))
            continue
        rec = parse_domestic(f)
        if rec is None:
            skipped.append((f.name, "no domestic row"))
            continue
        rec.update(gsp_group=gsp, charging_year=year, dno=f.parent.name, source_file=f.name)
        rows.append(rec)

    df = pd.DataFrame(rows)
    if df.empty:
        sys.exit("No DUoS tariffs parsed — check the charging statements.")

    # One row per (gsp_group, charging_year): keep the highest-version file if a
    # DNO shipped several. We sort by filename so the last (highest version) wins.
    df = (df.sort_values("source_file").drop_duplicates(["gsp_group", "charging_year"], keep="last"))

    for b in ("red", "amber", "green"):
        df[f"{b}_p_kwh"] = pd.to_numeric(df[f"{b}_p_kwh"], errors="coerce")
    df["fixed_gbp_yr"] = df["fixed_p_day"] * 365 / 100.0           # p/day -> £/yr

    # Join Ofgem's correctly-weighted £/customer/yr for the same charging year (its
    # charge-restriction periods are within-year, so average them to the year).
    if OFGEM_DUOS.exists():
        o = pd.read_csv(OFGEM_DUOS, parse_dates=["period_start"])
        o["charging_year"] = o["period_start"].dt.year
        oy = (o.groupby(["gsp_group", "charging_year"])["duos_gbp_per_customer_yr"]
              .mean().reset_index())
        df = df.merge(oy, on=["gsp_group", "charging_year"], how="left")
    else:
        df["duos_gbp_per_customer_yr"] = pd.NA
        print("  (run `ofgem_pull --extract-duos` for the weighted £/customer column)")

    keep = ["gsp_group", "charging_year", "dno", "red_p_kwh", "amber_p_kwh",
            "green_p_kwh", "fixed_p_day", "fixed_gbp_yr",
            "duos_gbp_per_customer_yr", "source_file"]
    out = cfg.processed_dir() / "duos_domestic_tariffs.csv"
    df[keep].sort_values(["gsp_group", "charging_year"]).to_csv(out, index=False)

    n_area = df["gsp_group"].nunique()
    yrs = f"{int(df['charging_year'].min())}-{int(df['charging_year'].max())}"
    print(f"Parsed {len(df):,} (area x year) raw-rate rows, {n_area}/14 areas, {yrs} -> {out}")
    if skipped:
        print(f"  skipped {len(skipped)} files: "
              f"{', '.join(sorted({w for _, w in skipped}))}")
    matched = df["duos_gbp_per_customer_yr"].notna().sum()
    print(f"  {matched}/{len(df)} rows matched to an Ofgem-weighted £/customer/yr value")


if __name__ == "__main__":
    sys.exit(main(sys.argv))
