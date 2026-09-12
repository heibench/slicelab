"""Whether an engine has been configured, established rather than inferred.

A freshly installed slicer has no configuration, and asking it to enumerate presets
gets an error on stdout where JSON was expected. slicelab reported that as
`incomplete` (2) -- *could not tell* -- when it can tell, and the answer is specific:
the engine is installed and has never been configured. Org contract 2.2 puts that with
"an engine that will not start": a fixable condition in the environment, not an
indeterminate result about the request. Exit 4, which a CI job can branch on.

The alternative was matching the engine's error prose. That would put engine strings
outside `adapters/`, depend on wording upstream can change without notice, and answer
differently under a different locale. Looking for the directory answers the same
question from a fact this module can check.

**What this module will not do is guess.** Where an adapter has not declared a
location for the platform in hand, the answer is `UNDETERMINED` and the caller keeps
whatever behaviour it had. Reporting "not configured" because slicelab does not know
where to look would be the substitution org contract 2.3 forbids, wearing the exit
code reserved for facts.
"""

from __future__ import annotations

import os
import stat
import sys
from enum import StrEnum, auto
from pathlib import Path

from slicelab.adapters import EngineSpec
from slicelab.engine.discover import Discovery, LaunchKind

__all__ = ["ConfigState", "configuration_state", "where_configuration_should_be"]


class ConfigState(StrEnum):
    """What slicelab established about this engine's configuration."""

    PRESENT = auto()
    """The marker is there. Says nothing about whether it is any good."""

    ABSENT = auto()
    """Looked in a known place and it is not configured. An environment fault."""

    UNDETERMINED = auto()
    """No location is declared for this engine on this platform, so slicelab did not
    look. NOT the same as absent, and it must never be reported as one."""


def where_configuration_should_be(
    spec: EngineSpec, discovery: Discovery, *, datadir: str | None = None
) -> Path | None:
    """The directory that decides, or `None` if slicelab cannot say which one that is.

    `datadir` wins when given: the author named a directory, so that is the one
    checked, and it is the one a report must name. An earlier revision answered the
    engine's default here while `configuration_state` checked the override, so the
    error told the reader to look somewhere nobody had looked.

    The launch form decides, not the host: a Flatpak engine reads
    `~/.var/app/<app-id>/config/`, and the same machine's PATH install reads
    `$XDG_CONFIG_HOME`. Answering from the platform alone would look in the wrong place
    on exactly the hosts that have both, which is this project's own development
    machine.
    """
    location = spec.config_location
    if location is None:
        return None

    if datadir is not None:
        if not datadir:
            return None
        try:
            return Path(datadir).expanduser()
        except (RuntimeError, ValueError):
            return None

    if discovery.form is None:
        return None

    if discovery.form.kind in (LaunchKind.FLATPAK, LaunchKind.FLATPAK_BYPASS):
        if location.flatpak is None or spec.flatpak_app_id is None:
            return None
        return Path.home() / ".var" / "app" / spec.flatpak_app_id / "config" / location.flatpak

    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if location.windows is None or not appdata:
            return None
        return Path(appdata) / location.windows

    if sys.platform == "darwin":
        if location.macos is None:
            return None
        return Path.home() / "Library" / "Application Support" / location.macos

    if location.xdg is None:
        return None
    # A relative XDG_CONFIG_HOME "MUST be ignored" per the basedir spec, and honouring
    # one here would look for the engine's configuration wherever the user happened to
    # be standing -- the same defect `launch._scratch_roots` is written about.
    base = os.environ.get("XDG_CONFIG_HOME") or ""
    root = Path(base) if base and Path(base).is_absolute() else Path.home() / ".config"
    return root / location.xdg


def configuration_state(
    spec: EngineSpec, discovery: Discovery, *, datadir: str | None = None
) -> ConfigState:
    """Has this engine been configured? `UNDETERMINED` when slicelab cannot tell.

    `datadir` is the caller's override, taken as given: the author named a directory
    and that is the one that decides. An override slicelab was handed but could not
    resolve is not this function's finding to make -- it answers `UNDETERMINED` and
    lets the caller's own refusal handle it. (`cli._presets` asks this question BEFORE
    it expands the path, so "the caller has already refused" -- which this comment
    used to say -- had the order backwards.)
    """
    location = spec.config_location
    if location is None:
        return ConfigState.UNDETERMINED

    # One resolver, so the directory checked and the directory reported cannot differ.
    # `--datadir ''` resolves to None here and stays UNDETERMINED: it is a request
    # slicelab cannot honour and the engine is the one that should say so.
    directory = where_configuration_should_be(spec, discovery, datadir=datadir)
    if directory is None:
        return ConfigState.UNDETERMINED
    # `os.stat`, not `Path.is_file()`. On CPython 3.14 `is_file` became
    # `os.path.isfile`, which swallows every OSError and answers False -- so a
    # directory slicelab cannot READ came back "not configured" rather than "could not
    # tell", and the comment below claimed the opposite. Measured: 3.11, 3.12 and 3.13
    # all raise PermissionError here and 3.14 returns False, while `requires-python`
    # admits all four and CI stops at 3.13, so the gate could not see it.
    marker = directory / location.marker
    try:
        return ConfigState.PRESENT if stat.S_ISREG(os.stat(marker).st_mode) else ConfigState.ABSENT
    except FileNotFoundError:
        # Looked, and it is not there. The finding this function exists for.
        return ConfigState.ABSENT
    except OSError:
        # A path slicelab cannot even stat establishes nothing about configuration.
        return ConfigState.UNDETERMINED
