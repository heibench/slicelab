"""slicelab exports no public Python names, and that is a contract.

heibench AGENTS.md section 5: "The stable surface is the artifact and the exit
code, never the Python API." A package that quietly grows an importable surface
acquires a second, weaker interface that consumers pin to and that the
exit-code contract does not cover.

**Measured in a subprocess, deliberately.** Importing ``slicelab.cli`` binds
``cli`` as an attribute of the package, so an in-process ``dir(slicelab)``
reports whatever the rest of the suite happened to import first -- it would
report a growing surface as this project grows submodules, which is not the
claim. A fresh interpreter that imports only the package measures what a
consumer actually sees.
"""

from __future__ import annotations

import subprocess
import sys


def _fresh_interpreter(code: str) -> str:
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    return proc.stdout.strip()


def test_importing_slicelab_exposes_no_public_names() -> None:
    out = _fresh_interpreter(
        "import slicelab, json;"
        "print(json.dumps(sorted(n for n in dir(slicelab) if not n.startswith('_'))))"
    )
    assert out == "[]", (
        f"slicelab grew a public Python surface: {out}. Depend on the CLI and "
        "slice.lock, not on importable names (org AGENTS.md 5)."
    )


def test_version_is_the_one_exported_name() -> None:
    out = _fresh_interpreter("import slicelab; print(slicelab.__all__, slicelab.__version__)")
    assert out.startswith("['__version__'] ")
    assert out.split()[-1]


def test_importing_slicelab_pulls_in_no_submodules() -> None:
    """The package must stay cheap to import and must not front-load a CLI."""
    out = _fresh_interpreter(
        "import slicelab, sys;print(sorted(m for m in sys.modules if m.startswith('slicelab.')))"
    )
    assert out == "[]", f"importing slicelab dragged in submodules: {out}"
