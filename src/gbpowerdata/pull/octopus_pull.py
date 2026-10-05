"""Pull GB retail electricity tariffs from the Octopus Energy REST API.

Public endpoints, **no API key** (only account/consumption data needs auth, which
we neither need nor pull). Base: https://api.octopus.energy/v1

Two products, both keyed by GSP group:

  AGILE-18-02-21  half-hourly wholesale-passthrough retail price. Octopus stopped
                  *selling* this in 2022 but still publishes rates for legacy
                  customers, so this single product code yields a gapless
                  half-hourly series from 2018-01-01 to today — the later Agile
                  codes (AGILE-FLEX-22-11-25, AGILE-23-12-06, AGILE-24-*) are
                  re-sales of the same formula and add no history.
  VAR-18-02-14    the standard variable tariff ("Flexible Octopus"), which tracks
    + VAR-22-11-01  the Ofgem default tariff cap. Two codes cover 2018-02 -> now;
                  the intermediate codes (VAR-19-04-12, VAR-21-05-19, VAR-22-04-02)
                  are new-customer entry points onto the *same* price schedule and
                  are bit-identical to VAR-18-02-14 on every shared date.

Region letters map 1:1 onto the `gsp_group` ids already produced by
`gbpowerdata.common.gsp` (_A.._P), so the output joins straight onto the locational
fleet with no crosswalk.

Prices are published in p/kWh; we carry a £/MWh column too, since every other
price series in this pipeline (MID, gas, carbon) is £/MWh.

⚠️ **Agile is censored at the top.** The tariff is hard-capped at 33.33 p/kWh
exc VAT (34.9965 inc), and the cap binds hard in the crisis years: 25.6% of all
half-hours in 2021 and **57.6% in 2022** sit exactly on it (12.5% across
2018-2025). Agile is therefore *not* a clean observation of wholesale passthrough
whenever prices are high — treat it as right-censored, and filter on the
`at_price_cap` flag before using it as a validation target or fitting anything to
it. The floor is not censored: negative prices pass through (42 half-hours in
2018 rising to 4,340 in 2024).

Usage:
  python -m gbpowerdata.pull.octopus_pull                    # agile + svt, all regions
  python -m gbpowerdata.pull.octopus_pull svt                # standard variable only
  python -m gbpowerdata.pull.octopus_pull agile --regions _C _M --years 2023 2024
"""

from __future__ import annotations

import argparse
import sys
import time

import pandas as pd
import requests

from gbpowerdata import config as cfg

API = "https://api.octopus.energy/v1"
OUT_DIR = cfg.raw_dir() / "octopus"

AGILE_PRODUCT = "AGILE-18-02-21"
SVT_PRODUCTS = ("VAR-18-02-14", "VAR-22-11-01")
GSP_GROUPS = ("_A", "_B", "_C", "_D", "_E", "_F", "_G", "_H",
              "_J", "_K", "_L", "_M", "_N", "_P")
PAGE_SIZE = 1500  # API hard cap; a year of half-hourly data is 12 pages
AGILE_CAP_P_KWH_EXC_VAT = 33.33  # see the censoring warning in the module docstring


def _get(url: str, params: dict | None = None) -> dict:
    for attempt in range(4):
        r = requests.get(url, params=params, timeout=120)
        if r.status_code == 200:
            return r.json()
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(2 ** attempt)
            continue
        r.raise_for_status()
    raise RuntimeError(f"giving up on {url}")


def fetch_rates(product: str, group: str, endpoint: str,
                period_from: str | None = None, period_to: str | None = None) -> pd.DataFrame:
    """All records from one tariff rate endpoint, following pagination."""
    tariff = f"E-1R-{product}-{group.lstrip('_')}"
    url = f"{API}/products/{product}/electricity-tariffs/{tariff}/{endpoint}/"
    params = {"page_size": PAGE_SIZE}
    if period_from:
        params["period_from"] = period_from
    if period_to:
        params["period_to"] = period_to
    rows: list[dict] = []
    while url:
        j = _get(url, params)
        rows.extend(j["results"])
        url, params = j.get("next"), None  # `next` carries the query string
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["gsp_group"] = group
    df["product_code"] = product
    return df


def _tidy(df: pd.DataFrame) -> pd.DataFrame:
    """Common cleanup: UTC timestamps, GBP/MWh alongside the published p/kWh."""
    for c in ("valid_from", "valid_to"):
        df[c] = pd.to_datetime(df[c], utc=True, errors="coerce")
    for c in ("value_exc_vat", "value_inc_vat"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    # p/kWh -> GBP/MWh: 1 p/kWh = 10 GBP/MWh.
    df["price_gbp_mwh_exc_vat"] = df["value_exc_vat"] * 10.0
    df["price_gbp_mwh_inc_vat"] = df["value_inc_vat"] * 10.0
    if "payment_method" not in df.columns:
        df["payment_method"] = pd.NA
    return df.rename(columns={"value_exc_vat": "price_p_kwh_exc_vat",
                              "value_inc_vat": "price_p_kwh_inc_vat"})


def pull_agile(groups: tuple[str, ...], years: range | list[int]) -> None:
    """Half-hourly Agile rates, cached per (region, year) so re-runs cost no calls."""
    cache = OUT_DIR / "agile" / "by_year"
    cache.mkdir(parents=True, exist_ok=True)
    frames = []
    for group in groups:
        for year in years:
            path = cache / f"agile_{group}_{year}.csv"
            if path.exists():
                frames.append(pd.read_csv(path, parse_dates=["valid_from", "valid_to"]))
                continue
            df = fetch_rates(AGILE_PRODUCT, group, "standard-unit-rates",
                             f"{year}-01-01T00:00Z", f"{year + 1}-01-01T00:00Z")
            if df.empty:
                print(f"  {group} {year}: no data", flush=True)
                continue
            df = _tidy(df).sort_values("valid_from")
            df.to_csv(path, index=False)
            print(f"  {group} {year}: {len(df):,} periods -> {path.name}", flush=True)
            frames.append(df)
            time.sleep(0.2)
    if not frames:
        return
    out = pd.concat(frames, ignore_index=True).sort_values(["valid_from", "gsp_group"])
    # Right-censoring flag — computed here (not in the cache) so it also applies to
    # region-years pulled by an earlier run.
    out["at_price_cap"] = out["price_p_kwh_exc_vat"] >= AGILE_CAP_P_KWH_EXC_VAT - 1e-3
    keep = ["valid_from", "valid_to", "gsp_group", "product_code",
            "price_p_kwh_exc_vat", "price_p_kwh_inc_vat",
            "price_gbp_mwh_exc_vat", "price_gbp_mwh_inc_vat", "at_price_cap"]
    path = OUT_DIR / f"agile_halfhourly_{min(years)}_{max(years)}.csv"
    out[keep].to_csv(path, index=False)
    capped = out["at_price_cap"].mean()
    print(f"Saved {len(out):,} rows x {len(keep)} cols -> {path}", flush=True)
    print(f"  ! {capped:.1%} of half-hours sit at the {AGILE_CAP_P_KWH_EXC_VAT} p/kWh "
          f"cap - Agile is right-censored, filter on at_price_cap", flush=True)


def pull_svt(groups: tuple[str, ...]) -> None:
    """Standard-variable unit rates + standing charges (whole history, small)."""
    for endpoint, stem in (("standard-unit-rates", "svt_unit_rates"),
                           ("standing-charges", "svt_standing_charges")):
        frames = []
        for product in SVT_PRODUCTS:
            for group in groups:
                df = fetch_rates(product, group, endpoint)
                if not df.empty:
                    frames.append(_tidy(df))
                time.sleep(0.1)
        if not frames:
            continue
        out = (pd.concat(frames, ignore_index=True)
               .sort_values(["gsp_group", "payment_method", "valid_from"]))
        # The intermediate VAR codes are identical to VAR-18-02-14, and the two we
        # keep overlap in 2022-11 -> 2023-03; dedupe on the economic key so the
        # series is one price per (region, payment method, period).
        out = out.drop_duplicates(
            subset=["gsp_group", "payment_method", "valid_from", "price_p_kwh_inc_vat"])
        keep = ["valid_from", "valid_to", "gsp_group", "product_code", "payment_method",
                "price_p_kwh_exc_vat", "price_p_kwh_inc_vat",
                "price_gbp_mwh_exc_vat", "price_gbp_mwh_inc_vat"]
        # Standing charges are p/day, not p/kWh — the GBP/MWh columns are meaningless.
        if endpoint == "standing-charges":
            out = out.rename(columns={"price_p_kwh_exc_vat": "charge_p_day_exc_vat",
                                      "price_p_kwh_inc_vat": "charge_p_day_inc_vat"})
            keep = ["valid_from", "valid_to", "gsp_group", "product_code", "payment_method",
                    "charge_p_day_exc_vat", "charge_p_day_inc_vat"]
        path = OUT_DIR / f"{stem}.csv"
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        out[keep].to_csv(path, index=False)
        print(f"Saved {len(out):,} rows x {len(keep)} cols -> {path}", flush=True)


def main(argv: list[str]) -> None:
    p = argparse.ArgumentParser(description="Pull GB retail tariffs from the Octopus API.")
    p.add_argument("products", nargs="*", choices=["agile", "svt"], default=["agile", "svt"],
                   help="which tariff families to pull (default: both).")
    p.add_argument("--regions", nargs="+", default=list(GSP_GROUPS),
                   help="GSP groups, e.g. _C _M (default: all 14).")
    p.add_argument("--years", nargs="+", type=int, default=list(range(2018, 2026)),
                   help="years for the half-hourly Agile pull (default: 2018-2025).")
    args = p.parse_args(argv[1:])

    groups = tuple(g if g.startswith("_") else f"_{g}" for g in args.regions)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if "agile" in args.products:
        print(f"\n=== Agile half-hourly ({AGILE_PRODUCT}) ===", flush=True)
        pull_agile(groups, args.years)
    if "svt" in args.products:
        print(f"\n=== Standard variable ({', '.join(SVT_PRODUCTS)}) ===", flush=True)
        pull_svt(groups)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
