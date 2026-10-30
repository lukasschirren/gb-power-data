"""Shared config + path helpers. Every pipeline stage reads paths and parameters from here so
nothing is hardcoded per year or per machine.

The configuration is config.yaml at the repo root. Two overrides, neither of which edits a
tracked file:

    GBPOWERDATA_CONFIG=/path/to/my.yaml   use another config file (e.g. one whose `paths` point
                                          at a data tree on a shared or external drive)
    PIPELINE_YEAR=2023                    the year a stage builds (scripts/run_pipeline.py sets
                                          it per subprocess)

GBPOWERDATA_CONFIG and the entries of `paths:` are relative to the repo root unless absolute, so
they mean the same thing from a notebook, a script or a subprocess.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]  # src/gbpowerdata/config.py -> repo root
CONFIG_PATH = REPO_ROOT / (os.environ.get("GBPOWERDATA_CONFIG") or "config.yaml")  # absolute wins


@lru_cache(maxsize=1)
def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    # The multi-year runner overrides the year per subprocess without editing config.yaml.
    if os.environ.get("PIPELINE_YEAR"):
        cfg["year"] = int(os.environ["PIPELINE_YEAR"])
    return cfg


def _path(key: str, *, make: bool = False) -> Path:
    """Resolve a directory from config['paths'] (relative to the repo root unless absolute)."""
    p = Path(os.path.normpath(REPO_ROOT / load_config()["paths"][key]))
    if make:
        p.mkdir(parents=True, exist_ok=True)
    return p


def raw_dir() -> Path:
    """Immutable source snapshots written by the pullers (gbpowerdata.pull)."""
    return _path("raw")


def processed_dir() -> Path:
    """Stage outputs written by gbpowerdata.build."""
    return _path("processed", make=True)


def reference_dir() -> Path:
    """Small hand-curated and derived lookup tables (overrides, crosswalks, weights)."""
    return _path("reference")


def load_reference_yaml(name: str) -> dict:
    """Load a YAML override/lookup table from data/reference/."""
    with open(reference_dir() / name, encoding="utf-8") as f:
        return yaml.safe_load(f)
