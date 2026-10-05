"""Build fuel_prices_{year}.csv locally from the public sources, for the years the data pack leaves out.

WHY. Until the UK left the EU ETS (end 2020) the carbon price in fuel_prices is the EEX EU ETS
auction clearing price, and EEX's market-data terms do not allow passing that data on. The data
pack therefore leaves out fuel_prices_2018-2021 (2021 because stage 2 interpolates between
mid-month prices, so 1-14 January 2021 still carries the December 2020 EEX price), and each user
fetches the prices from the public sources for their own use, which is what this script does.

STEPS (each a subprocess, as in scripts/run_pipeline.py)
    gbpowerdata.pull.gas_pull       ONS System Average Price of gas    -> data/raw/gas_sap_daily.csv
    gbpowerdata.pull.carbon_pull    EEX EUA auctions + gov.uk UK ETS   -> data/raw/carbon_monthly.csv
    gbpowerdata.pull.coal_pull      World Bank Pink Sheet coal         -> data/raw/coal_monthly.csv
    gbpowerdata.build.stage2_build_timeseries --fuel-only, per year    -> data/processed/fuel_prices_{year}.csv

No account or key is needed. `--no-pull` skips the three pulls when data/raw/ already holds them.

Usage:
    python scripts/build_fuel_prices.py                  # 2018-2021, the years the pack leaves out
    python scripts/build_fuel_prices.py 2018 2025        # any inclusive range
    python scripts/build_fuel_prices.py --no-pull 2019 2019
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
PULLS = ("gas_pull", "carbon_pull", "coal_pull")


def run(module: str, *args: str, year: int | None = None) -> None:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(p for p in (str(SRC), env.get("PYTHONPATH", "")) if p)
    if year is not None:
        env["PIPELINE_YEAR"] = str(year)
    r = subprocess.run([sys.executable, "-m", f"gbpowerdata.{module}", *args], env=env, cwd=ROOT,
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(f"  !! {module} FAILED (year={year})\n{(r.stdout or '')[-800:]}\n{(r.stderr or '')[-800:]}")
        sys.exit(1)
    last = [ln for ln in r.stdout.splitlines() if ln.strip()]
    print(f"  {module}{f' {year}' if year else ''}: {last[-1].strip() if last else 'done'}")


def main(argv: list[str]) -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("years", nargs="*", type=int, metavar="YEAR",
                   help="first and last year (default 2018 2021)")
    p.add_argument("--no-pull", action="store_true", help="use the raw files already in data/raw/")
    a = p.parse_args(argv)
    first, last = (a.years + a.years)[:2] if a.years else (2018, 2021)
    if not a.no_pull:
        for m in PULLS:
            run(f"pull.{m}")
    for y in range(first, last + 1):
        run("build.stage2_build_timeseries", "--fuel-only", year=y)


if __name__ == "__main__":
    main(sys.argv[1:])
