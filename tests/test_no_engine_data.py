"""D11's repository half: slicelab ships zero engine-written bytes.

``docs/DECISIONS.md`` D11 says slicelab ships nothing an engine produced, and
names this file as what pins it. The file did not exist, and the claim was
false: ``result.json`` -- an OrcaSlicer artifact, committed by accident in #17
-- sat tracked at the repository root for five commits.

The release workflow asserts the *packaging* half, and asserted it only over
the wheel. ``packages = ["slicelab"]`` means the wheel could never have carried
a root-level file, so that guard was green over a stray it structurally could
not see; the sdist did carry it. Both halves are checked now: the workflow
inspects the sdist too, and this file checks the tree the sdist is built from.

**What the sdist actually takes is what git does not *ignore*** -- not what git
tracks. So does this. An uncommitted ``result.json`` sitting in the working
tree ships just as surely as a committed one, and a rule about the index would
have reported green on the exact state that produced the incident.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent

#: Formats an engine writes and slicelab authors none of. A file with one of
#: these suffixes headed for the sdist is engine output that escaped into the
#: repository -- which is exactly how ``result.json`` arrived. ``.log`` is here
#: for ``00000.log``, the litter D20 and V13 are written about. Should slicelab
#: ever need to author one of its own (a JSON schema, say), narrow the rule to
#: the paths rather than deleting it: D11 is about provenance, not extensions.
ENGINE_WRITTEN_SUFFIXES = frozenset(
    {".json", ".ini", ".gcode", ".bgcode", ".log", ".3mf", ".stl", ".obj", ".amf", ".step"}
)


def _sdist_candidates() -> list[str]:
    """Every path hatchling would put in an sdist: tracked plus unignored.

    ``--others`` is the untracked-but-not-ignored half, and it is the half that
    matters -- a stray file is a defect before it is committed, not after.

    ``--exclude-from=.gitignore``, deliberately, and neither of the two obvious
    alternatives. Hatchling reads **exactly one** ignore file --- the
    ``.gitignore`` at the project root --- so that is what this has to read.

    * ``--exclude-standard`` additionally honours the user's global
      ``core.excludesFile`` and ``.git/info/exclude``. With ``*.log`` in a
      personal global gitignore, one of the most common entries anyone has, a
      stray file is invisible here and ships anyway. That matters precisely
      because ``.log`` is in the vocabulary below, for ``00000.log``.
    * ``--exclude-per-directory=.gitignore`` fixes those two and introduces a
      third: it reads *nested* ``.gitignore`` files, which hatchling does not.
      A ``result.json`` under a subdirectory whose own ``.gitignore`` covers it
      is then invisible here and ships anyway.

    Measured against real sdists in all three of those cases plus a
    force-added tracked artifact: this flag agrees with what hatchling shipped
    every time.

    **One divergence remains, in the unsafe direction.** Hatchling applies those
    lines through ``pathspec.GitIgnoreSpec``, which — unlike git — can
    re-include a file whose parent directory is excluded. Measured: with
    ``/ignoreddir/`` and ``!/ignoreddir/result.json`` in the root
    ``.gitignore``, hatchling ships ``ignoreddir/result.json`` and this rule
    does not report it. The root ``.gitignore`` has no negation patterns today,
    so it is inert; anyone adding one should know this guard stops seeing past
    it, and that the release workflow — which reads the built tarball — is the
    backstop.
    """
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-from=.gitignore"],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [line for line in out.splitlines() if line]


@pytest.fixture(scope="module", autouse=True)
def _needs_a_checkout() -> None:
    """Skip loudly outside a git checkout rather than failing with a traceback.

    This file ships in the sdist, so a distro packager or conda feedstock runs
    it from an unpacked tarball with no ``.git`` and no reason to have git
    installed. ``git ls-files`` there exits 128, and a `check=True` traceback
    would tell them neither the cause nor the requirement. The check is about
    what *this repository* is about to publish; from a published artifact there
    is nothing left to check.
    """
    if shutil.which("git") is None:
        pytest.skip("git is not installed; this check reads the repository's own file list")
    if not (_ROOT / ".git").exists():
        pytest.skip("not a git checkout (running from an sdist?); nothing to check here")
    if not (_ROOT / ".gitignore").exists():
        # `--exclude-from` on a missing file is `fatal:` and exit 128, which
        # `check=True` turns into a CalledProcessError traceback naming neither
        # the cause nor the requirement. Only reachable if someone deletes a
        # tracked file, but that is exactly when a legible message is wanted.
        pytest.skip(".gitignore is missing, so hatchling's ignore rule cannot be reproduced")


def test_git_reports_a_file_list_at_all() -> None:
    """A null result deserves the same evidence as a positive one.

    Without this, a `git ls-files` that returned nothing would make the
    assertion below pass over an empty list and report the strongest possible
    verdict having looked at nothing.
    """
    candidates = _sdist_candidates()
    assert len(candidates) > 20, f"git listed {len(candidates)} paths; it was not read"
    assert "pyproject.toml" in candidates


def test_nothing_an_engine_wrote_is_headed_for_the_sdist() -> None:
    strays = sorted(
        p for p in _sdist_candidates() if Path(p).suffix.lower() in ENGINE_WRITTEN_SUFFIXES
    )
    assert not strays, (
        "these files would ship in the sdist, in formats an engine writes and "
        f"slicelab does not author, which D11 forbids: {strays}"
    )
