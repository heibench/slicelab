"""The argv `resolve` composes, and the record of what it meant by it.

`plan_resolve` is pure, so every test here runs on a machine with no slicer. The
argv it produces was measured against the real engine and that measurement is in
`test_resolve_against_the_real_engine`, gated on the engine being present.
"""

from __future__ import annotations

from pathlib import Path

from slicelab.adapters import PRUSASLICER
from slicelab.intent import Intent
from slicelab.plan import plan_resolve

TRIPLE = {
    "printer-profile": "Original Prusa i3 MK3S & MK3S+",
    "print-profile": "0.20mm QUALITY @MK3",
    "material-profile": "Prusament PLA",
}


def intent(overrides: dict[str, object] | None = None) -> Intent:
    return Intent(
        engine="prusaslicer",
        base=dict(TRIPLE),
        overrides=dict(overrides or {}),  # type: ignore[arg-type]
        source=Path("slice.toml"),
    )


def test_the_argv_is_the_preset_triple_then_the_overrides_then_the_sidecar() -> None:
    plan = plan_resolve(intent({"perimeters": 4}), PRUSASLICER, Path("/tmp/out.ini"))
    assert plan.argv == (
        "--printer-profile=Original Prusa i3 MK3S & MK3S+",
        "--print-profile=0.20mm QUALITY @MK3",
        "--material-profile=Prusament PLA",
        "--perimeters=4",
        "--save=/tmp/out.ini",
    )


def test_no_geometry_and_no_export_are_in_the_argv() -> None:
    """`resolve` asks what the engine WOULD resolve; it slices nothing.

    That is what makes it ~0.2 s, and it is why the verb can ship before anything
    that produces an artifact exists.
    """
    plan = plan_resolve(intent({"perimeters": 4}), PRUSASLICER, Path("/tmp/o.ini"))
    joined = " ".join(plan.argv)
    assert "--export-gcode" not in joined
    assert ".stl" not in joined
    assert "-o" not in plan.argv


def test_the_argv_is_deterministic_across_authoring_order() -> None:
    """A Plan is diffed by humans and compared in tests; a reordering argv is one
    nobody can read. Base keys follow the engine's declared order, overrides sort."""
    a = plan_resolve(intent({"perimeters": 4, "fill-density": "60%"}), PRUSASLICER, Path("x"))
    b = plan_resolve(intent({"fill-density": "60%", "perimeters": 4}), PRUSASLICER, Path("x"))
    assert a.argv == b.argv


def test_requested_records_the_string_that_was_emitted() -> None:
    """The readback diff compares against THIS, not against a re-derivation.

    Re-deriving what was sent is where the defect lives: G2 produced a false
    `absent` by transforming a name, and the same trap exists for values -- a
    boolean emitted as `1` must not be compared as `True`.
    """
    plan = plan_resolve(intent({"spiral-vase": True, "perimeters": 4}), PRUSASLICER, Path("x"))
    assert plan.requested == {"spiral-vase": "1", "perimeters": "4"}


def test_an_empty_subject_set_plans_a_run_that_checks_nothing() -> None:
    """G1/D24: the first file anyone writes. `keys_checked` is 0, and the run that
    follows is `empty` at exit 3 rather than `sliced` at 0."""
    plan = plan_resolve(intent(), PRUSASLICER, Path("x"))
    assert plan.keys_checked == 0
    assert plan.requested == {}
    assert "--save=x" in plan.argv


def test_keys_checked_counts_the_authored_delta_not_the_resolution() -> None:
    """The mechanism adjudicates ~2-10 keys and only RECORDS the other ~370.

    G1's deeper point, and it is easy to lose: a 376-key resolution is not 376
    checks. Presenting it as one would be the vacuous green wearing a bigger number.
    """
    plan = plan_resolve(intent({"perimeters": 4, "fill-density": "60%"}), PRUSASLICER, Path("x"))
    assert plan.keys_checked == 2


def test_plan_is_frozen() -> None:
    plan = plan_resolve(intent(), PRUSASLICER, Path("x"))
    try:
        plan.argv = ()  # type: ignore[misc]
    except AttributeError:
        return
    raise AssertionError("Plan must not be rebindable after composition")
