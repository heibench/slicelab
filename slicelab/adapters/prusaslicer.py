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
    # Measured 2026-09-10: 1 sets the flag, ANY other value resolves to 0, and an
    # empty value resolves to 1. All at exit 0 with zero stderr.
    readback_flag="--save",
    bool_words=("1", "0"),
    base_keys=("printer-profile", "print-profile", "material-profile"),
    preset_query=PresetQuery(argv=("--query-printer-models",), root_key="printer_models"),
)
