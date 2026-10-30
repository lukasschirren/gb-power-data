"""Hourly 2030 marginal costs of GB's neighbours and of TYNDP's own GB node -> processed/tyndp_nt2030_cy2009_hourly.csv.

WHY. A projection that clears GB against its neighbours needs their 2030 prices hour by hour: when a neighbour is
in surplus its price is zero and GB cannot export its own surplus at a positive price. ENTSO-E's TYNDP 2024 market
model (`pull.tyndp_pull`) gives the marginal cost of every market node in 2030 for climate year 2009, the one year
published.

METHOD. The workbook's sheet "Hourly Market Data" holds 55 columns per market node (row 11 the quantity, row 12 the
node, row 13 the column code, hours from row 14). For every hour the stage keeps:
  mc_{node}            the marginal cost (EUR/MWh, 2021 money as the scenario's commodity prices) of the nodes GB's
                       links reach: FR00 (IFA, IFA2, ElecLink), BE00 (Nemo), NL00 (BritNed), NOS0 (North Sea Link,
                       southern Norway), DKW1 (Viking, West Denmark), IE00 and UKNI (the Irish links, one market),
                       and DE00 (NeuConnect, from 2028) and UK00 (GB itself) for reference
  uk00_demand_mw, uk00_wind_onshore_mw, uk00_wind_offshore_mw, uk00_solar_mw, uk00_dumped_mw
                       TYNDP's GB node: demand (losses included) and the wind and solar potential (generation plus
                       curtailment, the readme's definition), so GB's residual demand in the same weather can be
                       ranked against the neighbours' prices
The model's floor is zero: no node goes below 0 in any hour (renewables offer at zero, no support-driven negative
offers), so the series says when a neighbour is in surplus, not how deep its price would fall. Reading the 100 MB
workbook takes about two minutes.
Ported on 30 Oct 2026 from the research repository's gbabm.build.build_tyndp_hourly (its table reproduced value
for value; the name keeps the dataset's climate year, cy2009).

OUTPUT processed/tyndp_nt2030_cy2009_hourly.csv: hour (1-8736), label as the workbook gives it, month, day,
hour_of_day, then the columns above.
READ BY the merit-order model's projection (the neighbours' 2030 surplus hours), `modelinputs`.
RUN    python -m gbpowerdata.build.tyndp_hourly
"""
from __future__ import annotations

import argparse
import sys

import openpyxl
import pandas as pd

from gbpowerdata import config as cfg

WORKBOOK = "MMStandardOutputFile_NT2030_Plexos_CY2009_2.5_v40.xlsx"
SHEET = "Hourly Market Data"
OUT = "tyndp_nt2030_cy2009_hourly.csv"
NODES = ("FR00", "BE00", "NL00", "NOS0", "DKW1", "IE00", "UKNI", "DE00", "UK00")
GB_COLS = {"Demand [MW]": "uk00_demand_mw", "Wind Onshore [MW]": "uk00_wind_onshore_mw",
           "Wind Offshore [MW]": "uk00_wind_offshore_mw", "Solar (Photovoltaic) [MW]": "uk00_solar_mw",
           "Dumped Energy [MW]": "uk00_dumped_mw"}
MONTHS = {m: i + 1 for i, m in enumerate(("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT",
                                          "NOV", "DEC"))}
HOURS = 8736


def columns(labels: tuple, nodes: tuple) -> dict[str, int]:
    """Output column name -> sheet column index, from the quantity row and the node row of the header; raises
    when a node's marginal cost or one of GB's columns is not in the sheet."""
    out = {}
    for j, (lab, node) in enumerate(zip(labels, nodes)):
        if not isinstance(lab, str) or not isinstance(node, str):
            continue
        lab = lab.split("\n")[0].strip()
        if lab.startswith("Marginal Cost") and node in NODES:
            out[f"mc_{node.lower()}"] = j
        elif node == "UK00" and lab in GB_COLS:
            out[GB_COLS[lab]] = j
    missing = [f"mc_{n.lower()}" for n in NODES if f"mc_{n.lower()}" not in out] + \
              [c for c in GB_COLS.values() if c not in out]
    if missing:
        raise ValueError(f"tyndp_hourly: columns not found: {missing}")
    return out


def build() -> pd.DataFrame:
    """The hourly table from the workbook (METHOD)."""
    path = cfg.raw_dir() / "tyndp" / WORKBOOK
    if not path.exists():
        raise FileNotFoundError(f"no TYNDP workbook {path} (python -m gbpowerdata.pull.tyndp_pull)")
    ws = openpyxl.load_workbook(path, read_only=True)[SHEET]
    rows = ws.iter_rows(values_only=True)
    head = [next(rows) for _ in range(13)]
    cols = columns(head[10], head[11])
    data = []
    for r in rows:
        if r[0] is None or r[1] is None:
            continue
        data.append([int(r[0]), str(r[1])] + [float(r[j]) if r[j] is not None else float("nan")
                                              for j in cols.values()])
    d = pd.DataFrame(data, columns=["hour", "label"] + list(cols))
    lab = d["label"].str.strip()
    d.insert(2, "month", lab.str[2:5].map(MONTHS))
    d.insert(3, "day", lab.str[:2].astype(int))
    d.insert(4, "hour_of_day", lab.str[5:7].astype(int))
    if d["month"].isna().any() or len(d) != HOURS:
        raise ValueError(f"tyndp_hourly: {len(d)} hours, {int(d['month'].isna().sum())} unparsed labels")
    return d


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args(argv)
    d = build()
    out = cfg.processed_dir() / OUT
    out.parent.mkdir(parents=True, exist_ok=True)
    d.to_csv(out, index=False, float_format="%.3f")
    mc = [c for c in d.columns if c.startswith("mc_")]
    s = pd.DataFrame({"mean": d[mc].mean(), "hours_le_1": (d[mc] <= 1.0).sum(), "hours_below_0": (d[mc] < 0).sum()})
    print(f"wrote {out} ({len(d)} hours)\n{s.round(2).to_string()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
