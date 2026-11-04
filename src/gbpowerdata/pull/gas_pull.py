"""Build the daily GB gas price series from the ONS System Average Price (SAP).

SAP is the weighted-average price of On-the-Day Commodity Market trades — the GB
within-day balancing gas price, a close free proxy for the NBP day-ahead price
that sets CCGT/OCGT short-run marginal cost. ONS publishes it daily (source:
National Gas Transmission) in pence/kWh; we convert to pence/therm to match the
pipeline convention.

Heating-value basis: gross (GCV, the same as HHV). The OCM trades, and SAP prices, gas in the kWh of the
GB network, which a gas transporter calculates from volumes and calorific values (Gas Act 1986 s.12(1)),
and the Act defines a calorific value as "the number of megajoules (gross)" from burning one cubic metre
of gas at 15°C and 1013.25 millibars (s.12(2), https://www.legislation.gov.uk/ukpga/1986/44/section/12).
Neither ONS nor National Gas print "gross" beside SAP; the basis follows from the unit (checked 26 Oct
2026; docs/AUDIT.md A4-5). Efficiencies and emission factors paired with this price must therefore be
GCV (data/reference/tech_parameters.yaml, docs/thermal_parameters.md).

Coverage: ONS SAP runs Jan 2018 -> present. (The legacy MIPI SOAP service that
held earlier history was decommissioned in 2023, so 2016-2017 is not available
here.)

EDITIONS (4 Nov 2026). ONS republishes the workbook as dated editions, each with the full daily history from Jan
2018 (dataset page: https://www.ons.gov.uk/economy/economicoutputandproductivity/output/datasets/
systemaveragepricesapofgas). The series keeps the history it was built on: the base edition of 18 Dec 2025
(ons_sap_gas.xlsx, to 14 Dec 2025, from which the 2018-2025 panels were built), then each later edition in EDITIONS,
saved as ons_sap_gas_{date}.xlsx, adds only the days after the series' last. Where an edition shares days with the
series, they must agree within AGREE_P_THERM (the 24 Sep 2026 edition agrees with the base on every shared day to
0.012 p/therm), or the build stops. Until 4 Nov 2026 the puller rebuilt the series from ons_sap_gas.xlsx alone
whenever that file existed, which replaced the appended days by the base's; it now merges every edition on disk,
downloads only an edition that is missing, and refuses to replace gas_sap_daily.csv by a series that ends earlier
or has fewer days (--force overrides).

Output (data/raw/): gas_sap_daily.csv  [date, gas_price_pence_per_kwh, gas_price_pence_per_therm]

Usage:
  python -m gbpowerdata.pull.gas_pull                  # download any missing edition, merge them, write the series
  python -m gbpowerdata.pull.gas_pull --no-download    # merge the editions on disk only
  python -m gbpowerdata.pull.gas_pull --file path/to/ons_sap.xlsx [--force]   # one workbook alone
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd
import requests

from gbpowerdata import config as cfg

ONS = ("https://www.ons.gov.uk/file?uri=/economy/economicoutputandproductivity/"
       "output/datasets/systemaveragepricesapofgas/")
BASE = "ons_sap_gas.xlsx"
BASE_URL = ONS + "2025/systemaveragepriceofgasdataset181225.xlsx"     # the 18 Dec 2025 edition
# the later editions, by release date (docstring, EDITIONS); add the newest when ONS republishes
EDITIONS = {
    "2026-09-24": ONS + "2026/systemaveragepriceofgasdataset240926.xlsx",
    "2026-10-29": ONS + "2026/systemaveragepriceofgasdataset291026.xlsx",
}
SHEET = "1.Daily SAP Gas"
OUT = "gas_sap_daily.csv"
AGREE_P_THERM = 0.05
THERM_KWH = 29.3071  # 1 therm = 29.3071 kWh


def edition_file(date: str) -> str:
    return f"ons_sap_gas_{date}.xlsx"


def download(url: str, dst: Path) -> None:
    r = requests.get(url, timeout=120,
                     headers={"User-Agent": "Mozilla/5.0 (research data pull)"})
    r.raise_for_status()
    dst.write_bytes(r.content)
    print(f"Downloaded ONS SAP workbook -> {dst} ({len(r.content):,} bytes)")


def build(xlsx) -> pd.DataFrame:
    df = pd.read_excel(xlsx, sheet_name=SHEET, header=4)
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


def series(raw: Path) -> pd.DataFrame:
    """The base edition, then every dated edition on disk in date order adding the days after the series' last
    (docstring, EDITIONS)."""
    out = build(raw / BASE)
    for f in sorted(raw.glob("ons_sap_gas_*.xlsx")):
        e = build(f)
        shared = out.merge(e, on="date", suffixes=("", "_e"))
        if len(shared):
            gap = (shared["gas_price_pence_per_therm"] - shared["gas_price_pence_per_therm_e"]).abs()
            if gap.max() > AGREE_P_THERM:
                worst = shared.loc[gap.idxmax(), "date"]
                raise SystemExit(f"gas_pull: {f.name} and the series disagree by {gap.max():.3f} p/therm on {worst} "
                                 f"(more than {AGREE_P_THERM})")
        out = pd.concat([out, e[e["date"] > out["date"].max()]], ignore_index=True)
    return out


def main(argv: list[str]) -> None:
    p = argparse.ArgumentParser(description="Build daily GB gas (SAP) price series from ONS.")
    p.add_argument("--file", help="use one already-downloaded ONS workbook alone instead of the editions.")
    p.add_argument("--no-download", action="store_true", help="merge the editions on disk, download none.")
    p.add_argument("--force", action="store_true", help="replace the series even by a shorter one.")
    args = p.parse_args(argv[1:])

    raw = cfg.raw_dir()
    if args.file:
        xlsx = Path(args.file)
        out = build(xlsx if xlsx.is_absolute() else cfg.REPO_ROOT / xlsx)
    else:
        if not args.no_download:
            if not (raw / BASE).exists():
                download(BASE_URL, raw / BASE)
            for date, url in EDITIONS.items():
                if not (raw / edition_file(date)).exists():
                    download(url, raw / edition_file(date))
        out = series(raw)

    path = raw / OUT
    if path.exists() and not args.force:
        old = pd.read_csv(path, usecols=["date"])
        if len(out) < len(old) or out["date"].iloc[-1] < old["date"].iloc[-1]:
            raise SystemExit(f"gas_pull: refusing to replace {OUT} ({len(old)} days to {old['date'].iloc[-1]}) by a "
                             f"shorter series ({len(out)} days to {out['date'].iloc[-1]}); --force overrides")
    out.to_csv(path, index=False)
    span = f"{out['date'].iloc[0]} -> {out['date'].iloc[-1]}"
    print(f"Saved {len(out):,} daily SAP rows ({span}) -> {path.name}")
    yr = out.assign(d=pd.to_datetime(out["date"])).set_index("d")["gas_price_pence_per_therm"]
    print("Annual mean (p/therm):")
    print(yr.resample("YS").mean().round(1).to_string())


if __name__ == "__main__":
    sys.exit(main(sys.argv))
