"""D2's assertion, which the decision named for three releases before it existed.

`AGENTS.md` and `docs/DECISIONS.md` both claimed "`CORE_KEYS == frozenset()`,
asserted by a test" while neither the constant nor the test was in the tree. That
was corrected to the future tense in #27; this is the file that makes it true.
"""

from __future__ import annotations

from slicelab import vocab
from slicelab.adapters import ORCASLICER, PRUSASLICER


def test_the_core_vocabulary_is_empty() -> None:
    """A vocabulary written from one engine IS the PrusaSlicer-shaped abstraction.

    135 of PrusaSlicer's 343 config keys share a name with an Orca key, and sharing a
    name is not sharing a meaning: `gcode_label_objects` is an enum in one and a bool
    in the other, and `bed_temperature` has no single Orca counterpart at all. D2
    keeps the set empty until D3's admission procedure adds one, with evidence.
    """
    assert frozenset() == vocab.CORE_KEYS


def test_a_key_cannot_arrive_without_the_admission_procedure() -> None:
    """The guard on the guard: an empty set is also what a deleted constant looks like.

    Asserting emptiness alone would still pass if `CORE_KEYS` were renamed away, so
    this pins that the name exists and is the right kind of thing.
    """
    assert isinstance(vocab.CORE_KEYS, frozenset)
    assert not vocab.CORE_KEYS


def test_the_engine_owns_its_preset_flag_names_and_the_core_does_not() -> None:
    """D1's seam, and the reason `test_names_confined.py` exists.

    PrusaSlicer addresses a preset triple by NAME (`--printer-profile`); OrcaSlicer
    has no such flag and takes `--load-settings` with file PATHS -- a different kind
    of address. A shared constant naming PrusaSlicer's three would assume a mapping
    that does not exist, which is the PrusaSlicer-shaped abstraction D2 refuses.

    A first draft of `vocab.py` did exactly that, and the boundary test caught it on
    its first run.
    """
    assert PRUSASLICER.base_keys == (
        "printer-profile",
        "print-profile",
        "material-profile",
    )
    assert not [n for n in dir(vocab) if "base_key" in n.lower()]


def test_an_adapter_with_no_declared_base_is_not_guessed_for() -> None:
    """Orca's `[base]` is undecided, and an empty tuple says so rather than lying.

    Pre-flight will refuse on an empty `base_keys` rather than fall back to the other
    engine's names -- degrading to a neighbouring answer is the shape org contract
    section 3 calls a could-not-tell, not a success. `preflight.py` does not exist
    yet, so this pins the declaration and not the behaviour.
    """
    assert ORCASLICER.base_keys == ()


def test_preset_flag_names_are_spelled_as_the_engine_spells_them() -> None:
    """No name transformation anywhere, which is `notes/critique.md` G2's whole point.

    The authored key is the CLI option minus its leading dashes, so emission is
    `--{key}={value}` and there is no dash-to-underscore rule to be non-total.
    """
    for key in PRUSASLICER.base_keys:
        assert not key.startswith("-")
        assert "_" not in key
