"""Build the daily GB gas price series from the ONS System Average Price (SAP).

SAP is the weighted-average price of On-the-Day Commodity Market trades — the GB
within-day balancing gas price, a close free proxy for the NBP day-ahead price
that sets CCGT/OCGT short-run marginal cost. ONS publishes it daily (source:
National Gas Transmission) in pence/kWh; we convert to pence/therm to match the
pipeline convention.

Coverage: ONS SAP runs Jan 2018 -> present. (The legacy MIPI SOAP service that
held earlier history was decommissioned in 2023, so 2016-2017 is not available
here.)

Output (data/raw/): gas_sap_daily.csv  [date, gas_price_pence_per_kwh, gas_price_pence_per_therm]

Usage:
  python -m gbpowerdata.pull.gas_pull            # download latest ONS workbook + build the series
  python -m gbpowerdata.pull.gas_pull --file path/to/ons_sap.xlsx
"""

from __future__ import annotations

import argparse
import sys

import pandas as pd
import requests

from gbpowerdata import config as cfg

# Latest ONS "System Average Price of Gas" workbook (date-stamped edition; update
# when ONS republishes — it carries the full daily history from Jan 2018). The dataset page
# (.../datasets/systemaveragepricesapofgas) lists the newest edition under /current/. The
# 24 Sep 2026 edition runs to 20 Sep 2026 and matches the 18 Dec 2025 one on every shared day
# to 0.012 p/therm; it was appended to gas_sap_daily.csv for the 2026 days only.
ONS_URL = ("https://www.ons.gov.uk/file?uri=/economy/economicoutputandproductivity/"
           "output/datasets/systemaveragepricesapofgas/2026/"
           "systemaveragepriceofgasdataset240926.xlsx")
THERM_KWH = 29.3071  # 1 therm = 29.3071 kWh


def download(dst) -> None:
    r = requests.get(ONS_URL, timeout=120,
                     headers={"User-Agent": "Mozilla/5.0 (research data pull)"})
    r.raise_for_status()
    dst.write_bytes(r.content)
    print(f"Downloaded ONS SAP workbook -> {dst} ({len(r.content):,} bytes)")


def build(xlsx) -> pd.DataFrame:
    df = pd.read_excel(xlsx, sheet_name="1.Daily SAP Gas", header=4)
    df = df.rename(columns={df.columns[0]: "date", df.columns[1]: "sap_p_kwh"})
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).copy()
    df["sap_p_kwh"] = pd.to_numeric(df["sap_p_kwh"], errors="coerce")
    df = df.dropna(subset=["sap_p_kwh"])
    out = pd.DataFrame({
        "date": df["date"].dt.strftime("%Y-%m-%d"),
        "gas_price_pence_per_kwh": df["sap_p_kwh"].round(4),
        "gas_price_pence_per_therm": (df["sap_p_kwh"] * THERM_KWH).round(3),
    })
    return out.reset_index(drop=True)


def main(argv: list[str]) -> None:
    p = argparse.ArgumentParser(description="Build daily GB gas (SAP) price series from ONS.")
    p.add_argument("--file", help="use an already-downloaded ONS workbook instead of fetching.")
    args = p.parse_args(argv[1:])

    raw = cfg.raw_dir()
    xlsx = raw / "ons_sap_gas.xlsx"
    if args.file:
        xlsx = cfg.REPO_ROOT / args.file if not str(args.file).startswith("/") else args.file
    elif not xlsx.exists():
        download(xlsx)

    out = build(xlsx)
    path = raw / "gas_sap_daily.csv"
    out.to_csv(path, index=False)
    span = f"{out['date'].iloc[0]} -> {out['date'].iloc[-1]}"
    print(f"Saved {len(out):,} daily SAP rows ({span}) -> {path.name}")
    yr = out.assign(d=pd.to_datetime(out["date"])).set_index("d")["gas_price_pence_per_therm"]
    print("Annual mean (p/therm):")
    print(yr.resample("YS").mean().round(1).to_string())


if __name__ == "__main__":
    sys.exit(main(sys.argv))
