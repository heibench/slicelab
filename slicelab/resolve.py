"""The `resolve` verb: what would this engine actually do with this intent?

Answers the question a `slice.toml` author has before they care about G-code — will
this file do what I think — without producing an artifact. That is what makes it
cheap: the engine is asked to dump its resolved configuration and nothing else, so a
run costs a preset load rather than a slice.

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
5. **Redact**, **promote**, then **diff**. The readback is the evidence; the diff is
   the verdict.

**The engine never writes the author's file.** It writes into a staging directory
slicelab owns and destroys, and slicelab promotes a redacted copy afterwards (D31,
and D7's mechanism applied to the readback). The dump is unredacted at the moment
the engine writes it: on 2.9.6 a stock preset triple emits `print_host`,
`printhost_apikey` and `printhost_cafile` -- empty under stock presets, and
carrying whatever a configured physical printer sets -- and `printhost_password`,
`printhost_port` and `printhost_user` join them as soon as anything sets those.
Which keys appear depends on what was loaded, so the list is a statement about this
build's namespace rather than about every run. Pointing `--save` at the destination
and overwriting it a moment later leaves those bytes on disk on every path that
fails in between, in the directory the README's git model says you commit.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
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

__all__ = ["ResolveError", "ResolveIncomplete", "Resolved", "resolve"]


class ResolveError(Exception):
    """The run could not happen at all. An environment fault, never a verdict.

    No engine, an engine that would not start, a configuration that could not be
    read. Org contract 2.2: none of these say anything about the intent, so they
    must not reach a caller wearing the same code as one that does.
    """


class ResolveIncomplete(Exception):
    """The engine ran, answered, and left nothing to adjudicate. `incomplete`, exit 2.

    Deliberately NOT a :class:`ResolveError`. An engine that exits non-zero having
    written no configuration -- an unknown option, a preset name that does not exist
    -- has not established an environment fault: it started, read the request, and
    said no. Reporting that as `error` (4) asserts something about the machine that
    nobody measured, and `sliced` and `refused` both claim more than slicelab knows,
    because the exit status alone cannot separate "your request was wrong" from
    "this install is broken" ([V5], [V10]).

    `incomplete` is the word for exactly this: slicelab ran and cannot stand behind
    an answer. The engine's own diagnosis is carried in the message, because it names
    the cause every time and discarding it leaves the author with nothing to act on.
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

    # The staging directory is slicelab's, and it is removed on every path this
    # function can leave by -- return, refusal or traceback. Not on SIGKILL, which
    # nothing can clean up after; what survives then is an unredacted dump inside a
    # mode-0700 temporary directory, which is a much smaller exposure than the
    # author's git tree and is the reason the destination is not the staging path.
    with tempfile.TemporaryDirectory(prefix="slicelab-readback-") as staging:
        plan = plan_resolve(intent, spec, sidecar, Path(staging) / "readback")
        completed = run(argv_for(found.form, plan.argv, plan.paths))
        text = _artifact(completed, plan.staged, spec, intent)
        readback = redact(text, spec.secret_keys)
        adjudication = diff(plan.requested, _parse(text), name_map)
        _promote(readback, plan.destination)

    return Resolved(adjudication=adjudication, readback=readback, sidecar=plan.destination)


def _promote(readback: Redacted, destination: Path) -> None:
    """Write the redacted copy where the author asked for it. D7's promote step.

    Promoted on every adjudicated outcome, not only on `sliced` -- which is where
    this parts from D7's letter, and D31 says why: for G-code a partial artifact is
    dangerous, whereas the readback IS the evidence for `incomplete` and for the
    `empty` run D24 requires be kept. A run that reached adjudication has a complete,
    engine-written dump; withholding it would leave the author with a verdict and
    nothing to check it against.

    **Written beside, then renamed.** `write_text` opens for writing, which truncates
    at open, so a failure part-way through -- ENOSPC, EDQUOT, EIO, a signal -- left
    the author holding a half-written file where their previous readback had been,
    while slicelab reported exit 4 and "nothing was established". Reproduced with a
    write limit: a 1191-byte readback became 8192 bytes of the new one and the old
    content was gone. An earlier revision of this docstring asserted there was no
    such window; there was, and D7 says stage-then-promote for exactly this reason.

    `os.replace` is atomic on POSIX and on Windows, so the destination holds the old
    bytes or the new ones and never a mixture. The temporary lives in the
    destination's OWN directory, because a rename across filesystems is not atomic
    and the staging directory is often on a different one.
    """
    # A rename REPLACES what is there, which `write_text` did not: writing to
    # `/dev/null` discarded the bytes harmlessly, whereas renaming onto it would
    # substitute a regular file for the device node. Only reachable for a caller who
    # can write the containing directory -- root, in a container -- and only for a
    # destination they named explicitly, but the old behaviour was harmless and the
    # new one is not, so the promote declines anything that is not a regular file.
    if destination.exists() and not destination.is_file():
        raise ResolveError(
            f"{destination} is not a regular file, and promoting the readback would replace it"
        )

    try:
        handle = tempfile.NamedTemporaryFile(  # noqa: SIM115 - closed in the finally below
            mode="w",
            encoding="utf-8",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".slicelab-partial",
            delete=False,
        )
    except OSError as exc:
        # Could not write the evidence. That establishes nothing about the intent,
        # so it is an environment fault -- an uncaught traceback here exited 1,
        # which is `refused`, and put `Traceback` where D14 requires the outcome
        # word.
        raise ResolveError(f"cannot write the readback to {destination}: {exc}") from exc

    beside = Path(handle.name)
    try:
        with handle:
            handle.write(readback.text)
        os.replace(beside, destination)
    except OSError as exc:
        # Whatever failed, the partial file does not survive. `delete=False` is what
        # lets the rename happen at all, and it also means nothing else removes this.
        with contextlib.suppress(OSError):
            beside.unlink()
        raise ResolveError(f"cannot write the readback to {destination}: {exc}") from exc


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


def _artifact(completed, staged: Path, spec: EngineSpec, intent: Intent) -> str:
    """D7's gate, applied to the readback rather than to a G-code file.

    Exit 0 is not evidence the engine wrote anything. V15: a post-processing script
    in the resolved configuration makes 2.9.6 print `Continue(Y/N)?` to stdout and
    block on stdin, headless, producing no file at all -- at exit 0, with zero bytes
    on stderr. And it is reachable from data rather than only from a flag, so an
    authored `[base]` can trigger it.

    `staged` is fresh by construction: it is a path inside a directory this call
    created, so "the file is there" cannot mean "last run's file is still there".
    The earlier revision pointed the engine at the author's own path and gated on
    file-exists-and-non-empty, and the default destination derives from the intent
    path -- so re-running one `slice.toml` in one directory, the ordinary workflow,
    made a run that wrote nothing report `sliced` at exit 0 against the previous
    run's configuration, timestamp and all.
    """
    if completed.died_by_signal:
        raise ResolveError(
            f"{spec.name} died on signal {completed.signal} reading {intent.source}, "
            "and a signal carries no cause"
        )
    if completed.timed_out:
        raise ResolveError(f"{spec.name} did not answer in time")

    try:
        wrote_something = staged.is_file() and staged.stat().st_size
    except OSError as exc:  # pragma: no cover - staging is slicelab's own directory
        raise ResolveError(f"cannot examine the dump {spec.name} was asked for: {exc}") from exc

    if not wrote_something:
        # The engine ran and produced no configuration. Whether that is the request's
        # fault or the machine's is not readable from the exit status, so slicelab
        # says the one thing it established -- it cannot stand behind an answer --
        # and hands over the engine's own words, which name the cause every time
        # ("Unknown option --not-a-real-option", "Printer profile '...' wasn't
        # found"). Discarding them left the author with a verdict and no hint what
        # to change, which is the failure D28 exists to avoid.
        raise ResolveIncomplete(
            f"{spec.name} exited {completed.exit_status} and wrote no configuration, "
            "so there is nothing to adjudicate: "
            f"{_diagnosis(completed)}"
        )
    if completed.exit_status != 0:
        # The file exists AND the engine failed. A dump written by a run that then
        # failed is not evidence of what that run resolved, and reading it anyway is
        # how the stale-artifact defect returns by a different route.
        raise ResolveIncomplete(
            f"{spec.name} exited {completed.exit_status} having written a "
            f"configuration, which is not evidence of what it resolved: "
            f"{_diagnosis(completed)}"
        )

    try:
        return staged.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:  # pragma: no cover - staging is slicelab's own directory
        raise ResolveError(f"cannot read the dump {spec.name} wrote: {exc}") from exc


def _diagnosis(completed) -> str:
    """The engine's own account of why, or a statement that it gave none.

    Never an empty string spliced into a sentence. "and wrote no configuration: "
    trailing off is indistinguishable from slicelab having dropped the message, and
    an engine that says nothing on either stream is itself a finding worth naming --
    V6's partial triple is exactly that.

    **Not the first line.** 2.9.6 answers a preset name that does not exist with

        Error while loading config from profiles:
        Printer profile 'No Such Printer 9000' wasn't found.

    where line one is a header and line two is the only sentence an author can act
    on. A `splitlines()[0]` here reproduced, inside the fix for it, exactly the
    defect the fix was written to remove. Every line is kept, joined, and truncated
    once at the end, so what is dropped is the tail of a long message rather than
    the cause.
    """
    for stream, label in ((completed.stderr, "stderr"), (completed.stdout, "stdout")):
        said = " ".join(line.strip() for line in (stream or "").splitlines() if line.strip())
        if said:
            return f"{label}: {said[:400]}"
    return "it said nothing on either stream"


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
