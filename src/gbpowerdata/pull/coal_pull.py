"""Build a monthly GB coal price for thermal SRMC, from the World Bank Pink Sheet.

GB coal plants burn imported steam coal benchmarked to API 2 (CIF ARA). The World
Bank "Coal, South African" (Richards Bay) monthly series is a free, clean proxy
for ARA-delivered coal (highly correlated with API 2). Converted USD/tonne -> GBP
(ECB FX via Frankfurter) -> GBP/MWh-thermal for use in the SRMC:

    coal_cost £/MWh_e = coal_gbp_per_mwh_thermal / efficiency
    (+ carbon: emissions_factor[Hard Coal]=0.334 tCO2/MWh-th × carbon_price / eff)

The World Bank series is quoted for 6,000 kcal/kg NAR (net as received), so the price per MWh is on
the net calorific value (NCV) basis, and the coal efficiency and emission factor in
data/reference/tech_parameters.yaml are NCV to match it.

Output (data/raw/): coal_monthly.csv [month, coal_usd_per_tonne, coal_gbp_per_mwh_thermal]
Note: GB coal generation fell to ~0 by Sept 2024 (last plant closed), so this
mainly matters for 2018-2023.
"""

from __future__ import annotations

import sys

import pandas as pd
import requests

from gbpowerdata import config as cfg

# World Bank Commodity Markets "Pink Sheet" historical monthly workbook.
WB_URL = ("https://thedocs.worldbank.org/en/doc/"
          "18675f1d1639c7a34d463f59263ba0a2-0050012025/related/CMO-Historical-Data-Monthly.xlsx")
MWH_PER_TONNE = 6.978  # 6,000 kcal/kg NAR (net as received) steam coal, as the World Bank series is quoted
UA = {"User-Agent": "Mozilla/5.0 (research data pull)"}


def main() -> None:
    raw = cfg.raw_dir()
    x = raw / "wb_cmo_monthly.xlsx"
    r = requests.get(WB_URL, headers=UA, timeout=120)
    r.raise_for_status()
    x.write_bytes(r.content)

    df = pd.read_excel(x, sheet_name="Monthly Prices", header=4)
    df = df.rename(columns={df.columns[0]: "wbmonth"})
    col = next(c for c in df.columns if "South African" in str(c))
    df["wbmonth"] = df["wbmonth"].astype(str).str.strip()
    df = df[df["wbmonth"].str.match(r"20(1[89]|2[0-5])M", na=False)].copy()
    df["month"] = df["wbmonth"].str[:4] + "-" + df["wbmonth"].str[5:7]
    df["coal_usd_per_tonne"] = pd.to_numeric(df[col], errors="coerce")

    # USD -> GBP monthly (ECB reference via Frankfurter).
    fx = requests.get("https://api.frankfurter.app/2018-01-01..2025-12-31",
                      params={"from": "USD", "to": "GBP"}, headers=UA, timeout=60).json()
    fxs = pd.Series({pd.Timestamp(d): v["GBP"] for d, v in fx["rates"].items()})
    fxm = fxs.groupby(fxs.index.to_period("M").astype(str)).mean()
    df["fx"] = df["month"].map(fxm)
    df["coal_gbp_per_mwh_thermal"] = (df["coal_usd_per_tonne"] * df["fx"] / MWH_PER_TONNE).round(3)

    out = df[["month", "coal_usd_per_tonne", "coal_gbp_per_mwh_thermal"]].dropna()
    path = raw / "coal_monthly.csv"
    out.to_csv(path, index=False)
    print(f"Saved {len(out)} months ({out['month'].iloc[0]} -> {out['month'].iloc[-1]}) -> {path.name}")
    print("Annual mean coal (GBP/MWh-thermal):")
    yr = out.assign(y=out["month"].str[:4]).groupby("y")["coal_gbp_per_mwh_thermal"].mean()
    print(yr.round(2).to_string())


if __name__ == "__main__":
    sys.exit(main())
