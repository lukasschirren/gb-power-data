# Power Station Dictionary — vendored snapshot

`ids.csv` is copied verbatim from the OSUKED Power Station Dictionary.

    source   https://github.com/OSUKED/Power-Station-Dictionary
    file     data/dictionary/ids.csv
    commit   a9f5f0fa32  (2023-04-06)
    licence  MIT
    fetched  2026-07-22

## Why this is vendored, not pulled

The file has not been edited since **April 2023**; the repository's last push of
any kind was February 2025. It is treated here as a frozen historical artefact,
not a live dependency:

* a build-time fetch would add a network dependency on a barely-maintained repo
  for a 277-row CSV that does not change;
* the snapshot must be stable for a paper to be reproducible.

If upstream ever revives, re-vendor deliberately and re-run
`scripts/build_bmu_crosswalk.py`, which will report what changed.

## What is used from it, and what is not

Only the **station grouping** is used: which Elexon/NG BMU ids belong to the same
physical station, and which CfD contract ids attach to that station. Everything
else in the file is ignored in favour of live sources already in this pipeline:

| PSD column                   | Used? | Instead                                       |
|------------------------------|-------|-----------------------------------------------|
| `sett_bmu_id`, `ngc_bmu_id`  | yes   | — (the reason this file is here)              |
| `cfd_id`                     | yes   | — (joins directly to `agents_{year}.agent_id`)|
| `name`, `dictionary_id`      | yes   | — (station label + surrogate key)             |
| `eic_id`                     | no    | `bm_units_*.csv` `eic` (live, Elexon)         |
| fuel type (linked package)   | no    | `bm_units_*.csv` `fuelType` — agrees 315/315  |
| `old_repd_id`, `new_repd_id` | no    | `repd_q1_2026.csv` (PSD's REPD is Jan 2023)   |
| plant locations (linked pkg) | no    | powerplantmatching `lat`/`lon`, fleet-wide    |
| CfD strike prices (linked)   | no    | LCCC register (authoritative, current)        |

## Known limitations carried into the crosswalk

* **Historical roster, no retirement dates.** It lists Didcot, Cottam,
  Eggborough, Longannet, Aberthaw, Fiddler's Ferry. The build flags every BMU
  absent from the current Elexon register via `in_elexon_register`, which turns
  the staleness into a usable retirement signal — but do **not** treat presence
  in this file as evidence a station was operational in the modelled year.
* **Nothing after April 2023.** No AR5/AR6/AR7 CfDs.
* **Transmission-connected bias.** ~22% of generating BMUs, ~57% of
  non-interconnector capacity. No interconnectors, almost no embedded plant.
* **Phase-level CfDs share station-level BMUs.** Hornsea 1/2/3 all map to the
  same three `T_HOWAO-*` units, because the meter is at the station. Apportion
  by capacity at point of use; see the crosswalk docstring.
