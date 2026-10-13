"""The NESO puller's groups (gbpowerdata.pull.neso_pull) with the portal replaced: the historic demand data, one file
per year, pulled only when named, so a plain run still pulls the network charges alone. No network needed."""
import pandas as pd

from gbpowerdata.pull import neso_pull as N


def test_historic_demand_is_pulled_only_when_named(monkeypatch):
    pulled = []
    monkeypatch.setattr(N, "pull_group", pulled.append)
    N.main(["neso_pull"])
    N.main(["neso_pull", "demand"])
    assert pulled == ["bsuos", "aahedc", "tnuos", "demand"]


def test_historic_demand_is_one_file_per_year(tmp_path, monkeypatch):
    monkeypatch.setattr(N, "OUT_DIR", tmp_path)
    monkeypatch.setattr(N, "ckan", lambda action, **p: {"resources": [
        {"name": f"Historic Demand Data {y}", "id": str(y), "datastore_active": True} for y in (2022, 2023)]})
    monkeypatch.setattr(N, "datastore_fetch", lambda rid: pd.DataFrame({"SETTLEMENT_DATE": [rid], "ND": [1]}))
    N.pull_group("demand")                                  # the years the portal lacks are reported and skipped
    assert sorted(p.name for p in tmp_path.iterdir()) == ["historic_demand_2022.csv", "historic_demand_2023.csv"]
    assert pd.read_csv(tmp_path / "historic_demand_2023.csv")["SETTLEMENT_DATE"].tolist() == [2023]
