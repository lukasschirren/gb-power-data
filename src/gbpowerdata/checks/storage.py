"""Whether a storage unit's notified positions are feasible for its power and energy capacity.

From the notified energy per half-hour (gbpowerdata.common.elexon.fpn_energy; MWh, discharging positive), or
the position after the BM (after_bm: the notified energy plus the accepted volumes of the unit's offers and bids,
gbpowerdata.build.storage_revenues.accepted_volumes), and the capacities of gbpowerdata.build.storage_fleet:
  power    the notified MW (MWh / 0.5 h) within the unit's capacity, charging or discharging;
  energy   the swing of the implied state of charge within a UK local day (charged MWh count up, discharged MWh
           down, losses ignored) within the unit's energy capacity. Ignoring losses overstates the swing of a
           unit that charges more than it discharges, so a tolerance above 1 is needed.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def after_bm(notified: pd.Series, accepted: pd.Series) -> pd.Series:
    """The position after the BM per notified half-hour (MWh, discharging positive): the notified energy plus the
    accepted volumes (offers positive, bids negative, indexed by the half-hour's UTC start)."""
    return notified + accepted.groupby(level=0).sum().reindex(notified.index).fillna(0.0)


def discharge_ratio(energy: pd.Series) -> float:
    """MWh discharged per MWh charged over the series; NaN without charging."""
    charged = -energy.clip(upper=0).sum()
    return float(energy.clip(lower=0).sum() / charged) if charged > 0 else np.nan


def power_share(energy: pd.Series, capacity_mw: float, tol: float = 0.05) -> float:
    """Share of the notified half-hours whose level is within capacity x (1 + tol)."""
    if not len(energy) or not np.isfinite(capacity_mw) or capacity_mw <= 0:
        return np.nan
    return float(((energy.abs() / 0.5) <= capacity_mw * (1 + tol)).mean())


def daily_swing(energy: pd.Series) -> pd.Series:
    """The implied state of charge's swing (MWh) per UK local day: max minus min of the running sum of charged
    minus discharged energy, the day's opening state included."""
    soc = (-energy).cumsum()
    day = energy.index.tz_convert("Europe/London").date
    opening = soc.groupby(day).first() + energy.groupby(day).first()      # the state before the day's first period
    hi = np.maximum(soc.groupby(day).max(), opening)
    lo = np.minimum(soc.groupby(day).min(), opening)
    return hi - lo


def energy_share(energy: pd.Series, energy_mwh: float, tol: float = 0.25) -> float:
    """Share of days whose state-of-charge swing is within energy_mwh x (1 + tol)."""
    if not len(energy) or not np.isfinite(energy_mwh) or energy_mwh <= 0:
        return np.nan
    return float((daily_swing(energy) <= energy_mwh * (1 + tol)).mean())
