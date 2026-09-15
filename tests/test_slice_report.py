"""What the report says about an artifact that exists and was not handed over.

A run that fails reaches the author as a message rather than as a record, so D7's
"a withheld artifact is named" has to be satisfied by the reporting layer for those
outcomes. A mutation sweep found it was not pinned: emptying the line's producer
left all 421 tests green, because every test that asserts on it goes through the
returning path instead.
"""

from __future__ import annotations

from pathlib import Path

from slicelab.cli import _kept
from slicelab.resolve import ResolveError
from slicelab.slicing import _WITHHELD


def test_a_fault_carrying_a_withheld_artifact_is_reported_with_its_path() -> None:
    fault = ResolveError("cannot write the artifact")
    setattr(fault, _WITHHELD, Path("/scratch/slicelab-slice-abcd/artifact"))

    assert _kept(fault) == [
        "the artifact it did produce was kept at /scratch/slicelab-slice-abcd/artifact"
    ]


def test_a_fault_with_no_withheld_artifact_says_nothing() -> None:
    """The control, and the thing that matters more: [V4] and [V15] produce no
    artifact, and a report naming a path with no file at it is worse than silence."""
    assert _kept(ResolveError("no usable prusaslicer on this machine")) == []
