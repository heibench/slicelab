"""The argv `resolve` composes, and the record of what it meant by it.

`plan_resolve` is pure, so every test here runs on a machine with no slicer. The
argv it produces was measured against the real engine and that measurement is in
`test_resolve_against_the_real_engine`, gated on the engine being present.
"""

from __future__ import annotations

from pathlib import Path

import pytest

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


def test_the_argv_is_the_preset_triple_then_the_overrides_then_the_sidecar(
    tmp_path: Path,
) -> None:
    """The sidecar is compared as a resolved Path, not as a POSIX string.

    `plan_resolve` resolves the path, and a resolved path is platform-shaped --
    `/tmp/out.ini` becomes `D:\\tmp\\out.ini` on Windows. Hardcoding the POSIX form
    passed on this host and reddened CI's Windows leg, which is the whole reason
    that leg exists.
    """
    sidecar = tmp_path / "out.ini"
    plan = plan_resolve(intent({"perimeters": 4}), PRUSASLICER, sidecar)
    assert plan.argv == (
        "--printer-profile=Original Prusa i3 MK3S & MK3S+",
        "--print-profile=0.20mm QUALITY @MK3",
        "--material-profile=Prusament PLA",
        "--perimeters=4",
        f"--save={sidecar.resolve()}",
    )


def test_no_geometry_and_no_export_are_in_the_argv() -> None:
    """`resolve` asks what the engine WOULD resolve; it slices nothing.

    That is what makes it ~0.2 s, and it is why the verb can ship before anything
    that produces an artifact exists.
    """
    plan = plan_resolve(intent({"perimeters": 4}), PRUSASLICER, Path(__file__))
    joined = " ".join(plan.argv)
    assert "--export-gcode" not in joined
    assert ".stl" not in joined
    assert "-o" not in plan.argv


def test_the_argv_is_deterministic_across_authoring_order() -> None:
    """A Plan is diffed by humans and compared in tests; a reordering argv is one
    nobody can read. Base keys follow the engine's declared order, overrides sort."""
    a = plan_resolve(intent({"perimeters": 4, "fill-density": "60%"}), PRUSASLICER, Path(__file__))
    b = plan_resolve(intent({"fill-density": "60%", "perimeters": 4}), PRUSASLICER, Path(__file__))
    assert a.argv == b.argv


def test_requested_records_the_string_that_was_emitted() -> None:
    """The readback diff compares against THIS, not against a re-derivation.

    Re-deriving what was sent is where the defect lives: G2 produced a false
    `absent` by transforming a name, and the same trap exists for values -- a
    boolean emitted as `1` must not be compared as `True`.
    """
    plan = plan_resolve(intent({"spiral-vase": True, "perimeters": 4}), PRUSASLICER, Path(__file__))
    assert plan.requested == {"spiral-vase": "1", "perimeters": "4"}


def test_an_empty_subject_set_plans_a_run_that_checks_nothing(tmp_path: Path) -> None:
    """G1/D24: the first file anyone writes. `keys_checked` is 0, and the run that
    follows is `empty` at exit 3 rather than `sliced` at 0."""
    sidecar = tmp_path / "x.ini"
    plan = plan_resolve(intent(), PRUSASLICER, sidecar)
    assert plan.keys_checked == 0
    assert plan.requested == {}
    assert f"--save={sidecar.resolve()}" in plan.argv


def test_keys_checked_counts_the_authored_delta_not_the_resolution() -> None:
    """The mechanism adjudicates ~2-10 keys and only RECORDS the other ~370.

    G1's deeper point, and it is easy to lose: a 376-key resolution is not 376
    checks. Presenting it as one would be the vacuous green wearing a bigger number.
    """
    plan = plan_resolve(
        intent({"perimeters": 4, "fill-density": "60%"}), PRUSASLICER, Path(__file__)
    )
    assert plan.keys_checked == 2


def test_plan_is_frozen() -> None:
    plan = plan_resolve(intent(), PRUSASLICER, Path(__file__))
    try:
        plan.argv = ()  # type: ignore[misc]
    except AttributeError:
        return
    raise AssertionError("Plan must not be rebindable after composition")


def test_a_relative_sidecar_is_resolved_before_anyone_can_disagree_about_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two layers resolve a relative path differently, and the run vanishes between them.

    `grants_for` resolves against slicelab's cwd; `launch.run` runs the engine inside
    a scratch directory it deletes on exit. So a relative sidecar is granted in one
    place, written in another, and destroyed -- measured as exit 0, zero bytes on
    stderr, and no file at either location. An exit-0 run that produced nothing is
    the failure this project is named after.
    """
    monkeypatch.chdir(tmp_path)
    plan = plan_resolve(intent({"perimeters": 4}), PRUSASLICER, Path("rel.ini"))
    assert plan.sidecar.is_absolute()
    assert plan.paths == frozenset({str(tmp_path / "rel.ini")})
    assert f"--save={tmp_path / 'rel.ini'}" in plan.argv
