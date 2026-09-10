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
    readback_flag: str | None = None
    """The option that makes this engine dump its resolved configuration, or `None`.

    PrusaSlicer writes an ini with `--save`; OrcaSlicer writes JSON with
    `--export-settings` [V11]. Two engines, two mechanisms -- a 376-key ini and a
    626-key JSON -- answering one question, which is the fact that makes the readback
    seam real rather than a PrusaSlicer trick. The core asks for *a* readback and
    never for `--save`, or D1's supersede clause is decided by default.

    `None` means the emission form is unmeasured for this engine, and planning
    refuses rather than composing an argv nobody has run.
    """

    bool_words: tuple[str, str] | None = None
    """How this engine spells true and false on the command line, or `None`.

    `None` means **not measured**, and pre-flight refuses a boolean override rather
    than guessing. That is not caution for its own sake: PrusaSlicer 2.9.6 accepts
    `--spiral-vase=1`, resolves `--spiral-vase=true` to `0`, and resolves
    `--spiral-vase=` to `1` -- at exit 0, with nothing on stderr, in every case.
    Boolean options are the one type that validates nothing, so a wrong guess here
    is silently the opposite of what the author wrote. Orca's spelling is unmeasured,
    so Orca declines the question instead of inheriting PrusaSlicer's answer.
    """

    base_keys: tuple[str, ...] = ()
    """The option names an authored ``[<engine>.base]`` table must carry.

    These are the ENGINE's names and they live here rather than in the core for the
    reason D1's seam exists: PrusaSlicer addresses a preset triple by *name*
    (``--printer-profile``), and OrcaSlicer has no such flag at all -- it takes
    ``--load-settings`` with file *paths*, a different kind of address. A shared
    constant naming PrusaSlicer's three would assume a mapping that does not exist,
    which is the PrusaSlicer-shaped abstraction D2 refuses.

    Empty means the adapter has not decided what its ``[base]`` contains, and
    pre-flight will refuse rather than guess. **Nothing consumes this field yet**;
    `preflight.py` lands with the second half of #5. It is declared here now
    because the alternative was declaring it in the core, where
    `test_names_confined.py` refuses it.
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
