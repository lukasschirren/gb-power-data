"""Build a monthly GB coal price for thermal SRMC: the World Bank's Richards Bay price and the price of the
steam coal the UK landed (HMRC's trade statistics).

THE TWO PRICES
    coal_gbp_per_mwh_thermal          World Bank Pink Sheet "Coal, South African": FOB Richards Bay, NAR
                                      6,000 kcal/kg (the API 4 specification), USD/tonne converted to GBP (ECB
                                      FX via Frankfurter). The World Bank marks Jun-Nov 2022, several months of
                                      2023 and Jan-May 2024 as estimates (CMO historical data, Description sheet).
    coal_landed_gbp_per_mwh_thermal   HMRC overseas trade statistics: UK imports of CN 27011290 (bituminous coal,
                                      not agglomerated, excluding coking coal: the steam coal power stations
                                      burn), from EU and non-EU origins, value over net mass. HMRC values imports
                                      "on a Cost, Insurance and Freight (CIF) delivery terms basis", to "the point
                                      of entry into the UK" (methodology and quality report, section 8.2).
    GB coal plants bought coal priced on API 2 (CIF ARA), Argus/McCloskey's licensed index, so neither series is
    their benchmark. The Richards Bay price leaves out freight to Europe; the landed price includes it, but a
    unit value follows the contracts the cargoes arrived under, and DESNZ notes that the major power producers'
    coal prices "are typically for long-term contracts" (Quarterly Energy Prices, table 3.2.1, methodology).
    Rail from the port to the station is in neither.

WHAT THE LANDED PRICE SHOWS (yearly means of the monthly series, GBP/tonne; pulled 26 Oct 2026)
    year            2018   2019   2020   2021   2022   2023   2024   2025
    landed (CIF)    70.8   71.6   73.3   84.6  208.6  168.6  125.9  112.5
    Richards Bay    73.3   56.3   51.1   87.2  195.0   96.1   82.8   72.1
    imports (Mt)     5.2    2.6    0.9    2.3    4.3    1.8    1.2    0.8
    In 2018 and 2021 the two agree within GBP 3 a tonne; in 2019 and 2020 the landed price is GBP 15 and 22 a
    tonne higher (GBP 2.2 and 3.2 per MWh), on few cargoes in 2020. In the first half of 2022 it was lower
    (GBP 109-202 against 124-237 a tonne), and from September 2022 it is higher in every month, by GBP 32-124
    a tonne (an inference: contracts struck before spot prices fell, and from 2023 small cargoes for other
    users as the coal stations closed). So the freight the
    Richards Bay price leaves out is no fixed amount: about nothing in 2018 and 2021, GBP 2-3 per MWh in
    2019-2020, and of either sign from 2022. API 2 itself is licensed, so the spot benchmark is not checked
    here. fuel_prices keeps Richards Bay as `coal_price_gbp_per_mwh_thermal` (a spot index, the cost of the
    next cargo) and adds the landed price beside it (`coal_landed_price_gbp_per_mwh_thermal`, what the UK's
    cargoes cost at the border) for a backcast to use or to test against (docs/AUDIT.md A4-6).

METHOD OF THE LANDED PRICE
    A month's unit value rests on the cargoes that arrived in it, 1.1 kt in April 2019 and 14 kt in August 2019,
    so the price is the value over the tonnes of a centred window of LANDED_WINDOW months, and coal_cif_uk_kt
    keeps the window's tonnes (in the first and last month the window has two). Rows HMRC suppresses
    (SuppressionIndex not 0) or that carry no mass are left out. HMRC gives no calorific value, so the landed
    price per MWh assumes the imports match the benchmark's 6,000 kcal/kg NAR (MWH_PER_TONNE).

The World Bank series is quoted for 6,000 kcal/kg NAR (net as received), so the price per MWh is on
the net calorific value (NCV) basis, and the coal efficiency and emission factor in
data/reference/tech_parameters.yaml are NCV to match it:

    coal_cost £/MWh_e = coal_gbp_per_mwh_thermal / efficiency
    (+ carbon: emissions_factor[Hard Coal]=0.334 tCO2/MWh-th × carbon_price / eff)

Output (data/raw/):
    coal_monthly.csv        [month, coal_usd_per_tonne, coal_gbp_per_mwh_thermal, coal_cif_uk_gbp_per_tonne,
                             coal_cif_uk_kt, coal_landed_gbp_per_mwh_thermal]
    hmrc_coal_imports.csv   HMRC's rows as published (MonthId, FlowTypeId, CountryId, PortId, Value in GBP,
                            NetMass in kg, SuppressionIndex)
Sources: World Bank Commodity Price Data (CC BY 4.0); HMRC overseas trade statistics, api.uktradeinfo.com
(Open Government Licence v3.0).
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
HMRC_OTS = "https://api.uktradeinfo.com/OTS"
STEAM_COAL_CN8 = 27011290
IMPORT_FLOWS = (1, 3)  # EU imports, non-EU imports (api.uktradeinfo.com/FlowType)
FIRST_YEAR = 2018
LANDED_WINDOW = 3      # months, centred


def hmrc_imports(first_year: int = FIRST_YEAR, last_year: int | None = None) -> pd.DataFrame:
    """HMRC's monthly UK imports of steam coal (STEAM_COAL_CN8) by flow, origin and port, as published."""
    last_year = last_year or pd.Timestamp.today().year
    flows = " or ".join(f"FlowTypeId eq {f}" for f in IMPORT_FLOWS)
    rows = []
    for y in range(first_year, last_year + 1):
        url = HMRC_OTS
        params = {"$filter": f"CommodityId eq {STEAM_COAL_CN8} and MonthId ge {y}01 and MonthId le {y}12 and ({flows})"}
        while url:  # OData pages a long answer through @odata.nextLink
            r = requests.get(url, params=params, headers=UA, timeout=120)
            r.raise_for_status()
            page = r.json()
            rows += page["value"]
            url, params = page.get("@odata.nextLink"), None
    cols = ["MonthId", "FlowTypeId", "CountryId", "PortId", "Value", "NetMass", "SuppressionIndex"]
    return pd.DataFrame(rows, columns=cols).sort_values(cols[:4]).reset_index(drop=True)


def landed(imports: pd.DataFrame, window: int = LANDED_WINDOW) -> pd.DataFrame:
    """Price of the landed steam coal by month: CIF value over tonnes in a centred window of `window` months."""
    ok = imports[(imports["SuppressionIndex"] == 0) & (imports["NetMass"] > 0)]
    m = ok.assign(month=ok["MonthId"].astype(str).str[:4] + "-" + ok["MonthId"].astype(str).str[4:6])
    m = m.groupby("month")[["Value", "NetMass"]].sum()
    months = pd.period_range(m.index.min(), m.index.max(), freq="M").astype(str)
    roll = m.reindex(months, fill_value=0).rolling(window, center=True, min_periods=1).sum()
    out = pd.DataFrame({"month": months,
                        "coal_cif_uk_gbp_per_tonne": (roll["Value"] / (roll["NetMass"] / 1000)).round(2).to_numpy(),
                        "coal_cif_uk_kt": (roll["NetMass"] / 1e6).round(1).to_numpy()})
    out["coal_landed_gbp_per_mwh_thermal"] = (out["coal_cif_uk_gbp_per_tonne"] / MWH_PER_TONNE).round(3)
    return out


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
    imports = hmrc_imports()
    imports.to_csv(raw / "hmrc_coal_imports.csv", index=False)
    out = out.merge(landed(imports), on="month", how="left")
    path = raw / "coal_monthly.csv"
    out.to_csv(path, index=False)
    print(f"Saved {len(out)} months ({out['month'].iloc[0]} -> {out['month'].iloc[-1]}) -> {path.name}; "
          f"HMRC imports {len(imports)} rows -> hmrc_coal_imports.csv")
    print("Annual mean coal (GBP/MWh-thermal), Richards Bay FOB and landed in the UK:")
    yr = out.assign(y=out["month"].str[:4]).groupby("y")[["coal_gbp_per_mwh_thermal", "coal_landed_gbp_per_mwh_thermal"]].mean()
    print(yr.round(2).to_string())


if __name__ == "__main__":
    sys.exit(main())
