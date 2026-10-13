"""Transmission demand against what the transmission system metered: generation by fuel and interconnector flows
(Elexon FUELHH, data/raw/fuelhh_*.csv, gbpowerdata.pull.elexon_pull fuelhh).

Elexon's ITSDO (transmission system demand) includes interconnector exports, pumped storage pumping and station load,
so it equals the transmission-metered generation plus pumped storage generation plus interconnector imports:
measured on 2018-2025 the residual has a median of -59 MW and 95% of half-hours within 471 MW (2% of demand).
INDO (national demand) excludes the exports, the pumping and station load; NESO estimates station load at
500 MW in summer and 600 MW in winter (historic demand data), and the INDO residual below sits near -0.6 GW.
FUELHH reports pumped storage net (negative while pumping) and each interconnector net (negative for exports).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from gbpowerdata import config as cfg


def fuelhh(raw: Path | None = None) -> pd.DataFrame:
    """FUELHH as one column per fuel type (MW) on its UTC startTime, from every fuelhh_*.csv pull."""
    raw = cfg.raw_dir() if raw is None else Path(raw)
    files = sorted(raw.glob("fuelhh_*.csv"))
    if not files:
        raise FileNotFoundError(f"no fuelhh_*.csv in {raw}")
    f = pd.concat([pd.read_csv(p, usecols=["startTime", "fuelType", "generation"]) for p in files], ignore_index=True)
    f["startTime"] = pd.to_datetime(f["startTime"], utc=True)
    return f.pivot_table(index="startTime", columns="fuelType", values="generation", aggfunc="last")


def components(w: pd.DataFrame) -> pd.DataFrame:
    """Generation (excluding interconnectors and pumped storage), pumped storage generation and pumping, imports and
    exports (MW, all positive) from a FUELHH wide table."""
    ints = [c for c in w.columns if str(c).startswith("INT")]
    ps = w["PS"] if "PS" in w else pd.Series(0.0, index=w.index)
    return pd.DataFrame({"generation": w.drop(columns=ints + (["PS"] if "PS" in w else [])).sum(axis=1, min_count=1),
                         "ps_generation": ps.clip(lower=0), "pumping": -ps.clip(upper=0),
                         "imports": w[ints].clip(lower=0).sum(axis=1), "exports": -w[ints].clip(upper=0).sum(axis=1)})


def transmission_residual(itsdo: pd.Series, w: pd.DataFrame) -> pd.Series:
    """ITSDO minus (generation + pumped storage generation + imports), on the half-hours both have."""
    c = components(w)
    return (itsdo - (c["generation"] + c["ps_generation"] + c["imports"])).dropna()


def national_residual(indo: pd.Series, w: pd.DataFrame) -> pd.Series:
    """INDO minus (generation + pumped storage generation + imports - exports - pumping): minus station load."""
    c = components(w)
    return (indo - (c["generation"] + c["ps_generation"] + c["imports"] - c["exports"] - c["pumping"])).dropna()
