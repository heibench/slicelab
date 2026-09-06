"""slicelab -- a reproducible control plane over the Slic3r-descended slicers.

There is no stable Python API. The stable surface is the artifact and the exit
code (heibench AGENTS.md section 5), so this package exports exactly one name and
``tests/test_public_surface.py`` asserts it. Depend on the CLI and on
``slice.lock``; anything importable from here may move without notice.
"""

__version__ = "0.1.0.dev0"

__all__ = ["__version__"]
