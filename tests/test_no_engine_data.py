"""D11's repository half: slicelab tracks zero engine-written bytes.

``docs/DECISIONS.md`` D11 says slicelab ships nothing an engine produced, and
names this file as what pins it. The file did not exist, and the claim was
false: ``result.json`` -- an OrcaSlicer slice-data artifact, committed by
accident in #17 -- sat tracked at the repository root for four commits.

The release workflow asserts the *packaging* half, and asserted it only over
the wheel. ``packages = ["slicelab"]`` means the wheel could never have carried
a root-level file, so that guard was green over a stray it structurally could
not see; the sdist, which takes everything git tracks, did carry it. Both
halves are now checked: the workflow inspects the sdist too, and this file
checks the tree the sdist is built from.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent

#: Formats an engine writes and slicelab authors none of. A tracked file with
#: one of these suffixes is engine output that escaped into the repository --
#: which is exactly how ``result.json`` arrived. Should slicelab ever need to
#: author one of its own (a JSON schema, say), narrow the rule to the paths
#: rather than deleting it: D11 is about provenance, not about extensions.
ENGINE_WRITTEN_SUFFIXES = frozenset(
    {".json", ".ini", ".gcode", ".bgcode", ".3mf", ".stl", ".obj", ".amf", ".step"}
)


def _tracked() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [line for line in out.splitlines() if line]


def test_git_reports_a_tracked_tree_at_all() -> None:
    """A null result deserves the same evidence as a positive one.

    Without this, a `git ls-files` that returned nothing -- wrong directory, no
    git, an export with no repository -- would make every assertion below pass
    over an empty list and report the strongest possible verdict having looked
    at nothing.
    """
    tracked = _tracked()
    assert len(tracked) > 20, f"git ls-files returned {len(tracked)} paths; it was not read"
    assert "pyproject.toml" in tracked


def test_no_engine_written_artifact_is_tracked() -> None:
    strays = sorted(p for p in _tracked() if Path(p).suffix.lower() in ENGINE_WRITTEN_SUFFIXES)
    assert not strays, (
        "these tracked files are in formats an engine writes and slicelab does "
        f"not author, which D11 forbids shipping: {strays}"
    )
