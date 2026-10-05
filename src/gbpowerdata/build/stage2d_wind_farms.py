"""Stage 2d — the transmission wind FARMS of one year: regime, ROC band and observed output shape.

WHY. The copperplate comb gives every wind agent one national CF, and --vre-profile zonal one
reanalysis shape per GSP group, so no two farms in a zone differ. The per-farm WCfD quantities
(capture, participation floor, take-up) depend on exactly that difference: priced at the caprec
clearing, the per-unit capture spread of the BM-registered wind fleet is about twice the 14-zone
one. This stage turns the unit map (data/reference/wind_farm_map.csv, scripts/build_wind_farm_map.py)
into per-farm rows and per-farm half-hourly output, which meritorder's --vre-profile farm uses to
give each RO farm its own agent and each linked CfD agent its own farm's shape.

THE RULES (facts come from the map; only rules live here)
  in service   the unit ran before the FPN record began (fpn_state "pre_record") or first
               generated before the end of the year.
  regime       CfD   the unit carries an LCCC contract link (cfd_ids).
               RO    otherwise, if BOTH its REPD site was operational by the RO closure year
                     (config stage1.ro_closure_year, 2017) - the rule stage1 and stage3 use to
                     build the RO aggregates the comb carves these farms out of - AND the unit
                     itself belongs to that build (pre-record, first power by the closure year,
                     or within EXTENSION_GAP of the site's operational date), which is what keeps
                     a later extension under an old station name out of the RO. The model's rule
                     puts grace-period stations completed in 2018 (Galloper, 353 MW; EOWDC) in
                     the merchant aggregate although they hold RO accreditation; this follows it.
               None  otherwise (merchant), including RO-era units with no REPD link.
  band (RO)    the Ofgem banding in force at accreditation (OFG1164, RO Guidance for Generators,
               Appendix 4: Table A4.1 pp. 81-83 and the grandfathering rules p. 91):
                 offshore  accredited <= 2006-07-11: 1.0 (grandfathered);
                           2006-07-12 .. 2010-03-31: 1.5 (Art. 39 ROO 2015);
                           2010-04-01 .. 2015-03-31: 2.0 (pre-13, 13/14, 14/15 capacity);
                           2015-04-01 .. 2016-03-31: 1.9; from 2016-04-01: 1.8
                 onshore   accredited <= 2013-03-31: 1.0; from 2013-04-01: 0.9
               ACCREDITATION DATE PROXY: the unit's first FPN power where the record shows it;
               otherwise REPD's operational date - which records COMPLETION - less
               FIRST_POWER_LEAD. A station is accredited when it first generates, months before
               completion, and 5 months puts every pre-record station on the side of its band
               boundary that DESNZ's measured issuance by band supports (Thanet, completed
               Sep 2010, at 2.0: at 1.5 the band's measured ~2 TWh a year could not hold it).
               The special ROS bands (2.5 demonstration, 3.5 floating) belong to plant that is
               either not BM-registered (Hywind, Kincardine) or post-2017 in REPD (EOWDC), so no
               farm here carries one; they stay in the zonal remainder's measured band mix.
  farm         the units of one station sharing regime, band, zone and offshore class.

OUTPUT
  data/processed/wind_farms_{year}.csv      farm_id, station, units, tech_key (Wind_off/Wind_on),
                                            is_offshore, gsp_group, capacity_mw, regime, band,
                                            band_basis, accreditation_proxy, cfd_ids,
                                            fpn_coverage, mean_cf, and (since 30 Sep 2026)
                                            fpn_notified_share, full_service_from, full_service_to
  data/processed/wind_farm_fpn_{year}.csv   startTime + one column per farm_id: half-hourly mean
                                            FPN (MW), the time-weighted mean of the notified
                                            levels inside each settlement period; a gap reads 0
  data/processed/wind_farm_fpn_gaps_{year}.csv
                                            startTime + one column per farm_id: the share of the
                                            farm's capacity_mw that is in service in the half-hour
                                            but has NO notification after the 2-hour interpolation,
                                            in a hole of the FPN pull (the half-hours the FPN file
                                            reads as 0 for want of data)

FPN is the unit's intended output at gate closure, BEFORE balancing curtailment - the observed
analogue of what a farm offers day-ahead. The comb uses it as a SHAPE only and rescales every
half-hour to the metered national total, so curtailment is spread over the fleet, not
concentrated on the Scottish farms that bear it.

NOTIFICATION GAPS (added 30 Sep 2026; wind_farm_fpn_{year}.csv is unchanged by it). unit_fpn fills a
gap by linear interpolation for at most GAP_FILL_HH half-hours (pandas' limit fills the first 2 h of
a longer gap too) and reads the rest as 0, so in the FPN file a gap and a notified zero (calm,
outage, a constraint known at gate closure) look the same. The gaps are holes in the raw pull, the
same half-hours for every unit (scripts/fig_cfd_vs_tax/basis.py measures them; the pull-hole rule
below makes that the definition, since 1 Oct 2026). Most are runs of whole days, each day's hole
running from 01:00 UTC to 00:30 UTC the next day (48 half-hours), of which the interpolation fills
the first 2 h of a run. MEASURED (1 Oct 2026; days named by the date the hole starts at 01:00; gap
half-hours after interpolation, as in the gap file, then before it):
  2018  2 Oct and 9-10 Nov, two runs                                          136 (144)
  2019  9-10 Aug (92), and one half-hour (15 Jan 21:30) left of the scattered  93 (336)
        holes the interpolation bridges: 21-26 half-hours a day on 9-18 Jan, single
        half-hours on 19 and 20 Jan and 26 Feb
  2020  10 Jan 01:00-13:30 (22), 7 and 20 Jul (88), and 18 days of November   938 (986)
        in nine runs: 1-3, 8-9, 11-12, 14, 16-19, 21, 24, 26 and 28-30 (828)
  2021  ten days in four runs: 16-18, 20 and 24-27 Feb, 10-11 Mar             464 (480)
  2022-25  none (four single raw half-hours in 2022-23, all interpolated)        0 (2, 2, 0, 0)
Read as zero output, they cost the farm agents of the comb about 6.5% of their energy in 2020 and
2.7% in 2021, because the comb's per-half-hour rescaling to the metered national total hands that
energy to the reanalysis zones. The gap file says where they are, so meritorder.comb --fpn-gaps fill can put
the missing capacity on a weather shape instead (comb.fill_fpn_gaps).
  in service   per half-hour, a unit is in service from its first power (the map's first_power:
               its first positive notification) - or from the start of the record for a
               pre_record unit - to its last-ever notification in data/raw/fpn/{bmu}.csv (every
               unit's runs to the end of the pull, so none is decommissioned in the panel). Before
               first power a unit notifies zeros while it is built, and after its last
               notification it is gone, so a missing notification there is a genuine zero, not a
               gap. (First power, not first notification: Triton Knoll's units notified zero from
               Aug 2020 and first generated in Jul-Aug 2021, so the February 2021 hole is no gap.)
  pull hole    a half-hour in which at least PULL_HOLE_SHARE (0.5) of the year's in-service wind
               units have no notification (pull_holes). Only there is a unit's missing
               notification a gap; a unit silent on its own is read as the zero the FPN file
               already holds. MEASURED (1 Oct 2026, all 107-167 in-service units of 2018-2025): the
               unnotified share of a half-hour with any silent unit is either exactly 1 (every unit;
               136, 93, 938 and 464 half-hours in 2018-2021, none from 2022) or below 0.05 (one
               unit), so the rule does not depend on the threshold. The single-unit silences are
               commissioning: T_MOWEO-1 (Moray East) notified three test half-hours of at most 1 MW
               on 4 Jun 2021, nothing until 27 Jun, then zeros to the end of July (1,122 half-hours)
               while its sister unit notified throughout; T_CUMHW-1 one 50 MW half-hour on 27 Oct
               2023, then nothing until 31 Oct (164). Counted as gaps, the comb's fill put 34 GWh of
               weather output on Moray East in June 2021, three times its notified June energy.
  gap share    sum over the farm's units in service and without a notification in a pull hole of
               their capacity, over the farm's capacity_mw. For a farm whose units are all in service
               all year (every RO farm) that is the share of its in-service capacity; for a farm
               commissioned during the year it is the missing MW over the year's capacity, so the
               share times capacity_mw is always the missing MW.
  fpn_notified_share     the share of the year's half-hours with a gap share of 0 (no in-service unit
                         unnotified in a pull hole, after interpolation; basis.py's cov_notified
                         counts before interpolation, so it is at most this)
  full_service_from/_to  the first and last half-hour of the year in which every unit of the farm is
                         in service (the year's ends for most farms), the window over which the comb
                         measures a farm's own output level for the fill

Run: PIPELINE_YEAR=2023 python -m gbpowerdata.build.stage2d_wind_farms   (one year per call)
"""

from __future__ import annotations

import re
import sys

import numpy as np
import pandas as pd

from gbpowerdata import config as cfg

CFG = cfg.load_config()
YEAR = int(CFG["year"])
RO_CLOSURE = int(CFG["stage1"]["ro_closure_year"])
RES = int(CFG["resolution_minutes"])
FIRST_POWER_LEAD = pd.DateOffset(months=5)
EXTENSION_GAP = pd.DateOffset(months=12)
GAP_FILL_HH = 4          # interpolate notification gaps up to 2 h; longer gaps count as no output
PULL_HOLE_SHARE = 0.5    # a half-hour is a hole in the FPN pull when at least this share of the
                         # year's in-service wind units has no notification (docstring, NOTIFICATION GAPS)

OFFSHORE_BANDS = [(pd.Timestamp("2006-07-11"), 1.0), (pd.Timestamp("2010-03-31"), 1.5),
                  (pd.Timestamp("2015-03-31"), 2.0), (pd.Timestamp("2016-03-31"), 1.9)]
OFFSHORE_LATEST = 1.8
ONSHORE_BANDS = [(pd.Timestamp("2013-03-31"), 1.0)]
ONSHORE_LATEST = 0.9


def band_at(offshore: bool, accredited: pd.Timestamp) -> float:
    """ROCs/MWh for wind accredited on `accredited` (OFG1164 App. 4; see the module docstring)."""
    if pd.isna(accredited):
        return np.nan
    d = pd.Timestamp(accredited).tz_localize(None) if pd.Timestamp(accredited).tzinfo else pd.Timestamp(accredited)
    for last_day, band in (OFFSHORE_BANDS if offshore else ONSHORE_BANDS):
        if d.normalize() <= last_day:
            return band
    return OFFSHORE_LATEST if offshore else ONSHORE_LATEST


def classify(u: pd.Series, year: int) -> dict:
    """In-service flag, regime and band of one unit in `year` (the rules of the docstring)."""
    fp = pd.Timestamp(u["first_power"]) if pd.notna(u["first_power"]) else pd.NaT
    in_service = (u["fpn_state"] == "pre_record"
                  or (u["fpn_state"] == "observed" and fp < pd.Timestamp(f"{year + 1}-01-01", tz="UTC")))
    out = dict(in_service=bool(in_service), regime="None", band=np.nan, band_basis="",
               accreditation_proxy=pd.NaT)
    if str(u.get("cfd", "")).lower() == "true" or u.get("cfd") is True:
        out["regime"] = "CfD"
        return out
    op = pd.Timestamp(u["repd_operational"]) if pd.notna(u["repd_operational"]) else pd.NaT
    # A unit is part of its site's original build unless it first generates more than
    # EXTENSION_GAP after the site's operational date: Rampion's second unit (first power
    # 2018-04, site operational 2017-11) is the same accreditation, while an extension under an
    # old station name first generates years later (and is pinned to its own REPD row anyway).
    ro_era = (u["fpn_state"] == "pre_record"
              or (pd.notna(fp) and (fp.year <= RO_CLOSURE
                                    or (pd.notna(op) and fp.tz_localize(None) <= op + EXTENSION_GAP))))
    if pd.notna(op) and op.year <= RO_CLOSURE and ro_era:
        off = str(u["is_offshore"]).lower() == "true"
        if pd.notna(fp):
            proxy, basis = fp.tz_localize(None), "first_power"
        else:
            proxy, basis = op - FIRST_POWER_LEAD, "repd_completion_less_lead"
        out.update(regime="RO", band=band_at(off, proxy), band_basis=basis,
                   accreditation_proxy=proxy.normalize())
    return out


def fpn_from_notifications(d: pd.DataFrame, idx: pd.DatetimeIndex) -> tuple[pd.Series, np.ndarray]:
    """(half-hourly mean notified MW on `idx`, True where that value is a notification).

    `d` holds one unit's raw notifications (timeFrom, timeTo, levelFrom, levelTo); those starting in
    idx's year are time-weighted within the settlement period they start in. Gaps of up to
    GAP_FILL_HH half-hours are interpolated (pandas' limit also fills the first GAP_FILL_HH of a
    longer gap) and count as notified; what is still missing reads 0 in the MW series and False in
    the mask. The MW series is exactly what wind_farm_fpn_{year}.csv has always carried.
    """
    d = d[d["timeFrom"].str.startswith(str(idx[0].year))]
    if d.empty:
        return pd.Series(0.0, index=idx), np.zeros(len(idx), dtype=bool)
    t0 = pd.to_datetime(d["timeFrom"], utc=True)
    t1 = pd.to_datetime(d["timeTo"], utc=True)
    frac = (t1 - t0).dt.total_seconds() / (RES * 60.0)
    mw = ((d["levelFrom"] + d["levelTo"]) / 2.0 * frac).groupby(t0.dt.floor(f"{RES}min")).sum()
    s = mw.reindex(idx).interpolate(limit=GAP_FILL_HH, limit_area="inside")
    return s.fillna(0.0).clip(lower=0.0), s.notna().to_numpy()


def unit_fpn_record(bmu: str, idx: pd.DatetimeIndex) -> tuple[pd.Series, np.ndarray, pd.Timestamp]:
    """(MW on idx, notified mask on idx, the unit's last-ever notification) from data/raw/fpn/{bmu}.csv."""
    d = pd.read_csv(cfg.raw_dir() / "fpn" / f"{bmu}.csv",
                    usecols=["timeFrom", "timeTo", "levelFrom", "levelTo"])
    last = (pd.to_datetime(d["timeFrom"], utc=True, format="ISO8601").max() if len(d) else pd.NaT)
    mw, ok = fpn_from_notifications(d, idx)
    return mw, ok, last


def unit_fpn(bmu: str, idx: pd.DatetimeIndex) -> pd.Series:
    """Half-hourly mean notified MW of one unit on `idx` (time-weighted within each period)."""
    return unit_fpn_record(bmu, idx)[0]


def service_start(u: pd.Series) -> pd.Timestamp:
    """The half-hour from which unit `u` (a wind_farm_map row) is in service: the start of the FPN
    record for a pre_record unit, else its first power (first positive notification)."""
    t = u["fpn_record_start"] if u["fpn_state"] == "pre_record" else u["first_power"]
    if pd.isna(t):
        return pd.NaT
    t = pd.Timestamp(t)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def in_service_mask(idx: pd.DatetimeIndex, start: pd.Timestamp, last: pd.Timestamp) -> np.ndarray:
    """True on the half-hours of idx from `start` to the half-hour of the last notification `last`
    (both inclusive); a missing start means never in service, a missing end no end."""
    if pd.isna(start):
        return np.zeros(len(idx), dtype=bool)
    on = idx >= pd.Timestamp(start).floor(f"{RES}min")
    if pd.notna(last):
        on &= idx <= pd.Timestamp(last).floor(f"{RES}min")
    return np.asarray(on)


def pull_holes(notified: list[np.ndarray], live: list[np.ndarray],
               share: float = PULL_HOLE_SHARE) -> np.ndarray:
    """True in the half-hours in which at least `share` of the units in service (`live`) have no
    notification (`notified` False): the holes in the FPN pull. Pass every in-service wind unit of
    the year, not one farm's (module docstring, NOTIFICATION GAPS)."""
    if not notified:
        return np.zeros(0, dtype=bool)
    on = np.vstack(live)
    n_live = on.sum(axis=0)
    n_miss = (on & ~np.vstack(notified)).sum(axis=0)
    return (n_live > 0) & (n_miss >= share * n_live)


def gap_share(notified: list[np.ndarray], live: list[np.ndarray], caps, capacity: float,
              hole: np.ndarray | None = None) -> np.ndarray:
    """Per half-hour, the capacity of the units in service (`live`) without a notification
    (`notified` False) over the farm's `capacity`; with `hole` (pull_holes), only in the holes of
    the pull, so a unit's own silence reads as the genuine zero it is (module docstring,
    NOTIFICATION GAPS)."""
    miss = np.zeros(len(notified[0]) if notified else 0)
    for ok, on, c in zip(notified, live, caps):
        miss = miss + float(c) * (on & ~ok & (True if hole is None else hole))
    return miss / capacity if capacity > 0 else miss * 0.0


def full_service(idx: pd.DatetimeIndex, live: list[np.ndarray]) -> tuple[pd.Timestamp, pd.Timestamp]:
    """First and last half-hour of idx in which every unit is in service (NaT, NaT if none)."""
    allon = np.logical_and.reduce(live) if live else np.zeros(len(idx), dtype=bool)
    if not allon.any():
        return pd.NaT, pd.NaT
    w = np.flatnonzero(allon)
    return idx[w[0]], idx[w[-1]]


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", str(s)).strip("_")


def main() -> None:
    m = pd.read_csv(cfg.reference_dir() / "wind_farm_map.csv")
    idx = pd.date_range(f"{YEAR}-01-01", f"{YEAR + 1}-01-01", freq=f"{RES}min",
                        inclusive="left", tz="UTC")
    c = pd.DataFrame([classify(u, YEAR) for _, u in m.iterrows()], index=m.index)
    m = pd.concat([m, c], axis=1)
    m["is_offshore"] = m["is_offshore"].astype(str).str.lower() == "true"
    m["tech_key"] = np.where(m["is_offshore"], "Wind_off", "Wind_on")
    m["_band"] = m["band"].fillna(-1.0)
    m["_zone"] = m["gsp_group"].fillna("")
    gkey = ["station", "regime", "_band", "_zone", "is_offshore"]
    # A farm's id must not change between years: the multi-year contract panels follow an agent
    # by id, and Gordonbush's RO farm must stay one agent when its 2021 extension appears. So
    # whether a station's farms carry a regime/band/zone suffix is decided over ALL its units,
    # in service or not (regime and band do not depend on the year), and only then is the
    # year's in-service set taken.
    per_station = m.drop_duplicates(gkey).groupby("station").size()
    m = m[m["in_service"]].copy()
    groups = list(m.groupby(gkey, sort=True))

    # Every in-service unit's record first: a gap is a hole in the pull only where most of the
    # year's units lack a notification (pull_holes), which needs them all.
    rec = {u["elexon_bmu_id"]: unit_fpn_record(u["elexon_bmu_id"], idx) for _, u in m.iterrows()}
    on = {u["elexon_bmu_id"]: in_service_mask(idx, service_start(u), rec[u["elexon_bmu_id"]][2])
          for _, u in m.iterrows()}
    hole = pull_holes([rec[b][1] for b in rec], [on[b] for b in rec])

    farms, cols, gaps = [], {}, {}
    for (st, reg, band, zone, off), g in groups:
        fid = _slug(st)
        if per_station[st] > 1:
            fid += f"_{reg}" + (f"_{band:g}" if band >= 0 else "") + (f"_{zone.strip('_')}" if zone else "")
        recs = [rec[b] for b in g["elexon_bmu_id"]]
        prof = sum(r[0] for r in recs)                  # the same sum, in the same order, as always
        cap = float(g["bmu_capacity_mw"].sum())
        cols[fid] = prof.round(3)
        live = [on[b] for b in g["elexon_bmu_id"]]
        share = gap_share([r[1] for r in recs], live, g["bmu_capacity_mw"].to_numpy(float), cap, hole=hole)
        gaps[fid] = np.round(share, 6)
        f0, f1 = full_service(idx, live)
        farms.append(dict(
            farm_id=fid, station=st, units=";".join(sorted(g["elexon_bmu_id"])),
            tech_key="Wind_off" if off else "Wind_on", is_offshore=bool(off),
            gsp_group=zone or np.nan, capacity_mw=round(cap, 3), regime=reg,
            band=band if band >= 0 else np.nan, band_basis=";".join(sorted(set(g["band_basis"]) - {""})),
            accreditation_proxy=g["accreditation_proxy"].min(),
            cfd_ids=";".join(sorted({i for s in g["cfd_ids"].fillna("") for i in str(s).split(";") if i})),
            fpn_coverage=round(float((prof > 0).mean()), 4),
            mean_cf=round(float(prof.mean() / cap), 4) if cap > 0 else np.nan,
            fpn_notified_share=round(float((share <= 0).mean()), 4),
            full_service_from=f0, full_service_to=f1))
    f = pd.DataFrame(farms).sort_values(["regime", "tech_key", "farm_id"]).reset_index(drop=True)
    out = cfg.processed_dir() / f"wind_farms_{YEAR}.csv"
    f.to_csv(out, index=False)
    prof = pd.DataFrame(cols, index=idx)[f["farm_id"]]
    prof.index.name = "startTime"
    prof.to_csv(cfg.processed_dir() / f"wind_farm_fpn_{YEAR}.csv")
    gp = pd.DataFrame(gaps, index=idx)[f["farm_id"]]
    gp.index.name = "startTime"
    gp.to_csv(cfg.processed_dir() / f"wind_farm_fpn_gaps_{YEAR}.csv", float_format="%.6g")
    print(f"--- Stage 2d wind farms {YEAR}: {len(f)} farms from {len(m)} in-service units ---")
    print(f.groupby(["regime", "tech_key"]).agg(farms=("farm_id", "size"), mw=("capacity_mw", "sum"),
                                                mean_cf=("mean_cf", "mean")).round(3).to_string())
    ro = f[f["regime"] == "RO"]
    if len(ro):
        print("RO band mix (MW):", ro.groupby(["tech_key", "band"])["capacity_mw"].sum().round(0).to_dict())
    miss = (gp * f.set_index("farm_id")["capacity_mw"]).sum() * RES / 60.0      # MWh of capacity unnotified
    for reg, r in f.groupby("regime"):
        tot = float(r["capacity_mw"].sum()) * len(idx) * RES / 60.0
        print(f"FPN gaps, {reg}: {100 * float(miss[r['farm_id']].sum()) / tot:.2f}% of capacity-hours unnotified; "
              f"notified share min {r['fpn_notified_share'].min():.4f}")
    own = {b: int((on[b] & ~rec[b][1] & ~hole).sum()) for b in rec}
    own = {b: n for b, n in own.items() if n > 0}
    print(f"FPN pull holes: {int(hole.sum())} half-hours; unit-own silences read as zero (no gap): "
          + (", ".join(f"{b} {n} HH" for b, n in own.items()) or "none"))
    print(f"Saved -> {out.name}, wind_farm_fpn_{YEAR}.csv, wind_farm_fpn_gaps_{YEAR}.csv")


if __name__ == "__main__":
    sys.exit(main())
