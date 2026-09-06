"""The outcome vocabulary and the exit map.

This module is the thesis. It imports nothing else from ``slicelab`` and
depends on no engine, so the exit contract is fixed before anything exists to
muddy it.

Exit codes are the heibench org contract's section 6.2 table, which became the
settled org-wide vocabulary on 2026-09-06 when adjudications A1, A2 and A3
closed. slicelab **conforms to that table; it does not choose numbers.** A1
existed because two members picked ``2`` for different meanings and nobody
noticed until a consumer would have.

Only the *words* diverge. Section 6.1 scopes ``pass``/``fail`` to "every member
that adjudicates", and slicelab adjudicates nothing about the G-code -- that is
slicespec's job -- so calling a slice ``pass`` would claim a check that did not
happen. See ``docs/DECISIONS.md`` D14.
"""

from __future__ import annotations

from enum import StrEnum
from typing import assert_never

__all__ = [
    "EXIT_USAGE",
    "KeyStatus",
    "Outcome",
    "UnknownCode",
    "exit_code_for",
    "forced_outcome_for",
    "worst_of",
]


class Outcome(StrEnum):
    """What slicelab is willing to say about a whole run."""

    SLICED = "sliced"
    """The artifact exists, is non-empty, was promoted by this run, its config
    export was captured in the same invocation, every requested key came back
    applied, and the adapter was exact."""

    REFUSED = "refused"
    """slicelab established that the declared intent was not honoured. The
    driver's analogue of *violated*: we looked, and the answer is no."""

    INCOMPLETE = "incomplete"
    """slicelab ran but cannot stand behind the result. Never reachable from an
    unexamined success path."""

    EMPTY = "empty"
    """The run completed and verified nothing, because nothing was requested.

    Neither a success nor a finding. A ``slice.toml`` with a ``[base]`` triple
    and an empty ``[set]`` produces a real artifact, and "every requested key
    was applied" is vacuously true over zero keys -- the vacuous green
    ``notes/critique.md`` G1 reproduced. See D24.
    """

    ERROR = "error"
    """Environment fault. NOT a verdict on the intent (org contract 2.2)."""


EXIT_USAGE = 64
"""``EX_USAGE`` from sysexits.h: slicelab's own argv was wrong.

Deliberately not ``2``. argparse exits ``2`` on a bad flag, and ``2`` is
"could not tell" -- so an unremapped argparse leaks a usage error into a
verdict. netspec and gerberdiff both *declared* 64 and *returned* 2; see
``notes/evidence.md`` V14. ``cli`` performs the remap, and the test measures a
real process rather than asserting this constant.
"""


def exit_code_for(outcome: Outcome) -> int:
    """Map an outcome to its process exit code.

    Written as an exhaustive ``match`` with ``assert_never`` rather than a dict
    lookup with a default. Adding a member to :class:`Outcome` without adding a
    case here is a **type error**, caught by ``just check`` before any test
    runs. A dict with ``.get(outcome, 2)`` would silently give a new outcome a
    plausible number, which is precisely the substitution this project exists
    to refuse.
    """
    match outcome:
        case Outcome.SLICED:
            return 0
        case Outcome.REFUSED:
            return 1
        case Outcome.INCOMPLETE:
            return 2
        case Outcome.EMPTY:
            return 3
        case Outcome.ERROR:
            return 4
    assert_never(outcome)


class KeyStatus(StrEnum):
    """What happened to one authored override, per ``docs/DECISIONS.md`` D14.

    Deliberately NOT ``pass``/``fail``. Reusing checker vocabulary per-setting
    is the cargo-cult that netspec's ``test_report_carries_no_tolerance``
    exists to prevent.
    """

    APPLIED = "applied"
    """Present in the engine's readback with exactly the requested value."""

    COERCED = "coerced"
    """Present, value differs (``notes/evidence.md`` V1).

    ``notes/critique.md`` G4 is unresolved and lands with the readback issue:
    slicelab cannot yet distinguish "the engine ignored you" from "the engine
    applied a documented dependent constraint", and a NORMALIZED member is not
    added here before the probe that would justify telling them apart.
    """

    ABSENT = "absent"
    """Not in the readback at all (``notes/evidence.md`` V2). We cannot tell
    whether it was honoured under another name, so this is a could-not-tell."""

    UNSUPPORTED = "unsupported"
    """The adapter declined to translate it. Unreachable while the core
    vocabulary is empty (D2), because there is nothing to decline."""

    UNVALIDATED = "unvalidated"
    """A passthrough key that did not surface in the readback."""


def forced_outcome_for(status: KeyStatus) -> Outcome | None:
    """The run outcome one key's status forces, or ``None`` if it forces none.

    Exhaustive for the same reason :func:`exit_code_for` is.
    """
    match status:
        case KeyStatus.APPLIED:
            return None
        case KeyStatus.COERCED:
            return Outcome.REFUSED
        case KeyStatus.ABSENT:
            return Outcome.INCOMPLETE
        case KeyStatus.UNSUPPORTED:
            return Outcome.REFUSED
        case KeyStatus.UNVALIDATED:
            return Outcome.INCOMPLETE
    assert_never(status)


_PRECEDENCE: tuple[Outcome, ...] = (Outcome.SLICED, Outcome.INCOMPLETE, Outcome.REFUSED)
"""Least to most severe, over the outcomes a set of key statuses can produce.

``REFUSED`` outranks ``INCOMPLETE`` (D14): a finding about the request is
something slicelab established, and it stays one even when some other key could
not be evaluated. The reverse would let a single unreadable key mask a real
unhonoured override, and exit 2 would invite a retry that can never change the
answer.

Adopted from netspec D26's "fail outranks incomplete" rather than re-derived.
partspec's diff verbs order "different" over "indeterminate" for the same
reason; three layers, one rule.

``ERROR`` is deliberately absent. An environment fault means the engine never
produced a readback, so there are no key statuses to combine -- it is not more
severe than a verdict, it is not a verdict at all (org contract 2.2).
"""


def worst_of(outcomes: list[Outcome]) -> Outcome:
    """Combine the outcomes forced by individual keys.

    An **empty** input returns :attr:`Outcome.EMPTY`, not
    :attr:`Outcome.SLICED`. Nothing was requested, so nothing was verified, and
    saying ``sliced`` over zero checks is the vacuous green this project exists
    to refuse (D24, ``notes/critique.md`` G1).

    :attr:`Outcome.EMPTY` never participates in the precedence ordering: it is
    the answer to "there was nothing to combine", not a rank among things that
    were.
    """
    if not outcomes:
        return Outcome.EMPTY
    return max(outcomes, key=_PRECEDENCE.index)


class UnknownCode(StrEnum):
    """Closed vocabulary for what a run could not establish.

    Carried in the lock so a consumer can branch on our ignorance rather than
    infer it from absence. Members are added only when a decision names one;
    this enum is not a place to speculate.
    """

    CROSS_MACHINE_REPRODUCIBILITY_UNESTABLISHED = "cross_machine_reproducibility_unestablished"
    """Every determinism measurement behind this tool is one host, one build,
    one architecture. Rides on every lock until a second machine says otherwise
    (``docs/RESEARCH.md`` section 4)."""

    REPRODUCIBILITY_NOT_ESTABLISHED = "reproducibility_not_established"
    """``slice`` ran but no determinism probe did, so whether this
    configuration reproduces is unmeasured, not assumed (D8)."""

    BINARY_CONTAINER_NO_NORMALIZED_HASH = "binary_container_no_normalized_hash"
    """The output is a ``GCDE`` container, so the text normalizer does not
    apply and no normalized hash exists (D9, D10). Not an error: bgcode is the
    stock default for the current Prusa line."""
