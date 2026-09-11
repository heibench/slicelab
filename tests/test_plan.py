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
    staged = tmp_path / "staging" / "readback"
    plan = plan_resolve(intent({"perimeters": 4}), PRUSASLICER, sidecar, staged)
    assert plan.argv == (
        "--printer-profile=Original Prusa i3 MK3S & MK3S+",
        "--print-profile=0.20mm QUALITY @MK3",
        "--material-profile=Prusament PLA",
        "--perimeters=4",
        f"--save={staged.resolve()}",
    )
    assert f"--save={sidecar.resolve()}" not in plan.argv


def test_no_geometry_and_no_export_are_in_the_argv() -> None:
    """`resolve` asks what the engine WOULD resolve; it slices nothing.

    That is why the verb can ship before anything that produces an artifact exists.
    Measured cost is on `plan_resolve`; it is a preset load, not "fast".
    """
    plan = plan_resolve(intent({"perimeters": 4}), PRUSASLICER, Path(__file__), Path("staged"))
    joined = " ".join(plan.argv)
    assert "--export-gcode" not in joined
    assert ".stl" not in joined
    assert "-o" not in plan.argv


def test_the_argv_is_deterministic_across_authoring_order() -> None:
    """A Plan is diffed by humans and compared in tests; a reordering argv is one
    nobody can read. Base keys follow the engine's declared order, overrides sort."""
    a = plan_resolve(
        intent({"perimeters": 4, "fill-density": "60%"}), PRUSASLICER, Path(__file__), Path("s")
    )
    b = plan_resolve(
        intent({"fill-density": "60%", "perimeters": 4}), PRUSASLICER, Path(__file__), Path("s")
    )
    assert a.argv == b.argv


def test_requested_records_the_string_that_was_emitted() -> None:
    """The readback diff compares against THIS, not against a re-derivation.

    Re-deriving what was sent is where the defect lives: G2 produced a false
    `absent` by transforming a name, and the same trap exists for values -- a
    boolean emitted as `1` must not be compared as `True`.
    """
    plan = plan_resolve(
        intent({"spiral-vase": True, "perimeters": 4}), PRUSASLICER, Path(__file__), Path("s")
    )
    assert plan.requested == {"spiral-vase": "1", "perimeters": "4"}


def test_an_empty_subject_set_plans_a_run_that_checks_nothing(tmp_path: Path) -> None:
    """G1/D24: the first file anyone writes. `keys_checked` is 0, and the run that
    follows is `empty` at exit 3 rather than `sliced` at 0."""
    sidecar = tmp_path / "x.ini"
    staged = tmp_path / "staging" / "readback"
    plan = plan_resolve(intent(), PRUSASLICER, sidecar, staged)
    assert plan.keys_checked == 0
    assert plan.requested == {}
    assert f"--save={staged.resolve()}" in plan.argv


def test_keys_checked_counts_the_authored_delta_not_the_resolution() -> None:
    """The mechanism adjudicates ~2-10 keys and only RECORDS the other ~370.

    G1's deeper point, and it is easy to lose: a 376-key resolution is not 376
    checks. Presenting it as one would be the vacuous green wearing a bigger number.
    """
    plan = plan_resolve(
        intent({"perimeters": 4, "fill-density": "60%"}), PRUSASLICER, Path(__file__), Path("s")
    )
    assert plan.keys_checked == 2


def test_plan_is_frozen() -> None:
    plan = plan_resolve(intent(), PRUSASLICER, Path(__file__), Path("s"))
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
    plan = plan_resolve(intent({"perimeters": 4}), PRUSASLICER, Path("rel.ini"), Path("rel.staged"))
    assert plan.destination.is_absolute()
    assert plan.staged.is_absolute()
    assert plan.paths == frozenset({str(tmp_path / "rel.staged")})
    assert f"--save={tmp_path / 'rel.staged'}" in plan.argv


def test_the_engine_is_never_granted_the_author_s_path(tmp_path: Path) -> None:
    """The engine writes the staging path and is given access to nothing else.

    Its dump is unredacted at the moment it is written -- on 2.9.6 a preset triple
    emits six credential-bearing keys in cleartext -- so the author's directory,
    which the README's git model says you commit, is the one place it must not land.
    `paths` is what a sandboxed engine is granted (D19), so this is where that is
    enforced rather than merely intended.
    """
    sidecar = tmp_path / "out.ini"
    staged = tmp_path / "staging" / "readback"
    plan = plan_resolve(intent({"perimeters": 4}), PRUSASLICER, sidecar, staged)
    assert plan.paths == frozenset({str(staged.resolve())})
    assert str(sidecar.resolve()) not in plan.paths
    assert str(sidecar.resolve()) not in " ".join(plan.argv)
