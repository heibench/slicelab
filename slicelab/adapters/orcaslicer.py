"""OrcaSlicer."""

from __future__ import annotations

from slicelab.adapters.base import EngineSpec

SPEC = EngineSpec(
    name="orcaslicer",
    posix_exec="orca-slicer",
    windows_exec="orca-slicer.exe",
    flatpak_app_id="com.orcaslicer.OrcaSlicer",
    # OrcaSlicer 2.4.2 has NO preset-enumeration verb. Measured against its
    # --help: it has --load-settings and --load-filaments, which CONSUME
    # profile files, and nothing that reports which presets exist.
    #
    # None is the honest answer. slicelab could enumerate its profile
    # directories and present the result as "Orca's presets", and that would be
    # slicelab's inventory rather than the engine's -- a plausible substitute
    # for an answer the engine never gave (org contract 2.3).
    preset_query=None,
)
