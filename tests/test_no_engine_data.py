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

import json
import shutil
import subprocess
from collections.abc import Iterable
from pathlib import Path

import pytest

from slicelab.adapters import PRUSASLICER
from slicelab.engine.characterise import cache_path_for

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


#: The fields that identify a characterisation document and nothing else.
#:
#: Not a word list to grep for -- ``tests/test_characterise.py`` names every one of
#: these and must stay green. The rule below requires them to be **the keys of an
#: actual mapping**, which only the document itself satisfies.
_MAP_SIGNATURE = frozenset({"schema", "engine", "version", "entries"})


def _is_characterisation(document: object) -> bool:
    """Whether a parsed object is a characterisation map.

    The map is what D11 most specifically forbids shipping: an engine's option
    vocabulary, measured on someone's machine, written into XDG cache and
    gitignored. `cache_path_for` puts it outside the repository, and this is the
    check that the arrangement held.
    """
    return isinstance(document, dict) and set(document) >= _MAP_SIGNATURE


def _carries_a_map(path: Path) -> bool:
    """Whether a file's WHOLE CONTENT is a characterisation document.

    Whole-file, deliberately, and an earlier revision that also walked Python dict
    literals shows why: it flagged `slicelab/engine/characterise.py` -- the module
    that *writes* the document -- and this file's own fixture. A dict with those
    keys is how you construct a map, not how you ship one, so matching on the
    literal makes the rule red on every file that knows the shape.

    The container does not matter and the extension does not matter: the map is
    JSON, so `keys.txt`, `keys.csv` and an extension-free file all carry it
    identically, and all three pass the suffix rule.

    **A map deliberately re-encoded as a Python literal evades this**, and that is
    a stated bound rather than an oversight. The accident being guarded against is
    committing a generated file; `characterise` writes JSON to the XDG cache, so
    JSON is the form an accident takes. Re-encoding it is a deliberate act, and no
    content rule survives a determined author -- a base64 blob evades everything.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    try:
        return _is_characterisation(json.loads(text))
    except (json.JSONDecodeError, RecursionError):
        return False


def _maps_among(candidates: Iterable[str], root: Path) -> list[str]:
    """The judging half, separated from the scanning half so it can be tested.

    A previous revision asserted only over the real tree, which is supposed to be
    clean -- so the production rule had no red state and a threshold raised to
    10000 left every test green. Splitting the judge out is what makes the rule
    itself checkable.
    """
    return sorted(c for c in candidates if (p := root / c).is_file() and _carries_a_map(p))


def test_no_characterisation_map_is_headed_for_the_sdist() -> None:
    """D11 by content. The format rule matches on extension and cannot see this.

    The map committed as ``option_key_map.py``, ``.txt``, ``.csv`` or with no
    extension passes the suffix rule -- measured, it does -- so the thing D11 names
    most specifically was the one thing that rule could not catch.
    """
    strays = _maps_among(_sdist_candidates(), _ROOT)
    assert not strays, (
        "these files carry a characterisation map and would ship in the sdist, "
        f"which D11 forbids: {strays}. It belongs in the XDG cache, gitignored."
    )


def _real_document() -> dict[str, object]:
    """The document `_write_cache` writes, in miniature but in its real shape."""
    return {
        "schema": 3,
        "engine": "prusaslicer",
        "version": "2.9.6",
        "baseline_key_count": 343,
        "volatile_keys": [],
        "entries": {
            "perimeters": {
                "keys": ["perimeters"],
                "side_effects": [],
                "tracking": "exact",
                "outcome": "mapped",
            }
        },
        "inconclusive": 0,
    }


@pytest.mark.parametrize(
    "name",
    ["option-key-map.json", "keys.txt", "keys.csv", "option-key-map", "map.cache"],
)
def test_the_scan_reddens_on_a_planted_map_in_any_container(tmp_path: Path, name: str) -> None:
    """Red-capability of the production rule, through the same judge it uses.

    The containers are the ones the suffix rule misses. Only the first has an
    extension an engine writes; the rest are why a content rule had to exist.
    """
    (tmp_path / name).write_text(json.dumps(_real_document()), encoding="utf-8")
    assert _maps_among([name], tmp_path) == [name]


def test_the_scan_reddens_on_a_map_planted_in_the_real_tree() -> None:
    """End to end, through `_sdist_candidates` rather than a fixture list.

    A red-capable judge does not prove the scan reaches the file. An
    untracked-but-unignored file is exactly what `--others` is for, and this is the
    only test that exercises that path against a real violation.
    """
    planted = _ROOT / "slicelab" / "option-key-map.json"
    assert not planted.exists(), "the fixture path is already taken"
    planted.write_text(json.dumps(_real_document()), encoding="utf-8")
    try:
        assert "slicelab/option-key-map.json" in _maps_among(_sdist_candidates(), _ROOT)
    finally:
        planted.unlink()


def test_a_map_re_encoded_as_python_is_a_stated_bound_not_a_silent_one() -> None:
    """The limit, pinned so nobody closes it by reintroducing the false positives.

    Walking Python dict literals for the signature was tried and reverted: it made
    the rule red on `characterise.py`, the module that writes the document, and on
    this file's own fixture. Both are code that knows the shape rather than data
    that is one.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as scratch:
        path = Path(scratch) / "option_key_map.py"
        path.write_text("MAP = " + repr(_real_document()), encoding="utf-8")
        assert not _carries_a_map(path)


def test_the_detector_is_not_red_on_the_tests_that_name_its_fields() -> None:
    """A guard on the guard, and the reason this is a shape rule not a word list.

    ``tests/test_characterise.py`` names ``schema``, ``entries``,
    ``baseline_key_count`` and ``volatile_keys`` throughout, because it tests the
    thing that writes them. A rule that grepped for those words would be red on
    the suite that proves the map works, and would have been deleted rather than
    fixed.
    """
    named = _ROOT / "tests" / "test_characterise.py"
    assert named.is_file()
    assert not _carries_a_map(named)
    assert _maps_among(_sdist_candidates(), _ROOT) == []


def test_the_map_is_written_outside_the_repository() -> None:
    """The structural half: the accident this guards against should not be possible.

    A content rule catches a map that reached the tree. This checks it has no
    ordinary route in -- `cache_path_for` resolves under XDG, and nothing under
    the repository root.
    """
    destination = cache_path_for(PRUSASLICER, "2.9.6").resolve()
    assert _ROOT.resolve() not in destination.parents
    assert "slicelab" in destination.parts
