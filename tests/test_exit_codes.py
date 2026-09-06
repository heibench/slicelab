"""The exit map is the contract, so it is asserted value by value.

These numbers are the heibench org contract's section 6.2 table, settled
2026-09-06 across partspec, netspec and gerberdiff. If one of these assertions
has to change, that is an org-level conversation, not a fix.
"""

from __future__ import annotations

import pytest

from slicelab.status import KeyStatus, Outcome, exit_code_for, forced_outcome_for, worst_of


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        (Outcome.SLICED, 0),
        (Outcome.REFUSED, 1),
        (Outcome.INCOMPLETE, 2),
        (Outcome.ERROR, 4),
    ],
)
def test_each_outcome_maps_to_its_org_wide_code(outcome: Outcome, expected: int) -> None:
    assert exit_code_for(outcome) == expected


def test_only_sliced_is_green() -> None:
    """Everything a caller could mistake for success must not be zero."""
    non_green = [o for o in Outcome if o is not Outcome.SLICED]
    assert non_green, "guard against the enum being emptied"
    for outcome in non_green:
        assert exit_code_for(outcome) != 0, f"{outcome.value} must not exit 0"


def test_could_not_tell_and_environment_fault_are_distinct() -> None:
    """The two non-verdict codes must not collapse into each other.

    Adjudication A1 existed because two members used ``2`` for different
    things. An environment fault is not an inability to decide: one says the
    engine never ran, the other says it ran and slicelab could not conclude.
    """
    assert exit_code_for(Outcome.INCOMPLETE) != exit_code_for(Outcome.ERROR)


@pytest.mark.parametrize(
    ("status", "forced"),
    [
        (KeyStatus.APPLIED, None),
        (KeyStatus.COERCED, Outcome.REFUSED),
        (KeyStatus.ABSENT, Outcome.INCOMPLETE),
        (KeyStatus.UNSUPPORTED, Outcome.REFUSED),
        (KeyStatus.UNVALIDATED, Outcome.INCOMPLETE),
    ],
)
def test_each_key_status_forces_its_documented_outcome(
    status: KeyStatus, forced: Outcome | None
) -> None:
    assert forced_outcome_for(status) is forced


def test_refused_outranks_incomplete() -> None:
    """D14: a finding survives a partial inability to look.

    One key coerced and another absent is ``refused``. The reverse would let a
    single unreadable key mask a real unhonoured override, and exit 2 would
    invite a retry that can never change the answer.
    """
    assert worst_of([Outcome.INCOMPLETE, Outcome.REFUSED]) is Outcome.REFUSED
    assert worst_of([Outcome.REFUSED, Outcome.INCOMPLETE]) is Outcome.REFUSED


def test_a_clean_run_stays_sliced() -> None:
    assert worst_of([Outcome.SLICED, Outcome.SLICED]) is Outcome.SLICED


def test_incomplete_still_beats_sliced() -> None:
    assert worst_of([Outcome.SLICED, Outcome.INCOMPLETE]) is Outcome.INCOMPLETE


def test_an_empty_subject_set_is_empty_not_sliced() -> None:
    """The vacuous-green case, settled by D24.

    ``notes/critique.md`` G1: with zero requested keys, "every requested key
    was applied" is vacuously true, and a base-only slice.toml is the first
    file anyone writes. Returning SLICED here is the defect; EMPTY says the run
    happened and verified nothing, which is the truth.
    """
    assert worst_of([]) is Outcome.EMPTY
    assert exit_code_for(worst_of([])) == 3


def test_empty_is_not_green_and_not_a_finding() -> None:
    """It must be distinguishable from BOTH neighbours by exit code alone.

    That distinguishability is the whole argument for spending a code on it: a
    CI gate asking "does every slice.toml here verify anything?" branches on 3
    and cannot be written without it.
    """
    assert exit_code_for(Outcome.EMPTY) != exit_code_for(Outcome.SLICED)
    assert exit_code_for(Outcome.EMPTY) != exit_code_for(Outcome.REFUSED)
    assert exit_code_for(Outcome.EMPTY) != exit_code_for(Outcome.INCOMPLETE)


def test_empty_does_not_participate_in_precedence() -> None:
    """EMPTY answers "nothing to combine", it is not a rank among things.

    One applied key and one coerced key is a REAL run with a finding; it must
    not decay to EMPTY, and EMPTY must not outrank a finding.
    """
    assert worst_of([Outcome.SLICED, Outcome.REFUSED]) is Outcome.REFUSED
    assert worst_of([Outcome.SLICED]) is Outcome.SLICED
    assert Outcome.EMPTY not in {worst_of([Outcome.SLICED]), worst_of([Outcome.INCOMPLETE])}


def test_empty_matches_partspecs_code_for_the_same_idea() -> None:
    """3 is partspec's `empty`. Deliberate alignment, not a coincidence.

    It is NOT in the org contract's section 6.2 table, which lists 0/1/2/4/64.
    slicelab is the second member using it -- see D24 and the escalation.
    """
    assert exit_code_for(Outcome.EMPTY) == 3
