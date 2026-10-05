"""Build the monthly GB carbon price series across the EU-ETS -> UK-ETS switch.

GB thermal generators faced the EU ETS allowance (EUA) price until the UK left it
end-2020, then the UK ETS allowance (UKA) price from 2021. This assembles one
monthly carbon series in GBP/tonne, tagged by scheme:

  2018-2020  EUA  - EEX EU-ETS primary-auction clearing price (EUR/t), converted
                    to GBP via ECB EUR->GBP (Frankfurter API).
  2021+      UKA  - gov.uk UK-ETS "CCM trigger prices and average monthly prices"
                    table (already GBP/t). UK ETS began May 2021; Jan-Apr 2021 is
                    backfilled with the first available UKA month.

Carbon moves slowly, so a monthly series (interpolated to half-hourly in Stage 2)
is adequate. Output (data/raw/): carbon_monthly.csv [month, carbon_price_gbp_per_tonne, scheme]

Sources (all free):
  EEX   https://public.eex-group.com/eex/eua-auction-report/
  govuk https://www.gov.uk/.../cost-containment-mechanism-ccm-trigger-prices-and-average-monthly-prices-full-table
  FX    https://api.frankfurter.app  (ECB reference rates)
"""

from __future__ import annotations

import io
import re
import sys

import pandas as pd
import requests

from gbpowerdata import config as cfg

UA = {"User-Agent": "Mozilla/5.0 (research data pull)"}
EEX = ("https://public.eex-group.com/eex/eua-auction-report/"
       "emission-spot-primary-market-auction-report-{year}-data.{ext}")
GOVUK = ("https://www.gov.uk/government/publications/taking-part-in-the-uk-emissions-"
         "trading-scheme-markets/cost-containment-mechanism-ccm-trigger-prices-and-"
         "average-monthly-prices-full-table")
EUA_YEARS = (2018, 2019, 2020)


def _num(x) -> float:
    """Pull a float out of a possibly currency-prefixed / mis-encoded string."""
    m = re.search(r"-?\d+(?:\.\d+)?", str(x).replace(",", ""))
    return float(m.group()) if m else float("nan")


# --------------------------------------------------------------------------- #
# EUA (EU ETS) — EEX auctions, EUR/t -> GBP/t
# --------------------------------------------------------------------------- #
def eua_monthly() -> pd.DataFrame:
    rows = []
    raw = cfg.raw_dir() / "eex_eua"
    raw.mkdir(parents=True, exist_ok=True)
    for y in EUA_YEARS:
        path = None
        for ext in ("xlsx", "xls"):
            r = requests.get(EEX.format(year=y, ext=ext), headers=UA, timeout=120)
            if r.status_code == 200 and len(r.content) > 5000:
                path = raw / f"eua_{y}.{ext}"
                path.write_bytes(r.content)
                break
        if path is None:
            print(f"  EUA {y}: download failed")
            continue
        df = pd.read_excel(path, sheet_name="Primary Market Auction", header=5)
        df = df[df["Date"].notna()].copy()
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        df["price"] = pd.to_numeric(df["Auction Price €/tCO2"], errors="coerce")
        df = df.dropna(subset=["Date", "price"])
        rows.append(df[["Date", "price"]])
        print(f"  EUA {y}: {len(df)} auctions, mean EUR {df['price'].mean():.2f}/t")
    eua = pd.concat(rows, ignore_index=True)
    eua["month"] = eua["Date"].dt.to_period("M")
    monthly = eua.groupby("month")["price"].mean().rename("eua_eur").reset_index()

    # ECB EUR->GBP, monthly mean.
    fx = requests.get("https://api.frankfurter.app/2018-01-01..2020-12-31",
                      params={"from": "EUR", "to": "GBP"}, headers=UA, timeout=60).json()
    fxs = pd.Series({pd.Timestamp(d): v["GBP"] for d, v in fx["rates"].items()})
    fxm = fxs.groupby(fxs.index.to_period("M")).mean()
    monthly["fx"] = monthly["month"].map(fxm)
    monthly["carbon_price_gbp_per_tonne"] = (monthly["eua_eur"] * monthly["fx"]).round(3)
    monthly["scheme"] = "EU-ETS"
    return monthly[["month", "carbon_price_gbp_per_tonne", "scheme"]]


# --------------------------------------------------------------------------- #
# UKA (UK ETS) — gov.uk CCM monthly table, already GBP/t
# --------------------------------------------------------------------------- #
def uka_monthly() -> pd.DataFrame:
    html = requests.get(GOVUK, headers=UA, timeout=60).text
    out = {}
    for t in pd.read_html(io.StringIO(html)):
        period_col = next((c for c in t.columns if "monitoring period" in str(c)), None)
        price_cols = [c for c in t.columns if "average price" in str(c)]
        if not period_col or not price_cols:
            continue
        n = len(price_cols)
        for _, r in t.iterrows():
            decision = pd.to_datetime(str(r["Month"]), format="%b-%y", errors="coerce")
            if pd.isna(decision):
                continue
            for k, pc in enumerate(price_cols):  # Month k+1 = decision - (n - k)
                price = _num(r[pc])
                if pd.isna(price):
                    continue
                m = (decision - pd.DateOffset(months=n - k)).to_period("M")
                out[m] = price  # later periods overwrite with the same confirmed value
    s = pd.Series(out).sort_index()
    # Backfill UK-ETS launch gap (Jan-Apr 2021) with the first available month.
    full = pd.period_range(f"{s.index.min().year}-01", s.index.max(), freq="M")
    s = s.reindex(full).bfill()
    df = s.rename("carbon_price_gbp_per_tonne").reset_index()
    df = df.rename(columns={df.columns[0]: "month"})
    df["scheme"] = "UK-ETS"
    return df


def main() -> None:
    print("EUA (EU ETS, 2018-2020):")
    eua = eua_monthly()
    print("UKA (UK ETS, 2021+): gov.uk CCM table")
    uka = uka_monthly()
    uka = uka[uka["month"].astype(str) >= "2021-01"]

    carbon = pd.concat([eua, uka], ignore_index=True).sort_values("month")
    carbon["month"] = carbon["month"].astype(str)
    path = cfg.raw_dir() / "carbon_monthly.csv"
    carbon.to_csv(path, index=False)
    print(f"\nSaved {len(carbon)} months ({carbon['month'].iloc[0]} -> {carbon['month'].iloc[-1]}) "
          f"-> {path.name}")
    print("\nAnnual mean carbon (GBP/t):")
    yr = carbon.assign(y=carbon["month"].str[:4]).groupby("y")["carbon_price_gbp_per_tonne"].mean()
    print(yr.round(1).to_string())


if __name__ == "__main__":
    sys.exit(main())
