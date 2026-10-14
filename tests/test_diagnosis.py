"""What slicelab carries from the engine's own account of a failure.

The engine's reason is the only thing an author can act on when a run is
`incomplete`, so dropping it costs them the whole message. It has been dropped twice
in different ways: once by taking `splitlines()[0]`, which kept a header and threw
away the sentence under it, and once by truncating from the front, which kept
whatever the runtime printed before the engine spoke.
"""

from __future__ import annotations

from slicelab.engine.launch import Completed
from slicelab.resolve import _DIAGNOSIS_BUDGET, _diagnosis

#: What the Flatpak launcher prints on a runner with no writable dbus path, verbatim
#: from the engine matrix. ~160 characters, and it appears twice before the engine
#: says anything.
NOISE = (
    "(/usr/bin/flatpak run:48295): dconf-CRITICAL **: 01:57:13.201: unable to create "
    "file '/run/user/1001/dconf/user': Permission denied.  dconf will not work properly."
)

#: 2.9.6 answering a preset name that does not exist. Line one is a header; line two
#: is the only sentence an author can act on.
CAUSE = (
    "Error while loading config from profiles:\n"
    "Printer profile 'No Such Printer 9000' wasn't found."
)


def _said(stderr: str) -> str:
    return _diagnosis(Completed(exit_status=1, signal=None, stdout="", stderr=stderr))


def test_the_engine_s_reason_survives_noise_printed_before_it() -> None:
    """The measured case, which failed at a 400-character budget.

    Two repetitions of the warning are ~320 characters on their own, so the cause fell
    outside 400 and the message stopped mid-word at `Printer profile 'No Such Print`.
    `test_a_previous_run_s_dump_is_never_adjudicated_as_this_run_s` failed with its own
    name for it: the engine named the cause and slicelab dropped it.
    """
    said = _said(f"{NOISE}\n{NOISE}\n{CAUSE}\n")

    assert len(said) > 400, "a shorter message would not establish anything here"
    assert "Printer profile 'No Such Printer 9000' wasn't found." in said


def test_what_falls_outside_the_budget_is_the_front() -> None:
    """Noise is prepended by the runtime and the cause is the last thing said, so the
    end is the half worth keeping. A leading ellipsis says something was cut."""
    said = _said(("x" * _DIAGNOSIS_BUDGET) + "\n" + CAUSE + "\n")

    assert "Printer profile 'No Such Printer 9000' wasn't found." in said
    assert said.startswith("stderr: ...")
    assert "xxxx" in said, "the budget is spent on the tail, not emptied"


def test_the_budget_keeps_what_was_said_around_the_cause() -> None:
    """What raising it from 400 buys, which is not the cause itself.

    With the tail kept, 400 would hold the cause as well -- the mutation lowering this
    number leaves every other assertion here green, which is how the first version of
    this comment came to justify the number with the wrong reason. The measured message
    is 422 characters joined, so at 400 the first warning is what gets cut: context the
    author needs, since a host that cannot write its runtime directory is worth knowing
    about.
    """
    said = _said(f"{NOISE}\n{NOISE}\n{CAUSE}\n")

    assert "..." not in said, "422 characters fits in the budget; nothing was dropped"
    assert said.count("dconf will not work properly") == 2, "both warnings, not one"


def test_a_message_inside_the_budget_is_carried_whole() -> None:
    """No ellipsis where nothing was dropped: "..." is a claim about what is missing."""
    said = _said(f"{CAUSE}\n")

    assert said == (
        "stderr: Error while loading config from profiles: "
        "Printer profile 'No Such Printer 9000' wasn't found."
    )
    assert "..." not in said


def test_an_engine_that_says_nothing_is_itself_reported() -> None:
    """Never an empty string spliced into a sentence: "and wrote no configuration: "
    trailing off cannot be told apart from slicelab having dropped the message."""
    assert _said("") == "it said nothing on either stream"
