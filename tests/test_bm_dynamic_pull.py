"""The BM dynamic data puller's submissions mode (gbpowerdata.pull.bm_dynamic_pull.pull_submissions) with the API
replaced: one file per dataset and month, a quiet month written as an empty file with its columns, a month that is
over not pulled again, the month in progress pulled again. No network needed."""
import pandas as pd

from gbpowerdata.pull import bm_dynamic_pull as B


def test_submissions_are_kept_by_month_and_the_current_month_is_pulled_again(tmp_path, monkeypatch):
    monkeypatch.setattr(B, "OUT", tmp_path)
    calls = []

    def fake(url, params):
        calls.append((url.rsplit("/", 2)[-2], params["from"][:7]))
        return [{"dataset": "MDV", "time": params["from"], "volumeMax": 98, "bmUnit": "2__B001"}] \
            if params["from"].startswith("2024-01") else []

    monkeypatch.setattr(B, "_get_list", fake)
    monkeypatch.setattr(B.time, "sleep", lambda s: None)
    now = pd.Timestamp.now(tz="UTC").strftime("%Y-%m")
    B.pull_submissions(("MDV",), start="2024-01", end="2024-02")
    assert calls == [("MDV", "2024-01"), ("MDV", "2024-02")]
    assert pd.read_csv(tmp_path / "submissions_MDV_2024-01.csv")["volumeMax"].tolist() == [98]
    assert pd.read_csv(tmp_path / "submissions_MDV_2024-02.csv").empty               # a quiet month, kept
    calls.clear()
    B.pull_submissions(("MDV",), start="2024-01", end=now)
    assert ("MDV", "2024-01") not in calls and calls[-1] == ("MDV", now)              # over: kept; current: again


def test_the_submissions_option_takes_dynamic_datasets_and_defaults_to_mdv_and_mdp(monkeypatch):
    seen = []
    monkeypatch.setattr(B, "pull_submissions", lambda datasets: seen.append(tuple(datasets)))
    B.main(["--submissions"])
    B.main(["--submissions", "MZT", "MNZT"])
    assert seen == [("MDV", "MDP"), ("MZT", "MNZT")]
