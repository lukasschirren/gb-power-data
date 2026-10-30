"""Ofgem's Renewables Obligation accredited stations as a processed table, without their holders.

WHY. The Renewables Obligation pays each accredited station certificates per MWh for 20 years from its
accreditation (and to 31 March 2037 at the latest), so a model of the scheme's cost or of the RO fleet's offers
needs each station's accreditation date, capacity and technology: which stations are still in support in a given
year, and which farms of the panel they are. Ofgem's register (`pull.ofgem_pull`, the newest
raw/ofgem/RO_Accredited_Stations_*.csv) carries them beside the holder's organisation name and address, which this
repository never packs (the holder of a small station can be a person). This table keeps the station and drops the
holder, so it can travel with the data packs and the model inputs.

COLUMNS. accreditation_number (Ofgem's reference), station_name, technology (Ofgem's label), tech (Offshore,
Onshore, Solar, Hydro or Other, by TECH, as the models group plant), dnc_mw (the declared net capacity, from kW),
commissioning_date and accreditation_date (Ofgem's effective date; day first), country, station_postcode (the
site's postcode read from the station address: the full postcode for stations of at least SITE_POSTCODE_MIN_MW,
the outward district only below it, since a small station's address is its owner's), register_file (the snapshot
read, so a user knows the register's date).

Ported on 30 Oct 2026 from the research repository's gbabm.common.ro_register (`load_register`, `TECH`); the
matching of stations to REPD sites stays with the models that need it.

OUTPUT processed/ro_stations.csv, one row per accredited station.
READ BY the merit-order model (RO support by year), `modelinputs`.
RUN    python -m gbpowerdata.build.ro_stations
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import pandas as pd

from gbpowerdata import config as cfg

OUT = "ro_stations.csv"
PATTERN = "RO_Accredited_Stations_*.csv"
SITE_POSTCODE_MIN_MW = 1.0
HOLDER_COLUMNS = ("Organisation name", "Organisation address")
TECH = {"Offshore wind": "Offshore", "Offshore wind - demonstration turbines": "Offshore",
        "Offshore wind - floating turbines": "Offshore", "Onshore wind": "Onshore",
        "Wind with a DNC of 50kW or less": "Onshore", "Photovoltaic": "Solar",
        "Photovoltaic with a DNC of 50kW or less": "Solar", "Hydro with a DNC of 20MW or less": "Hydro",
        "Hydro with a DNC greater than 20 MW": "Hydro", "Hydro with a DNC of 50kW or less": "Hydro",
        "Micro hydro": "Hydro"}
_PC = re.compile(r"\b([A-Z]{1,2}[0-9][0-9A-Z]?)\s*([0-9][A-Z]{2})\b", re.I)


def _postcode(text) -> str:
    """The last UK postcode in `text`, as 'AB1 2CD'; empty where there is none."""
    m = _PC.findall(str(text))
    return f"{m[-1][0]} {m[-1][1]}".upper() if m else ""


def register_file(path: Path | None = None) -> Path:
    """The register snapshot to read: `path`, else the newest in raw/ofgem/."""
    if path is not None:
        return Path(path)
    files = sorted((cfg.raw_dir() / "ofgem").glob(PATTERN))
    if not files:
        raise FileNotFoundError(f"no {PATTERN} in {cfg.raw_dir() / 'ofgem'} (python -m gbpowerdata.pull.ofgem_pull)")
    return files[-1]


def load_register(path: Path | None = None) -> pd.DataFrame:
    """Every row and column of the register snapshot as Ofgem publishes it (holders included: local use only)."""
    p = register_file(path)
    d = pd.read_csv(p, encoding="utf-8-sig", low_memory=False)
    d.attrs["source"] = p.name
    return d


def stations(register: pd.DataFrame, source: str) -> pd.DataFrame:
    """The name-free table (COLUMNS) from a register frame; `source` is the snapshot's file name."""
    d = register
    dnc = pd.to_numeric(d["Station DNC in kW"].astype(str).str.replace(",", ""), errors="coerce") / 1e3
    full = d["Station address"].map(_postcode)
    out = pd.DataFrame({
        "accreditation_number": d["Accreditation reference"].astype(str).str.strip(),
        "station_name": d["Station name"].astype(str).str.strip(),
        "technology": d["Technology"].astype(str).str.strip(),
        "tech": d["Technology"].map(TECH).fillna("Other"),
        "dnc_mw": dnc,
        "commissioning_date": pd.to_datetime(d["Commissioning date"], dayfirst=True, errors="coerce").dt.date,
        "accreditation_date": pd.to_datetime(d["Effective date"], dayfirst=True, errors="coerce").dt.date,
        "country": d["Country"].astype(str).str.strip(),
        "station_postcode": full.where(dnc >= SITE_POSTCODE_MIN_MW, full.str.split(" ").str[0]),
        "register_file": source,
    })
    holder = [c for c in out.columns if "organisation" in c.lower() or "holder" in c.lower()]
    if holder:
        raise AssertionError(f"ro_stations: holder columns in the output: {holder}")
    return out.reset_index(drop=True)


def build(path: Path | None = None) -> pd.DataFrame:
    """The table from the newest register (or `path`), written to processed/."""
    reg = load_register(path)
    out = stations(reg, reg.attrs["source"])
    target = cfg.processed_dir() / OUT
    target.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(target, index=False)
    by_tech = out.groupby("tech")["dnc_mw"].agg(["size", "sum"]).round(0)
    print(f"wrote {target} ({len(out):,} stations from {reg.attrs['source']})\n{by_tech.to_string()}")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--file", default=None, help="a register snapshot instead of the newest in raw/ofgem/")
    a = ap.parse_args(argv)
    build(a.file)
    return 0


if __name__ == "__main__":
    sys.exit(main())
