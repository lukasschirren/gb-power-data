"""The TYNDP hourly table (build.tyndp_hourly): the header map on a synthetic header."""
from __future__ import annotations

import pytest

from gbpowerdata.build import tyndp_hourly as T


def _header():
    labels, nodes = ["Hour", "Label"], ["", ""]
    for node in T.NODES:
        labels.append("Marginal Cost\n[EUR/MWh]")
        nodes.append(node)
    for lab in T.GB_COLS:
        labels.append(lab)
        nodes.append("UK00")
    labels.append("Demand [MW]")          # another node's demand, which is not kept
    nodes.append("FR00")
    return tuple(labels), tuple(nodes)


def test_columns_maps_each_nodes_marginal_cost_and_gbs_own_columns():
    labels, nodes = _header()
    got = T.columns(labels, nodes)
    assert got["mc_fr00"] == 2 and got["mc_uk00"] == 2 + len(T.NODES) - 1
    assert got["uk00_demand_mw"] == 2 + len(T.NODES)
    assert len(got) == len(T.NODES) + len(T.GB_COLS)           # FR00's demand is not kept


def test_columns_raises_when_a_node_is_missing():
    labels, nodes = _header()
    nodes = tuple("XX00" if n == "BE00" else n for n in nodes)
    with pytest.raises(ValueError, match="mc_be00"):
        T.columns(labels, nodes)
