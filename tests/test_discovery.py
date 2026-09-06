"""Discovery, and the claim that makes it worth having.

The unit tests here use fake launchers, because the behaviour being asserted --
"discard any form that returns 0 for a flag it rejects" -- must hold on hosts
with no slicer at all. The engine tests below then confirm the same logic
against real installed engines.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from slicelab.adapters import REGISTRY, EngineSpec
from slicelab.engine.discover import (
    INVALID_FLAG,
    ExitFidelity,
    LaunchKind,
    discover,
)
from slicelab.engine.identity import identify


def _fake_engine(
    directory: Path,
    stem: str,
    *,
    help_output: str | None,
    help_rc: int = 0,
    other_rc: int = 1,
) -> str:
    """Create a fake engine and return the name discovery should look for.

    Written for both platforms rather than skipped on Windows. These tests
    assert the discovery LOGIC -- discard a launcher whose exit status carries
    no information -- and that logic has to hold everywhere slicelab runs. The
    Windows job is also the only native (non-Flatpak) control this project has,
    so it is the last job that should be quietly opted out of.

    A POSIX shell script is invisible to ``shutil.which`` on Windows: no
    extension in PATHEXT and no usable shebang. So each platform gets the
    script kind it can actually execute.
    """
    if os.name == "nt":
        name = f"{stem}.cmd"
        echo = f"    echo {help_output}\n" if help_output else ""
        body = (
            f'@echo off\nif "%~1"=="--help" (\n{echo}    exit /b {help_rc}\n)\nexit /b {other_rc}\n'
        )
        (directory / name).write_text(body, encoding="ascii", newline="\r\n")
        return name

    name = stem
    echo = f"  echo '{help_output}'\n" if help_output else ""
    body = f'#!/bin/sh\nif [ "$1" = --help ]; then\n{echo}  exit {help_rc}\nfi\nexit {other_rc}\n'
    path = directory / name
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return name


@pytest.fixture
def on_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("PATH", str(tmp_path))
    return tmp_path


def test_an_engine_that_returns_zero_for_everything_is_unusable(
    on_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The V10 defect, in miniature.

    PrusaSlicer's Flathub entrypoint backgrounds its child and therefore
    returns 0 for every invocation. A launcher like that makes every subsequent
    verdict meaningless, so discovery must refuse it rather than adopt it.
    """
    name = _fake_engine(on_path, "always-fine", help_output="AlwaysFine-1.0.0", other_rc=0)
    spec = EngineSpec("fake", name, name, None)

    found = discover(spec, timeout=20)

    assert found.form is None
    assert found.fidelity is ExitFidelity.UNUSABLE
    assert found.rejected, "the rejection must be reported, not merely acted on"
    assert "carries no information" in found.rejected[0][1]


def test_an_engine_that_rejects_a_bad_flag_is_usable(on_path: Path) -> None:
    name = _fake_engine(on_path, "honest", help_output="Honest-3.2.1")
    spec = EngineSpec("fake", name, name, None)

    found = discover(spec, timeout=20)

    assert found.fidelity is ExitFidelity.ESTABLISHED
    assert found.form is not None
    assert found.form.kind is LaunchKind.PATH


def test_an_absent_engine_is_absent_not_unusable(on_path: Path) -> None:
    """The two are different environment faults and must stay distinguishable.

    "Not installed" and "installed but undriveable" call for different actions.
    """
    spec = EngineSpec("fake", "nothing-here-at-all", "nothing.exe", None)

    found = discover(spec, timeout=20)

    assert found.fidelity is ExitFidelity.ABSENT
    assert found.form is None


def test_the_probe_flag_is_one_no_engine_would_accept() -> None:
    assert INVALID_FLAG.startswith("--")
    assert "slicelab" in INVALID_FLAG


def test_identity_of_an_absent_engine_is_not_exact(on_path: Path) -> None:
    """A version we could not read must never report as one we could.

    Same shape as orlab's ``profile_exact`` -- silence.html case 3.
    """
    spec = EngineSpec("fake", "nothing-here-at-all", "nothing.exe", None)
    who = identify(spec, discover(spec, timeout=20), timeout=20)

    assert who.exact is False
    assert who.version is None


def test_a_version_that_cannot_be_parsed_is_not_exact(on_path: Path) -> None:
    """An engine that runs but says nothing recognisable is inexact, not wrong."""
    name = _fake_engine(on_path, "mute", help_output="no version here")
    spec = EngineSpec("fake", name, name, None)
    found = discover(spec, timeout=20)
    who = identify(spec, found, timeout=20)

    assert found.fidelity is ExitFidelity.ESTABLISHED
    assert who.exact is False


# --- engine-dependent ---------------------------------------------------------


def test_a_real_engine_is_discovered_and_identified(any_engine: EngineSpec) -> None:
    found = discover(any_engine)
    assert found.fidelity is ExitFidelity.ESTABLISHED
    who = identify(any_engine, found)
    assert who.exact, f"could not read a version from {any_engine.name}: {who.banner!r}"
    assert who.version and who.version[0].isdigit()


def test_a_real_engine_reports_what_it_rejected(any_engine: EngineSpec) -> None:
    """Whichever form wins, the reasoning must be inspectable.

    On this project's development host PrusaSlicer's default Flatpak entrypoint
    is rejected and the --command= bypass wins, while OrcaSlicer keeps its
    entrypoint. Both are correct, and the record of why is the point.
    """
    found = discover(any_engine)
    assert found.reason
    for _form, why in found.rejected:
        assert why


@pytest.mark.parametrize("name", sorted(REGISTRY))
def test_every_known_engine_can_at_least_be_looked_for(name: str) -> None:
    """Discovery must answer for an engine that is not installed, not raise."""
    spec = REGISTRY[name]
    found = discover(spec, timeout=30)
    assert found.fidelity in set(ExitFidelity)
    assert found.engine == name


@pytest.mark.skipif(os.name == "nt", reason="POSIX signal semantics")
def test_signal_death_is_reported_separately_from_an_exit_status(tmp_path: Path) -> None:
    """D15: a process killed by a signal has no exit status.

    Python's single negative returncode conflates the two, so a caller cannot
    tell exit 11 from signal 11. V6 is a real engine that dies this way with
    zero bytes on both streams.
    """
    from slicelab.engine.launch import run

    path = tmp_path / "crasher"
    path.write_text("#!/bin/sh\nkill -SEGV $$\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    completed = run([str(path)], timeout=20)

    assert completed.died_by_signal
    assert completed.signal == 11
    assert completed.exit_status is None
    assert completed.is_silent


def test_a_launcher_that_never_reaches_the_engine_is_not_established(
    on_path: Path,
) -> None:
    """The defect this project's own discovery shipped with, for one revision.

    A launcher that fails BEFORE the engine starts also exits non-zero. A probe
    that only asked "did it reject a bad flag?" read that as "the engine's exit
    status can be believed" -- concluding an engine was driveable from a run
    where it never ran.

    Observed for real: with an unwritable HOME, `flatpak run` exits non-zero
    with "mkdirat: Permission denied" having started nothing, and discovery
    called that exit fidelity established.

    Discovery now asks the engine to identify itself first. An engine that
    cannot answer a request for its own help is not one we are talking to,
    whatever its exit codes look like.
    """
    name = _fake_engine(on_path, "broken-launcher", help_output=None, help_rc=3, other_rc=3)
    spec = EngineSpec("fake", name, name, None)

    found = discover(spec, timeout=20)

    assert found.fidelity is ExitFidelity.UNUSABLE, (
        "a launcher that fails before the engine starts must not be reported "
        "as an engine whose exit status can be believed"
    )
    assert found.rejected
    assert "did not reach the engine" in found.rejected[0][1]
