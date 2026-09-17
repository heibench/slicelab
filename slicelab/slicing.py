"""The `slice` verb: produce the artifact, and refuse to hand it over unless it is one.

`resolve` asks the engine what it would do. `slice` makes it do it, and the whole
difference is the gate: **exit 0 plus a configuration dump is not evidence a slice
happened.** Two independent measurements say so, and neither is exotic.

[V4] `--scale 30` puts the object outside the print volume. 2.9.6 exits **0**, writes
no G-code, and writes a complete 9957-byte configuration anyway, because `--save`
executes before the slice block and is not conditioned on it. [V15] a post-processing
script in the *resolved configuration* makes it print `Continue(Y/N)?` to stdout and
block on stdin, headless: exit **0**, no G-code, no configuration, zero bytes on
stderr -- and reachable from data through a `--load`ed file, not only from a flag.

A third arrived while this module was written, and it is the one that settles the
argument. `--export-gcode=<model> -o=<path>` -- a plausible way to compose the argv,
and wrong -- is accepted at exit 0 and writes a complete configuration and no G-code.
So does `-o <path>` with `--export-gcode=<model>`. **slicelab's own argv bug is
indistinguishable from the engine refusing the request**, which means the gate is not
protection against the engine; it is protection against being wrong at all.

So the engine slices into a directory slicelab owns, and slicelab promotes to the
author's path only on `sliced` -- or on `empty`, which is D24's carve-out from D7 and
is not a fault. The destination is never deleted, and an artifact the engine produced
that slicelab withheld outlives the run at a path the report names.
"""

from __future__ import annotations

import hashlib
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from slicelab.container import Container, sniff
from slicelab.engine.configured import ConfigState, configuration_state
from slicelab.engine.discover import argv_for, discover
from slicelab.engine.launch import run
from slicelab.intent import read_intent
from slicelab.plan import plan_slice
from slicelab.preflight import preflight
from slicelab.promote import PromotionError, promote
from slicelab.readback import Adjudication, diff
from slicelab.redact import Redacted, redact
from slicelab.resolve import (
    ResolveError,
    ResolveIncomplete,
    _diagnosis,
    _name_map,
    _parse,
    _promote_readback,
)
from slicelab.status import Outcome

__all__ = ["Sliced", "slice_intent", "withheld_by"]

#: The outcomes whose artifact reaches the author's path. D7 says `sliced`; D24 adds
#: `empty` as an explicit carve-out, because an intent that asserted nothing produced
#: a G-code file that nothing was found wrong with.
_HANDED_OVER: Final = frozenset({Outcome.SLICED, Outcome.EMPTY})

#: Attribute an artifact-withholding fault carries the staged path on. Set here and
#: read by the reporting layer, which is the only place that knows how to say it.
_WITHHELD: Final = "_slicelab_withheld_artifact"


@dataclass(frozen=True)
class Sliced:
    """What one `slice` run established."""

    adjudication: Adjudication
    readback: Redacted
    artifact: Path | None
    """Where the artifact ended up, or `None` when it was not promoted."""

    container: Container
    destination_prehash: str | None
    """sha256 of whatever stood at the destination before this run replaced it.

    `None` when nothing stood there. D7 requires it because "this file is here" does
    not establish "this run wrote it" -- and the mtime check that would be the obvious
    alternative was measured and rejected: 198 of 200 tmpfs writes had identical
    `st_mtime_ns`. The prehash says what was displaced, which is the question a reader
    actually has.
    """

    withheld: Path | None
    """The artifact the engine produced and slicelab did not hand over.

    `None` when it was handed over, and `None` when the engine produced none. D7
    requires a withheld artifact to be named, which is only worth saying if the file
    is still there -- so the scratch directory outlives the run in exactly this case.
    """

    @property
    def outcome(self) -> Outcome:
        return self.adjudication.outcome


def slice_intent(intent_path: Path) -> Sliced:
    """Slice what the intent names, and adjudicate what came back."""
    intent = read_intent(intent_path)
    spec = preflight(intent)
    found = discover(spec)
    if found.form is None:
        raise ResolveError(f"no usable {spec.name} on this machine")
    if configuration_state(spec, found) is ConfigState.ABSENT:
        raise ResolveError(
            f"{spec.name} is installed but not configured. Run the engine once to "
            "create one. reason = engine_has_no_configuration"
        )
    name_map = _name_map(spec, found)

    scratch = Path(tempfile.mkdtemp(prefix="slicelab-slice-"))
    staged_artifact = scratch / "artifact"
    promoted: Path | None = None
    keep = False
    try:
        plan = plan_slice(intent, spec, staged_artifact, scratch / "readback")
        completed = run(
            argv_for(found.form, plan.argv, plan.paths),
            capture=(spec.run_record.name,) if spec.run_record else (),
        )
        assert plan.staged_artifact is not None and plan.artifact_destination is not None

        _gate(completed, plan.staged_artifact, spec, intent_path)
        text = _configuration(completed, plan.staged, spec, intent_path)
        readback = redact(text, spec)
        # Sniffed before adjudication, on purpose: D31 promises the readback of any
        # run that reached a verdict, and everything standing between the verdict
        # and that promotion is a line that can fail. This one opens a file. Moved
        # above `diff`, the only thing left between them is `_prehash`, which cannot
        # raise.
        container = sniff(plan.staged_artifact, spec.binary_container_magic)
        adjudication = diff(plan.requested, _parse(text, spec), name_map)

        prehash = _prehash(plan.artifact_destination)
        # The readback goes first, and unconditionally. It is evidence for a verdict of
        # any kind, and going second is how a run that exits 4 promoting it leaves the
        # author's artifact already replaced -- which makes "nothing was handed over"
        # false in exactly the case it most needs to be true.
        _promote_readback(readback, plan.destination)
        if adjudication.outcome in _HANDED_OVER:
            # `sliced`, and `empty` by D24's carve-out from D7: `empty` is not a fault,
            # it is a valid artifact against an intent that asserted nothing, and
            # withholding it would punish an author for not having written an override
            # yet. Every other outcome keeps the file, because handing over an artifact
            # from a run slicelab could not stand behind is the failure it is named for.
            # The read is outside the `try`: a failure to read slicelab's own scratch is
            # not a failure to write the author's path, and reporting it as one was
            # what the old `(OSError, PromotionError)` arm did.
            payload = plan.staged_artifact.read_bytes()
            try:
                promote(payload, plan.artifact_destination)
            except PromotionError as unwritable:
                raise ResolveError(f"cannot write the artifact: {unwritable}") from unwritable
            promoted = plan.artifact_destination

        keep = promoted is None
        return Sliced(
            adjudication=adjudication,
            readback=readback,
            artifact=promoted,
            container=container,
            destination_prehash=prehash,
            withheld=plan.staged_artifact if keep else None,
        )
    except Exception as fault:
        # EVERY fault, not the two the happy path raises. `redact` refuses on an
        # unmeasured secret key, `sniff` opens a file, `promote` writes one -- each
        # can fail after the engine has produced a perfectly good artifact, and
        # deleting it because the failure came from an unexpected class is the same
        # loss by a different route.
        #
        # The path travels ON the exception rather than inside a rebuilt message:
        # `type(fault)(str(fault) + ...)` assumes every class takes one string
        # argument, which is true of these two today and is not a property anything
        # checks. `KeyboardInterrupt` is deliberately not caught -- an author who
        # interrupted a slice did not ask for its leftovers.
        if _is_an_artifact(staged_artifact):
            keep = True
            setattr(fault, _WITHHELD, staged_artifact)
        raise
    finally:
        # D7: a withheld artifact is named in the report, and a path naming a deleted
        # file is not a report. Kept only where it was named -- an engine that wrote no
        # artifact leaves nothing worth keeping, and keeping it unannounced is litter.
        if not keep:
            shutil.rmtree(scratch, ignore_errors=True)


def _gate(completed, staged: Path, spec, source: Path) -> None:
    """D7, on the artifact. The engine ran; did it produce one?

    Asked of the FILE, never of the exit status, because the two disagree in both
    directions and the disagreement is the ordinary case rather than the exotic one.
    """
    if completed.died_by_signal:
        raise ResolveError(
            f"{spec.name} died on signal {completed.signal} slicing {source}, "
            "and a signal carries no cause"
        )
    if completed.timed_out:
        raise ResolveError(f"{spec.name} did not finish slicing {source} in time")

    try:
        wrote_something = _is_an_artifact(staged)
    except OSError as exc:  # pragma: no cover - staging is slicelab's own directory
        raise ResolveError(f"cannot examine the artifact {spec.name} was asked for: {exc}") from exc

    if not wrote_something:
        raise ResolveIncomplete(
            f"{spec.name} exited {completed.exit_status} and wrote no artifact, so there "
            f"is nothing to hand over: {_diagnosis(completed)}"
        )
    if completed.exit_status != 0:
        raise ResolveIncomplete(
            f"{spec.name} exited {completed.exit_status} having written an artifact, "
            f"which is not evidence of what it produced: {_diagnosis(completed)}"
        )


def _configuration(completed, staged: Path, spec, source: Path) -> str:
    """The configuration from the SAME invocation that produced the artifact.

    Its absence is `incomplete` rather than an error: the engine sliced, so something
    happened, and slicelab cannot adjudicate what without the document. [V15] is the
    case where neither appears.
    """
    try:
        wrote_something = staged.is_file() and staged.stat().st_size
    except OSError as exc:  # pragma: no cover - staging is slicelab's own directory
        raise ResolveError(f"cannot examine the configuration for {source}: {exc}") from exc
    if not wrote_something:
        raise ResolveIncomplete(
            f"{spec.name} produced an artifact and no configuration, so what it resolved "
            f"cannot be adjudicated: {_diagnosis(completed)}"
        )
    try:
        return staged.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:  # pragma: no cover - staging is slicelab's own directory
        raise ResolveError(f"cannot read the configuration {spec.name} wrote: {exc}") from exc


def _is_an_artifact(staged: Path) -> bool:
    """Present AND non-empty, which is one definition used in two places.

    The engine creates `-o` before it has anything to put in it, so `is_file()` alone
    says yes to a run that failed immediately. Split across the gate and the
    withholding clause, the two disagreed: one report said the engine "wrote no
    artifact" and then named the zero-byte artifact it had kept.
    """
    return staged.is_file() and staged.stat().st_size > 0


def _prehash(destination: Path) -> str | None:
    """sha256 of what stands at the destination now, or `None` if nothing does."""
    try:
        with destination.open("rb") as handle:
            return hashlib.file_digest(handle, "sha256").hexdigest()
    except OSError:
        return None


def withheld_by(fault: BaseException) -> Path | None:
    """The artifact a failed run produced and slicelab kept, or `None`.

    D7 requires a withheld artifact to be named. A run that fails reaches the author
    as a message rather than as a :class:`Sliced`, so the path rides on the exception
    and is rendered by whoever renders the message.
    """
    return getattr(fault, _WITHHELD, None)
