"""The cap's make-up per period (gbpowerdata.build.build_cap_tariff): every number comes from Ofgem's model, and
the benchmark consumption of each period is read off the cap itself.

The tests build the three tabs (1b history, 3d schemes, 3a CfD allowance) in Ofgem's layout for periods no real
model covers (2031/32), with the benchmark changing between them as it did in 2026, and check that the parser gives
back the benchmark, the unit rate and each of its parts, ignores the multi-register block, and stops when the
policy identity or the components' sum does not hold. tests/realdata/test_cap_tariff.py checks the real model."""
import numpy as np
import pandas as pd
import pytest

from gbpowerdata.build import build_cap_tariff as C

RNG = np.random.default_rng(20261023)
P1B, P2B = "Apr 2031 - Sep 2031", "Oct 2031 - Mar 2032"                    # tab 1b's labels
P1, P2 = "April 2031 - September 2031", "October 2031 - March 2032"       # tabs 3a/3d's labels
KWH = {"electricity": (3100.0, 2500.0), "gas": (12000.0, 9500.0)}         # the benchmark moves between the periods
NAN = np.nan


def _cap(seed_shift: float = 0.0):
    """Synthetic tabs and the numbers they were built from."""
    sch = {"electricity": {"ro_gbp_mwh": RNG.uniform(5, 40, 2), "fit_gbp_mwh": RNG.uniform(3, 9, 2),
                           "whd_gbp_customer": RNG.uniform(3, 20, 2)},
           "gas": {"eco_gbp_mwh": RNG.uniform(1, 4, 2), "whd_gbp_customer": RNG.uniform(3, 20, 2),
                   "ggl_gbp_customer": RNG.uniform(0, 5, 2)}}
    cfd = RNG.uniform(-40, 40, (len(C.REGION_TO_GSP), 2))
    lv = {}
    for fuel, s in sch.items():
        per_mwh = s.get("ro_gbp_mwh", 0) + s.get("fit_gbp_mwh", 0) + s.get("eco_gbp_mwh", 0)
        pc_nil = s["whd_gbp_customer"] + s.get("ggl_gbp_customer", 0)
        kwh = np.array(KWH[fuel])
        nil = {"DF": np.zeros(2), "CM": np.zeros(2), "PC": pc_nil, "NC": RNG.uniform(20, 120, 2),
               "OC": RNG.uniform(30, 130, 2)}
        bench = {"DF": RNG.uniform(200, 900, 2) + (cfd.mean(axis=0) if fuel == "electricity" else 0),
                 "CM": RNG.uniform(5, 45, 2) if fuel == "electricity" else np.zeros(2),
                 "PC": pc_nil + per_mwh * kwh / C.MWH * (1 + seed_shift), "NC": nil["NC"] + RNG.uniform(100, 300, 2),
                 "OC": nil["OC"] + RNG.uniform(30, 90, 2)}
        lv[fuel] = (nil, bench)
    return sch, cfd, lv


def _hist(lv, total_shift: float = 0.0) -> pd.DataFrame:
    e, g = 1, 5                                                  # the label columns of the two blocks
    rows = [[NAN, "Historical level tables"], [NAN, "Other Payment Method"],
            [NAN, "Electricity: Single-Rate Metering Arrangement", NAN, NAN, NAN, "Gas"], []]
    for block, k in (("Nil consumption", 0), ("Typical consumption", 1)):
        rows.append([NAN, block, P1B, P2B, NAN, block, P1B, P2B])
        for comp in ("DF", "CM", "PC", "NC", "OC", "Total_GB average"):
            r = [NAN] * 8
            for fuel, c0 in (("electricity", e), ("gas", g)):
                vals = lv[fuel][k]
                v = sum(vals.values()) + (total_shift if comp.startswith("Total") else 0) \
                    if comp.startswith("Total") else vals[comp]
                r[c0] = comp
                r[c0 + 1:c0 + 3] = ["-" if not np.any(v) else x for x in v]
            rows.append(r)
        rows.append([])
    return pd.DataFrame(rows)


def _schemes(sch) -> pd.DataFrame:
    rows = [[NAN, "Policy Cost Allowance"], [NAN, "Fuel and Benchmark Metering Arrangement", "Scheme", "Unit"],
            [NAN, "28AD Charge Restriction Period:", NAN, NAN, P1, P2]]
    e, g = sch["electricity"], sch["gas"]
    rows += [[NAN, "Electricity - Single-Rate Metering Arrangement", "RO", "£/MWh supplied", *e["ro_gbp_mwh"]],
             [NAN, NAN, "FiT", "£/MWh supplied", *e["fit_gbp_mwh"]],
             [NAN, NAN, "WHD", "£/customer", *e["whd_gbp_customer"]],
             [NAN, "Electricity - Multi-Register Metering Arrangement", "RO", "£/MWh supplied", 999.0, 999.0],
             [NAN, "Gas", "ECO", "£/MWh supplied", *g["eco_gbp_mwh"]],
             [NAN, NAN, "WHD", "£/customer", *g["whd_gbp_customer"]],
             [NAN, NAN, "GGL", "£/customer", *g["ggl_gbp_customer"]]]
    return pd.DataFrame(rows)


def _wholesale(cfd) -> pd.DataFrame:
    rows = [[NAN, "28AD Charge Restriction Period:", NAN, NAN, NAN, P1, P2], [NAN, "CFD allowance"]]
    for k, region in enumerate(C.REGION_TO_GSP):
        lead = ["Electricity", "Single-Rate Metering Arrangement"] if k == 0 else [NAN, NAN]
        rows.append([NAN, *lead, region, "£ per customer per year" if k == 0 else NAN, *cfd[k]])
    return pd.DataFrame(rows)


# ------------------------------------------------------------------------------------------------ fast
def test_the_history_gives_back_each_periods_benchmark_unit_rate_and_parts():
    sch, cfd, lv = _cap()
    t = C.history(_hist(lv), _schemes(sch), _wholesale(cfd)).set_index(["fuel", "period"])
    for fuel in ("electricity", "gas"):
        nil, bench = lv[fuel]
        for k, period in enumerate((P1B, P2B)):
            r, kwh = t.loc[(fuel, period)], KWH[fuel][k]
            assert r["benchmark_kwh"] == kwh
            per = lambda comp: (bench[comp][k] - nil[comp][k]) * C.MWH / kwh             # noqa: E731
            assert r["unit_rate_gbp_mwh"] == pytest.approx(sum(per(c) for c in bench))
            c = cfd[:, k].mean() * C.MWH / kwh if fuel == "electricity" else 0.0
            assert r["cfd_gbp_mwh"] == pytest.approx(c)
            assert r["wholesale_gbp_mwh"] == pytest.approx(per("DF") - c)
            assert r["cm_gbp_mwh"] == pytest.approx(per("CM"))
            assert r["network_gbp_mwh"] == pytest.approx(per("NC"))
            assert r["other_gbp_mwh"] == pytest.approx(per("OC"))
            assert r["standing_charge_gbp_yr"] == pytest.approx(sum(nil[c][k] for c in nil))
            assert r["policy_gbp_customer"] == pytest.approx(nil["PC"][k])
            for col, v in sch[fuel].items():
                assert r[col] == pytest.approx(v[k])
    assert t.loc[("gas", P1B), "ro_gbp_mwh"] == 0.0                     # a scheme a fuel does not carry
    assert t.loc[("electricity", P1B), "ro_gbp_mwh"] == pytest.approx(sch["electricity"]["ro_gbp_mwh"][0])


def test_a_policy_allowance_that_implies_no_whole_benchmark_stops_the_build():
    sch, cfd, lv = _cap(seed_shift=0.03)                            # PC 3% off the schemes x benchmark
    with pytest.raises(ValueError, match="benchmark"):
        C.history(_hist(lv), _schemes(sch), _wholesale(cfd))


def test_allowances_that_do_not_add_up_to_the_caps_total_stop_the_build():
    sch, cfd, lv = _cap()
    with pytest.raises(ValueError, match="add up"):
        C.history(_hist(lv, total_shift=1.0), _schemes(sch), _wholesale(cfd))


def test_scheme_columns_name_the_scheme_and_its_unit():
    assert C.scheme_column("RO", "£/MWh supplied") == "ro_gbp_mwh"
    assert C.scheme_column("AAHEDC (GB average)", "£/MWh supplied") == "aahedc_gbp_mwh"
    assert C.scheme_column("WHD", "£/customer") == "whd_gbp_customer"
