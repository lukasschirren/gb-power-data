"""Day-ahead VENUE abstraction — the one place that knows which auction the model targets.

The GB day-ahead price the merit order is fitted to comes from one of several auctions, all on
the same 30-min model spine (built by gbpowerdata.build.build_dayahead_prices):

    n2ex         N2EX (Nord Pool), hourly morning auction         2016-2025
    epex         EPEX SPOT UK hourly morning auction              2020-2025  (N2EX like-for-like)
    epex_hh      EPEX SPOT UK half-hourly afternoon auction       2020-2025  (a LATER, separate
                                                                              product; not N2EX-comparable)

Swapping the target is a one-line change: run with GBPOWERDATA_VENUE=epex (env) or venue.get("epex").
Every consumer reads the active venue's day-ahead price through `load_da_price(year)`; nothing
else names a price file, and outputs are venue-tagged so the runs never clobber each other.

`n2ex` and `epex` are the LIKE-FOR-LIKE pair (same product and gate closure); they were an
identical coupled price until GB left the Single Day-Ahead Coupling at end-2020, and diverge after.
Fitting the model to each and comparing is the point of the swap.

INFORMATION DISCIPLINE
    All of these clear the morning before delivery, so the target is known ahead of the modelled
    period; nothing here is fitted. The venue only selects which independently-published auction
    price is the model's TARGET.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from gbpowerdata import config as cfg

RAW = cfg.raw_dir()
PROC = cfg.processed_dir()


@dataclass(frozen=True)
class Venue:
    """A GB day-ahead auction and where the model reads its price + offer curve.

    The day-ahead price comes from the per-year processed files
    (data/processed/dayahead_price_{key}_{year}.csv), which are already on the 30-min model spine.
    """

    key: str                       # short id, e.g. "n2ex" | "epex" | "epex_hh"; also the output suffix
    label: str                     # human label for figures/logs
    price_floor: float             # exchange price floor of this auction, GBP/MWh
    market_share_note: str         # coverage/comparability caveat, printed into outputs
    da_file_tmpl: str              # str.format(year=...) -> processed per-year day-ahead price csv
    curves_dir: Path               # per-day aggregated supply/demand curve files (offer-curve check)
    bid_panel_tmpl: str            # str.format(year=...) -> processed offer-curve panel csv
    offer_feat_tmpl: str           # str.format(year=...) -> processed offer-feature csv

    # ---- day-ahead cleared price ---------------------------------------------------
    def load_da_price(self, year: int) -> pd.Series:
        """This venue's day-ahead price for `year`, tz-aware UTC half-hourly index, GBP/MWh,
        named 'da_price_gbp_mwh'. Empty if the venue did not operate that year (e.g. EPEX < 2020).
        The processed file is already on the 30-min spine, so no upsampling here."""
        f = Path(self.da_file_tmpl.format(year=year))
        if not f.exists():
            return pd.Series(dtype=float, name="da_price_gbp_mwh")
        d = pd.read_csv(f, usecols=["startTime", "price_gbp_per_mwh"])
        d["startTime"] = pd.to_datetime(d["startTime"], utc=True)
        return (d.dropna(subset=["price_gbp_per_mwh"])
                 .drop_duplicates("startTime")
                 .set_index("startTime")["price_gbp_per_mwh"]
                 .astype(float).sort_index()
                 .rename("da_price_gbp_mwh"))

    def da_on_index(self, year: int, index) -> np.ndarray:
        """This venue's day-ahead price aligned to a (half-hourly) startTime index. NaN where the
        venue has no price (uncovered years/half-hours)."""
        s = self.load_da_price(year)
        if s.empty:
            return np.full(len(np.asarray(index)), np.nan)
        idx = pd.to_datetime(pd.Series(np.asarray(index)), utc=True)
        return idx.map(s).to_numpy(dtype=float)

    def covers(self, year: int) -> bool:
        return Path(self.da_file_tmpl.format(year=year)).exists()

    # ---- offer curves (for validate_offer_curve.py) --------------------------------
    def curve_dir(self) -> Path:
        return self.curves_dir

    def bid_panel_path(self, year: int) -> Path:
        return Path(self.bid_panel_tmpl.format(year=year))

    def offer_features_path(self, year: int) -> Path:
        return Path(self.offer_feat_tmpl.format(year=year))

    # ---- output tagging ------------------------------------------------------------
    @property
    def suffix(self) -> str:
        """Filename/column suffix so venues never overwrite each other's outputs."""
        return self.key

    # ---- shared helper (kept for callers that hold an hourly series) ----------------
    @staticmethod
    def broadcast_to_index(hourly: pd.Series, index) -> np.ndarray:
        idx = pd.to_datetime(pd.Series(np.asarray(index)), utc=True).dt.floor("h")
        return idx.map(hourly).to_numpy(dtype=float)


N2EX = Venue(
    key="n2ex",
    label="N2EX day-ahead",
    price_floor=-500.0,
    market_share_note=("N2EX (Nord Pool) hourly morning auction, 2016-2025. Its aggregated curve "
                       "carries hedged portfolio volume and IC nominations, not only physical plant "
                       "- absolute-MW offer-curve comparisons carry this caveat."),
    da_file_tmpl=str(PROC / "dayahead_price_n2ex_{year}.csv"),
    curves_dir=RAW / "nordpool" / "curves",
    bid_panel_tmpl=str(PROC / "n2ex_bid_panel_{year}.csv"),
    offer_feat_tmpl=str(PROC / "n2ex_offer_features_{year}.csv"),
)

EPEX = Venue(
    key="epex",
    label="EPEX SPOT UK day-ahead (hourly)",
    price_floor=-500.0,
    market_share_note=("EPEX SPOT UK hourly morning auction, 2020-2025 - the like-for-like N2EX "
                       "counterpart (same product and gate closure; coupled-identical until GB left "
                       "SDAC end-2020, divergent after)."),
    da_file_tmpl=str(PROC / "dayahead_price_epex_hourly_{year}.csv"),
    # The HOURLY auction publishes its own curves, in its own sFTP subtree (2008-2025).
    # Pointing this at aggregated_curves/ would hand the hourly venue the half-hourly
    # afternoon auction's book — a different product with a different order book.
    curves_dir=RAW / "epex" / "great-britain" / "aggregated_curves_hourly",
    bid_panel_tmpl=str(PROC / "epex_bid_panel_{year}.csv"),
    offer_feat_tmpl=str(PROC / "epex_offer_features_{year}.csv"),
)

# EPEX SPOT UK half-hourly afternoon auction — a later, separate product (NOT N2EX-comparable), but
# natively on the 30-min settlement spine. Available as a target for completeness.
EPEX_HH = Venue(
    key="epex_hh",
    label="EPEX SPOT UK day-ahead (half-hourly)",
    price_floor=-500.0,
    market_share_note=("EPEX SPOT UK half-hourly AFTERNOON auction, 2020-2025 - a later, separate "
                       "product from the morning hourly auctions; not directly N2EX-comparable."),
    da_file_tmpl=str(PROC / "dayahead_price_epex_hh_{year}.csv"),
    curves_dir=RAW / "epex" / "great-britain" / "aggregated_curves",
    bid_panel_tmpl=str(PROC / "epex_bid_panel_{year}.csv"),
    offer_feat_tmpl=str(PROC / "epex_offer_features_{year}.csv"),
)

# BLEND — the traded-capacity-weighted composite of the two like-for-like morning auctions
# (N2EX + EPEX hourly), weighting each venue's price by its cleared volume that half-hour
# (built by gbpowerdata.build.build_dayahead_prices). Pre-2020 (no EPEX) it is just N2EX. This is the
# single "GB day-ahead price" that reflects where volume actually traded, so it is the natural
# headline fit target.
BLEND = Venue(
    key="blend",
    label="GB day-ahead (volume-weighted N2EX+EPEX)",
    price_floor=-500.0,
    market_share_note=("Traded-capacity-weighted composite of N2EX and EPEX hourly day-ahead "
                       "prices: each half-hour weighted by that HH's own cleared volume, so the "
                       "weight VARIES by half-hour and year (EPEX share ranges ~0.11-0.54 per HH; "
                       "annual mean ~0.28-0.33, 2020-25). N2EX only pre-2020."),
    da_file_tmpl=str(PROC / "dayahead_price_blend_{year}.csv"),
    curves_dir=RAW / "nordpool" / "curves",
    bid_panel_tmpl=str(PROC / "n2ex_bid_panel_{year}.csv"),
    offer_feat_tmpl=str(PROC / "n2ex_offer_features_{year}.csv"),
)

REGISTRY = {v.key: v for v in (N2EX, EPEX, EPEX_HH, BLEND)}


def get(key: str | None = None) -> Venue:
    """The active venue. Override with GBPOWERDATA_VENUE=epex (env) or an explicit key."""
    key = (key or os.environ.get("GBPOWERDATA_VENUE") or "n2ex").lower()
    if key not in REGISTRY:
        raise ValueError(f"unknown venue {key!r}; known: {sorted(REGISTRY)}")
    return REGISTRY[key]
