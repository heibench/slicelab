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
from slicelab.digest import CONTAINER_IS_BINARY, normalized_sha256, raw_sha256
from slicelab.engine.configured import ConfigState, configuration_state
from slicelab.engine.discover import argv_for, discover
from slicelab.engine.identity import identify
from slicelab.engine.launch import run
from slicelab.geometry import (
    MESH_NOT_DESCRIBED,
    PLACEMENT_NOT_STATED,
    MeshFacts,
    mesh_sha256,
)
from slicelab.intent import read_intent
from slicelab.lock import SCHEMA_VERSION, dumps
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

    lock: Path | None
    """Where `slice.lock` was written, or `None` when none was.

    `None` on every outcome but `sliced`: D24 gives `empty` its artifact and no lock,
    because a lock records a resolution slicelab verified and `empty` verified none.
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
    # Read once and reused: `_name_map` needs the version to key the option map and
    # the lock needs the build it talked to. Asking twice is a second chance to meet
    # the intermittent failure in #47, and a run that accepted the first answer and
    # refused the second would look like slicelab being nondeterministic.
    who = identify(spec, found)
    name_map = _name_map(spec, found, who=who)

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

        locked: Path | None = None
        if adjudication.outcome is Outcome.SLICED and plan.lock_destination is not None:
            # Only on `sliced`. D24 is explicit that `empty` writes none -- a lock is
            # the record of a resolution slicelab verified, and `empty` verified none --
            # so the lock exists if and only if the run was one slicelab stands behind.
            # That is also why it carries no `outcome` field: a value that cannot vary
            # tells a reader nothing and invites branching on it.
            #
            # After the artifact, deliberately. The lock describes where the artifact
            # landed, so a lock written first and an artifact promotion that then failed
            # would leave a record asserting a file that is not there -- and the lock is
            # read by another tool as its premise (D22). The cost is stated in the
            # report instead: a lock that cannot be written is exit 4 saying the
            # artifact was handed over and the lock was not.
            document = _lock_document(
                intent_path=intent_path,
                spec=spec,
                identity=who,
                found=found,
                plan=plan,
                container=container,
                text=_artifact_text(plan.staged_artifact, container),
                readback=readback,
                prehash=prehash,
            )
            try:
                promote((dumps(document) + "\n").encode("utf-8"), plan.lock_destination)
            except PromotionError as unwritable:
                raise ResolveError(
                    f"the artifact was handed over to {promoted} and the lock was not: {unwritable}"
                ) from unwritable
            locked = plan.lock_destination

        keep = promoted is None
        return Sliced(
            adjudication=adjudication,
            readback=readback,
            artifact=promoted,
            container=container,
            destination_prehash=prehash,
            withheld=plan.staged_artifact if keep else None,
            lock=locked,
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


def _mesh_facts(spec, found, model: Path) -> tuple[MeshFacts | None, str | None]:
    """Ask the engine to describe the mesh, and never let that cost the slice.

    A second invocation, and the cheap kind: `--info` answers in about a third of a
    second and slices nothing, so it cannot be mistaken for the run that produced the
    artifact the way a second `--save` could (D7). It runs after the artifact is
    promoted, so a slice that was never going to finish does not pay for it.

    Every failure here is a missing field and never a missing slice. The mesh is still
    identified: `mesh_sha256` is slicelab hashing the file, which needs no engine.
    """
    if spec.compose_mesh_info is None or spec.read_mesh_info is None:
        return None, MESH_NOT_DESCRIBED
    invocation = spec.compose_mesh_info(model)
    try:
        completed = run(argv_for(found.form, invocation.argv, invocation.paths))
    except Exception:  # noqa: BLE001 - a field is worth less than the artifact
        return None, MESH_NOT_DESCRIBED
    if completed.exit_status != 0 or not completed.stdout:
        return None, MESH_NOT_DESCRIBED
    facts = spec.read_mesh_info(completed.stdout)
    return facts, None if facts is not None else MESH_NOT_DESCRIBED


def _lock_document(
    *,
    intent_path: Path,
    spec,
    identity,
    found,
    plan,
    container: Container,
    text: str | None,
    readback: Redacted,
    prehash: str | None,
) -> dict[str, object]:
    """Assemble `slice.lock`, and record every gap rather than omitting it.

    `text` is the artifact's own text, or `None` when the container carries none --
    which is D10's case, not a failure: `GCDE` has no text footer, so no stat and no
    normalized hash can come from it, and both are recorded as unknowns with the
    container's own code.

    The builder lives here rather than in `slicelab/lock.py` so that module keeps
    naming no field at all. That is the property that lets it stay inside both the
    declared-vocabulary scan and the live engine-key cross-check.
    """
    unknowns: list[dict[str, object]] = []
    artifact: dict[str, object] = {
        "path": str(plan.artifact_destination),
        "container": container.value,
        "raw_sha256": raw_sha256(plan.artifact_destination),
    }
    if prehash is not None:
        # What this run displaced. "This file is here" does not establish "this run
        # wrote it" (D7), and the lock is where that distinction has to survive.
        artifact["destination_prehash"] = prehash

    stats: dict[str, object] = {}
    if text is None:
        unknowns.append(
            {
                "code": CONTAINER_IS_BINARY,
                "detail": f"{container.value}: the container carries no text footer to read",
                "fields": ["artifact.normalized", "stats"],
            }
        )
    else:
        if spec.normalize_artifact is not None:
            normalized = normalized_sha256(text, spec.normalize_artifact)
            artifact["normalized"] = normalized.as_table()
            if normalized.reason is not None:
                unknowns.append(
                    {
                        "code": normalized.reason,
                        "detail": "normalization matched nothing, so no normalized hash",
                        "fields": ["artifact.normalized.sha256"],
                    }
                )
        if spec.read_artifact_stats is not None:
            for field, stat in sorted(spec.read_artifact_stats(text).items()):
                stats[field] = stat.as_table()
                if stat.reason is not None:
                    unknowns.append(
                        {
                            "code": stat.reason,
                            "detail": f"{stat.key} was printed and is not a measurement",
                            "fields": [f"stats.{field}"],
                        }
                    )

    geometry: dict[str, object] = {}
    if plan.model is not None:
        geometry["mesh_sha256"] = mesh_sha256(plan.model)
        facts, why = _mesh_facts(spec, found, plan.model)
        if facts is not None:
            geometry["mesh_bbox"] = facts.as_table()
        elif why is not None:
            unknowns.append(
                {
                    "code": why,
                    "detail": f"{spec.name} described no mesh slicelab could read",
                    "fields": ["geometry.mesh_bbox"],
                }
            )
    if text is not None and spec.read_placement is not None:
        placement = spec.read_placement(text)
        if placement is not None:
            geometry["plated_footprint"] = placement.as_table()
        else:
            unknowns.append(
                {
                    "code": PLACEMENT_NOT_STATED,
                    "detail": "the artifact stated no object placement",
                    "fields": ["geometry.plated_footprint"],
                }
            )

    document: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        # D6: both engines export a resolved DOCUMENT, not resolved values.
        # PrusaSlicer reports `extrusion_width = 0` while the toolpaths were generated
        # at 0.45 mm. Saying so here is what stops a reader treating this as the
        # numbers the engine actually used.
        "values_resolved": False,
        "reproducibility": {
            "scope": "cross_machine",
            "state": "not_established",
            "reason": (
                "one host, one build, one architecture; only a second machine can establish this"
            ),
        },
        "intent": {"path": str(intent_path), "sha256": raw_sha256(intent_path)},
        "engine": {
            "name": identity.engine,
            "launch": found.form.description if found.form is not None else "unknown",
            **({"version": identity.version} if identity.version else {}),
            **({"digest": identity.digest} if identity.digest else {}),
        },
        "artifact": artifact,
        "geometry": geometry,
        "stats": stats,
        "readback": {"path": str(plan.destination), "redacted_keys": list(readback.keys)},
        "unknowns": unknowns,
        "effective_config": dict(spec.read_readback(readback.text)) if spec.read_readback else {},
    }
    return document


def _artifact_text(staged: Path, container: Container) -> str | None:
    """The artifact as text, or `None` when its container carries none.

    D10 decides this and the core enforces it, not the adapter: `GCDE` has no text
    footer, so nothing is read out of it. Measured 2026-10-05 on an MK4IS triple --
    the file begins `GCDE`, holds zero `prusaslicer_config` and zero `;LAYER_CHANGE`,
    and does not decode as UTF-8. The metadata strings ARE in there as bytes, so the
    footer is absent rather than the information; reading them would mean implementing
    the container format, which belongs to the engine (org contract section 3).
    """
    if container is not Container.GCODE:
        return None
    return staged.read_text(encoding="utf-8", errors="replace")


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
