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

import ast
import json
import re
import shutil
import subprocess
import tempfile
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


#: Above what slicelab writes, far below any engine's vocabulary.
#:
#: The smallest corpus D11 forbids is PrusaSlicer's 343 config keys; OrcaSlicer's
#: dump is 616 and the probed option map 342. What this project itself authors is
#: two orders of magnitude below that, so any threshold in the gap is arbitrary
#: only in the sense that the middle of a chasm is.
#:
#: The lower bound is deliberately NOT written down here. It moved from 8 to 22 the
#: first time a substantial module landed, which is what a count in prose beside a
#: growing tree does. ``test_the_threshold_keeps_headroom_over_what_we_write``
#: measures it instead, and fails when the gap closes rather than when a comment
#: goes stale -- as it did on its first run, which is why this is 60 and not the 40
#: originally guessed. 60 also catches a *partial* corpus: the 70 options with no
#: matching config key would ship under a threshold of 100.
CORPUS_THRESHOLD = 60

_KEYISH = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$")


def _snake_case_literals(path: Path) -> set[str]:
    """Distinct snake_case string literals in a file, whatever its extension.

    Read as source where it parses as Python, and as text otherwise, because the
    point is to catch a corpus regardless of the container someone chose for it.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return set()
    if path.suffix == ".py":
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return set()
        return {
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and _KEYISH.match(node.value)
        }
    return {
        m.group(1) for m in re.finditer(r'"([a-z][a-z0-9_]+)"', text) if _KEYISH.match(m.group(1))
    }


def test_no_corpus_of_engine_key_names_is_headed_for_the_sdist() -> None:
    """D11 by content, because the suffix rule alone does not pin what D11 claims.

    ``test_nothing_an_engine_wrote_is_headed_for_the_sdist`` matches on extension,
    so the characterisation map -- 342 option names and the config keys they write
    -- ships green as ``option_key_map.py``, ``.txt``, ``.csv``, or with no
    extension at all. D11 says it is "pinned by ``test_no_engine_data.py``"; until
    this test existed, that claim was larger than the file delivered.

    The two rules answer different questions and both are kept: the suffix rule
    catches an engine's *output format* landing in the tree (how ``result.json``
    arrived), and this one catches an engine's *vocabulary* landing in any format.
    """
    dense = {}
    for candidate in _sdist_candidates():
        path = _ROOT / candidate
        if not path.is_file():
            continue
        found = _snake_case_literals(path)
        if len(found) > CORPUS_THRESHOLD:
            dense[candidate] = len(found)
    assert not dense, (
        "these files carry a corpus of engine-shaped key names and would ship in "
        f"the sdist, which D11 forbids: {dense}. Generate it into the XDG cache "
        "instead, and gitignore it."
    )


def test_the_corpus_rule_catches_a_map_in_any_container() -> None:
    """Red-capability, proven against the containers the suffix rule misses.

    Org contract 2.4: a check whose red state you have not observed is not a check.
    This one's red state cannot be reached by breaking the tree, because the
    property under test is that the tree is clean -- so the detector is run against
    a corpus directly, in each format someone might reach for.
    """
    corpus = [f"config_key_{n}" for n in range(CORPUS_THRESHOLD + 10)]
    written = {
        "map.py": "KEYS = " + repr(corpus),
        "map.txt": "\n".join(f'"{k}"' for k in corpus),
        "map.csv": ",".join(f'"{k}"' for k in corpus),
        "option-key-map": json.dumps({k: [k] for k in corpus}),
    }
    with tempfile.TemporaryDirectory() as scratch:
        for name, body in written.items():
            path = Path(scratch) / name
            path.write_text(body, encoding="utf-8")
            found = _snake_case_literals(path)
            assert len(found) > CORPUS_THRESHOLD, f"{name} evaded the corpus rule"


def test_the_corpus_rule_is_not_red_on_what_slicelab_writes() -> None:
    """A guard on the guard: a rule red on our own source would be deleted, not fixed."""
    ours = _ROOT / "slicelab" / "status.py"
    assert ours.is_file()
    assert len(_snake_case_literals(ours)) <= CORPUS_THRESHOLD


def test_the_threshold_keeps_headroom_over_what_we_write() -> None:
    """The rule is only useful while our densest file is far below the line.

    Measured rather than asserted, because the number moves: it was 8 when this
    test was written and 22 one merge later. If slicelab ever legitimately authors
    a file near the threshold, this fails and the rule needs rethinking -- which is
    the honest failure, rather than a comment quietly describing a tree that has
    moved on.
    """
    densest = max(
        (
            (len(_snake_case_literals(_ROOT / c)), c)
            for c in _sdist_candidates()
            if (_ROOT / c).is_file()
        ),
        default=(0, "<none>"),
    )
    count, where = densest
    assert count * 2 <= CORPUS_THRESHOLD, (
        f"{where} carries {count} snake_case literals against a threshold of "
        f"{CORPUS_THRESHOLD}. The rule separates 'what we author' from 'a corpus' "
        "only while there is room between them."
    )
