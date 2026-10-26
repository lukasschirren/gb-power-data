"""Build the monthly GB carbon price series across the EU-ETS -> UK-ETS switch.

GB thermal generators faced the EU ETS allowance (EUA) price until the UK left it
end-2020, then the UK ETS allowance (UKA) price from 2021. This assembles one
monthly carbon series in GBP/tonne, tagged by scheme:

  2018-2020     EUA  - EEX EU-ETS primary-auction clearing price (EUR/t), converted
                       to GBP via ECB EUR->GBP (Frankfurter API).
  Jan-Apr 2021  "UK-ETS (EUA proxy)" - the EUA auction price of the month in GBP, as above.
  May 2021 on   UKA  - gov.uk UK-ETS "CCM trigger prices and average monthly prices"
                       table (already GBP/t).

THE FIRST MONTHS OF THE UK ETS
    The UK ETS "came into effect on 1 January 2021" (gov.uk, Participating in the UK ETS), so emissions from
    January 2021 had to be covered by UK allowances, surrendered by 30 April of the next year. No UK allowance
    traded until ICE Endex's first auction on 19 May 2021, and the CCM table's first month is May 2021. The cost
    of carbon to a generator in January-April 2021 was therefore the price it expected a UKA to fetch, which no
    market published. The proxy is the EUA price of the same month: the price of the scheme GB had just left,
    observed at the time. On 19 May 2021 the first UK auction cleared at GBP 43.99 (ICAP, "UK ETS holds first
    auction") and the EU auction of the same day at EUR 52.12, GBP 44.94 at that day's ECB rate (0.86233): the
    first UK price sat 2% below the EU one, which supports reading the EUA as the price the market expected for
    a UKA (an inference). The EU's auctions of 2021 began on 29 January, so January's EUA mean rests on that
    one day.
    Until 26 Oct 2026 the four months carried the first UKA month (the May 2021 average) labelled UK-ETS: a
    price from after the period, which stage 2's interpolation between mid-month values also carried into late
    December 2020 (docs/AUDIT.md A4-1). `--backfill first-uka` rebuilds that series as a sensitivity, labelled
    "UK-ETS (first UKA month)". Another candidate, not built, is the UK ETS carbon price DESNZ sets for 2021
    civil penalties: an average of the 2021 auctions, so also from after the period.
    The EUA months come from EEX, whose terms do not allow passing the data on, so fuel_prices_2021 stays out
    of the data pack (datapack.EEX_YEARS), as it already did for its first half of January.

Carbon moves slowly, so a monthly series (interpolated to half-hourly in Stage 2)
is adequate. Output (data/raw/): carbon_monthly.csv [month, carbon_price_gbp_per_tonne, scheme]

Sources (all free):
  EEX   https://public.eex-group.com/eex/eua-auction-report/
  govuk https://www.gov.uk/.../cost-containment-mechanism-ccm-trigger-prices-and-average-monthly-prices-full-table
  FX    https://api.frankfurter.app  (ECB reference rates)

Usage:  python -m gbpowerdata.pull.carbon_pull [--backfill {eua,first-uka}]     (default eua)
"""

from __future__ import annotations

import argparse
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
EUA_YEARS = (2018, 2019, 2020, 2021)  # 2021 for the proxy of January-April
UK_ETS_START = "2021-01"
BACKFILLS = {"eua": "UK-ETS (EUA proxy)", "first-uka": "UK-ETS (first UKA month)"}


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
    fx = requests.get(f"https://api.frankfurter.app/{EUA_YEARS[0]}-01-01..{EUA_YEARS[-1]}-12-31",
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
    """The months the CCM table prices (from May 2021), with no back-fill: combine() fills the months before."""
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
    df = s.rename("carbon_price_gbp_per_tonne").reset_index()
    df = df.rename(columns={df.columns[0]: "month"})
    df["scheme"] = "UK-ETS"
    return df


def combine(eua: pd.DataFrame, uka: pd.DataFrame, backfill: str = "eua") -> pd.DataFrame:
    """One monthly series: EUA before UK_ETS_START, the back-filled months from it to the first UKA month, UKA after.

    `backfill` "eua" prices each back-filled month at that month's EUA price, "first-uka" at the first UKA month's;
    either way the scheme says which (BACKFILLS)."""
    if backfill not in BACKFILLS:
        raise ValueError(f"backfill {backfill!r}: one of {sorted(BACKFILLS)}")
    eua = eua.assign(month=eua["month"].astype(str))
    uka = uka.assign(month=uka["month"].astype(str)).sort_values("month")
    uka = uka[uka["month"] >= UK_ETS_START]
    first = uka["month"].iloc[0]
    gap = pd.period_range(UK_ETS_START, first, freq="M")[:-1].astype(str)
    if backfill == "eua":
        fill = eua.set_index("month").reindex(gap)["carbon_price_gbp_per_tonne"]
        if fill.isna().any():
            raise ValueError(f"no EUA price for {list(fill.index[fill.isna()])}: EUA_YEARS must cover them")
    else:
        fill = pd.Series(uka["carbon_price_gbp_per_tonne"].iloc[0], index=gap)
    filled = pd.DataFrame({"month": gap, "carbon_price_gbp_per_tonne": fill.to_numpy(), "scheme": BACKFILLS[backfill]})
    out = pd.concat([eua[eua["month"] < UK_ETS_START], filled, uka], ignore_index=True)
    return out[["month", "carbon_price_gbp_per_tonne", "scheme"]].sort_values("month").reset_index(drop=True)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--backfill", choices=sorted(BACKFILLS), default="eua",
                    help="price of January-April 2021, before the first UK auction (default eua)")
    a = ap.parse_args(argv)
    print(f"EUA (EU ETS, {EUA_YEARS[0]}-{EUA_YEARS[-1]}):")
    eua = eua_monthly()
    print("UKA (UK ETS, 2021+): gov.uk CCM table")
    uka = uka_monthly()

    carbon = combine(eua, uka, a.backfill)
    path = cfg.raw_dir() / "carbon_monthly.csv"
    carbon.to_csv(path, index=False)
    print(f"\nSaved {len(carbon)} months ({carbon['month'].iloc[0]} -> {carbon['month'].iloc[-1]}) "
          f"-> {path.name}; {BACKFILLS[a.backfill]} for {', '.join(carbon.loc[carbon['scheme'] == BACKFILLS[a.backfill], 'month'])}")
    print("\nAnnual mean carbon (GBP/t):")
    yr = carbon.assign(y=carbon["month"].str[:4]).groupby("y")["carbon_price_gbp_per_tonne"].mean()
    print(yr.round(1).to_string())


if __name__ == "__main__":
    sys.exit(main())
