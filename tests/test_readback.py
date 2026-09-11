"""The mechanism, adjudicated.

Every test here is named for the claim it makes, and most exist because the
alternative — a green slicelab could not support — is the worst outcome in the
system. A false red gets investigated; a false green does not.
"""

from __future__ import annotations

import pytest

from slicelab.engine.characterise import MapEntry, ProbeOutcome, Tracking
from slicelab.readback import diff
from slicelab.status import KeyStatus, Outcome


def mapped(*keys: str, tracking: Tracking = Tracking.EXACT, side: tuple[str, ...] = ()) -> MapEntry:
    return MapEntry(keys=keys, side_effects=side, tracking=tracking, outcome=ProbeOutcome.MAPPED)


def unmapped(outcome: ProbeOutcome) -> MapEntry:
    return MapEntry(keys=(), side_effects=(), tracking=None, outcome=outcome)


def test_a_key_that_came_back_as_asked_is_applied() -> None:
    r = diff({"perimeters": "4"}, {"perimeters": "4"}, {"perimeters": mapped("perimeters")})
    assert r.verdicts[0].status is KeyStatus.APPLIED
    assert r.outcome is Outcome.SLICED


def test_v1_the_defect_this_project_exists_to_catch() -> None:
    """`--perimeters 4.7` resolves to `4`, at exit 0, with zero bytes on stderr.

    Reproduced on PrusaSlicer 2.9.6 and the reason slicelab exists. The engine
    says nothing; the diff is the only thing that does.
    """
    r = diff({"perimeters": "4.7"}, {"perimeters": "4"}, {"perimeters": mapped("perimeters")})
    verdict = r.verdicts[0]
    assert verdict.status is KeyStatus.COERCED
    assert verdict.compared == ("perimeters",)
    assert verdict.observed == ("4",)
    assert "4.7" in verdict.reason and "4" in verdict.reason
    assert r.outcome is Outcome.INCOMPLETE


def test_a_coerced_key_does_not_claim_the_engine_ignored_the_request() -> None:
    """D27. slicelab cannot tell V1 from a documented dependent constraint.

    Both reach the readback as the same bytes, so `refused` would assert a cause
    that was never established.
    """
    r = diff({"perimeters": "4"}, {"perimeters": "1"}, {"perimeters": mapped("perimeters")})
    assert r.outcome is not Outcome.REFUSED
    assert r.outcome is Outcome.INCOMPLETE


def test_every_key_a_fan_out_option_writes_must_agree() -> None:
    """`--extruder` writes three keys; checking one and reporting green on it is
    the "right key, incomplete check" false `applied` G2 warned about."""
    entry = mapped("infill_extruder", "perimeter_extruder", "solid_infill_extruder")
    resolved = {"infill_extruder": "2", "perimeter_extruder": "2", "solid_infill_extruder": "9"}
    r = diff({"extruder": "2"}, resolved, {"extruder": entry})
    assert r.verdicts[0].status is KeyStatus.COERCED
    assert "solid_infill_extruder" in r.verdicts[0].reason
    assert r.verdicts[0].compared == entry.keys


def test_a_fan_out_option_is_applied_only_when_all_of_them_agree() -> None:
    entry = mapped("infill_extruder", "perimeter_extruder", "solid_infill_extruder")
    resolved = dict.fromkeys(entry.keys, "2")
    r = diff({"extruder": "2"}, resolved, {"extruder": entry})
    assert r.verdicts[0].status is KeyStatus.APPLIED


def test_a_dependent_constraint_is_never_compared_against() -> None:
    """G4, closed by the probe rather than here.

    `--spiral-vase=1` moves five keys; only `spiral_vase` carries the value. The
    other four are the engine adjusting the print around the request, and
    adjudicating the authored value against them is the false red that made a
    correct slice report as a finding.
    """
    entry = mapped("spiral_vase", side=("perimeters", "fill_density", "top_solid_layers"))
    resolved = {
        "spiral_vase": "1",
        "perimeters": "1",
        "fill_density": "0%",
        "top_solid_layers": "0",
    }
    r = diff({"spiral-vase": "1"}, resolved, {"spiral-vase": entry})
    assert r.verdicts[0].status is KeyStatus.APPLIED
    assert r.verdicts[0].compared == ("spiral_vase",)
    assert "perimeters" not in r.verdicts[0].compared


def test_a_key_missing_from_the_readback_is_absent_not_a_finding() -> None:
    """The key SET is value-dependent: `bed_custom_texture` is in no default dump
    and appears the moment it is set. So absence has not shown anything."""
    r = diff({"perimeters": "4"}, {}, {"perimeters": mapped("perimeters")})
    assert r.verdicts[0].status is KeyStatus.ABSENT
    assert r.outcome is Outcome.INCOMPLETE


def test_an_option_the_probe_never_saw_is_not_a_claim_about_the_engine() -> None:
    """A candidate list can under-produce — Orca's comes from its own dump keys —
    so "not measured" must not become "the engine ignored you"."""
    r = diff({"wall-loops": "3"}, {}, {})
    assert r.verdicts[0].status is KeyStatus.UNVALIDATED
    assert r.verdicts[0].status is not KeyStatus.ABSENT
    assert r.verdicts[0].status is not KeyStatus.UNSUPPORTED


def test_an_option_the_engine_denies_is_a_finding() -> None:
    """The one case where the engine itself answered. That IS established."""
    r = diff({"nonsense": "1"}, {}, {"nonsense": unmapped(ProbeOutcome.UNKNOWN_OPTION)})
    assert r.verdicts[0].status is KeyStatus.UNSUPPORTED
    assert r.outcome is Outcome.REFUSED


@pytest.mark.parametrize(
    "outcome",
    [
        ProbeOutcome.TIMED_OUT,
        ProbeOutcome.REJECTED,
        ProbeOutcome.NO_ARTIFACT,
        ProbeOutcome.UNSTABLE,
        ProbeOutcome.NAMESPACE_CHANGED,
    ],
)
def test_an_inconclusive_probe_never_becomes_a_statement_about_the_engine(
    outcome: ProbeOutcome,
) -> None:
    """G2's defect returning through the cache, refused here.

    An option the probe hung on is not an option the engine ignored, and the
    difference is exactly what `MapEntry.conclusive` carries.
    """
    r = diff({"perimeters": "4"}, {}, {"perimeters": unmapped(outcome)})
    assert r.verdicts[0].status is KeyStatus.UNVALIDATED
    assert r.outcome is Outcome.INCOMPLETE


def test_an_option_that_writes_no_key_cannot_be_adjudicated() -> None:
    """Conclusive, and still not adjudicable: there is no key to compare against."""
    r = diff({"info": "1"}, {}, {"info": unmapped(ProbeOutcome.NO_KEY_MOVED)})
    assert r.verdicts[0].status is KeyStatus.UNVALIDATED


def test_an_inexact_entry_is_never_green_and_never_a_finding() -> None:
    """The asymmetric case, and the one most likely to be argued away later.

    INEXACT means no key held either sentinel verbatim, so how the authored value
    lands in the key is unknown. Equality would be a green slicelab cannot
    support; inequality would be a finding against a key that may never have been
    meant to hold the value. Orca's JSON-list keys are 170 entries of this shape —
    `--activate-air-filtration=1` resolves to `["1"]`, which is neither agreement
    nor disagreement.
    """
    entry = mapped("wall_loops", tracking=Tracking.INEXACT)
    agreeing = diff({"wall-loops": "3"}, {"wall_loops": "3"}, {"wall-loops": entry})
    differing = diff({"wall-loops": "3"}, {"wall_loops": '["3"]'}, {"wall-loops": entry})
    assert agreeing.verdicts[0].status is KeyStatus.UNVALIDATED
    assert differing.verdicts[0].status is KeyStatus.UNVALIDATED
    assert agreeing.outcome is Outcome.INCOMPLETE


def test_an_empty_subject_set_verifies_nothing() -> None:
    """G1/D24: the first file anyone writes, and it must not print the green word."""
    r = diff({}, {"perimeters": "3"}, {})
    assert r.keys_checked == 0
    assert r.outcome is Outcome.EMPTY


def test_authored_but_unadjudicable_is_incomplete_not_empty() -> None:
    """`keys_checked` counts what was ASKED, not what was answered.

    Three overrides slicelab could only record is a run that asked for something
    and could not stand behind the answer. Reporting `empty` would say nothing was
    requested, which is a different and false claim.
    """
    r = diff(
        {"a-opt": "1", "b-opt": "2"},
        {},
        {"a-opt": unmapped(ProbeOutcome.TIMED_OUT), "b-opt": unmapped(ProbeOutcome.REJECTED)},
    )
    assert r.keys_checked == 2
    assert r.outcome is Outcome.INCOMPLETE
    assert r.outcome is not Outcome.EMPTY


def test_one_bad_key_is_enough() -> None:
    """A run is only as good as its worst key; a green beside a finding is a lie."""
    r = diff(
        {"perimeters": "4", "layer-height": "0.2"},
        {"perimeters": "1", "layer_height": "0.2"},
        {"perimeters": mapped("perimeters"), "layer-height": mapped("layer_height")},
    )
    assert {v.status for v in r.verdicts} == {KeyStatus.COERCED, KeyStatus.APPLIED}
    assert r.outcome is Outcome.INCOMPLETE


def test_the_verdicts_record_which_key_was_compared() -> None:
    """G2's first action: the report says which key, so a reader can check the
    comparison rather than reconstruct it and get a different answer."""
    entry = mapped("layer_gcode")
    r = diff({"after-layer-gcode": "M117"}, {"layer_gcode": "M117"}, {"after-layer-gcode": entry})
    assert r.verdicts[0].compared == ("layer_gcode",)
    assert r.verdicts[0].observed == ("M117",)


def test_verdicts_are_ordered_deterministically() -> None:
    """A report humans diff must not reorder between runs."""
    m = {k: mapped(k.replace("-", "_")) for k in ("c-opt", "a-opt", "b-opt")}
    resolved = {k.replace("-", "_"): "1" for k in m}
    first = diff({"c-opt": "1", "a-opt": "1", "b-opt": "1"}, resolved, m)
    second = diff({"a-opt": "1", "b-opt": "1", "c-opt": "1"}, resolved, m)
    assert [v.option for v in first.verdicts] == ["a-opt", "b-opt", "c-opt"]
    assert [v.option for v in first.verdicts] == [v.option for v in second.verdicts]


def test_a_mapped_entry_with_no_keys_is_never_green() -> None:
    """The false `applied` that reached this module through its own cache loader.

    With `keys=()`, `missing` and `differing` are both empty comprehensions over an
    empty tuple, so both guards pass and the verdict was `applied` over **zero**
    compared keys -- printing "every key this option writes came back '4'", which is
    vacuously true of nothing. That is G1's defect one level down, inside the module
    whose `keys_checked` docstring names that exact shape as the thing it refuses.

    `_probe_one` cannot build this; `_read_cache` can, and its own docstring
    anticipates a truncated or hand-edited cache.
    """
    entry = MapEntry(keys=(), side_effects=(), tracking=Tracking.EXACT, outcome=ProbeOutcome.MAPPED)
    r = diff({"perimeters": "4"}, {"perimeters": "1"}, {"perimeters": entry})
    assert r.verdicts[0].status is KeyStatus.UNVALIDATED
    assert r.verdicts[0].status is not KeyStatus.APPLIED
    assert r.outcome is not Outcome.SLICED


def test_an_entry_whose_tracking_was_never_established_is_never_green() -> None:
    """The second route in, and the same bug: a blacklist instead of a whitelist.

    `tracking=None` is neither EXACT nor INEXACT, so a test written as "refuse
    INEXACT" let it through to the strict-equality path reserved for a measurement
    nobody made -- and agreeing values then read as `applied`.
    """
    entry = MapEntry(
        keys=("perimeters",), side_effects=(), tracking=None, outcome=ProbeOutcome.MAPPED
    )
    agreeing = diff({"perimeters": "4"}, {"perimeters": "4"}, {"perimeters": entry})
    assert agreeing.verdicts[0].status is KeyStatus.UNVALIDATED
    assert agreeing.outcome is not Outcome.SLICED


def test_only_an_exact_entry_is_ever_adjudicated() -> None:
    """The rule stated positively, so a new tracking value cannot slip through.

    A blacklist is only as complete as its list; this is complete by construction.
    D26 records the same lesson for the boundary guard, and it is the third time in
    this project that naming what is refused turned out to name too little.
    """
    for tracking in (None, Tracking.INEXACT):
        entry = MapEntry(
            keys=("perimeters",), side_effects=(), tracking=tracking, outcome=ProbeOutcome.MAPPED
        )
        r = diff({"perimeters": "4"}, {"perimeters": "4"}, {"perimeters": entry})
        assert r.verdicts[0].status is KeyStatus.UNVALIDATED, tracking


def test_an_absence_does_not_hide_an_established_disagreement() -> None:
    """One key missing and two actively wrong: slicelab DID establish a disagreement.

    Reporting only the absence points an investigator at the key nothing is known
    about, which is what G2's "record what was compared" action exists to prevent.
    """
    entry = mapped("infill_extruder", "perimeter_extruder", "solid_infill_extruder")
    resolved = {"infill_extruder": "9", "perimeter_extruder": "9"}
    r = diff({"extruder": "2"}, resolved, {"extruder": entry})
    reason = r.verdicts[0].reason
    assert r.verdicts[0].status is KeyStatus.ABSENT
    assert "solid_infill_extruder" in reason
    assert "infill_extruder" in reason and "came back different" in reason
