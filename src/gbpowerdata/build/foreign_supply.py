"""The neighbours' inverse-supply slope: how far a zone's price moves per MW of residual demand.

WHY. A merit-order model that takes the neighbour's day-ahead price as a fixed floor on each interconnector
overstates what GB earns abroad in surplus hours: exporting Q into zone Z lowers Z's residual demand by Q and so Z's
price, importing Q raises it. The slope dP_Z/d(residual) is a property of Z's own supply curve, estimated here from
the neighbour's load and wind and solar (`pull.entsoe_residual_pull`) and its day-ahead price
(`build.interconnector_capacity`). None of GB's own price enters, so the estimate is not circular for GB, which is
small relative to each neighbour.

ESTIMATION. The relevant slope is the local one at the low-residual operating point: GB exports when it is long on
wind, and the neighbour, weather-correlated, is usually long too. Fuel and carbon shift the whole price-residual
curve year to year, so the slope is taken within year (price and residual de-meaned by calendar year) on the
low-residual half of each year with at least 500 hours, prices outside (-200, 1000) GBP/MWh dropped as scarcity or
floor outliers, and fitted once over the pooled de-meaned hours. The values this gave in October 2026 (GBP/MWh per
GW): fr 3.6 (a huge zone, nearly flat), nl 13.1 (weak, R2 0.004: a small zone whose price is set regionally), be
20.0, ie 26.8 (a small island), dk1 18.2; no2 is unusable, 96% hydro, its price a reservoir water value whose sign
flips across specifications.

Ported on 30 Oct 2026 from the research repository's scripts/build_foreign_supply_slope.py (its table reproduced
value for value).

OUTPUT processed/foreign_supply_slope.csv: zone, link, slope_gbp_per_mw, r2, n, usable.
READ BY the merit-order model (the elastic interconnector block), `modelinputs`.
RUN    python -m gbpowerdata.build.foreign_supply
"""
from __future__ import annotations

import argparse
import sys

import numpy as np
import pandas as pd

from gbpowerdata import config as cfg
from gbpowerdata.build import interconnector_capacity as IC

OUT = "foreign_supply_slope.csv"
# residual-demand zone -> interconnector link (for the foreign price series)
ZONE_LINK = {"fr": "IFA_ElecLink_IFA2", "nl": "BritNed", "be": "Nemo",
             "ie": "Ireland", "no2": "NSL", "dk1": "Viking"}
UNUSABLE = {"no2"}                       # hydro water value, not residual-driven
PRICE_BAND = (-200.0, 1000.0)            # scarcity and floor outliers dropped
MIN_HOURS = 500                          # a year's low-residual half enters only with at least this many hours


def slope(price: pd.Series, resid: pd.Series) -> dict:
    """The within-year slope of price on residual demand over the low-residual half of each year (ESTIMATION):
    slope_gbp_per_mw, r2 and n, from two series on the same UTC index."""
    d = pd.DataFrame({"resid": resid, "p": price}).dropna()
    d = d[(d["p"] > PRICE_BAND[0]) & (d["p"] < PRICE_BAND[1])]
    d["yr"] = d.index.year
    parts = []
    for _, g in d.groupby("yr"):
        lo = g[g["resid"] < g["resid"].quantile(0.5)]
        if len(lo) > MIN_HOURS:
            parts.append(lo.assign(p=lo["p"] - lo["p"].mean(), resid=lo["resid"] - lo["resid"].mean()))
    pooled = pd.concat(parts)
    s = float(np.polyfit(pooled["resid"], pooled["p"], 1)[0])     # GBP/MWh per MW
    r2 = float(np.corrcoef(pooled["resid"], pooled["p"])[0, 1] ** 2)
    return {"slope_gbp_per_mw": s, "r2": r2, "n": int(len(pooled))}


def build() -> pd.DataFrame:
    """One row per zone, written to processed/, with the price impact of a full-capacity export printed."""
    ic = pd.read_parquet(cfg.processed_dir() / IC.OUT)
    ic["t"] = pd.to_datetime(ic["startTime"], utc=True)
    price = {lk: ic[ic["link"] == lk].set_index("t")["price_gbp_mwh"] for lk in ZONE_LINK.values()}
    folder = cfg.raw_dir() / "entsoe" / "foreign_residual"

    rows = []
    for z, lk in ZONE_LINK.items():
        f = folder / f"{z}_residual_hourly.csv"
        if not f.exists():
            raise FileNotFoundError(f"no residual demand for {z}: {f} (python -m gbpowerdata.pull.entsoe_residual_pull)")
        r = pd.read_csv(f)
        r["t"] = pd.to_datetime(r["deliveryStart"], utc=True)
        est = slope(price[lk], r.set_index("t")["residual_mw"])
        rows.append({"zone": z, "link": lk, "slope_gbp_per_mw": round(est["slope_gbp_per_mw"], 5),
                     "r2": round(est["r2"], 3), "n": est["n"],
                     "usable": z not in UNUSABLE and est["slope_gbp_per_mw"] > 0})

    out = pd.DataFrame(rows)
    path = cfg.processed_dir() / OUT
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(path, index=False)
    print(f"wrote {path}\n")
    shown = out.assign(slope_per_GW=(out["slope_gbp_per_mw"] * 1000).round(1))
    print(shown[["zone", "link", "slope_per_GW", "r2", "n", "usable"]].to_string(index=False))
    print("\nprice impact of a full-capacity export (GBP), usable zones:")
    ntc = ic.groupby("link")["export_cap_mw"].max()
    for _, r in out[out["usable"]].iterrows():
        print(f"  {r['zone']:<4} {r['slope_gbp_per_mw'] * ntc.get(r['link'], 0):5.1f}  (capacity {ntc.get(r['link'], 0):.0f} MW)")
    return out


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args(argv)
    build()
    return 0


if __name__ == "__main__":
    sys.exit(main())
