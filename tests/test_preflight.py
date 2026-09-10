"""What slicelab refuses before the engine is reached, and why each one is refused.

D15: where slicelab composed the offending argv it refuses pre-flight, rather than
launching and reporting what came back. Every test here is a request slicelab
declines to compose.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from slicelab.adapters import ORCASLICER, PRUSASLICER, REGISTRY
from slicelab.intent import Intent
from slicelab.preflight import PreflightError, preflight, render

TRIPLE = {
    "printer-profile": "Original Prusa i3 MK3S & MK3S+",
    "print-profile": "0.20mm QUALITY @MK3",
    "material-profile": "Prusament PLA",
}


def intent(**kw: object) -> Intent:
    fields: dict[str, object] = {
        "engine": "prusaslicer",
        "base": dict(TRIPLE),
        "overrides": {},
        "source": Path("slice.toml"),
    }
    fields.update(kw)
    return Intent(**fields)  # type: ignore[arg-type]


def test_a_complete_request_resolves_its_adapter() -> None:
    assert preflight(intent()) is PRUSASLICER


def test_an_engine_with_no_adapter_is_refused() -> None:
    """`spec_for` returning None is D1's sanctioned shape for exactly this."""
    with pytest.raises(PreflightError, match="no adapter"):
        preflight(intent(engine="slic3r"))


def test_a_partial_base_triple_is_refused_before_the_engine_runs() -> None:
    """The refusal D15 exists for.

    On 2.9.6 any proper non-empty subset of the triple is a deterministic SIGSEGV
    -- rc=139, zero bytes on BOTH streams, for every action including `--info`
    [V6] -- and the byte-identical signature was also reproduced from an unrelated
    flag. So the observation carries no cause. Launching and reporting it would
    attribute a crash slicelab caused to a design it never read.
    """
    partial = {"printer-profile": TRIPLE["printer-profile"]}
    with pytest.raises(PreflightError) as caught:
        preflight(intent(base=partial))
    message = str(caught.value)
    assert "print-profile" in message
    assert "material-profile" in message


def test_an_unknown_base_key_is_refused_and_says_what_the_engine_uses() -> None:
    bad = dict(TRIPLE)
    del bad["material-profile"]
    bad["filament-profile"] = "Prusament PLA"
    with pytest.raises(PreflightError, match="filament-profile"):
        preflight(intent(base=bad))


def test_an_adapter_that_has_not_declared_its_base_is_refused_not_guessed_for() -> None:
    """Orca addresses presets by file path and its `[base]` is undecided.

    Falling back to PrusaSlicer's three flags would assume a mapping that does not
    exist -- degrading to a neighbouring answer, which org contract section 3 calls
    a could-not-tell rather than a success.
    """
    assert ORCASLICER.base_keys == ()
    with pytest.raises(PreflightError, match="has not declared"):
        preflight(intent(engine="orcaslicer"))


def test_a_boolean_is_refused_for_an_engine_whose_spelling_is_unmeasured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The one guess that is silently the opposite of what the author wrote.

    Exercised against a spec that HAS declared its preset keys but not its boolean
    spelling, because Orca has declared neither and its base check fires first --
    testing it through Orca would have passed for the wrong reason.
    """
    assert ORCASLICER.bool_words is None
    undeclared = replace(PRUSASLICER, name="probe-engine", bool_words=None)
    monkeypatch.setitem(REGISTRY, "probe-engine", undeclared)
    with pytest.raises(PreflightError, match="boolean"):
        preflight(intent(engine="probe-engine", overrides={"spiral-vase": True}))


def test_that_guard_is_not_passing_for_the_wrong_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same synthetic engine WITH a spelling must pass, or the test above proves
    only that something refused."""
    declared = replace(PRUSASLICER, name="probe-engine")
    monkeypatch.setitem(REGISTRY, "probe-engine", declared)
    assert preflight(intent(engine="probe-engine", overrides={"spiral-vase": True}))


def test_a_boolean_is_accepted_where_the_spelling_was_measured() -> None:
    assert PRUSASLICER.bool_words == ("1", "0")
    assert preflight(intent(overrides={"spiral-vase": True})) is PRUSASLICER


def test_a_boolean_renders_as_the_engines_word_not_pythons() -> None:
    """`str(True)` is `"True"`, which PrusaSlicer 2.9.6 resolves to FALSE.

    Measured: `--spiral-vase=1` sets the flag, and `=true`, `=True`, `=banana`,
    `=yes` and `=2` all resolve to `0` -- at exit 0, with nothing on stderr.
    Boolean options are the only type that validates nothing, so this is the one
    place a naive `str()` is silently the opposite of the request.
    """
    assert render(True, PRUSASLICER) == "1"
    assert render(False, PRUSASLICER) == "0"
    assert render(True, PRUSASLICER) != str(True)


def test_every_other_type_renders_as_itself() -> None:
    """D5: `--key=value` carries every type, so no per-key knowledge is needed."""
    assert render(4, PRUSASLICER) == "4"
    assert render(0.15, PRUSASLICER) == "0.15"
    assert render("60%", PRUSASLICER) == "60%"
    assert render("PLA;PETG", PRUSASLICER) == "PLA;PETG"
