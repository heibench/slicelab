"""D11's repository half: slicelab ships zero engine-written bytes.

``docs/DECISIONS.md`` D11 says slicelab ships nothing an engine produced, and
names this file as what pins it. The file did not exist, and the claim was
false: ``result.json`` -- an OrcaSlicer artifact, committed by accident in #17
-- sat tracked at the repository root for five commits.

The release workflow asserts the *packaging* half, and asserted it only over
the wheel. ``packages = ["slicelab"]`` means the wheel could never have carried
a root-level file, so that guard was green over a stray it structurally could
not see; the sdist did carry it. Both halves are checked now: the workflow
inspects the sdist too, and this file builds the sdist from the working tree
and checks what it holds.

**What the sdist actually takes is what hatchling does not *ignore*** -- not what
git tracks. An uncommitted ``result.json`` sitting in the working tree ships just
as surely as a committed one, and a rule about the index would have reported
green on the exact state that produced the incident. Asking git to emulate
hatchling's ignore rule was tried three times and diverged each time (#26), so
the file set is now the one hatchling actually produces.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tarfile
from collections.abc import Iterable
from pathlib import Path, PurePosixPath

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


def _build_sdist(project: Path, scratch: Path) -> tuple[list[str], Path]:
    """Build ``project``'s sdist with hatchling, unpack it, and list what it holds.

    Returns every regular file's path relative to the sdist's top directory, and
    the directory it was unpacked into, so a rule can judge the bytes that ship
    rather than the working-tree file they came from.

    **The sdist itself, not an emulation of it.** Three successive rules asked git
    to reproduce hatchling's ignore handling, and each closed the previous one's
    divergence while carrying its own (#23, #26). The last was
    ``git ls-files --cached --others --exclude-from=.gitignore``, which cannot see
    past a ``!`` re-include: hatchling applies the root ``.gitignore`` through
    ``pathspec.GitIgnoreSpec``, which can re-include a file under an excluded
    directory, and git never descends into one. Measured: with ``/ignoreddir/``
    and ``!/ignoreddir/result.json`` in the root ``.gitignore`` that rule listed
    nothing and the suite was green while ``uv build`` shipped the file. Building
    removes the class rather than the instance -- the list is hatchling's, so
    there is no rule left to diverge.

    The sdist, not the wheel, because it is the superset: ``packages =
    ["slicelab"]`` confines the wheel to the package, which the sdist also carries.
    The release workflow inspects both built artifacts.

    ``uv`` and not ``python -m build``, because uv is this repository's toolchain
    and ``build`` is not installed. Its absence in a checkout is a failure rather
    than a skip: a guard that quietly stops looking is the defect this file exists
    to refuse.
    """
    uv = shutil.which("uv")
    if uv is None:
        pytest.fail(
            "uv is not on PATH; this check builds the sdist with it (`just setup` needs it too)"
        )
    out = scratch / "dist"
    built = subprocess.run(
        [uv, "build", "--sdist", "--out-dir", str(out), str(project)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if built.returncode != 0:
        pytest.fail(f"`uv build --sdist` exited {built.returncode}:\n{built.stderr}")
    tarballs = sorted(out.glob("*.tar.gz"))
    assert len(tarballs) == 1, f"expected one sdist, found {tarballs}"

    unpacked = scratch / "unpacked"
    files: list[str] = []
    with tarfile.open(tarballs[0]) as tf:
        members = [m for m in tf.getmembers() if m.isfile()]
        tops = {PurePosixPath(m.name).parts[0] for m in members}
        assert len(tops) == 1, f"an sdist has one top directory, this one has {sorted(tops)}"
        for member in members:
            relative = PurePosixPath(*PurePosixPath(member.name).parts[1:])
            # Written by hand rather than with `extractall(filter="data")`, which
            # Python 3.11 only has from 3.11.4. The tarball is one this function
            # just built from our own tree; refusing `..` keeps a malformed one
            # from writing outside `scratch` all the same.
            assert ".." not in relative.parts and not relative.is_absolute(), member.name
            source = tf.extractfile(member)
            assert source is not None, member.name
            destination = unpacked / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(source.read())
            files.append(relative.as_posix())
    return sorted(files), unpacked


@pytest.fixture(scope="module")
def shipped(tmp_path_factory: pytest.TempPathFactory) -> tuple[list[str], Path]:
    """This repository's sdist, built once for the module: (paths, unpacked root)."""
    return _build_sdist(_ROOT, tmp_path_factory.mktemp("sdist"))


@pytest.fixture(scope="module", autouse=True)
def _needs_a_checkout() -> None:
    """Skip loudly outside a checkout rather than check an sdist of an sdist.

    This file ships in the sdist, so a distro packager or conda feedstock runs it
    from an unpacked tarball. The check is about what *this repository* is about to
    publish; from a published artifact there is nothing left to check, and the
    packager has no reason to have uv.
    """
    if not (_ROOT / ".git").exists():
        pytest.skip("not a git checkout (running from an sdist?); nothing to check here")


def test_the_sdist_lists_a_file_set_at_all(shipped: tuple[list[str], Path]) -> None:
    """A null result deserves the same evidence as a positive one.

    Without this, a build that unpacked nothing would make the assertions below
    pass over an empty list and report the strongest possible verdict having
    looked at nothing.
    """
    files, _ = shipped
    assert len(files) > 20, f"the sdist holds {len(files)} files; it was not read"
    assert "pyproject.toml" in files


def test_a_gitignore_negation_cannot_hide_a_file_that_ships(tmp_path: Path) -> None:
    """#26: the file set is hatchling's, so a ``!`` re-include is seen, not missed.

    The reproduction from the issue, in a project of its own so the real
    ``.gitignore`` is never edited. ``other.json`` is the control: it sits under
    the same excluded directory without a re-include, and must stay out -- or the
    assertion on ``result.json`` would pass over a build that ignored nothing.
    """
    project = tmp_path / "project"
    (project / "ignoreddir").mkdir(parents=True)
    (project / "pyproject.toml").write_text(
        '[build-system]\nrequires = ["hatchling"]\nbuild-backend = "hatchling.build"\n\n'
        '[project]\nname = "probe"\nversion = "0"\n',
        encoding="utf-8",
    )
    (project / ".gitignore").write_text(
        "/ignoreddir/\n!/ignoreddir/result.json\n", encoding="utf-8"
    )
    (project / "ignoreddir" / "result.json").write_text("{}\n", encoding="utf-8")
    (project / "ignoreddir" / "other.json").write_text("{}\n", encoding="utf-8")

    files, _ = _build_sdist(project, tmp_path / "build")

    assert "ignoreddir/other.json" not in files
    assert _engine_written_among(files) == ["ignoreddir/result.json"]


def _engine_written_among(candidates: Iterable[str]) -> list[str]:
    """The judging half of the format rule, separated so it can be tested.

    The content rule was given this split after a review found its production
    assertion had no red state -- it runs over a tree that is supposed to be clean.
    The format rule was marked unchanged in that round and inherited the identical
    defect: emptying `ENGINE_WRITTEN_SUFFIXES` left every test green, and that is
    the rule which catches the incident D11 is actually written about.
    """
    return sorted(c for c in candidates if Path(c).suffix.lower() in ENGINE_WRITTEN_SUFFIXES)


def test_nothing_an_engine_wrote_is_headed_for_the_sdist(shipped: tuple[list[str], Path]) -> None:
    files, _ = shipped
    strays = _engine_written_among(files)
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
        # utf-8-sig, because a BOM is the one evasion ordinary tooling produces
        # without being asked -- a Windows editor or a PowerShell redirection adds
        # one. It is a strict superset of utf-8 for files that do not have one.
        text = path.read_text(encoding="utf-8-sig")
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


def test_no_characterisation_map_is_headed_for_the_sdist(shipped: tuple[list[str], Path]) -> None:
    """D11 by content. The format rule matches on extension and cannot see this.

    The map committed as ``option_key_map.py``, ``.txt``, ``.csv`` or with no
    extension passes the suffix rule -- measured, it does -- so the thing D11 names
    most specifically was the one thing that rule could not catch.
    """
    strays = _maps_among(*shipped)
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


def test_the_scan_reddens_on_a_map_planted_in_the_real_tree(tmp_path: Path) -> None:
    """End to end, through a real sdist build rather than a fixture list.

    A red-capable judge does not prove the scan reaches the file. An untracked
    file ships just as surely as a committed one, and this is the only test that
    exercises that path against a real violation. It builds its own sdist, since
    the module's one was built before the file was planted.
    """
    planted = _ROOT / "slicelab" / "option-key-map.json"
    assert not planted.exists(), "the fixture path is already taken"
    try:
        planted.write_text(json.dumps(_real_document()), encoding="utf-8")
        files, unpacked = _build_sdist(_ROOT, tmp_path)
        assert "slicelab/option-key-map.json" in _maps_among(files, unpacked)
    finally:
        planted.unlink(missing_ok=True)


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


def test_the_detector_is_not_red_on_the_tests_that_name_its_fields(
    shipped: tuple[list[str], Path],
) -> None:
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
    assert "tests/test_characterise.py" in shipped[0]
    assert _maps_among(*shipped) == []


def test_the_map_is_written_outside_the_repository() -> None:
    """The structural half: the accident this guards against should not be possible.

    A content rule catches a map that reached the tree. This checks it has no
    ordinary route in -- `cache_path_for` resolves under XDG, and nothing under
    the repository root.
    """
    destination = cache_path_for(PRUSASLICER, "2.9.6").resolve()
    assert _ROOT.resolve() not in destination.parents
    assert "slicelab" in destination.parts


@pytest.mark.parametrize("name", ["result.json", "00000.log", "part.gcode", "out.bgcode"])
def test_the_format_rule_reddens_on_an_engine_written_file(name: str) -> None:
    """Red-capability of the rule that catches the incident D11 exists for.

    `result.json` is not hypothetical: it is how engine output reached this
    repository once already, and `00000.log` is the litter D20 and V13 are written
    about. Without this, emptying `ENGINE_WRITTEN_SUFFIXES` left the whole suite
    green -- a rule with no red state, guarding the original defect.
    """
    assert _engine_written_among([name]) == [name]


def test_the_format_rule_is_quiet_on_what_slicelab_authors() -> None:
    """A guard on the guard: a rule red on our own tree would be deleted, not fixed."""
    assert _engine_written_among(["pyproject.toml", "README.md", "slicelab/cli.py"]) == []


def test_the_format_vocabulary_is_not_empty() -> None:
    """An empty set makes every file pass, which reads exactly like a clean tree."""
    assert ENGINE_WRITTEN_SUFFIXES
    assert ".json" in ENGINE_WRITTEN_SUFFIXES
    assert ".gcode" in ENGINE_WRITTEN_SUFFIXES


def test_the_signature_is_not_empty() -> None:
    """`set(document) >= frozenset()` is True for every dict.

    So emptying `_MAP_SIGNATURE` degrades the detector to "any JSON object" and
    survives, because no tracked file is one. The direction is benign -- it
    over-broadens rather than opening a hole -- but an unpinned constant that reads
    as a tightening is worth refusing.
    """
    assert _MAP_SIGNATURE
    assert not _is_characterisation({"unrelated": 1})
