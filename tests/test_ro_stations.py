"""The RO accredited stations without their holders (build.ro_stations), on a synthetic register."""
from __future__ import annotations

import pandas as pd

from gbpowerdata.build import ro_stations as S


def _register():
    return pd.DataFrame({
        "Accreditation reference": ["R00001SCSC", "R00002ENSC", "R00003WASC"],
        "Station name": ["Hill Farm Turbine", "Big Offshore", "Brook Hydro"],
        "Organisation name": ["J Smith", "Big Wind Ltd", "A Jones"],
        "Station DNC in kW": ["1,500", "630,000", "45"],
        "Technology": ["Onshore wind", "Offshore wind", "Micro hydro"],
        "Commissioning date": ["12/03/2010", "01/06/2012", "05/05/2015"],
        "Effective date": ["01/04/2010", "01/07/2012", "01/06/2015"],
        "Country": ["Scotland", "England", "Wales"],
        "Contract type": ["General", "General", "General"],
        "Organisation address": ["1 Lane, Aberdeen, AB1 2CD, Scotland", "Tower, London, EC1A 1AA, England", "Brook House, LL1 1AA"],
        "Station address": ["Hill Farm, Aberdeen, AB1 2CD, Scotland", "North Sea", "Brook Mill, Brook, LL1 1AA, Wales"],
    })


def test_output_has_no_holder_columns():
    out = S.stations(_register(), "RO_Accredited_Stations_test.csv")
    text = " ".join(out.columns) + " " + out.astype(str).to_string()
    assert "J Smith" not in text and "A Jones" not in text and "Organisation" not in text
    assert "1 Lane" not in text and "Tower" not in text and "Brook House" not in text
    assert list(out.columns) == ["accreditation_number", "station_name", "technology", "tech", "dnc_mw",
                                 "commissioning_date", "accreditation_date", "country", "station_postcode",
                                 "register_file"]


def test_capacity_dates_and_technology_are_parsed():
    out = S.stations(_register(), "RO_Accredited_Stations_test.csv").set_index("accreditation_number")
    assert out.loc["R00001SCSC", "dnc_mw"] == 1.5 and out.loc["R00002ENSC", "dnc_mw"] == 630.0
    assert out.loc["R00002ENSC", "tech"] == "Offshore" and out.loc["R00003WASC", "tech"] == "Hydro"
    assert str(out.loc["R00001SCSC", "accreditation_date"])[:10] == "2010-04-01"
    assert str(out.loc["R00001SCSC", "commissioning_date"])[:10] == "2010-03-12"
    assert (out["register_file"] == "RO_Accredited_Stations_test.csv").all()


def test_station_postcode_is_full_for_large_stations_and_outward_only_below_one_mw():
    out = S.stations(_register(), "RO_Accredited_Stations_test.csv").set_index("accreditation_number")
    assert out.loc["R00001SCSC", "station_postcode"] == "AB1 2CD"       # 1.5 MW: the site's full postcode
    assert out.loc["R00003WASC", "station_postcode"] == "LL1"           # 45 kW: the district only
    assert out.loc["R00002ENSC", "station_postcode"] == ""              # no postcode in the address
