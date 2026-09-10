"""What every adapter must state about its engine."""

from __future__ import annotations

import sys
from dataclasses import dataclass

__all__ = ["EngineSpec", "PresetQuery"]


@dataclass(frozen=True)
class PresetQuery:
    """How to ask an engine what printer presets it knows about.

    ``None`` on a spec is a real answer, not a gap to fill in later: OrcaSlicer
    2.4.2 has no preset-enumeration verb at all. Inventing one -- by reading its
    profile directories ourselves and calling the result "the engine's presets"
    -- would be the org contract's 2.3 failure, substituting a plausible answer
    for one the engine never gave.
    """

    argv: tuple[str, ...]
    root_key: str


@dataclass(frozen=True)
class EngineSpec:
    """The minimum needed to find an engine and read its identity.

    Deliberately holds no launch-form preference. Whether the Flatpak
    ``--command=`` bypass is needed is **probed per package and per host**, not
    declared here -- it is mandatory for PrusaSlicer and harmful for OrcaSlicer
    (``notes/evidence.md`` V10, D18). A field for it would invite copying a
    constant that is only true on one machine.
    """

    name: str
    posix_exec: str
    windows_exec: str
    flatpak_app_id: str | None
    macos_exec: tuple[str, ...] = ()
    preset_query: PresetQuery | None = None
    base_keys: tuple[str, ...] = ()
    """The option names an authored ``[<engine>.base]`` table must carry.

    These are the ENGINE's names and they live here rather than in the core for the
    reason D1's seam exists: PrusaSlicer addresses a preset triple by *name*
    (``--printer-profile``), and OrcaSlicer has no such flag at all -- it takes
    ``--load-settings`` with file *paths*, a different kind of address. A shared
    constant naming PrusaSlicer's three would assume a mapping that does not exist,
    which is the PrusaSlicer-shaped abstraction D2 refuses.

    Empty means the adapter has not decided what its ``[base]`` contains, and
    pre-flight refuses rather than guessing.
    """

    @property
    def exec_names(self) -> tuple[str, ...]:
        """Candidate executable names on this platform, in preference order.

        A tuple rather than one name, because macOS ships the engine inside an
        .app bundle whose binary is named after the application, not after the
        command. The Homebrew cask installs /Applications/PrusaSlicer.app, and
        the binary in its Contents/MacOS is NOT `prusa-slicer` -- discovery
        looking only for the POSIX name reported the engine absent on a runner
        that had just installed it (engine matrix, 2026-09-06).

        Several candidates rather than one per platform, because which name a
        bundle uses is a packaging decision that can change, and trying two
        cheap `shutil.which` calls is better than being confidently wrong.
        """
        if sys.platform == "win32":
            return (self.windows_exec,)
        if sys.platform == "darwin" and self.macos_exec:
            return (*self.macos_exec, self.posix_exec)
        return (self.posix_exec,)

    @property
    def exec_name(self) -> str:
        """The primary candidate, for messages that name one thing."""
        return self.exec_names[0]
