"""Renewable Energy Guarantees of Origin (REGOs): the price of a certificate by vintage and month, and the official
figures of the market it trades in -> data/processed/rego_vintages.csv and data/processed/rego_price_monthly.csv.

WHY
    Ofgem issues one REGO for every MWh of renewable electricity an accredited station generates; suppliers redeem
    them to show renewable electricity in their fuel mix disclosure. A REGO is therefore revenue a renewable
    generator earns on every MWh whatever the power price, and a cost to a supplier selling a green tariff. In a
    model of the day-ahead market it sets how far below zero wind and solar outside support will offer (zero less
    the certificate), and in the entry/exit layer it is part of a merchant plant's revenue. Its value moved by two
    orders of magnitude within this panel's years, so one constant does not describe it.

SOURCES
    No official REGO price exists (Ofgem, 2018: "The REGO price is set by the market, so there is no set price"):
    certificates trade over the counter and at e-POWER's e-REGO auctions, and prices reach the public through market
    commentary. data/reference/rego_prices.csv holds every price a freely readable page states (collected and
    checked 26 Oct 2026; 205 rows from 52 pages), with the quote as its locator, the vintage and technology as the
    source states them, and whether the number is a traded level, a bid or offer, an auction average, a forecast or
    an approximate statement (`basis`). Its main series:
      e-POWER (NFPAS Ltd), "e-REGO track record - May 2019 to May 2024": the average price by technology at each of
        its auctions (wind and biomass transcribed), with the vintage sold; free until mid-2024, now 404 on
        epower.net and cited from the Internet Archive's copy; e-POWER has since put auction prices in a paid service.
      C-Zero Markets' monthly REGO reports, February 2023 to June 2025: the prices of the current and forward
        vintages, split into wind/solar/hydro and bio from 2025.
      Cornwall Insight's Green Certificates Survey as reported in its free analyses and press releases (2019-2025),
        Renewable Exchange's REGO Index of bids for REGOs attached to PPAs (2021-2023), Veyt's market notes (2023-2025)
        and suppliers' statements (Good Energy, TotalEnergies, SmartestEnergy, Drax), which fill the gaps.
    Left out: Argus's assessments (licensed price data; its free sample forbids using "single prices"), two ICIS
    figures readable only through a search index, a supplier's retail tariff uplift and an unnamed forecast. A level
    the source writes in pence is in GBP here (status `converted`), and a range read from words ("in the mid £8s" as
    8-9) is `derived`. Where the source names no vintage but the context does (an e-REGO auction's position in the
    compliance year), `vintage_basis` is `inferred`. data/reference/rego_price_sources.csv names each page with its
    URL, the date accessed and its terms: the sources reserve their copyright, so the prices are cited facts with
    their quotes, never the pages, and neither the table nor the outputs below are packed.
    data/reference/rego_statistics.csv holds the official figures, each with its URL and locator (Open Government
    Licence v3.0), checked against the documents on 26 Oct 2026:
      DESNZ's fuel mix disclosure data table (the Electricity (Fuel Mix Disclosure) Regulations 2005) for each
        disclosure period 2014/15-2025/26 (the final edition; older ones from the UK Government Web Archive, because
        gov.uk reuses an attachment's URL for the next edition): the loss factor, the residual fuel mix (the
        electricity no supplier evidenced, imports by the European Attribute Mix included) and the UK fuel mix. The
        residual's renewable share is renewable output no certificate was redeemed for: 8-9% in 2018/19-2019/20,
        2.7-3.5% in 2020/21-2021/22, 12.2% in 2022/23, 0.2-0.3% in 2023/24-2024/25 and 10.8% in 2025/26.
      Ofgem's count of the EU Guarantees of Origin it recognised for GB fuel mix disclosure, 2015/16-2022/23 (17 to
        69 million a year; stated by Ofgem, or summed from its workbooks, status `derived`). From the disclosure
        period beginning 1 April 2023 GoOs no longer count (SI 2022/1247; Ofgem's fuel mix disclosure page): REGOs
        are then the only evidence of renewable supply, and the 2023/24 vintage went from about GBP 8 to 25.

VINTAGES
    A certificate's vintage is the compliance period of its generation, April to March, numbered as the Renewables
    Obligation's: CP1 is April 2002 to March 2003, so CP22 is April 2023 to March 2024 (vintage_of). Suppliers
    redeem a vintage for the fuel mix disclosure of the same period, by the following 1 July (Ofgem's REGO
    guidance). The value of generation in a month is the price of its own vintage, which trades before, during and
    after the period.

METHOD
    rego_vintages.csv, one row per vintage CP (generation_from/to): the number of price observations of the vintage
    (all technologies; every basis but forecasts; bounds such as "below 20p" left out, being no level) and how many
    have an inferred vintage, their median (a range at its midpoint), lowest and highest levels (a range contributes
    its low and high) and the first and last month observed; the disclosure period's fuel mix figures
    (fmd_* columns) and the EU GoOs Ofgem recognised for it (0 from 2023/24). The median pools every month a vintage
    traded in, forward quotes included: CP24's (1.48) rests on quotes of 2024-25, while a supplier put a REGO at 34p
    in December 2025. It summarises what the sources report, not a traded index.
    rego_price_monthly.csv, one row per month and vintage ("unstated" where none is named), from the observations
    dated within that month, with the same statistics; current_vintage marks the vintage being generated in the
    month, whose price then is the value of a MWh generated then as known at the time: GBP 0.10-0.55 from
    September 2019 to February 2021, 2.5-6.3 from October 2021 to March 2023, 8-15 from April 2023 to March 2024
    (24.80 at e-POWER's auction of 17 October 2023), 7.5-8.5 from April to July 2024, 2.0-5.5 from August 2024 to
    January 2025 and 0.5-1.0 from February to June 2025. Nothing is interpolated between months; months without an
    observation are absent.

COVERAGE AND GAPS
    Before May 2019 only approximate statements exist (about GBP 0.15-0.50). From July 2025 the free sources thin
    out to four supplier statements without a vintage: GBP 1-2 in August 2025 (TotalEnergies), and about 30p late in
    2025, 34p in December 2025 and 71p in August 2026 (Good Energy). The volumes behind the prices, REGOs issued and
    redeemed by technology, are in the Renewable Electricity Register's public reports, which Ofgem provides through
    a SharePoint on request (renewable.enquiry@ofgem.gov.uk), so no puller fetches them (docs/DATA_GAPS.md). Ofgem's
    REGO guidance names no fee for accreditation or issue; e-POWER charged sellers 10p a REGO at its auctions in
    2022 (Veyt, 8 Sep 2022).

Outputs (data/processed/): rego_vintages.csv, rego_price_monthly.csv; read them with
gbpowerdata.processed.read_rego(). Not packed (datapack): their prices are cited from commentary.

Usage: python -m gbpowerdata.build.rego
"""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from gbpowerdata import config as cfg

PRICE_FILE = "rego_prices.csv"
SOURCE_FILE = "rego_price_sources.csv"
STATISTICS_FILE = "rego_statistics.csv"
PRICE_COLUMNS = ["observed_from", "observed_to", "vintage", "vintage_basis", "generation_from", "generation_to",
                 "technology", "value", "low", "high", "unit", "basis", "source", "locator", "status", "note"]
VINTAGE_BASES = ("stated", "inferred", "none")
SOURCE_COLUMNS = ["source_id", "publisher", "title", "published", "kind", "url", "accessed", "licence"]
STATISTICS_COLUMNS = ["stat", "period", "period_from", "period_to", "value", "unit", "publisher", "title", "url",
                      "locator", "licence", "status", "checked", "note"]
BASES = ("traded", "bid", "offer", "auction_average", "auction_high", "forecast", "approximate")
SUMMARY_BASES = tuple(b for b in BASES if b != "forecast")
FIRST_CP_YEAR = 2002  # CP1 = April 2002 to March 2003


def vintage_of(month) -> int:
    """The compliance period (CP number) of generation in `month`: April to March, CP1 from April 2002."""
    t = pd.Timestamp(month)
    return t.year - FIRST_CP_YEAR + 1 if t.month >= 4 else t.year - FIRST_CP_YEAR


def vintage_period(cp: int) -> tuple[str, str]:
    """First and last month (YYYY-MM) of the generation of vintage `cp`."""
    start = FIRST_CP_YEAR + cp - 1
    return f"{start}-04", f"{start + 1}-03"


def disclosure_label(cp: int) -> str:
    """The disclosure period of vintage `cp` as DESNZ and Ofgem write it, e.g. 2023/24 for CP22."""
    start = FIRST_CP_YEAR + cp - 1
    return f"{start}/{str(start + 1)[2:]}"


def read_prices(ref=None) -> pd.DataFrame:
    """The cited price observations with their vintage as a CP number (`cp`, from generation_from)."""
    ref = ref or cfg.reference_dir()
    p = pd.read_csv(ref / PRICE_FILE, dtype={"observed_from": str, "observed_to": str, "generation_from": str,
                                             "generation_to": str})
    p["cp"] = p["generation_from"].map(lambda m: vintage_of(m) if isinstance(m, str) and m else np.nan)
    return p


def within_a_month(p: pd.DataFrame) -> pd.Series:
    """Observations dated to a day or a month, or a span inside one month (not a quarter, a year or a 'since')."""
    f, t = p["observed_from"].fillna(""), p["observed_to"].fillna("")
    return (f.str.len() >= 7) & (f.str[:7] == t.str[:7])


def summarise(p: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    """Per group: observations, the median of their levels (a range counts at its midpoint), the lowest and highest
    level any observation reports (a point's value, a range's low and high), and the first and last month. Forecasts
    and bounds (only a low or only a high: "above GBP 0.40", "below 20p") are left out: neither is a price level."""
    level = p["value"].notna() | (p["low"].notna() & p["high"].notna())
    p = p[p["basis"].isin(SUMMARY_BASES) & p[by].notna().all(axis=1) & level].copy()
    p["month"] = p["observed_from"].str[:7]
    rows = []
    for key, g in p.groupby(by, sort=True):
        key = key if isinstance(key, tuple) else (key,)
        lv = pd.concat([g["value"], g["low"], g["high"]]).dropna()
        mid = g["value"].fillna((g["low"] + g["high"]) / 2)
        inferred = int((g["vintage_basis"] == "inferred").sum()) if "vintage_basis" in g else 0
        rows.append(dict(zip(by, key), n_obs=len(g), n_vintage_inferred=inferred,
                         price_median=round(float(mid.median()), 3),
                         price_min=round(float(lv.min()), 3), price_max=round(float(lv.max()), 3),
                         first_observed=g["month"].min(), last_observed=g["month"].max(),
                         sources=";".join(sorted(g["source"].unique()))))
    return pd.DataFrame(rows)


def vintages(p: pd.DataFrame, stats: pd.DataFrame) -> pd.DataFrame:
    """One row per vintage from the first observed or reported to the last: prices and the period's statistics."""
    cps = set(p["cp"].dropna().astype(int))
    st = stats.assign(cp=stats["period_from"].map(vintage_of))
    cps |= set(st["cp"].astype(int))
    out = pd.DataFrame({"cp": sorted(cps)})
    out["vintage"] = "CP" + out["cp"].astype(str)
    out["generation_from"], out["generation_to"] = zip(*out["cp"].map(vintage_period))
    out["disclosure_period"] = out["cp"].map(disclosure_label)
    out = out.merge(summarise(p, ["cp"]), on="cp", how="left")
    wide = st.pivot_table(index="cp", columns="stat", values="value", aggfunc="first")
    out = out.merge(wide, left_on="cp", right_index=True, how="left")
    if "eu_goo_recognised" in out:
        # GoOs count for GB fuel mix disclosure until 2022/23 only (Ofgem, REGO public reports and data page)
        out.loc[out["cp"] >= vintage_of("2023-04"), "eu_goo_recognised"] = 0
    out["n_obs"] = out["n_obs"].fillna(0).astype(int)
    return out


def build(ref=None, out_dir=None) -> tuple[pd.DataFrame, pd.DataFrame]:
    ref, out_dir = ref or cfg.reference_dir(), out_dir or cfg.processed_dir()
    p = read_prices(ref)
    stats = pd.read_csv(ref / STATISTICS_FILE, dtype={"period_from": str, "period_to": str})
    v = vintages(p, stats)
    one = p[within_a_month(p)].assign(month=lambda d: d["observed_from"].str[:7],
                                      vintage_label=lambda d: d["cp"].map(lambda c: "unstated" if pd.isna(c) else f"CP{int(c)}"))
    m = summarise(one, ["month", "vintage_label"]).rename(columns={"vintage_label": "vintage"})
    # the vintage being generated in the month: its price then is the value of a MWh generated then, as known then
    m.insert(2, "current_vintage", m["vintage"] == m["month"].map(lambda t: f"CP{vintage_of(t)}"))
    v.to_csv(out_dir / "rego_vintages.csv", index=False)
    m.to_csv(out_dir / "rego_price_monthly.csv", index=False)
    print(f"  rego_vintages.csv: {len(v)} vintages ({v['vintage'].iloc[0]}-{v['vintage'].iloc[-1]}), "
          f"{int(v['n_obs'].sum())} observations; rego_price_monthly.csv: {len(m)} vintage-months")
    return v, m


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args()
    build()
