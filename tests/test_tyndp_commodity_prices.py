"""TYNDP 2024's commodity prices (build.tyndp_commodity_prices): the sheet's rows to a long table, on synthetic rows
laid out as the workbook's "Matrix 2024" sheet."""
from __future__ import annotations

import pytest

from gbpowerdata.build import tyndp_commodity_prices as C


def _rows(blend=True, co2=True, currency="(Currency 2021 €)"):
    rows = [(None, None, None, "Same for all scenarios", None, None),
            (None, None, None, None, None, None),
            (None, "Fuel", "Unit", 2030, 2040, 2050, "Source "),
            (None, "Natural Gas", "€/GJ", 6.29, 5.65, 5.02, "IEA 2022 (APS)")]
    if co2:
        rows.append((None, "CO2 price", "€/ton", 113.4, 147, 168, "IEA 2022 (APS)"))
    rows.append((None, "Amonia imports prices ", "€/GJ", 38.3, 30.1, 24.1, "EWI"))
    if blend:
        rows.append((None, "Gas (blend of biomethane, synthetic gas and NG) NT+", "€/GJ", "7.5", "9.0", None, "see"))
    rows += [(None, "Gas (blend of biomethane, synthetic gas and NG) DE", "€/GJ", None, 10.86, 17.93, "see"),
             (None, None, currency, None, "Interpolation", None)]
    return rows


def test_table_has_each_fuel_scenario_and_year_with_its_unit():
    t = C.table(_rows())
    nt = t[(t["fuel"] == C.GAS_BLEND) & (t["scenario"] == "NT+")].set_index("year")["value"]
    assert nt.to_dict() == {2030: 7.5, 2040: 9.0}                    # the workbook's strings read as numbers
    co2 = t[t["fuel"] == "CO2 price"]
    assert set(co2["scenario"]) == {"all"} and set(co2["unit"]) == {"EUR2021/t"}
    assert co2.set_index("year").loc[2040, "value"] == 147.0
    assert t.loc[t["fuel"] == "Natural Gas", "unit"].iloc[0] == "EUR2021/GJ"
    assert "Amonia imports prices" in set(t["fuel"])                  # names stripped
    de = t[(t["fuel"] == C.GAS_BLEND) & (t["scenario"] == "DE")]
    assert sorted(de["year"]) == [2040, 2050]                         # no 2030 value, no row
    assert list(t.columns) == ["fuel", "scenario", "year", "value", "unit"]


@pytest.mark.parametrize("kw, match", [(dict(blend=False), "NT\\+"), (dict(co2=False), "CO2"),
                                       (dict(currency="(Currency 2023 €)"), "2021")])
def test_table_raises_without_what_the_model_reads_or_in_another_money(kw, match):
    with pytest.raises(ValueError, match=match):
        C.table(_rows(**kw))
