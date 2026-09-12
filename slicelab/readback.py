"""The mechanism: what was asked for, against what the engine says it resolved.

One mechanism justifies this whole tool and nothing else does. Everything else --
the lock, the multi-engine story, a native backend -- is downstream of this: ask the
engine what it *actually resolved*, diff that against what was requested, per key,
and refuse to call the run green when they disagree.

This module knows **no engine's vocabulary**. It is handed three things: what
slicelab emitted, what came back, and a map measured against the installed build.
The map is what stops it guessing. `notes/critique.md` G2 produced a false `absent`
on a perfectly applied key by transforming a name -- `--after-layer-gcode` writes
`layer_gcode` -- and the lesson is not "handle that one alias" but that **no
derivable rule exists**. So none is used here.

What this module will not do, in order of how much it would cost:

* **Never report `applied` on evidence it did not have.** A green on an unhonoured
  intent is the worst outcome in the system, worse than any false red, because a
  false red gets investigated and a false green does not.
* **Never turn a could-not-measure into a statement about the engine.** An option
  the probe timed out on is not an option the engine ignored. That distinction is
  what `MapEntry.conclusive` exists to carry, and collapsing it here would bring
  G2's defect back through the cache.
* **Never compare against a key it was not told to compare against.** Where an
  option writes several keys, all of them are checked; where the engine merely
  adjusted something nearby, none of them are.

An `INEXACT` entry is refused in **both** directions, and the reason usually given
for that -- the value may be wrapped, as Orca's JSON-list keys are -- is the weaker
half. (How many entries that is on a given engine is in D30's measured table, not
repeated here: a count in prose beside the thing it counts is a claim that rots,
and this one already had two different values in two files.)

The half that decides it is `characterise.py`'s: an inexact entry is one where
**the side-effect separation did not happen**, so its `keys` may contain the
engine's dependent constraints rather than the option's own. `--spiral-vase` probed
at the sentinels `('true', '1')` yields `INEXACT` carrying all five keys and zero
side effects. Adjudicating that would resurrect G4's false red against keys nobody
requested, which is a stronger objection than a wrapped value.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from slicelab.engine.characterise import MapEntry, ProbeOutcome, Tracking
from slicelab.status import KeyStatus, Outcome, forced_outcome_for, worst_of

__all__ = ["KeyVerdict", "Adjudication", "diff"]


@dataclass(frozen=True)
class KeyVerdict:
    """What slicelab established about one authored override."""

    option: str
    requested: str
    status: KeyStatus
    compared: tuple[str, ...]
    """The readback keys actually looked at. Empty when none could be.

    Recorded rather than re-derivable, which is `notes/critique.md` G2's first
    action: the report says *which* key was compared, so a reader can check the
    comparison rather than reconstruct it and get a different answer.
    """

    observed: tuple[str, ...]
    """What came back for each entry in :attr:`compared`, positionally."""

    reason: str


@dataclass(frozen=True)
class Adjudication:
    """Every authored override, adjudicated."""

    verdicts: tuple[KeyVerdict, ...]

    @property
    def keys_checked(self) -> int:
        """How many overrides were authored. The number D24 turns on.

        Zero means the run verified nothing and is `empty` at exit 3, never
        `sliced` -- "every requested key was applied" is vacuously true over an
        empty set (G1). Note this counts what was **authored**, not what was
        successfully adjudicated: a run of three overrides that could all only be
        recorded is `incomplete`, not `empty`, because something *was* asked.
        """
        return len(self.verdicts)

    @property
    def outcome(self) -> Outcome:
        """The run's outcome, combined from the per-key statuses (D14, D27).

        An applied key forces no outcome -- `forced_outcome_for` returns `None` --
        so it contributes `SLICED` rather than being dropped. Dropping it made an
        all-applied run `worst_of([])`, which is `EMPTY`: the answer to "nothing was
        requested", asserted over a run that requested several things and honoured
        them all. Two different silences collapsing into one word is the shape this
        module exists to refuse, and it reached the module itself first.
        """
        return worst_of([forced_outcome_for(v.status) or Outcome.SLICED for v in self.verdicts])


def diff(
    requested: Mapping[str, str],
    resolved: Mapping[str, str],
    name_map: Mapping[str, MapEntry],
) -> Adjudication:
    """Adjudicate each authored override against the engine's own readback.

    `requested` is what slicelab emitted, option name to the exact string sent --
    `Plan.requested`, not a reconstruction. `resolved` is the engine's dump, its
    own key names to its own values. `name_map` is the probed measurement tying
    one to the other.
    """
    return Adjudication(
        verdicts=tuple(
            _adjudicate(option, value, resolved, name_map.get(option))
            for option, value in sorted(requested.items())
        )
    )


def _adjudicate(
    option: str,
    value: str,
    resolved: Mapping[str, str],
    entry: MapEntry | None,
) -> KeyVerdict:
    def verdict(status: KeyStatus, reason: str, compared: tuple[str, ...] = ()) -> KeyVerdict:
        return KeyVerdict(
            option=option,
            requested=value,
            status=status,
            compared=compared,
            observed=tuple(resolved.get(k, "") for k in compared),
            reason=reason,
        )

    if entry is None:
        # Not a candidate the probe ever saw. That is NOT the engine saying no:
        # a candidate list can under-produce -- Orca's comes from its own dump
        # keys rather than a help listing -- so this is a could-not-tell about
        # slicelab's measurement, not a finding about the request.
        return verdict(
            KeyStatus.UNVALIDATED,
            "the characterisation never probed this option, so what it writes is unmeasured",
        )

    if entry.outcome is ProbeOutcome.UNKNOWN_OPTION:
        # The engine itself said there is no such option. That IS a finding.
        return verdict(
            KeyStatus.UNSUPPORTED,
            "the engine has no such option",
        )

    if not entry.conclusive:
        return verdict(
            KeyStatus.UNVALIDATED,
            f"the probe could not establish what this option writes ({entry.outcome.value})",
        )

    if entry.outcome is ProbeOutcome.NO_KEY_MOVED:
        return verdict(
            KeyStatus.UNVALIDATED,
            "this option writes no configuration key, so the readback cannot show whether "
            "it was honoured",
        )

    if entry.tracking is not Tracking.EXACT or not entry.keys:
        # A WHITELIST, and the distinction is the whole finding. An earlier revision
        # asked `is Tracking.INEXACT` -- adjudicate everything except one named
        # failure -- while the module's stated principle is the opposite: adjudicate
        # only what was measured exactly. Two live routes to a false `applied` came
        # through that inversion, both via the cache loader, which `_read_cache`
        # itself anticipates ("a truncated or hand-edited cache"):
        #
        #   MAPPED with keys=()      -> `missing` and `differing` are both empty
        #                               comprehensions over an empty tuple, so both
        #                               guards pass and the verdict is `applied`
        #                               over ZERO compared keys, reason and all.
        #                               That is G1's vacuous green one level down,
        #                               inside the module written to refuse it.
        #   MAPPED with tracking=None -> never EXACT, never INEXACT, so it fell
        #                               through to the strict-equality path reserved
        #                               for a measurement nobody made.
        #
        # This is also D26's lesson for the third time in this project: a rule that
        # names what it refuses is only as complete as the list, and a rule that
        # names what it permits is complete by construction.
        if not entry.keys:
            return verdict(
                KeyStatus.UNVALIDATED,
                "the probe recorded no keys for this option, so there is nothing a "
                "comparison could look at",
            )
        return verdict(
            KeyStatus.UNVALIDATED,
            "the probe could not tie this option's value to its keys verbatim, so the "
            "comparison would not mean what it appears to",
        )

    missing = [key for key in entry.keys if key not in resolved]
    differing = [key for key in entry.keys if key in resolved and resolved[key] != value]
    if missing:
        # Absence is not evidence: the readback's key SET is value-dependent --
        # `bed_custom_texture` is in no default dump and appears the moment it is
        # set -- so a key that is not there has not been shown to be unhonoured.
        return verdict(
            KeyStatus.ABSENT,
            f"{', '.join(missing)} did not appear in the readback, and a key set that "
            "varies with its values cannot make absence mean anything"
            + (f"; separately, {', '.join(differing)} came back different" if differing else ""),
            entry.keys,
        )

    if differing:
        # Requested is not resolved, and the cause is unknown (D27). Not `refused`:
        # slicelab cannot tell the engine ignoring a request from the engine
        # applying a documented dependent constraint, and asserting either would
        # name a cause it never established.
        return verdict(
            KeyStatus.COERCED,
            f"requested {value!r}, and "
            + ", ".join(f"{k} came back {resolved[k]!r}" for k in differing),
            entry.keys,
        )

    return verdict(
        KeyStatus.APPLIED,
        f"every key this option writes came back {value!r}",
        entry.keys,
    )
