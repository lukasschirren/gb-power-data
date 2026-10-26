"""The annual generation by fuel (gbpowerdata.build.generation_by_fuel) on synthetic sheets: a table found by its
title and read to the next title, labels stripped of their notes and named, '[x]' read as not available, Great Britain
as England + Scotland + Wales and, for a year only DUKES has, the UK less Northern Ireland's latest year; shares of the
total; and the reconciliation's supplied basis and the half-hourly technologies it sums. No data/ and no network."""
import numpy as np
import pandas as pd
import pytest

from gbpowerdata.build import generation_by_fuel as G


def _sheet():
    rows = [["Table 5.6.B Electricity generated, GWh", None, None, None],
            ["Generation type", "Fuel", 2024.0, 2025.0],
            ["Major power producers [note 6]", "Gas", 75.0, 81.0],
            ["Major power producers [note 6]", "Total major power producers", 100.0, 110.0],
            ["All generating companies", "Gas", 87.0, 93.0],
            ["All generating companies", "Thermal renewables [note 9]", 40.0, "[x]"],
            ["All generating companies", "Total all generating companies", 200.0, 210.0],
            ["Table 5.6.C Shares", None, None, None]]
    return pd.DataFrame(rows)


def test_a_table_is_read_from_its_title_to_the_next_and_labels_are_named():
    rows, h = G._block(_sheet(), "Table 5.6.B")
    assert h == 1 and len(rows) == 5
    d = G._long(rows, [(2, dict(year=2024)), (3, dict(year=2025))])
    assert set(d["fuel"]) == {"gas", "total", "bioenergy"}
    assert set(d["generator_type"]) == {"major_power_producers", "all"}
    assert len(d) == 9                                          # the '[x]' of 2025 bioenergy is left out
    with pytest.raises(ValueError):
        G._long(pd.DataFrame([["Major power producers", "Unobtainium", 1.0]]), [(2, dict(year=2024))])


def _regional():
    rows = []
    for area, gas, tot in (("England", 60.0, 150.0), ("Scotland", 5.0, 40.0), ("Wales", 10.0, 20.0),
                           ("Northern Ireland", 4.0, 8.0)):
        rows += [dict(year=2024, area=area, generator_type="all", fuel="gas", measure="generated", gwh=gas, source="r"),
                 dict(year=2024, area=area, generator_type="all", fuel="total", measure="generated", gwh=tot,
                      source="r")]
    return pd.DataFrame(rows)


def test_great_britain_is_three_countries_and_later_years_the_uk_less_northern_ireland():
    uk = pd.DataFrame([dict(year=2025, area="UK", generator_type="all", fuel=f, measure="generated", gwh=v, source="d")
                       for f, v in (("gas", 90.0), ("total", 230.0), ("wind_onshore", 30.0))])
    gb = G.great_britain(_regional(), uk).set_index(["year", "fuel"])
    assert gb.loc[(2024, "gas"), "gwh"] == 75.0 and gb.loc[(2024, "total"), "gwh"] == 210.0
    assert gb.loc[(2025, "gas"), "gwh"] == 86.0 and gb.loc[(2025, "gas"), "source"].startswith("estimate")
    assert (2025, "wind_onshore") not in gb.index               # Northern Ireland's has no such row
    s = G.with_shares(pd.concat([_regional(), gb.reset_index()], ignore_index=True))
    assert s[(s["area"] == "GB") & (s["year"] == 2024) & (s["fuel"] == "gas")]["share"].iloc[0] == pytest.approx(75 / 210,
                                                                                                                   abs=1e-5)


def test_the_reconciliation_puts_gb_on_the_supplied_basis_and_sums_its_technologies():
    a = [dict(year=2023, area="GB", generator_type="all", fuel=f, measure="generated", gwh=v)
         for f, v in (("gas", 100.0), ("total", 300.0), ("pumped_storage", 2.0), ("wind", 80.0))]
    a += [dict(year=2023, area="UK", generator_type="all", fuel=f, measure=m, gwh=v)
          for f, m, v in (("gas", "generated", 110.0), ("gas", "supplied_gross", 99.0), ("total", "generated", 310.0),
                          ("total", "supplied_gross", 300.0), ("storage", "generated", 2.0),
                          ("storage", "supplied_gross", 1.9), ("wind", "generated", 82.0),
                          ("wind", "supplied_gross", 82.0))]
    s = pd.DataFrame([dict(resolution="year", period="2023", technology=t, energy_gwh=v, coverage=1.0)
                      for t, v in (("gas_ccgt", 85.0), ("gas_ocgt", 0.5), ("generation", 260.0),
                                   ("pumped_storage_generation", 1.5), ("wind_metered", 60.0),
                                   ("wind_embedded", 20.0))])
    r = G.reconcile(pd.DataFrame(a), s).set_index("fuel")
    assert r.loc["gas", "official_supplied_gwh"] == pytest.approx(90.0)                # 100 x 99/110
    assert r.loc["gas", "half_hourly_gwh"] == 85.5 and r.loc["gas", "missing_gwh"] == pytest.approx(4.5)
    assert r.loc["gas", "half_hourly_share"] == pytest.approx(0.95)
    assert r.loc["pumped_storage", "supplied_ratio"] == pytest.approx(0.95)            # DUKES's storage
    assert r.loc["wind", "half_hourly_gwh"] == 80.0 and np.isclose(r.loc["wind", "half_hourly_share"], 1.0)
