"""What every adapter must state about its engine."""

from __future__ import annotations

import os
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
    preset_query: PresetQuery | None = None

    @property
    def exec_name(self) -> str:
        return self.windows_exec if os.name == "nt" else self.posix_exec
