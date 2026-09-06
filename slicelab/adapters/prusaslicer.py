"""PrusaSlicer."""

from __future__ import annotations

from slicelab.adapters.base import EngineSpec

SPEC = EngineSpec(
    name="prusaslicer",
    # The console variant is the one that speaks on Windows; the GUI binary
    # detaches and answers nothing.
    posix_exec="prusa-slicer",
    windows_exec="prusa-slicer-console.exe",
    flatpak_app_id="com.prusa3d.PrusaSlicer",
)
