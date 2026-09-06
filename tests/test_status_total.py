"""Every member of every status enum is mapped, with no default branch.

``exit_code_for`` and ``forced_outcome_for`` are exhaustive ``match``
statements ending in ``assert_never``, so mypy rejects a new enum member with
no case -- ``just check`` fails before ``just test`` runs. These tests are the
runtime half: they iterate the enum rather than restating a literal list, so a
member added without a mapping fails here too, on a machine with no type
checker.

The point of both halves is that a new outcome must be a *decision*. A dict
with ``.get(outcome, 2)`` would hand it a plausible number instead.
"""

from __future__ import annotations

from slicelab.status import KeyStatus, Outcome, exit_code_for, forced_outcome_for


def test_every_outcome_has_an_exit_code() -> None:
    for outcome in Outcome:
        assert isinstance(exit_code_for(outcome), int)


def test_every_key_status_has_a_forced_outcome_decision() -> None:
    """``None`` is a decision here, not a gap: APPLIED forces nothing."""
    for status in KeyStatus:
        forced = forced_outcome_for(status)
        assert forced is None or isinstance(forced, Outcome)


def test_no_two_outcomes_share_an_exit_code() -> None:
    """A collision would make the code unable to carry the distinction."""
    codes = [exit_code_for(o) for o in Outcome]
    assert len(set(codes)) == len(codes), f"exit codes collide: {codes}"


def test_outcome_values_are_the_words_the_renderer_prints() -> None:
    """The enum value IS the user-facing word; nothing translates between them."""
    assert {o.value for o in Outcome} == {"sliced", "refused", "incomplete", "error"}
