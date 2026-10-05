"""Pull CfD data from the LCCC Data Portal (CKAN REST API) into data/raw/lccc/.

The Low Carbon Contracts Company portal (https://dp.lowcarboncontracts.uk) runs
on CKAN — a standard REST API, no key for public data. Best practice (LCCC
guidance): resolve resources by *dataset name* at runtime; never hardcode
resource ids — they change when LCCC republishes.

This replaces (and enriches) the hand-downloaded CfD_Register_*.xlsx with live
data, including two datasets the static register lacks:
  - cfd-to-bm-unit-mapping            CfD_Id <-> BMU_Id (join key onto BMRS)
  - actual-cfd-generation-...-ghg     actual per-unit generation, strike, payments
                                      (the CfD settlement-cost question itself)

A second group (--levy) pulls the *supplier obligation* side: the daily levy rate
in GBP/MWh that LCCC charges suppliers and that lands on consumer bills. This is
the bridge from the model's CfD settlement cost to the final consumer tariff.

Usage:
  python -m gbpowerdata.pull.lccc_pull                 # default relevant set
  python -m gbpowerdata.pull.lccc_pull --levy          # supplier-obligation / levy set
  python -m gbpowerdata.pull.lccc_pull --list cfd      # search datasets matching "cfd"
  python -m gbpowerdata.pull.lccc_pull cfd-to-bm-unit-mapping cfd-contract-portfolio-status
"""

from __future__ import annotations

import argparse
import json
import sys
import time

import pandas as pd
import requests

from gbpowerdata import config as cfg

CKAN_BASE = "https://dp.lowcarboncontracts.uk/api/3/action"
OUT_DIR = cfg.raw_dir() / "lccc"

# Default relevant datasets -> output filename stem. The portfolio status is the
# live equivalent of the static register; the other two are net-new.
DEFAULT_DATASETS = {
    "cfd-contract-portfolio-status": "cfd_contract_portfolio_status",  # the name build_cfd_fleet reads
    "cfd-to-bm-unit-mapping": "cfd_to_bm_unit_mapping",
    "actual-cfd-generation-and-avoided-ghg-emissions": "cfd_actual_generation",
    "administrative-strike-prices": "cfd_admin_strike_prices",
    "auction-outcomes": "cfd_auction_outcomes",
}

# Supplier-obligation (levy) side: what CfDs cost consumers per MWh supplied.
# Suppliers pay a forward-looking Interim Levy Rate (ILR, set quarterly) and are
# later trued up against the Reconciled Daily Levy Rate, so the reconciled series
# is the settled ground truth and the ILR is what was billed at the time.
#
# Deliberately excluded after checking the actual contents:
#   actual-eligible-demand         its two numeric columns are bit-identical to
#                                  actual-ilr-income; the only extra column is a
#                                  ratio derivable from cfd_actual_generation.
#   settlement-costs-levy          GBP totals only, no per-MWh rate, and ~£1-4m/yr
#                                  against a £2-6bn CfD levy — below rounding.
#   forecast-ilr-tra               2 rows, current forward determination only.
#   price-cap-inputs-cfd-and-nrab  4 rows, forward quarters only — not a history.
LEVY_DATASETS = {
    "actual-ilr-income": "levy_actual_ilr_income",           # daily ILR + eligible demand
    "reconciled-daily-levy-rates": "levy_reconciled_daily",  # daily, per settlement run
    "operational-costs-levy": "levy_operational_costs",      # LCCC opex adder (OCL)
}


def ckan(action: str, **params) -> dict | list:
    r = requests.get(f"{CKAN_BASE}/{action}", params=params, timeout=120)
    r.raise_for_status()
    payload = r.json()
    if not payload.get("success"):
        raise RuntimeError(payload.get("error"))
    return payload["result"]


def list_datasets(query: str = "") -> pd.DataFrame:
    res = ckan("package_search", q=query, rows=200)
    return pd.DataFrame([{"name": d["name"], "title": d["title"],
                          "resources": len(d.get("resources", []))}
                         for d in res["results"]])


def resolve_resource(dataset_name: str, datastore: bool = True) -> str:
    """Resource id of a dataset's main data table (skips the field-dictionary file)."""
    pkg = ckan("package_show", id=dataset_name)
    cand = [r for r in pkg["resources"] if "definition" not in r["name"].lower()]
    if datastore:
        cand = [r for r in cand if r.get("datastore_active")] or cand
    if not cand:
        raise ValueError(f"no data resource found in '{dataset_name}'")
    return cand[0]["id"]


def datastore_fetch(resource_id: str, filters: dict | None = None,
                    page_size: int = 32_000, max_records: int | None = None) -> pd.DataFrame:
    """Pull rows from a datastore-active resource, paginating with limit/offset."""
    frames, offset = [], 0
    while True:
        params = {"resource_id": resource_id, "limit": page_size, "offset": offset}
        if filters:
            params["filters"] = json.dumps(filters)
        res = ckan("datastore_search", **params)
        recs = res["records"]
        if not recs:
            break
        frames.append(pd.DataFrame(recs))
        offset += len(recs)
        print(f"    {offset:,} / {res['total']:,} rows", flush=True)
        if offset >= res["total"] or (max_records and offset >= max_records):
            break
        time.sleep(0.2)
    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return df.drop(columns="_id", errors="ignore")


def pull(dataset_name: str, stem: str) -> None:
    print(f"\n=== {dataset_name} ===", flush=True)
    rid = resolve_resource(dataset_name)
    df = datastore_fetch(rid)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{stem}.csv"
    df.to_csv(path, index=False)
    print(f"  Saved {len(df):,} rows x {df.shape[1]} cols -> {path}", flush=True)


def main(argv: list[str]) -> None:
    p = argparse.ArgumentParser(description="Pull CfD data from the LCCC CKAN portal.")
    p.add_argument("datasets", nargs="*", help="dataset slugs (default: relevant set).")
    p.add_argument("--list", metavar="QUERY", help="search datasets and exit.")
    p.add_argument("--levy", action="store_true",
                   help="pull the supplier-obligation / levy set instead of the default.")
    p.add_argument("--all", action="store_true", help="pull the default AND levy sets.")
    args = p.parse_args(argv[1:])

    if args.list is not None:
        print(list_datasets(args.list).to_string(index=False))
        return

    if args.datasets:
        targets = {d: d.replace("-", "_") for d in args.datasets}
    elif args.all:
        targets = {**DEFAULT_DATASETS, **LEVY_DATASETS}
    elif args.levy:
        targets = LEVY_DATASETS
    else:
        targets = DEFAULT_DATASETS
    for name, stem in targets.items():
        pull(name, stem)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
