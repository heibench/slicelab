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
author's path only on `sliced` (D7). The destination is never deleted, and the staged
path is named in every report that is not one.
"""

from __future__ import annotations

import hashlib
import tempfile
from dataclasses import dataclass
from pathlib import Path

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

__all__ = ["Sliced", "slice_intent"]


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
    if intent.model is not None and not intent.model.is_file():
        # Checked before the engine, because slicelab named this path and can say so
        # plainly. Handing a missing mesh to 2.9.6 is another exit-0-with-a-config.
        raise ResolveError(f"{intent_path} names a model slicelab cannot read: {intent.model}")

    name_map = _name_map(spec, found)

    with tempfile.TemporaryDirectory(prefix="slicelab-slice-") as staging:
        scratch = Path(staging)
        plan = plan_slice(intent, spec, scratch / "artifact", scratch / "readback")
        completed = run(
            argv_for(found.form, plan.argv, plan.paths),
            capture=(spec.run_record.name,) if spec.run_record else (),
        )
        assert plan.staged_artifact is not None and plan.artifact_destination is not None

        _gate(completed, plan.staged_artifact, spec, intent_path)
        text = _configuration(completed, plan.staged, spec, intent_path)
        readback = redact(text, spec)
        adjudication = diff(plan.requested, _parse(text, spec), name_map)
        container = sniff(plan.staged_artifact, spec.binary_container_magic)

        prehash = _prehash(plan.artifact_destination)
        promoted: Path | None = None
        if adjudication.outcome is Outcome.SLICED:
            # ONLY on `sliced`, which is D7 and is the difference between this verb and
            # `resolve`. A readback is evidence for a verdict of any kind; a G-code file
            # the author will print is not, and handing over an artifact from a run
            # slicelab could not stand behind is the failure this tool is named after.
            try:
                promote(plan.staged_artifact.read_bytes(), plan.artifact_destination)
            except (OSError, PromotionError) as unwritable:
                raise ResolveError(f"cannot write the artifact: {unwritable}") from unwritable
            promoted = plan.artifact_destination
        _promote_readback(readback, plan.destination)

    return Sliced(
        adjudication=adjudication,
        readback=readback,
        artifact=promoted,
        container=container,
        destination_prehash=prehash,
    )


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
        wrote_something = staged.is_file() and staged.stat().st_size
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


def _prehash(destination: Path) -> str | None:
    """sha256 of what stands at the destination now, or `None` if nothing does."""
    try:
        with destination.open("rb") as handle:
            return hashlib.file_digest(handle, "sha256").hexdigest()
    except OSError:
        return None
