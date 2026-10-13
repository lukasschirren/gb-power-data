"""The storage fleet's rules (gbpowerdata.build.storage_fleet) on synthetic values: the kind of a unit from its id, a
declared MDV taken as energy only when it is not a placeholder and is plausible at the unit's capacity, entry as the
first evidence of trading (censored where its source opens), exit only well before the end of the data, and the
units operating on a date. No data/ and no network needed."""
import numpy as np
import pandas as pd
import pytest

from gbpowerdata.build import storage_fleet as F

T = pd.Timestamp


def test_the_kind_of_a_unit_follows_its_id():
    assert [F.kind_of(u) for u in ("E_CHAPB-1", "T_DINO-1", "2__FBPGM001", "V__NHABI005", "GSET-07")] == \
        ["bm", "bm", "supplier", "vlp", "non_bm"]


def test_a_declared_mdv_is_energy_only_when_plausible():
    assert F.plausible_mdv(pd.Series([98.0, 99999.0, 1.0]), 50.0) == 98.0       # placeholders ignored
    assert np.isnan(F.plausible_mdv(pd.Series([1.0, 0.0, 99999.0]), 50.0))
    assert np.isnan(F.plausible_mdv(pd.Series([5.0]), 50.0))                    # 0.1 h at 50 MW: not its energy
    assert np.isnan(F.plausible_mdv(pd.Series([98.0]), np.nan))


WINDOWS = {"notified": (T("2016-03-01"), T("2026-10-08")), "bm_action": (T("2018-01-01"), T("2026-10-09")),
           "ancillary": (T("2020-10-02"), T("2026-10-07"))}


def test_entry_is_the_first_evidence_of_trading_and_censored_at_a_window_start():
    e = F.entry_exit({"notified": T("2021-05-03"), "bm_action": T("2021-06-01"), "ancillary": T("2021-04-20")},
                     {"notified": T("2026-10-01"), "bm_action": T("2026-10-05"), "ancillary": T("2026-10-06")}, WINDOWS)
    assert e["entry_date"] == T("2021-04-20") and not e["entry_censored"] and pd.isna(e["exit_date"])
    c = F.entry_exit({"notified": pd.NaT, "bm_action": pd.NaT, "ancillary": T("2020-10-02")},
                     {"notified": pd.NaT, "bm_action": pd.NaT, "ancillary": T("2022-03-31")}, WINDOWS)
    assert c["entry_censored"] and c["exit_date"] == T("2022-03-31")            # left the market in 2022
    n = F.entry_exit({"notified": pd.NaT, "bm_action": pd.NaT, "ancillary": pd.NaT},
                     {"notified": pd.NaT, "bm_action": pd.NaT, "ancillary": pd.NaT}, WINDOWS)
    assert pd.isna(n["entry_date"]) and pd.isna(n["exit_date"])               # registered, never traded


def test_neso_spellings_of_one_unit_are_merged_and_a_registered_spelling_finds_its_bm_unit(tmp_path):
    rows = pd.DataFrame({
        "delivery_start": ["2020-10-13T22:00:00Z", "2021-09-15T22:00:00Z", "2023-01-30T23:00:00Z"],
        "unit": ["AFFR1", "AFFR-1", "AG_CBS06B"], "elexon_unit": [None, None, None],
        "participant": ["UK Power Reserve Ltd", "UK POWER RESERVE LIMITED", "X"], "technology": ["Battery"] * 3,
        "mw": [20.0, 20.0, 18.0]})
    rows.to_csv(tmp_path / "ancillary_by_unit_2021.csv", index=False)
    g, window = F.ancillary_dates(tmp_path, {F.id_key("AG-CBS06B"): "V__BCEND004"})
    affr = g[g["unit_id"] == "AFFR-1"].iloc[0]                      # one unit, NESO's latest spelling
    assert len(g) == 2 and affr["first_ancillary"] == T("2020-10-13") and affr["last_ancillary"] == T("2021-09-15")
    assert "V__BCEND004" in set(g["unit_id"])                       # mapped to its Elexon id despite the underscore
    assert window == (T("2020-10-13"), T("2023-01-30"))


def test_a_unit_named_by_its_elexon_id_in_some_files_and_its_national_grid_id_in_others_is_one_unit(tmp_path):
    rows = pd.DataFrame({"delivery_start": ["2021-01-19T23:00:00Z", "2022-04-21T22:00:00Z"],
                         "unit": ["E_ARNKB-2", "ARNKB-2"], "elexon_unit": [None, None], "participant": ["F", "F"],
                         "technology": ["Battery", "Battery"], "mw": [10.0, 12.0]})
    rows.to_csv(tmp_path / "ancillary_by_unit_2022.csv", index=False)
    g, _ = F.ancillary_dates(tmp_path, {F.id_key("ARNKB-2"): "E_ARNKB-2"})
    assert g["unit_id"].tolist() == ["E_ARNKB-2"] and g["first_ancillary"].iat[0] == T("2021-01-19")


def test_supplier_and_vlp_units_take_their_name_and_lead_party_from_the_newest_snapshot(tmp_path, monkeypatch):
    from gbpowerdata.build import bm_units as B

    old, new = tmp_path / "bm_units_20260101.csv", tmp_path / "bm_units_20260605.csv"
    pd.DataFrame({"elexonBmUnit": ["2__FBPGM001"], "bmUnitName": ["2__FBPGM001"], "leadPartyName": ["BP"],
                  "gspGroupName": ["Yorkshire"]}).to_csv(old, index=False)
    pd.DataFrame({"elexonBmUnit": ["2__FBPGM001", None], "bmUnitName": ["Wormald Green BESS", "X"],
                  "leadPartyName": ["BP Gas Marketing Limited", "Y"], "gspGroupName": ["Yorkshire", "Z"]}).to_csv(
        new, index=False)
    monkeypatch.setattr(B, "register_files", lambda: {T("2026-01-01"): old, T("2026-06-05"): new})
    assert F.register_names().to_dict("records") == [{"unit_id": "2__FBPGM001", "unit_name": "Wormald Green BESS",
                                                      "lead_party": "BP Gas Marketing Limited", "gsp_group": "Yorkshire"}]


def test_mdv_declarations_read_the_snapshots_and_every_submission(tmp_path):
    d = tmp_path / "bm_dynamic"
    d.mkdir()
    pd.DataFrame({"bmUnit": ["E_A-1", "E_A-1"], "dataset": ["MDV", "SEL"], "value": [50.0, 1.0]}).to_csv(
        d / "dynamic_2025-07-15_sp24.csv", index=False)
    pd.DataFrame({"dataset": ["MDV"], "time": ["2024-01-19T10:29:00Z"], "volumeMax": [98], "nationalGridBmUnit": ["X"],
                  "bmUnit": ["2__B001"]}).to_csv(d / "submissions_MDV_2024-01.csv", index=False)
    pd.DataFrame(columns=["dataset", "time", "bmUnit", "nationalGridBmUnit"]).to_csv(d / "submissions_MDV_2024-02.csv",
                                                                                     index=False)   # a quiet month
    pd.DataFrame({"dataset": ["MDP"], "periodMax": [120], "bmUnit": ["2__B001"]}).to_csv(d / "submissions_MDP_2024-01.csv",
                                                                                      index=False)
    m = F.mdv_declarations(tmp_path)
    assert sorted(map(tuple, m.values.tolist())) == [("2__B001", "MDP", 120), ("2__B001", "MDV", 98), ("E_A-1", "MDV", 50.0)]


def test_postcodes_and_the_cm_duration_class_at_a_postcode(tmp_path):
    assert F.postcode_of("Holes Bay Road, Poole, BH15 1AA") == "BH151AA" and F.postcode_of("no code here") is None
    anc = tmp_path / "neso" / "ancillary"
    anc.mkdir(parents=True)
    pd.DataFrame({"auctionUnit": ["AG-X01", "AG-X01", "AG-X01"], "postCode": ["BH15 1AA", "bh151aa", "SO1 1AA"],
                  "technologyType": ["Battery"] * 3}).to_csv(anc / "eac_by_unit_fy2025.csv", index=False)
    assert F.eac_postcodes(tmp_path).to_dict() == {"AGX01": "BH151AA"}             # the most frequent
    reg = tmp_path / "neso" / "cm_register"
    reg.mkdir(parents=True)
    pd.DataFrame({"Generating Technology Class": ["Storage (Duration 1h)", "Storage (Duration 2h)", "Storage (Duration 1h)",
                                                  "Storage (Duration 4h)", "Gas"],
                  "Delivery Year": ["2022", "2025", "2025", "2025", "2025"],
                  "Location and Post Code": ["Poole BH15 1AA", "Poole BH15 1AA", "Hythe SO45 6AA", "Hythe SO45 6AA",
                                             "Leeds LS1 1AA"]}).to_csv(reg / "components_20261010.csv", index=False)
    d = F.cm_postcode_durations(tmp_path)
    assert d.to_dict() == {"BH151AA": 2.0}       # the latest year's class; two classes at SO45 6AA in one year: left out


def test_the_cm_duration_of_a_linked_unit_is_the_agreement_in_force_not_a_later_extension(tmp_path):
    pd.DataFrame({"agreement_id": ["A", "B", "C", "D"], "auction_id": ["T-1-2025", "T-4-2025", "T-4-2027", "T-4-2028"],
                  "cmu_id": ["X", "X", "Y", "Z"], "unit_id": ["E_B-1", "E_B-1", "E_B-1", "E_N-1"],
                  "unit_name": ["B"] * 4, "basis": ["name"] * 4, "share": [1.0] * 4}).to_csv(
        tmp_path / "capacity_market_links.csv", index=False)
    pd.DataFrame({"agreement_id": ["A", "B", "C", "D"], "auction_id": ["T-1-2025", "T-4-2025", "T-4-2027", "T-4-2028"],
                  "duration_h": [2.0, 2.0, 9.0, 4.0], "connection_mw": [47.5, 46.5, 6.97, 50.0],
                  "first_delivery_year": [2025, 2026, 2027, 2028]}).to_csv(tmp_path / "capacity_market_agreements.csv",
                                                                            index=False)
    d = F.cm_link_durations(tmp_path, as_of="2026-10-10")
    assert d.to_dict() == {"E_B-1": 2.0, "E_N-1": 4.0}     # E_N-1: none started yet, the first to start


def test_operating_units_on_a_date():
    # D is seen only in NESO's results, last in March 2023: counted while seen, then not (it may have become a BM unit)
    fleet = pd.DataFrame({"unit_id": ["A", "B", "C", "D"], "kind": ["bm", "bm", "bm", "non_bm"],
                          "entry_date": ["2020-01-01", "2023-06-01", None, "2021-01-01"],
                          "exit_date": [None, "2024-01-01", None, None],
                          "last_seen": ["2026-10-01", "2024-01-01", None, "2023-03-01"],
                          "capacity_mw": [10.0, 20.0, 30.0, 5.0]})
    assert F.operating(fleet, "2023-02-15")["unit_id"].tolist() == ["A", "D"]
    assert F.operating(fleet, "2023-12-31")["unit_id"].tolist() == ["A", "B"]
    assert F.operating(fleet, "2024-06-30")["unit_id"].tolist() == ["A"]
