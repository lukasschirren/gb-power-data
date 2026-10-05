"""Every module of the package imports, in a fresh interpreter, without the research code.

gbpowerdata is the data layer: models and analyses import it, never the other way round. The
check imports every module in one subprocess and inspects sys.modules, so a broken module or a
stray import of the research packages (gbabm, meritorder, spikeabm) fails the fast suite.

Two build stages read a hand-curated reference table at import time; they are left out of the
import list (with a note in the test output) until data/reference/ holds those tables.
"""
import os
import pkgutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
PKG = "gbpowerdata"
FORBIDDEN = {"gbabm", "meritorder", "spikeabm"}
# module -> the data/reference/ table it loads on import
NEEDS_REFERENCE = {
    "gbpowerdata.build.stage1_tag_plants": "plant_overrides.yaml",
    "gbpowerdata.build.stage3_build_agents": "tech_parameters.yaml",
}


def _modules() -> list[str]:
    names = [PKG]
    for m in pkgutil.walk_packages([str(SRC / PKG)], prefix=f"{PKG}."):
        names.append(m.name)
    return [n for n in names if not n.endswith("__main__")]


def test_every_module_imports_and_none_pulls_in_the_research_code():
    sys.path.insert(0, str(SRC))
    from gbpowerdata import config as cfg
    ref = cfg.reference_dir()
    mods = [m for m in _modules()
            if m not in NEEDS_REFERENCE or (ref / NEEDS_REFERENCE[m]).exists()]
    skipped = sorted(set(_modules()) - set(mods))
    if skipped:
        print(f"not imported (reference table missing in {ref}): {skipped}")

    code = (
        "import importlib, sys\n"
        f"for m in {mods!r}:\n"
        "    try:\n"
        "        importlib.import_module(m)\n"
        "    except Exception as e:\n"
        "        print('IMPORT-ERROR', m, type(e).__name__, e)\n"
        "print('LOADED', ' '.join(sorted({k.split('.')[0] for k in sys.modules})))\n"
    )
    env = {**os.environ,
           "PYTHONPATH": os.pathsep.join(p for p in (str(SRC), os.environ.get("PYTHONPATH", "")) if p)}
    r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-2000:]
    errors = [ln for ln in r.stdout.splitlines() if ln.startswith("IMPORT-ERROR")]
    assert not errors, "\n".join(errors)
    loaded = set([ln for ln in r.stdout.splitlines() if ln.startswith("LOADED")][-1].split()[1:])
    assert not (loaded & FORBIDDEN), f"{PKG} imports {sorted(loaded & FORBIDDEN)}"
