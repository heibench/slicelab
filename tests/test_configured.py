"""Establishing that an engine has no configuration, and never guessing it.

A fresh install answers `presets` with an error on stdout where JSON was expected.
slicelab called that `incomplete` (2) -- *could not tell* -- when it can tell, and the
answer is specific: installed, never configured. That is org contract 2.2's shape, and
exit 4 is the code a CI job can branch on (D29).

The hazard being guarded is the other direction. Reporting "not configured" because
slicelab does not know where this engine keeps its configuration would put a guess
behind the exit code reserved for established facts (org 2.3), so an undeclared
platform must answer `UNDETERMINED` and change nothing.
"""

from __future__ import annotations

import os
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from slicelab.adapters import ORCASLICER, PRUSASLICER
from slicelab.adapters.base import ConfigLocation
from slicelab.engine.configured import (
    ConfigState,
    configuration_state,
    where_configuration_should_be,
)
from slicelab.engine.discover import Discovery, ExitFidelity, LaunchForm, LaunchKind


def _found(kind: LaunchKind = LaunchKind.FLATPAK) -> Discovery:
    return Discovery(
        engine="prusaslicer",
        form=LaunchForm(kind=kind, argv_prefix=["x"], description="a stub"),
        fidelity=ExitFidelity.ESTABLISHED,
        reason="stubbed",
    )


def test_a_named_datadir_holding_a_configuration_is_present(tmp_path: Path) -> None:
    (tmp_path / "PrusaSlicer.ini").write_text("[x]\n", encoding="utf-8")
    assert configuration_state(PRUSASLICER, _found(), datadir=str(tmp_path)) is ConfigState.PRESENT


def test_a_named_datadir_without_one_is_absent(tmp_path: Path) -> None:
    """The finding. An empty directory is not a configuration."""
    assert configuration_state(PRUSASLICER, _found(), datadir=str(tmp_path)) is ConfigState.ABSENT


def test_the_directory_existing_is_not_the_question(tmp_path: Path) -> None:
    """The Flatpak runtime creates a config directory before the engine ever runs.

    Testing for the directory rather than the marker would report every fresh Flatpak
    install as configured, which is the defect this check exists to catch, inverted.
    """
    (tmp_path / "cache").mkdir()
    assert configuration_state(PRUSASLICER, _found(), datadir=str(tmp_path)) is ConfigState.ABSENT


def test_an_engine_with_no_declared_location_is_never_reported_absent(tmp_path: Path) -> None:
    """org 2.3: not knowing where to look is not the same as looking and finding none.

    This is the assertion that keeps the exit code honest. Without it, adding the
    check would turn every engine nobody has measured into a permanent exit 4.
    """
    unmeasured = replace(PRUSASLICER, config_location=None)
    assert configuration_state(unmeasured, _found(), datadir=str(tmp_path)) is (
        ConfigState.UNDETERMINED
    )
    assert where_configuration_should_be(unmeasured, _found()) is None


def test_a_platform_the_adapter_has_not_measured_is_undetermined() -> None:
    """Declaring the Flatpak path says nothing about where a PATH install looks."""
    flatpak_only = replace(
        PRUSASLICER, config_location=ConfigLocation(marker="PrusaSlicer.ini", flatpak="PrusaSlicer")
    )
    assert where_configuration_should_be(flatpak_only, _found(LaunchKind.PATH)) is None
    assert configuration_state(flatpak_only, _found(LaunchKind.PATH)) is ConfigState.UNDETERMINED


def test_an_empty_datadir_override_is_left_to_the_engine() -> None:
    """`--datadir ''` is a request slicelab cannot honour, and the engine says so."""
    assert configuration_state(PRUSASLICER, _found(), datadir="") is ConfigState.UNDETERMINED


def test_a_datadir_whose_home_cannot_be_resolved_establishes_nothing() -> None:
    """A path slicelab cannot resolve is not a finding about configuration.

    Only reachable where `expanduser` actually refuses. POSIX raises `RuntimeError`
    for a `~user` it cannot look up; Windows expands the same string to a plausible
    path under the profile root and raises nothing, so there is no unresolvable input
    to feed the branch and the run takes the ordinary "named a directory that is not
    there" route instead. Asserting the POSIX answer unconditionally reddened the
    Windows leg, which is the leg that exists to catch exactly this.
    """
    unresolvable = "~nosuchuser99/x"
    try:
        Path(unresolvable).expanduser()
    except (RuntimeError, ValueError):
        pass
    else:
        pytest.skip(
            f"{sys.platform} resolves {unresolvable!r} without raising, so this "
            "branch cannot be reached here"
        )
    assert (
        configuration_state(PRUSASLICER, _found(), datadir=unresolvable) is ConfigState.UNDETERMINED
    )


def test_the_directory_reported_is_the_directory_checked(tmp_path: Path) -> None:
    """These came from two code paths once, so the error named a place nobody looked."""
    assert where_configuration_should_be(PRUSASLICER, _found(), datadir=str(tmp_path)) == tmp_path


@pytest.mark.parametrize("spec", [PRUSASLICER, ORCASLICER])
def test_each_adapter_declares_where_its_flatpak_keeps_configuration(spec: object) -> None:
    """Both are installed as Flatpaks here, so both were measurable and are declared."""
    location = spec.config_location  # type: ignore[attr-defined]
    assert location is not None, f"{spec.name} declares no config location"  # type: ignore[attr-defined]
    assert location.flatpak, "the Flatpak location is the one that was measurable here"
    assert location.marker.endswith((".ini", ".conf")), location.marker


def test_resolve_refuses_an_unconfigured_engine_too(tmp_path: Path, monkeypatch) -> None:
    """D29's whole reason for existing: the two verbs must not disagree.

    `presets`'s copy of this check is covered; `resolve`'s was not. Mutating it to
    `if False:` left the entire suite green, so the clause existed and nothing held it
    there -- which is how the two verbs came to disagree in the first place, the
    condition #19 was filed to prevent.

    In-process and engine-free: the check sits above `_name_map`, so stubbing
    discovery is enough to reach it and no slicer is needed. That matters because
    every CI runner is without one.
    """
    from slicelab import resolve as resolve_module
    from slicelab.resolve import ResolveError

    monkeypatch.setattr(resolve_module, "discover", lambda _spec: _found())
    empty = tmp_path / "datadir"
    empty.mkdir()
    monkeypatch.setattr(
        resolve_module,
        "configuration_state",
        lambda _spec, _found: ConfigState.ABSENT,
    )
    intent = tmp_path / "slice.toml"
    intent.write_text(
        "[prusaslicer.base]\n"
        'printer-profile = "Original Prusa i3 MK3S & MK3S+"\n'
        'print-profile = "0.20mm QUALITY @MK3"\n'
        'material-profile = "Prusament PLA"\n',
        encoding="utf-8",
    )

    with pytest.raises(ResolveError, match="installed but not configured"):
        resolve_module.resolve(intent, tmp_path / "out.ini")


def test_a_directory_slicelab_cannot_read_is_not_reported_as_unconfigured(
    tmp_path: Path,
) -> None:
    """The dangerous direction: a fabricated environment fault about a working machine.

    `Path.is_file()` became `os.path.isfile` in CPython 3.14, which swallows every
    `OSError` and answers False. So a datadir that IS configured but that slicelab
    cannot traverse read as `absent`, and the verb told the author to configure an
    engine that already was. Measured: 3.11, 3.12 and 3.13 raise `PermissionError`
    there and 3.14 does not, while `requires-python` admits all four.

    On 3.11-3.13 this test passes whether the fix is present or not: `is_file()` raises
    `PermissionError`, the `OSError` guard converts it to `UNDETERMINED`, and that is
    the right answer by a different route. So the interpreter is half the test, and the
    CI matrix had to grow `3.14` for the gate to be able to see the defect at all --
    it stopped at 3.13, which is why this shipped untested twice.

    Both halves are pinned, because either reinstates it: reverting to `is_file()`, and
    turning the `OSError` guard into `ABSENT`.
    """
    datadir = tmp_path / "configured-but-unreadable"
    datadir.mkdir()
    (datadir / "PrusaSlicer.ini").write_text("[x]\n", encoding="utf-8")
    datadir.chmod(0o000)
    try:
        if os.access(datadir / "PrusaSlicer.ini", os.R_OK):  # pragma: no cover - root
            pytest.skip("this user can read inside a mode-000 directory")
        assert (
            configuration_state(PRUSASLICER, _found(), datadir=str(datadir))
            is ConfigState.UNDETERMINED
        ), "a directory slicelab cannot read was reported as an unconfigured engine"
    finally:
        datadir.chmod(0o700)


def test_a_relative_xdg_config_home_is_ignored(monkeypatch) -> None:
    """The basedir spec says a relative `XDG_CONFIG_HOME` "MUST be ignored".

    Unreachable today: no adapter declares an `xdg` location, so the branch returns
    before the environment is read. It is tested anyway because this change invites
    contributors to fill those fields in for a PATH install, and the guard would then
    be load-bearing on the first host with a relative value set — looking for the
    engine's configuration wherever the user happened to be standing, which is the
    defect `launch._scratch_roots` is written about.

    `launch` and `characterise` each have the same guard and each test it; this is the
    third place that reads an XDG variable and the only one that did not.

    POSIX only, and the second platform assumption this change shipped -- the first
    was a `~user` input that raises on POSIX and expands silently on Windows. The
    dispatch in `where_configuration_should_be` is by launch form and then platform,
    so on win32 the APPDATA branch answers before XDG is ever read.
    """
    if sys.platform == "win32":
        pytest.skip(
            "the XDG branch is unreachable on win32: `where_configuration_should_be` "
            "dispatches to the APPDATA branch first, by design"
        )
    xdg_engine = replace(
        PRUSASLICER,
        config_location=ConfigLocation(marker="PrusaSlicer.ini", xdg="PrusaSlicer"),
    )
    found = _found(LaunchKind.PATH)

    monkeypatch.setenv("XDG_CONFIG_HOME", "relative-config")
    ignored = where_configuration_should_be(xdg_engine, found)
    assert ignored is not None
    assert not str(ignored).startswith("relative-config"), (
        f"a relative XDG_CONFIG_HOME was honoured, so slicelab looks for the engine's "
        f"configuration relative to the working directory: {ignored}"
    )
    assert ignored == Path.home() / ".config" / "PrusaSlicer"

    monkeypatch.setenv("XDG_CONFIG_HOME", str(Path.home() / "xdg-absolute"))
    assert where_configuration_should_be(xdg_engine, found) == (
        Path.home() / "xdg-absolute" / "PrusaSlicer"
    ), "an absolute XDG_CONFIG_HOME was ignored, which is the opposite defect"
