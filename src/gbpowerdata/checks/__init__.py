"""Checks of the built tables against themselves, the raw sources and official statistics.

The build stages test their logic on synthetic data (tests/); these functions check the data the stages wrote, so a
source that changes its format, a pull with a hole in it or a definition that drifts shows up as a failing check.
They read only, never write, and each returns a small table or number that tests/realdata asserts on (those tests
are skipped where the data are absent, so the synthetic suite runs anywhere).

  timeseries   the half-hourly UTC spine: rows per year, duplicates, the grid, 46 and 50 settlement periods on
               the clock-change days, settlement periods against UTC start times
  balance      transmission demand against metered generation and interconnector flows (FUELHH)
  official     the curated official totals of data/reference/official_statistics.csv
  storage      whether a storage unit's notifications are feasible for its power and energy capacity

Usage: python -m pytest tests/realdata (GBPOWERDATA_CONFIG picks the data folders, as for every stage).
"""
