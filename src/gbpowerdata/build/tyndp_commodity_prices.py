"""The fuel and carbon prices TYNDP 2024's scenarios assume, by fuel, scenario and year -> processed/tyndp_commodity_prices.csv.

WHY. TYNDP's market model prices (`build.tyndp_hourly`) are set at the scenario's own fuel and carbon prices, so a
model that reads them needs those prices too: to move them to another gas price, or to tell from a neighbour's price
whether gas set it (its price against a gas plant's cost at the same gas and carbon). The prices change between the
scenario years (the National Trends+ gas blend from 7.5 EUR/GJ in 2030 to 9.0 in 2040, CO2 from 113.4 to 147 EUR/t),
so a reader of the 2030 and 2040 tables needs each year's, which this table gives instead of numbers copied into code.

SOURCE. ENTSO-E / ENTSOG, TYNDP 2024 Scenarios, "2023 06 22 TYNDP 2024 Commodity prices Final.xlsx" (in Prices.zip,
https://2024-data.entsos-tyndp-scenarios.eu/files/scenarios-inputs/Prices.zip; `pull.tyndp_pull`), licence CC BY 4.0
as Open-TYNDP records it. Sheet "Matrix 2024", the matrix the scenario report quotes: one row per fuel (column B),
its unit (C) and its price in 2030, 2040 and 2050 (D-F, the header row's years), in 2021 euros (the footer row,
"(Currency 2021 €)"). Most fuels are the same in every scenario (IEA World Energy Outlook 2022, announced pledges, for
gas, coal, oil and CO2); the gas blend (natural gas, biomethane and synthetic methane in the scenario's shares, sheet
"Gas Blend Final") has one row per scenario: National Trends+ (NT+, 2030 and 2040), Distributed Energy and Global
Ambition (DE, GA, 2040 and 2050). The workbook stores NT+'s blend as text ("7.5", "9.0"); the stage reads it as
numbers. TYNDP's power market runs price gas plants at the blend, not at the natural gas row.

METHOD. The rows from the header (the row whose cells read "Fuel" and "Unit") to the first row with no fuel name;
a fuel name ending in a scenario code (NT+, DE, GA) is split into the fuel and its scenario, the others take scenario
"all"; units are written in their money ("EUR2021/GJ", "EUR2021/t"); an empty cell is no row. The stage raises when
the footer does not name 2021 money or when the NT+ gas blend or the CO2 price lacks 2030 or 2040, the values the
merit-order model reads.

OUTPUT processed/tyndp_commodity_prices.csv: fuel, scenario (all, NT+, DE, GA), year (2030, 2040, 2050), value, unit.
READ BY the merit-order model's projection (TYNDP's gas plant cost in 2030 and 2040), `modelinputs`.
RUN    python -m gbpowerdata.build.tyndp_commodity_prices
"""
from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Iterable

import openpyxl
import pandas as pd

from gbpowerdata import config as cfg

WORKBOOK = "2023 06 22 TYNDP 2024 Commodity prices Final.xlsx"
SHEET = "Matrix 2024"
OUT = "tyndp_commodity_prices.csv"
MONEY = "EUR2021"
GAS_BLEND = "Gas (blend of biomethane, synthetic gas and NG)"
SCENARIO = re.compile(r"^(?P<fuel>.*?)\s+(?P<scenario>NT\+|DE|GA)$")
UNITS = {"gj": "GJ", "ton": "t", "t": "t", "mwh": "MWh"}
REQUIRED = {(GAS_BLEND, "NT+"): (2030, 2040), ("CO2 price", "all"): (2030, 2040)}


def _unit(u: str) -> str:
    """'€/GJ', '€/Gj' or '€/ton' -> 'EUR2021/GJ' or 'EUR2021/t' (the euro sign's encoding varies)."""
    per = str(u).split("/")[-1].strip().lower()
    if per not in UNITS:
        raise ValueError(f"tyndp_commodity_prices: unit {u!r} not known")
    return f"{MONEY}/{UNITS[per]}"


def table(rows: Iterable[tuple]) -> pd.DataFrame:
    """The long table from the sheet's rows (METHOD)."""
    rows = [tuple(r) for r in rows]
    head = next((i for i, r in enumerate(rows) if len(r) > 2 and r[1] == "Fuel" and r[2] == "Unit"), None)
    if head is None:
        raise ValueError("tyndp_commodity_prices: no header row (Fuel, Unit, years)")
    years = {j: int(v) for j, v in enumerate(rows[head]) if isinstance(v, (int, float)) and 2000 < v < 2100}
    out, end = [], len(rows)
    for i in range(head + 1, len(rows)):
        r = rows[i]
        name = r[1] if len(r) > 1 else None
        if not isinstance(name, str) or not name.strip():
            end = i
            break
        name = name.strip()
        m = SCENARIO.match(name)
        fuel, scenario = (m["fuel"], m["scenario"]) if m else (name, "all")
        for j, year in years.items():
            v = r[j] if j < len(r) else None
            if v is None or (isinstance(v, str) and not v.strip()):
                continue
            out.append(dict(fuel=fuel, scenario=scenario, year=year, value=float(v), unit=_unit(r[2])))
    footer = " ".join(str(v) for r in rows[end:end + 2] for v in r if v is not None)
    if "Currency" not in footer or "2021" not in footer:
        raise ValueError(f"tyndp_commodity_prices: the footer names no 2021 money ({footer!r})")
    t = pd.DataFrame(out, columns=["fuel", "scenario", "year", "value", "unit"])
    for (fuel, scenario), need in REQUIRED.items():
        got = set(t.loc[(t["fuel"] == fuel) & (t["scenario"] == scenario), "year"])
        if not set(need) <= got:
            raise ValueError(f"tyndp_commodity_prices: {fuel} ({scenario}) lacks {sorted(set(need) - got)}")
    return t


def build() -> pd.DataFrame:
    """The table from the workbook as `pull.tyndp_pull` extracts it."""
    path = cfg.raw_dir() / "tyndp" / WORKBOOK
    if not path.exists():
        raise FileNotFoundError(f"no TYNDP commodity prices {path} (python -m gbpowerdata.pull.tyndp_pull)")
    ws = openpyxl.load_workbook(path, read_only=True, data_only=True)[SHEET]
    return table(ws.iter_rows(values_only=True))


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args(argv)
    t = build()
    out = cfg.processed_dir() / OUT
    out.parent.mkdir(parents=True, exist_ok=True)
    t.to_csv(out, index=False)
    key = t[t["fuel"].isin([GAS_BLEND, "CO2 price", "Natural Gas"])]
    print(f"wrote {out} ({len(t)} rows)\n"
          f"{key.pivot_table(index=['fuel', 'scenario', 'unit'], columns='year', values='value').to_string()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
