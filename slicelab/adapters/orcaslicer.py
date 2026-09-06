"""OrcaSlicer."""

from __future__ import annotations

from slicelab.adapters.base import EngineSpec

SPEC = EngineSpec(
    name="orcaslicer",
    posix_exec="orca-slicer",
    windows_exec="orca-slicer.exe",
    flatpak_app_id="com.orcaslicer.OrcaSlicer",
)
