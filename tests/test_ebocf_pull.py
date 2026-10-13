"""The BM cashflow puller's month files (gbpowerdata.pull.ebocf_pull) with the API replaced: a month on disk is
pulled again only for the units it does not hold, their rows merged in and the unit list kept beside it; a file
written before the lists were kept holds the register's storage units of the snapshots kept on its day; the current
month is pulled again for every unit; the fleet's supplier and virtual lead party units are added; the volumes keep
Elexon's "Original" data type only. No network needed."""
import os
from datetime import date, datetime, timezone

import pandas as pd

from gbpowerdata.pull import ebocf_pull as E


def _row(day: str, unit: str, cashflow: float) -> dict:
    return {"settlementDate": day, "settlementPeriod": 1, "startTime": f"{day}T00:00:00Z", "bmUnit": unit,
            "nationalGridBmUnit": unit, "side": "offer", "cashflow_gbp": cashflow, "createdDateTime": None}


def test_a_month_on_disk_is_pulled_only_for_the_units_it_does_not_hold(tmp_path, monkeypatch):
    monkeypatch.setattr(E, "RAW", tmp_path)
    calls = []

    def fake_month(year, month, units, last, workers=E.WORKERS, ds=E.CASHFLOWS):
        calls.append(sorted(units))
        return pd.DataFrame([_row(f"{year}-{month:02d}-02", u, 10.0) for u in units if u != "V__B-1"],
                            columns=E.COLUMNS)

    monkeypatch.setattr(E, "pull_month", fake_month)
    path = E.month_path(2024, 1)
    path.parent.mkdir(parents=True)
    pd.DataFrame([_row("2024-01-01", "E_A-1", 5.0)]).to_csv(path, index=False)
    E.units_path(path).write_text("E_A-1\nE_C-1\n", encoding="utf-8")
    last = date(2026, 10, 9)
    assert E.update_month(2024, 1, ["E_A-1", "E_C-1", "2__B-1", "V__B-1"], last, current=False) == 2
    assert calls == [["2__B-1", "V__B-1"]]
    assert sorted(pd.read_csv(path)["bmUnit"]) == ["2__B-1", "E_A-1"]          # the old row kept, the new merged in
    assert E.held_units(path) == {"E_A-1", "E_C-1", "2__B-1", "V__B-1"}        # a unit without a cashflow is held too
    assert E.update_month(2024, 1, ["E_A-1", "2__B-1"], last, current=False) == 0
    E.update_month(2024, 1, ["E_A-1", "2__B-1"], last, current=True)            # the current month: every unit again
    assert calls[-1] == ["2__B-1", "E_A-1"]
    assert pd.read_csv(path).sort_values("bmUnit")["cashflow_gbp"].tolist() == [10.0, 10.0]


def test_a_failed_request_leaves_the_month_as_it_was(tmp_path, monkeypatch):
    monkeypatch.setattr(E, "RAW", tmp_path)
    monkeypatch.setattr(E, "pull_month", lambda *a, **k: None)
    path = E.month_path(2024, 2)
    path.parent.mkdir(parents=True)
    pd.DataFrame([_row("2024-02-01", "E_A-1", 5.0)]).to_csv(path, index=False)
    E.units_path(path).write_text("E_A-1\n", encoding="utf-8")
    assert E.update_month(2024, 2, ["E_A-1", "2__B-1"], date(2026, 10, 9), current=False) is None
    assert E.held_units(path) == {"E_A-1"} and len(pd.read_csv(path)) == 1


def test_a_file_without_a_unit_list_holds_the_register_storage_units_of_its_day(tmp_path, monkeypatch):
    seen = []

    def fake_register(before=None):
        seen.append(before)
        return ("E_A-1", "T_P-1")

    monkeypatch.setattr(E, "register_storage_units", fake_register)
    path = tmp_path / "ebocf_2021-05.csv"
    pd.DataFrame(columns=E.COLUMNS).to_csv(path, index=False)
    stamp = datetime(2026, 10, 7, 12, tzinfo=timezone.utc).timestamp()
    os.utime(path, (stamp, stamp))
    assert E.held_units(path) == {"E_A-1", "T_P-1"} and seen == [date(2026, 10, 7)]


def test_the_register_units_of_a_day_come_from_the_snapshots_kept_by_then(monkeypatch):
    from gbpowerdata.build import bm_units as B

    snaps = {pd.Timestamp("2026-06-05"): "a", pd.Timestamp("2026-11-01"): "b"}
    regs = {"a": ["E_A-1", "T_G-1"], "b": ["E_A-1", "E_NEW-1"]}
    tech = {"E_A-1": "battery", "T_G-1": "ccgt", "E_NEW-1": "battery"}
    monkeypatch.setattr(B, "register_files", lambda: snaps)
    monkeypatch.setattr(B, "register", lambda p: pd.DataFrame({"unit_id": regs[p], "tech": [tech[u] for u in regs[p]]}))
    E.register_storage_units.cache_clear()
    try:
        assert E.register_storage_units(date(2026, 10, 7)) == ("E_A-1",)
        assert E.register_storage_units(date(2026, 1, 1)) == ("E_A-1",)        # older than every snapshot: the oldest
        assert E.register_storage_units() == ("E_A-1", "E_NEW-1")
    finally:
        E.register_storage_units.cache_clear()


def test_the_fleets_supplier_and_virtual_lead_party_units_are_pulled_too(monkeypatch):
    from gbpowerdata import processed as P

    monkeypatch.setattr(P, "read_storage_fleet", lambda: pd.DataFrame({
        "unit_id": ["E_A-1", "2__B-1", "V__C-1", "GSET-07"], "kind": ["bm", "supplier", "vlp", "non_bm"]}))
    assert E.fleet_units() == ["2__B-1", "V__C-1"]

    def absent():
        raise FileNotFoundError("storage_fleet.csv")

    monkeypatch.setattr(P, "read_storage_fleet", absent)
    assert E.fleet_units() == []


def test_volumes_keep_the_whole_accepted_volume_with_its_sign_in_their_own_folder(tmp_path, monkeypatch):
    payload = {"data": [
        {"settlementDate": "2025-06-01", "settlementPeriod": 3, "startTime": "2025-06-01T00:00:00Z", "bmUnit": "E_A-1",
         "nationalGridBmUnit": "A-1", "dataType": t, "totalVolumeAccepted": v, "createdDateTime": "x"}
        for t, v in (("Original", -12.5), ("Original-Priced", -3.0), ("Re-priced", 0.0), ("Tagged", -20.0))]}
    r = E.rows(payload, "bid", E.VOLUMES)
    assert [x["volume_mwh"] for x in r] == [-12.5] and list(r[0]) == E.columns(E.VOLUMES)
    monkeypatch.setattr(E, "RAW", tmp_path)
    assert E.month_path(2025, 6, E.VOLUMES) == tmp_path / "bm_volumes" / "bm_volumes_2025-06.csv"
    path = E.month_path(2025, 6, E.VOLUMES)
    path.parent.mkdir(parents=True)
    pd.DataFrame(columns=E.columns(E.VOLUMES)).to_csv(path, index=False)
    assert E.held_units(path, E.VOLUMES) == set()       # no list: no legacy rule for the volumes, pulled again
