"""GB electricity-market data pipeline: source pulls -> immutable raw snapshots -> per-year
half-hourly panels (2018-2025) of demand, capacity factors, fuel and carbon prices, plant
fleet and support regimes, CfD settlement, system prices, D-1 forecasts and day-ahead prices.

Subpackages and modules:
    gbpowerdata.pull       data acquisition, one module per source (writes data/raw/)
    gbpowerdata.build      processing stages (writes data/processed/)
    gbpowerdata.common     shared helpers (GSP geolocation, REPD, name matching, PECD regions)
    gbpowerdata.config     config.yaml loader + path helpers
    gbpowerdata.processed  loaders for the processed per-year tables
    gbpowerdata.venue      which day-ahead auction (N2EX / EPEX hourly / EPEX half-hourly) a
                           consumer reads its price from
"""

__version__ = "0.1.0"
