"""The `resolve` verb: what would this engine actually do with this intent?

Answers the question a `slice.toml` author has before they care about G-code — will
this file do what I think — without producing an artifact. That is what makes it
fast: the engine is asked to dump its resolved configuration and nothing else, so a
run is a fraction of a second rather than a slice.

The phases, and why each is separate:

1. **Read** the intent. An unknown key is refused here (D13), never ignored.
2. **Pre-flight.** Refusals slicelab can make without touching the engine, which is
   the whole of D15: a partial preset triple crashes PrusaSlicer with no diagnostic
   on either stream, so slicelab declines to compose that argv rather than reporting
   a signal it caused.
3. **Plan.** Pure. The argv is reviewable before anything runs.
4. **Run**, and **gate on the artifact** (D7). An engine that exits 0 having written
   nothing is the founding defect of this org, and it is not hypothetical here: a
   post-processing script in the resolved configuration makes PrusaSlicer 2.9.6 print
   an interactive prompt to stdout and produce no file, at exit 0, with zero bytes on
   stderr [V15].
5. **Redact**, then **diff**. The readback is the evidence; the diff is the verdict.
"""

from __future__ import annotations

import contextlib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from slicelab.adapters import EngineSpec
from slicelab.engine.characterise import CharacterisationError, MapEntry, load_name_map
from slicelab.engine.discover import Discovery, argv_for, discover
from slicelab.engine.identity import identify
from slicelab.engine.launch import run
from slicelab.intent import Intent, read_intent
from slicelab.plan import plan_resolve
from slicelab.preflight import preflight
from slicelab.readback import Adjudication, diff
from slicelab.redact import Redacted, redact
from slicelab.status import Outcome

__all__ = ["ResolveError", "Resolved", "resolve"]


class ResolveError(Exception):
    """The run could not happen at all. An environment fault, never a verdict.

    No engine, an engine that would not start, a configuration that could not be
    read. Org contract 2.2: none of these say anything about the intent, so they
    must not reach a caller wearing the same code as one that does.
    """


@dataclass(frozen=True)
class Resolved:
    """What one `resolve` run established."""

    adjudication: Adjudication
    readback: Redacted
    sidecar: Path

    @property
    def outcome(self) -> Outcome:
        """`empty` when nothing was requested, never `sliced` (D24, G1).

        The base-only `slice.toml` is the first file anyone writes, and over zero
        overrides "every requested key was applied" is vacuously true. The
        configuration was still dumped and is still kept -- the run happened and
        its evidence is real; it simply verified nothing.
        """
        return self.adjudication.outcome


def resolve(intent_path: Path, sidecar: Path) -> Resolved:
    """Ask the engine what it would resolve, and adjudicate the answer."""
    intent = read_intent(intent_path)
    spec = preflight(intent)
    found = discover(spec)
    if found.form is None:
        raise ResolveError(f"no usable {spec.name} on this machine")

    name_map = _name_map(spec, found)
    plan = plan_resolve(intent, spec, sidecar)

    # Discard any previous run's dump BEFORE launching. Without this the artifact
    # gate cannot tell "the engine wrote this" from "the engine wrote nothing and
    # last time's file is still here" -- and the default sidecar path is derived
    # from the intent path, so re-running one slice.toml in one directory, the
    # ordinary workflow, is exactly what arms it. Measured: an intent naming a
    # printer that does not exist makes the engine exit 1 saying so and write
    # nothing, and slicelab reported `sliced` at exit 0 against the previous run's
    # configuration, timestamp and all. `characterise._discard` has done this since
    # the probe existed -- "so the next probe cannot read the last one's" -- and the
    # omission here is the whole of the defect.
    with contextlib.suppress(OSError):
        plan.sidecar.unlink()

    completed = run(argv_for(found.form, plan.argv, plan.paths))
    text = _artifact(completed, plan.sidecar, spec, intent)
    readback = redact(text, spec.secret_keys)
    try:
        plan.sidecar.write_text(readback.text, encoding="utf-8")
    except OSError as exc:
        # Could not write the evidence. That establishes nothing about the intent,
        # so it is an environment fault -- an uncaught traceback here exited 1,
        # which is `refused`, and put `Traceback` where D14 requires the outcome
        # word.
        raise ResolveError(f"cannot write the readback to {plan.sidecar}: {exc}") from exc

    return Resolved(
        adjudication=diff(plan.requested, _parse(text), name_map),
        readback=readback,
        sidecar=plan.sidecar,
    )


def _name_map(spec: EngineSpec, found: Discovery) -> Mapping[str, MapEntry]:
    """The probed map for THIS build, or an environment fault naming why there is none.

    Never a fallback to deriving keys from option names. `notes/critique.md` G2
    measured what that costs -- a false `absent` on a perfectly applied key -- and
    the lesson is that no derivable rule exists, so the absence of a map is a reason
    to stop rather than a reason to guess.

    An **inexact** version is refused, which is the same shape as orlab's
    `profile_exact` (silence.html case 3). D30 makes the map a property of a build:
    two releases of one engine rename options and add keys. Keying a map on a
    version slicelab could not read means serving one build's measurements for
    another, silently, which is confidently wrong in the direction this project
    exists to refuse.
    """
    who = identify(spec, found)
    if not who.exact or who.version is None:
        raise ResolveError(
            f"{spec.name} did not state a version slicelab could read, and the "
            "option map is a property of a build -- using one measured against a "
            "different build would be a claim nobody established"
        )
    try:
        return load_name_map(spec, who.version)
    except CharacterisationError as exc:
        raise ResolveError(str(exc)) from exc


def _artifact(completed, sidecar: Path, spec: EngineSpec, intent: Intent) -> str:
    """D7's gate, applied to the readback rather than to a G-code file.

    Exit 0 is not evidence the engine wrote anything. V15: a post-processing script
    in the resolved configuration makes 2.9.6 print `Continue(Y/N)?` to stdout and
    block on stdin, headless, producing no file at all -- at exit 0, with zero bytes
    on stderr. And it is reachable from data rather than only from a flag, so an
    authored `[base]` can trigger it.
    """
    if completed.died_by_signal:
        raise ResolveError(
            f"{spec.name} died on signal {completed.signal} reading {intent.source}, "
            "and a signal carries no cause"
        )
    if completed.timed_out:
        raise ResolveError(f"{spec.name} did not answer in time")
    if not sidecar.is_file() or not sidecar.stat().st_size:
        raise ResolveError(
            f"{spec.name} exited {completed.exit_status} and wrote no configuration. "
            "An exit status is not evidence a file exists"
        )
    if completed.exit_status != 0:
        # The file exists AND the engine failed. Belt to the unlink's braces: a
        # dump written by a run that then failed is not evidence of what that run
        # resolved, and reading it anyway is how the stale-artifact defect returns
        # by a different route.
        raise ResolveError(
            f"{spec.name} exited {completed.exit_status} having written a "
            f"configuration: {completed.stderr.strip()[:200] or 'nothing on stderr'}"
        )
    return sidecar.read_text(encoding="utf-8", errors="replace")


def _parse(text: str) -> Mapping[str, str]:
    """The engine's dump as a mapping. Parsed from the ORIGINAL, not the redacted copy.

    A redacted value is `<redacted>`, and diffing against that would report a
    credential the author set as coerced -- slicelab's own removal surfacing as a
    finding about the engine.
    """
    resolved: dict[str, str] = {}
    for line in text.splitlines():
        key, separator, value = line.partition(" = ")
        if separator and not key.startswith(("#", "[")):
            resolved[key.strip()] = value
    return resolved
