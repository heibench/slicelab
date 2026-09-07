"""Structural guarantees about where engine knowledge is allowed to live.

Org contract section 3: the engine leaks in through exactly one module, and
netspec calls that boundary its migration plan. slicelab drives more than one
engine, so the boundary is drawn twice -- one for the process, one for the
names.

These read source text rather than importing, because the claim is about what
the repository contains, not about what happens to be imported at runtime.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

from slicelab.adapters import EngineSpec
from slicelab.engine.discover import discover
from slicelab.engine.launch import run

PACKAGE = Path(__file__).resolve().parent.parent / "slicelab"

#: The one module allowed to spawn a process.
SUBPROCESS_OWNER = PACKAGE / "engine" / "launch.py"


def _modules() -> list[Path]:
    return sorted(p for p in PACKAGE.rglob("*.py"))


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


def test_only_launch_may_import_subprocess() -> None:
    offenders = [
        str(path.relative_to(PACKAGE))
        for path in _modules()
        if path != SUBPROCESS_OWNER and "subprocess" in _imports(path)
    ]
    assert offenders == [], (
        f"subprocess imported outside engine/launch.py: {offenders}. "
        "Every engine invocation goes through launch.run, or the decisions it "
        "makes -- stdin=DEVNULL, errors='replace', the signal split, the "
        "timeout -- are decided again, differently, somewhere else."
    )


def test_the_subprocess_owner_actually_owns_it() -> None:
    """Guard against the test above passing because nothing spawns anything."""
    assert "subprocess" in _imports(SUBPROCESS_OWNER)


def test_engine_names_appear_only_in_adapters() -> None:
    """No engine-specific identifier outside slicelab/adapters/.

    Scoped to engine IDENTIFIERS -- application ids and executable names -- not
    to every string. A blanket "no engine word anywhere" assertion is red on
    day one, because `output`, `load`, `save` and `info` are simultaneously
    engine option names and ordinary English.

    This is the test that has no red state until a second engine exists, which
    is why the Orca adapter is in v0.1.0 rather than deferred (D1).
    """
    from slicelab.adapters import REGISTRY

    identifiers = set()
    for spec in REGISTRY.values():
        identifiers.update({spec.posix_exec, spec.windows_exec})
        if spec.flatpak_app_id:
            identifiers.add(spec.flatpak_app_id)

    adapters = PACKAGE / "adapters"
    offenders: list[str] = []
    for path in _modules():
        if adapters in path.parents:
            continue
        text = path.read_text(encoding="utf-8")
        for identifier in identifiers:
            if identifier in text:
                offenders.append(f"{path.relative_to(PACKAGE)} names {identifier!r}")
    assert offenders == [], "engine identifiers escaped slicelab/adapters/: " + "; ".join(offenders)


def test_that_boundary_test_has_something_to_find() -> None:
    """The identifier list must be non-empty, or the check above is vacuous."""
    from slicelab.adapters import REGISTRY

    assert len(REGISTRY) >= 2, "the names boundary has no red state with one engine"
    assert all(spec.flatpak_app_id for spec in REGISTRY.values())


def test_an_engine_never_runs_in_the_directory_the_user_invoked_from(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``run`` with no ``cwd`` must not spawn into the caller's directory.

    OrcaSlicer writes ``result.json`` into its process working directory, so
    while ``run`` defaulted to ``cwd=None`` every verb littered wherever the
    user happened to be standing. Measured with a real engine: ``slicelab which
    orcaslicer`` in an empty directory left a 180-byte ``result.json`` at exit
    0, and an identical file was committed to this repository's root (D11).

    A stand-in process is used rather than an engine so the guarantee is
    checked on every runner, including the ones with no slicer installed --
    the property is about ``run``, not about any engine's behaviour.
    """
    monkeypatch.chdir(tmp_path)
    completed = run([sys.executable, "-c", "open('litter.txt', 'w').write('engine was here')"])

    assert completed.exit_status == 0, f"the stand-in did not run: {completed}"
    assert not (tmp_path / "litter.txt").exists(), (
        "the spawned process wrote into the caller's working directory; "
        f"left behind: {sorted(p.name for p in tmp_path.iterdir())}"
    )


def test_a_caller_that_owns_a_directory_still_gets_the_output_there(tmp_path: Path) -> None:
    """The other half: scratching by default must not make litter unreachable.

    The slice verb has to read what the engine dropped. Without this, the fix
    above could be "discard the working directory entirely" and pass, which
    would silently break the one caller that needs it.
    """
    completed = run(
        [sys.executable, "-c", "open('artifact.txt', 'w').write('kept')"],
        cwd=tmp_path,
    )

    assert completed.exit_status == 0, f"the stand-in did not run: {completed}"
    assert (tmp_path / "artifact.txt").read_text() == "kept"


def _fingerprint(directory: Path) -> dict[str, tuple[int, int]]:
    """Name -> (mtime_ns, size) for the visible entries of a directory.

    Names alone are not enough, and finding that out cost a round: the
    session-scoped engine fixture runs discovery, which launches the engine,
    which -- while the defect was present -- had *already* written
    ``$HOME/result.json`` before the test body took its "before" snapshot. The
    test body then merely overwrote it, and a set difference of names reported
    nothing. The test passed against the exact build it was written to catch.

    Dot-entries are skipped. `~/.cache` and `~/.config` churn constantly for
    reasons that have nothing to do with slicelab, and engine litter --
    ``result.json``, ``00000.log`` -- is never hidden.
    """
    seen = {}
    for entry in directory.iterdir():
        if entry.name.startswith("."):
            continue
        try:
            stat = entry.stat()
        except OSError:  # vanished between listing and stat; not ours
            continue
        seen[entry.name] = (stat.st_mtime_ns, stat.st_size)
    return seen


def test_no_real_engine_writes_outside_the_directory_it_was_given(
    usable_engines: list[EngineSpec], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The guarantee the two tests above cannot see, checked against real engines.

    A `sys.executable` stand-in honours `cwd` by construction. A Flatpak does
    not: its sandbox has its own `/tmp`, so a host `/tmp` cwd is dropped and the
    process starts in `$HOME` instead. The first version of the cwd fix used
    `tempfile`'s default and therefore moved the litter from the caller's
    directory to the user's home directory, while both stand-in tests stayed
    green -- the founding rule inverted, on the very change that was meant to
    honour it.

    So this launches every believable engine on the host and watches two
    directories, not one. It is engine-gated: `SLICELAB_REQUIRE_ENGINE=1` turns
    a missing engine into a failure, which is how `engine.yml`'s Flatpak job
    makes this bite.
    """
    monkeypatch.chdir(tmp_path)
    home = Path.home()
    before = _fingerprint(home)

    launched = 0
    for spec in usable_engines:
        found = discover(spec)
        assert found.form is not None, f"{spec.name} was reported usable but has no launch form"
        completed = run([*found.form.argv_prefix, "--help"])
        assert completed.exit_status is not None, f"{spec.name}: {completed}"
        launched += 1
    assert launched, "no engine was launched, so this test established nothing"

    assert not list(tmp_path.iterdir()), (
        "an engine wrote into the caller's working directory: "
        f"{sorted(p.name for p in tmp_path.iterdir())}"
    )
    after = _fingerprint(home)
    touched = sorted(name for name, mark in after.items() if before.get(name) != mark)
    assert not touched, (
        f"an engine wrote into $HOME instead of the directory it was given: {touched}"
    )
