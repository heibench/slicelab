"""What every adapter must state about its engine."""

from __future__ import annotations

import os
from dataclasses import dataclass

__all__ = ["EngineSpec"]


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

    @property
    def exec_name(self) -> str:
        return self.windows_exec if os.name == "nt" else self.posix_exec
