"""Where the artifact is allowed to land, decided before the engine is asked.

`plan_slice` composes one invocation that both slices and dumps the resolved
configuration, which means one run writes to two paths the author chose separately.
Nothing stops those from being the same path, or from being an input to the run --
and each collision was measured to produce `sliced` at exit 0 with the declared
path holding something that is not this run's G-code:

* `gcode = "slice.readback.ini"` promotes the artifact, promotes the readback over
  it, and reports success. The file left behind is a 14787-byte configuration dump.
* `gcode = "part.stl"` overwrites the mesh being sliced with the result of slicing
  it.

Both are refusals rather than gates, because the answer is knowable from the intent
alone and a slice takes a minute. Pure: no engine on the machine is required.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from slicelab.adapters import PRUSASLICER
from slicelab.intent import Intent
from slicelab.plan import PlanError, plan_slice

TRIPLE = {
    "printer-profile": "Original Prusa i3 MK3S & MK3S+",
    "print-profile": "0.20mm QUALITY @MK3",
    "material-profile": "Prusament PLA",
}


def _intent(tmp_path: Path, gcode: str) -> Intent:
    (tmp_path / "part.stl").write_text("solid cube\nendsolid cube\n", encoding="utf-8")
    return Intent(
        engine="prusaslicer",
        base=dict(TRIPLE),
        overrides={},
        source=tmp_path / "slice.toml",
        model=tmp_path / "part.stl",
        gcode=tmp_path / gcode,
    )


def _plan(intent: Intent, tmp_path: Path):
    return plan_slice(intent, PRUSASLICER, tmp_path / "staged", tmp_path / "staged.ini")


def test_a_plan_that_sends_the_artifact_where_the_readback_goes_is_refused(
    tmp_path: Path,
) -> None:
    """Measured: without this, exit 0 and the configuration dump stands in the
    G-code's place. The readback destination is derived from the intent's own name,
    so an author who names their output after their intent collides by accident."""
    intent = _intent(tmp_path, "slice.readback.ini")
    with pytest.raises(PlanError, match="where the readback goes"):
        _plan(intent, tmp_path)


def test_a_plan_that_sends_the_artifact_onto_its_own_model_is_refused(
    tmp_path: Path,
) -> None:
    intent = _intent(tmp_path, "part.stl")
    with pytest.raises(PlanError, match="the model this run slices"):
        _plan(intent, tmp_path)


def test_a_plan_whose_output_directory_does_not_exist_is_refused(tmp_path: Path) -> None:
    """Refused rather than discovered after a minute of slicing, and refused in
    slicelab's own words rather than by leaking the name of a partial staging file
    the author never asked for."""
    intent = _intent(tmp_path, "nowhere/part.gcode")
    with pytest.raises(PlanError, match="is not a directory"):
        _plan(intent, tmp_path)


def test_a_plan_whose_model_is_not_a_file_is_refused(tmp_path: Path) -> None:
    """`refused`, not `error`: the intent names something slicelab can read the
    intent well enough to reject. Handing a missing mesh to 2.9.6 is one more
    exit-0-with-a-configuration."""
    intent = _intent(tmp_path, "part.gcode")
    (tmp_path / "part.stl").unlink()
    with pytest.raises(PlanError, match="names a model slicelab cannot read"):
        _plan(intent, tmp_path)


def test_a_model_that_is_a_directory_is_refused(tmp_path: Path) -> None:
    intent = _intent(tmp_path, "part.gcode")
    (tmp_path / "part.stl").unlink()
    (tmp_path / "part.stl").mkdir()
    with pytest.raises(PlanError, match="names a model slicelab cannot read"):
        _plan(intent, tmp_path)


def test_distinct_destinations_plan_normally(tmp_path: Path) -> None:
    """The control. Four refusals that fire on everything would pass every test
    above and ship a verb that cannot slice."""
    plan = _plan(_intent(tmp_path, "part.gcode"), tmp_path)
    assert plan.artifact_destination == (tmp_path / "part.gcode").resolve()
    assert plan.destination == (tmp_path / "slice.readback.ini").resolve()
    assert plan.model == (tmp_path / "part.stl").resolve()


def test_a_plan_with_no_model_is_refused(tmp_path: Path) -> None:
    """`plan_slice` is reachable with either table absent -- `read_intent` accepts an
    intent with no `[geometry]`, because `resolve` does not need one."""
    intent = _intent(tmp_path, "part.gcode")
    with pytest.raises(PlanError, match="declares no .geometry. model"):
        _plan(replace(intent, model=None), tmp_path)


def test_a_plan_with_nowhere_to_put_the_result_is_refused(tmp_path: Path) -> None:
    """A mutation sweep found this refusal had no red state: removing it left all 408
    tests green, and what stood behind it was an `AttributeError` on `None`."""
    intent = _intent(tmp_path, "part.gcode")
    with pytest.raises(PlanError, match="declares no .output. gcode"):
        _plan(replace(intent, gcode=None), tmp_path)


def test_a_plan_that_sends_the_artifact_onto_the_intent_is_refused(tmp_path: Path) -> None:
    """The same sentence as the model, about the other input.

    Measured before this refusal existed: the intent was overwritten with 599093
    bytes of G-code at exit 0, and the report named its sha256 as what had been
    "displaced". A run whose own description is gone cannot be repeated, which makes
    it the one destination collision that destroys more than a file.
    """
    intent = _intent(tmp_path, "slice.toml")
    with pytest.raises(PlanError, match="the intent itself"):
        _plan(intent, tmp_path)


def test_a_plan_whose_destination_is_a_directory_is_refused(tmp_path: Path) -> None:
    """`promote` refuses this too -- after the slice. Minutes on a real part, and it
    reports `error` where the collisions above report `refused`, for the same class
    of fact. Knowable from the intent, so answered from the intent."""
    (tmp_path / "part.gcode").mkdir()
    with pytest.raises(PlanError, match="not a regular file"):
        _plan(_intent(tmp_path, "part.gcode"), tmp_path)


def test_a_destination_that_is_a_regular_file_is_not_refused(tmp_path: Path) -> None:
    """The control for the one above. Replacing an existing G-code file is the
    ordinary case -- a refusal that fired on it would make re-slicing impossible."""
    (tmp_path / "part.gcode").write_text("PREVIOUS\n", encoding="utf-8")
    plan = _plan(_intent(tmp_path, "part.gcode"), tmp_path)
    assert plan.artifact_destination == (tmp_path / "part.gcode").resolve()
