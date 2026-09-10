"""The first token of output is the outcome word. Always.

Not a style preference. A past-tense verb leading a non-zero run reads green to
someone skimming CI logs, and every fact after it can be true while the line as
a whole misrepresents the run (``docs/DECISIONS.md`` D14).
"""

from __future__ import annotations

import pytest

from slicelab.report import render
from slicelab.status import Outcome


@pytest.mark.parametrize("outcome", list(Outcome))
def test_first_token_is_always_the_outcome_word(outcome: Outcome) -> None:
    text = render(outcome, "some summary", ["a detail line"])
    assert text.split()[0].rstrip(":") == outcome.value


@pytest.mark.parametrize("outcome", list(Outcome))
def test_first_token_holds_with_no_summary_and_no_detail(outcome: Outcome) -> None:
    assert render(outcome).split()[0].rstrip(":") == outcome.value


def test_detail_lines_are_indented_under_the_outcome() -> None:
    """The fixture is V1, and after D27 V1 is `incomplete` rather than `refused`.

    `render` is a pure formatter with no coupling to `forced_outcome_for`, so this
    passed either way -- which is exactly why it was the copy of the old claim that
    a sweep of the code missed. A depiction that cannot happen is still a depiction.
    """
    text = render(Outcome.INCOMPLETE, "1 override was not honoured", ["perimeters: 4.7 -> 4"])
    lines = text.splitlines()
    assert lines[0] == "incomplete: 1 override was not honoured"
    assert lines[1] == "  perimeters: 4.7 -> 4"


def test_a_non_green_outcome_never_leads_with_a_past_tense_success_verb() -> None:
    """The specific regression this rule exists to prevent.

    A proposed design printed `sliced part.gcode ... 1 override coerced` on a
    run that exited 2.
    """
    for outcome in Outcome:
        if outcome is Outcome.SLICED:
            continue
        text = render(outcome, "part.gcode 604407 B 100 layers")
        assert not text.startswith("sliced")
