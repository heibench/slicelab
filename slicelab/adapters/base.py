"""What every adapter must state about its engine."""

from __future__ import annotations

import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass

__all__ = ["EngineSpec", "OptionProbe", "PresetQuery"]


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
class OptionProbe:
    """How to characterise one engine's option-name -> config-key map.

    ``notes/critique.md`` G2: there is no derivable rule. Measured on PrusaSlicer
    2.9.6, ``--after-layer-gcode`` writes ``layer_gcode``, so a dash-to-underscore
    transform reports ``absent`` on a key the engine applied exactly -- exit 2 on a
    correct run. The map is established by *setting each option to a sentinel and
    observing which key moved*, and the only parts of that which differ per engine
    are the four fields below. The measuring itself is engine-neutral and lives in
    :mod:`slicelab.engine.characterise`.

    This exists so that ``--help-fff`` parsing and ini parsing -- both
    PrusaSlicer-shaped, neither portable -- sit on the adapter side of D1's seam.
    """

    sentinels: tuple[tuple[str, str], ...]
    """**Pairs** of distinct values of the same type, tried in order.

    Options are typed and no single value fits them all: an int option rejects a
    string at rc=1, a points option rejects an int. Order is by how *distinctive*
    the result is rather than by likelihood -- a string marker is unambiguous when
    it lands, whereas a number can coincide with the default and read as "moved
    nothing".

    **Two values, not one, and the pair is the mechanism rather than a retry.**
    Setting an option once says which keys moved; setting it twice says which of
    them *followed the value*. Only a key the option writes holds the first value
    after the first run and the second after the second; a key the engine adjusted
    as a dependent constraint does not. That is what separates ``spiral_vase``
    from the four keys ``--spiral-vase=1`` also moves, with no heuristic and no
    threshold, and it costs one extra invocation per candidate.

    The two must be **distinct and of one type**, or the pair discriminates
    nothing: a boolean given two different strings resolves both to ``0``, which
    is why ``("1", "0")`` is here as its own pair rather than folded into the
    numeric one.
    """

    unknown_option: str
    """This engine's own wording for "there is no such option", or ``""``.

    Distinguishing "no such option" from "wrong value for a real option" is what
    lets the probe stop trying sentinels on a name that does not exist, instead of
    charging through every one of them.

    ``""`` means this engine does not distinguish the two, and it is a measurement
    rather than an omission -- OrcaSlicer 2.4.2 answers the same words at the same
    exit status for both. The probe then cascades every sentinel and records
    ``rejected``, which is slower and is what the engine actually established.
    """

    candidates: Callable[[str, Mapping[str, str]], tuple[str, ...]]
    """(enumeration output, baseline readback) -> option names to probe, no leading dashes.

    A *candidate* generator, not an answer. It may over- or under-produce freely,
    because the probe is what establishes truth; that is the whole difference
    between this and the string transform G2 refuses. PrusaSlicer's reads
    ``--help-fff``; OrcaSlicer has no such listing and derives candidates from the
    keys of its own settings dump.
    """

    read_config: Callable[[str], Mapping[str, str]]
    """The text of a readback artifact -> key/value pairs.

    Takes text rather than a path on purpose. Whether the artifact exists and is
    non-empty is D7's question, it is asked about every engine alike, and the
    driver asks it -- so an adapter cannot answer ``{}`` for a file that was never
    written and have the caller read that as "nothing moved".
    """

    enumerate_argv: tuple[str, ...] = ()
    """Argv that makes this engine list its options, or ``()`` if it will not.

    Empty means :attr:`candidates` is called with an empty string and must work
    from the baseline readback alone.
    """


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
    secret_keys: tuple[str, ...] | None = None
    """Keys this engine's readback carries in cleartext that must never be written out.

    `None` means **unmeasured**, and writing a sidecar is refused rather than
    risking a credential reaching a file someone commits. Not caution for its own
    sake: PrusaSlicer's `--save` emits `printhost_apikey` and `print_host` in
    cleartext, and the G-code footer — the same configuration by another route —
    strips exactly those. So one artifact of this engine is safe to keep and
    another is not, and which is which was measured rather than assumed.

    They appear only under a preset triple. A bare `--save` emits none of them, so
    a guard written against the default dump would have found nothing and reported
    the file clean.

    **This is secret hygiene and nothing else.** The frozen dossier refuted the
    licensing rationale explicitly and flags it as a trap not to reintroduce: the
    committed G-code already carries the same vendor payload, so withholding the
    sidecar removes no bytes from anyone's repository. Diff noise, lock size and
    credentials are the reasons that survived.
    """

    readback_flag: str | None = None
    """The option that makes this engine dump its resolved configuration, or `None`.

    PrusaSlicer writes an ini with `--save`; OrcaSlicer writes JSON with
    `--export-settings` [V11]. Two engines, two mechanisms answering one question,
    which is the fact that makes the readback seam real rather than a PrusaSlicer
    trick.

    Both dumps' key counts are profile-dependent and neither number means anything
    unqualified: PrusaSlicer is 343 keys bare and 376 under a stock preset triple;
    Orca is 616 bare, 626 under V11's Creality triple and 639 under an Artillery
    one. Two of those figures previously sat in two files as though they were one
    fact about the engine, which is the rot `readback.py` warns about -- a count in
    prose beside the thing it counts is a claim that has to be maintained by hand.

    The core asks for *a* readback and never for `--save`, or D1's supersede clause
    is decided by default.

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

    option_probe: OptionProbe | None = None
    """How to build this engine's option-to-key map, or ``None`` if unmeasured.

    ``None`` is a refusal, not a gap: with no probe there is no honest map, and
    the alternative -- transforming the name -- is the defect G2 reproduced.
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
    pre-flight will refuse rather than guess. Consumed by `preflight._check_base`. Declared
    here rather than in the core because `test_names_confined.py` refuses an
    engine's names there.
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
