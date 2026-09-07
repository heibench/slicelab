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
import os
import sys
from pathlib import Path

import pytest

from slicelab.adapters import EngineSpec
from slicelab.engine.discover import discover
from slicelab.engine.launch import _scratch, _scratch_roots, run

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
            if not entry.is_file():
                # Directories are deliberately skipped: a directory's mtime
                # bumps when anything is added inside it, so a download landing
                # mid-run would report `$HOME/Downloads` as engine litter and
                # name an engine for something no engine did. Every stray we
                # know of -- `result.json`, `00000.log` -- is a regular file at
                # the top level and is still caught. An engine that dropped a
                # DIRECTORY in `$HOME` would not be, which is a real gap and
                # not one any observed engine has walked into.
                continue
            stat = entry.stat()
        except OSError:  # vanished between listing and stat; not ours
            continue
        seen[entry.name] = (stat.st_mtime_ns, stat.st_size)
    return seen


@pytest.mark.parametrize(
    "xdg",
    [
        pytest.param(None, id="ambient-environment"),
        pytest.param("outside-home", id="xdg-cache-home-outside-home"),
    ],
)
def test_no_real_engine_writes_outside_the_directory_it_was_given(
    xdg: str | None,
    usable_engines: list[EngineSpec],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
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
    if xdg is not None:
        # The case a reviewer had to find by hand, because the suite only ever
        # ran in the ambient environment: an absolute XDG_CACHE_HOME pointing
        # OUTSIDE the home directory. The sandbox cannot translate such a path,
        # so it dropped the cwd and started the engine in $HOME -- at exit 0,
        # with every test green. `tmp_path` is under the system temp directory,
        # which is exactly the shape that broke it.
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / xdg))

    monkeypatch.chdir(tmp_path)
    home = Path.home()
    before = _fingerprint(home)

    launched = []
    for spec in usable_engines:
        found = discover(spec)
        assert found.form is not None, f"{spec.name} was reported usable but has no launch form"
        completed = run([*found.form.argv_prefix, "--help"])
        assert completed.exit_status is not None, f"{spec.name}: {completed}"
        launched.append(f"{spec.name} via {found.form.description}")
    # Named, not counted. Only OrcaSlicer litters, and only its Flatpak form is
    # sandbox-translated -- so a green here means very different things on the
    # Flatpak runner and on the macOS one, and a reader deserves to see which
    # without going to the workflow file to find out.
    assert launched, "no engine was launched, so this test established nothing"
    proof = "; ".join(launched)

    stray = [p.name for p in tmp_path.iterdir() if xdg is None or p.name != xdg]
    assert not stray, (
        f"an engine wrote into the caller's working directory: {sorted(stray)} -- launched {proof}"
    )
    after = _fingerprint(home)
    touched = sorted(name for name, mark in after.items() if before.get(name) != mark)
    assert not touched, (
        f"an engine wrote into $HOME instead of the directory it was given: "
        f"{touched} -- launched {proof}"
    )


@pytest.fixture
def fake_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A home directory the test owns, so the ladder can be walked safely."""
    home = tmp_path / "home"
    (home / ".cache").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    return home


def test_an_absolute_xdg_cache_home_inside_home_is_preferred(
    fake_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    xdg = fake_home / "xdg"
    monkeypatch.setenv("XDG_CACHE_HOME", str(xdg))
    assert _scratch_roots()[0] == xdg / "slicelab" / "engine-cwd"


def test_an_xdg_cache_home_outside_the_home_directory_is_not_offered(
    fake_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Absolute is not enough; it has to be somewhere a Flatpak can see.

    `XDG_CACHE_HOME=/var/cache/$USER` is an ordinary setting, and while only
    `is_absolute()` was checked it put `result.json` back in `$HOME` at exit 0:
    the sandbox cannot translate a path outside the home directory, so `bwrap`
    drops the cwd and starts the engine in `$HOME` instead. Measured with the
    real engine at `XDG_CACHE_HOME=/tmp/xdgprobe` -- 180 bytes, exit 0.
    """
    outside = tmp_path / "outside-home"
    monkeypatch.setenv("XDG_CACHE_HOME", str(outside))

    roots = _scratch_roots()

    assert all(fake_home in r.parents or r == fake_home for r in roots), (
        f"a scratch root outside the home directory was offered: {roots}"
    )
    assert roots[0] == fake_home / ".cache" / "slicelab" / "engine-cwd"


def test_a_symlink_out_of_the_home_directory_is_not_offered(
    fake_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Lexically inside `$HOME` and outside it by inode.

    A containment check on the string would accept this. Only `resolve()` can
    tell, which is why every candidate is resolved before it is judged.
    """
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    link = fake_home / "cache-link"
    link.symlink_to(outside)
    monkeypatch.setenv("XDG_CACHE_HOME", str(link))

    # Judged AFTER resolution, deliberately. Asking whether the returned path
    # is lexically under $HOME is the mistake this test exists to catch: the
    # symlink satisfies that and still lands the engine outside the sandbox's
    # reach. A test that judged the string would pass against the defect.
    landing = [r.resolve() for r in _scratch_roots()]

    assert landing, "the ladder offered nothing at all"
    assert all(fake_home in r.parents or r == fake_home for r in landing), (
        f"a symlink pointing out of the home directory was accepted: {landing}"
    )


def test_a_relative_xdg_cache_home_is_ignored_rather_than_resolved_against_cwd(
    fake_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The basedir spec says a relative value MUST be ignored. It was honoured.

    `mkdir(parents=True)` resolved it against the process working directory, so
    `XDG_CACHE_HOME=mycache slicelab which orcaslicer` created
    `./mycache/slicelab/engine-cwd` in the directory the user was standing in
    and ran the engine inside it -- the exact litter this whole mechanism
    exists to prevent, authored by slicelab rather than by the engine.
    """
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    monkeypatch.setenv("XDG_CACHE_HOME", "mycache")

    roots = _scratch_roots()

    assert roots, "the ladder offered nothing at all"
    assert all(r.is_absolute() for r in roots)
    assert not list(cwd.iterdir()), (
        f"a relative XDG_CACHE_HOME reached the working directory: "
        f"{sorted(p.name for p in cwd.iterdir())}"
    )


def test_a_relative_home_offers_nothing_rather_than_the_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`Path.home()` hands back `$HOME` verbatim, relative and all.

    The `XDG_CACHE_HOME` guard did not cover it, so `HOME=relhome slicelab
    which orcaslicer` created `./relhome/.cache/slicelab/engine-cwd` where the
    user was standing -- the same defect through the other variable. Resolving
    a relative home would anchor it to the working directory, which is the
    thing being prevented, so the honest answer is that there is no
    home-visible location at all.
    """
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: Path("relhome")))

    assert _scratch_roots() == []
    assert not list(cwd.iterdir()), (
        f"a relative HOME reached the working directory: {sorted(p.name for p in cwd.iterdir())}"
    )


def test_an_unusable_cache_directory_falls_back_inside_the_home_directory(
    fake_home: Path,
) -> None:
    """`except OSError: return None` sent this straight to `/tmp`.

    Under a Flatpak that means the engine starts in `$HOME`, so an ordinary
    stray file at `~/.cache/slicelab` reinstated the whole defect, at exit 0,
    on a host whose home and whose Flatpak were both healthy.
    """
    (fake_home / ".cache" / "slicelab").write_text("a file, where a directory is needed")

    with _scratch() as scratch:
        used = Path(scratch).resolve()

    assert fake_home in used.parents, f"scratch fell outside the home directory: {used}"


@pytest.mark.skipif(
    os.name == "nt",
    reason="chmod cannot make a directory unwritable on Windows, so the precondition "
    "is unbuildable; the descent itself is not POSIX-specific",
)
def test_a_root_that_exists_but_cannot_be_written_is_descended_past(
    fake_home: Path,
) -> None:
    """Existence is not usability, and `mkdir(exist_ok=True)` cannot tell them apart.

    It returns success on a directory that is already there and unwritable, so
    a ladder that only called `mkdir` settled on a root it could not use and
    let the `PermissionError` escape from the launch instead of descending.

    Skipped on Windows, where `os.chmod` only toggles a file's read-only flag
    and leaves directories writable -- so the unwritable root cannot be
    created, the ladder correctly uses it, and the assertion below fails on a
    precondition that was never established. CI found that; this change was
    verified only on Linux.
    """
    blocked = fake_home / ".cache" / "slicelab" / "engine-cwd"
    blocked.mkdir(parents=True)
    blocked.chmod(0o500)  # readable and traversable, not writable
    try:
        with _scratch() as scratch:
            used = Path(scratch).resolve()
    finally:
        blocked.chmod(0o700)

    assert fake_home in used.parents, f"scratch fell outside the home directory: {used}"
    assert blocked not in used.parents, "the unwritable root was used anyway"
