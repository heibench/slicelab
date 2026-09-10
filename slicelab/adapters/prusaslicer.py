"""PrusaSlicer."""

from __future__ import annotations

from slicelab.adapters.base import EngineSpec, PresetQuery

SPEC = EngineSpec(
    name="prusaslicer",
    # The console variant is the one that speaks on Windows; the GUI binary
    # detaches and answers nothing.
    posix_exec="prusa-slicer",
    windows_exec="prusa-slicer-console.exe",
    flatpak_app_id="com.prusa3d.PrusaSlicer",
    # The Homebrew cask installs /Applications/PrusaSlicer.app; the binary in
    # its Contents/MacOS carries the application's name.
    macos_exec=("PrusaSlicer", "prusa-slicer"),
    # Exits 1 on complete success, with valid JSON on stdout and nothing on
    # stderr -- the same code it returns for "that printer was not found"
    # (notes/evidence.md V5). slicelab adjudicates the artifact, never this
    # exit code (D17).
    readback_flag="--save",
    # Measured 2026-09-10 across seven boolean options. `1` and `0` are the only two
    # spellings that mean the same thing everywhere: =1 resolved true and =0 resolved
    # false on every option tried, both directions. EVERYTHING ELSE is per-option.
    # --spiral-vase=True resolves to 0; --thin-walls=False resolves to 1, the literal
    # string "False" turning the option ON; --cooling=True yields an empty value that
    # is neither. All at exit 0 with zero stderr, because boolean options validate
    # nothing. The hazard is bidirectional, so the only safe emission is one of the
    # two words every option agreed on.
    bool_words=("1", "0"),
    base_keys=("printer-profile", "print-profile", "material-profile"),
    preset_query=PresetQuery(argv=("--query-printer-models",), root_key="printer_models"),
)
