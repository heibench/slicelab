"""Which config key does each of this engine's options actually write?

``notes/critique.md`` G2 is the reason this module exists, and its finding is
that **there is no derivable rule**. Measured on PrusaSlicer 2.9.6: 411 options
at the leading position of ``--help-fff``, 343 config keys in a default
``--save``. ``--after-layer-gcode`` writes ``layer_gcode``, so a
dash-to-underscore transform returns ``absent`` for a key the engine applied
exactly -- a correct run reported as exit 2. G2 names the fix and it is not a
better transform: **probe**. Set one option to two different sentinels,
dump the configuration each time, and see which key followed the value.

Three things are established here rather than assumed, because each of them
turns silence into data if it is not:

* **An engine invocation that returns is not one that answered.** Some options
  make PrusaSlicer write no ini at all, at exit 0 -- ``--post-process`` and
  ``--info`` are two. Parsing a file that is not there yields ``{}``, every
  default then reads as "moved", and the probe concludes that one option writes
  all 343 keys. That is D7's rule aimed at this module: gate on the artifact
  existing and being non-empty, or the engine's silence becomes the measurement.
* **An engine invocation that hangs is not one that failed.**
  ``--gcodeviewer=<anything>`` opens a window and never returns. A sweep with no
  timeout hangs the machine of whoever first characterises a build.
* **A dump with different keys in it is a different question.**
  ``--export-sla`` switches printer technology, and the FFF namespace is
  replaced rather than edited: measured, it drops 334 of the 343 baseline keys
  and adds 143 of its own. A "moved" count in the hundreds is a mode switch, not
  a mapping, and the test for it needs no threshold -- see
  :data:`ProbeOutcome.NAMESPACE_CHANGED`.
* **A key that moved is not necessarily a key the option wrote.** Each candidate
  is probed with **two** distinct sentinels, and only a key that holds the first
  under the first and the second under the second is the option's; the rest moved
  because the engine adjusted the print around the request. One extra invocation
  per candidate, and `notes/critique.md` G4's dependent constraints fall out
  structurally instead of being guessed at.

Nothing here knows any engine's option names. What differs per engine is the
four fields of :class:`~slicelab.adapters.base.OptionProbe`, which live under
``adapters/`` where D1's seam puts them.

The output is engine-derived and D11 forbids shipping a byte of it, so it is
generated on the user's machine into the XDG cache, keyed by engine and by
version.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from slicelab.adapters import EngineSpec, OptionProbe
from slicelab.engine.discover import Discovery, ExitFidelity, argv_for, discover
from slicelab.engine.launch import run

__all__ = [
    "Characterisation",
    "CharacterisationError",
    "MapEntry",
    "ProbeOutcome",
    "Tracking",
    "cache_path_for",
    "characterise",
    "load_name_map",
]

PROBE_TIMEOUT_S = 20.0
"""Ceiling on one probe invocation.

A normal probe on 2.9.6 takes about 0.22 s, so this is generous by two orders of
magnitude and still fails fast on the option that never returns at all.
"""

SCHEMA = 2
"""Bumped when the cache file's shape changes.

A cache written by an older slicelab is *discarded*, not adapted. Reading an
unknown shape leniently is how a stale map survives the change that invalidated
it, and this map's whole job is to be the thing nobody guessed at.
"""


class CharacterisationError(Exception):
    """The map could not be built. An environment fault (exit 4), never a verdict.

    Returning an empty mapping instead would be the founding defect: every option
    would then look unmapped, the readback would report ``absent`` for all of
    them, and a run that never reached the engine would be indistinguishable from
    one whose keys really did not land.
    """


class ProbeOutcome(StrEnum):
    """What one option's probe established. Only the first is a mapping."""

    MAPPED = "mapped"
    """A sentinel was accepted, the artifact was written, and named keys moved."""

    NO_KEY_MOVED = "no-key-moved"
    """Accepted, artifact written, nothing in the dump changed.

    An action or a runtime option rather than a config option. Not a failure, and
    not a mapping either -- there is no key to compare a readback against, so the
    option must never reach one.
    """

    NAMESPACE_CHANGED = "namespace-changed"
    """The dump lost keys the baseline had, so this is a different question.

    Threshold-free on purpose. A config option only ever changes a value or adds
    a key -- ``--bed-custom-texture`` adds exactly one and drops none -- whereas
    ``--export-sla`` swaps printer technology and drops 334. "Did any baseline key
    disappear" separates the two exactly, where "did more than N keys move" is a
    number someone would have to keep true.
    """

    NO_ARTIFACT = "no-artifact"
    """Exit 0 and no readback written, or one of zero bytes. D7, aimed here."""

    UNKNOWN_OPTION = "unknown-option"
    """The engine says there is no such option, so no sentinel will help."""

    REJECTED = "rejected"
    """Every sentinel was refused. The option is real and none of the values fit.

    A could-not-tell, not a mapping: the option exists, and which key it writes is
    still unknown.
    """

    TIMED_OUT = "timed-out"
    """The engine never returned. ``--gcodeviewer`` opens a window and waits."""


class Tracking(StrEnum):
    """How firmly an entry's keys were tied to the option's own value."""

    EXACT = "exact"
    """Every key in the entry took sentinel A under A and sentinel B under B.

    The strong result, and the one a readback may adjudicate a requested value
    against without qualification.
    """

    INEXACT = "inexact"
    """The keys responded to both sentinels but carried neither verbatim.

    Value normalisation, which is the readback diff's problem and not this
    module's: ``--fill-density=0.17`` resolves to ``17%`` and ``--draft-shield=1``
    to ``enabled``. The key is still the option's -- it moved differently under
    two different values, which a dependent constraint does not do -- but the
    entry is weaker and says so.
    """


@dataclass(frozen=True)
class MapEntry:
    """One option's keys, and the keys that merely moved when it was set."""

    keys: tuple[str, ...]
    """What this option writes. The only keys a readback may compare against."""

    side_effects: tuple[str, ...]
    """Keys that moved but did not respond to the option's own value.

    These are the engine's **dependent constraints**, and separating them is what
    the second sentinel buys. ``--spiral-vase=1`` moves five keys; only
    ``spiral_vase`` takes ``1`` under ``=1`` and ``0`` under ``=0``, while
    ``perimeters``, ``fill_density``, ``top_solid_layers`` and
    ``filament_retract_layer_change`` are the engine adjusting the print around
    the request. `notes/critique.md` G4 is exactly the run where adjudicating the
    authored value against those four turns a correct slice red. They are
    recorded because they are true, and excluded from `keys` because they were
    never requested.
    """

    tracking: Tracking


@dataclass(frozen=True)
class Characterisation:
    """One engine build's option-to-key map, and what it could not map.

    ``outcomes`` carries every candidate, including the ones that produced no
    mapping. An option missing from ``entries`` is then a fact with a recorded
    cause rather than an absence, which is what lets a caller refuse an unmapped
    option at 64 instead of reporting it as ``absent``.
    """

    engine: str
    version: str
    entries: dict[str, MapEntry]
    outcomes: dict[str, str]
    baseline_key_count: int
    volatile_keys: tuple[str, ...]
    """Keys that differed between two identical baseline runs, and are excluded.

    Measured rather than assumed (D8's habit applied to this module). A key that
    moves on its own moves under every option, and would otherwise be attributed
    to all of them at once.
    """

    @property
    def name_map(self) -> dict[str, tuple[str, ...]]:
        """What `load_name_map` hands back: option -> the keys it writes."""
        return {option: entry.keys for option, entry in self.entries.items()}


def load_name_map(spec: EngineSpec, version: str) -> Mapping[str, tuple[str, ...]]:
    """Authored option name (no leading dashes) -> the config keys it writes.

    Cached under XDG per engine and per version; a miss builds the map by probing
    the installed engine, which costs a few hundred invocations once per build.

    **The value is a tuple of keys, not one key, and that is not defensive
    generality.** Measured on 2.9.6, one option really does write several:
    ``--extruder`` writes ``infill_extruder``, ``perimeter_extruder`` and
    ``solid_infill_extruder``; ``--solid-layers`` writes three. A ``str`` value
    would have to pick one of them, and a readback comparing only the one that
    was picked reports ``applied`` while two other keys went unchecked -- green
    over an intent that was only partly honoured. Every option maps to a tuple,
    including the 1-tuples, because a value whose type depends on how many
    answers there happen to be is a second bug waiting for the caller.

    An option **absent from the mapping** is one the probe could not map, and the
    reason is in the cache alongside. It must never be compared against a key
    derived from its own name -- that transform is what G2 reproduced a false
    ``absent`` from.

    **A dependent constraint is not a key, and the second sentinel is what says
    so.** ``--spiral-vase=1`` moves five keys on 2.9.6, and only ``spiral_vase``
    follows the value: it reads ``1`` under ``=1`` and ``0`` under ``=0``, while
    ``perimeters``, ``fill_density``, ``top_solid_layers`` and
    ``filament_retract_layer_change`` are the engine adjusting the print around a
    request that never named them. Adjudicating an authored value against those
    four is `notes/critique.md` G4's false red -- a correct slice reported as a
    finding -- so they are recorded on the entry as ``side_effects`` and are not
    in this mapping. The separation is structural, with no heuristic and no
    threshold, and the whole of it is one extra invocation per candidate.

    ``perimeters`` is why one sentinel could never do it: the constraint sets it
    to ``1``, which is exactly what was sent, so "did this key take my value" says
    yes about a key nobody asked for.

    Entries also carry how firmly the tie was measured. ``Tracking.INEXACT`` means
    the keys responded to both sentinels but carried neither verbatim, which is
    value normalisation -- ``--fill-density=0.17`` resolves to ``17%`` -- and is
    the readback diff's problem rather than the map's.
    """
    if not version.strip():
        raise CharacterisationError(
            f"{spec.name} reported no version, and the option-to-key map is a "
            "per-build fact: caching one under an unknown build would hand the next "
            "release a map measured on this one"
        )
    cached = _read_cache(cache_path_for(spec, version))
    if cached is not None:
        return cached
    result = characterise(spec, version)
    _write_cache(cache_path_for(spec, version), result)
    return result.name_map


def cache_path_for(spec: EngineSpec, version: str) -> Path:
    """Where this build's map lives. Engine and version both, never engine alone.

    The map is a property of a build. Two releases of one engine rename options
    and add keys, and a map carried across that boundary is confidently wrong in
    the direction this project exists to refuse.
    """
    return _cache_root() / spec.name / _safe(version) / "option-key-map.json"


def characterise(
    spec: EngineSpec, version: str, *, timeout: float = PROBE_TIMEOUT_S
) -> Characterisation:
    """Build the map by probing. Every claim in it was measured on this host."""
    probe = spec.option_probe
    if probe is None:
        raise CharacterisationError(
            f"{spec.name} has no measured way to probe which key an option writes, "
            "and deriving one from the option's own name is the transform that "
            "reports a correct run as incomplete"
        )
    if spec.readback_flag is None:
        raise CharacterisationError(
            f"{spec.name} has no measured way to dump its resolved configuration, so "
            "there is nothing to watch move"
        )

    found = discover(spec)
    if found.form is None or found.fidelity is not ExitFidelity.ESTABLISHED:
        raise CharacterisationError(
            f"{spec.name} is not driveable on this host ({found.fidelity.value}): {found.reason}"
        )

    with tempfile.TemporaryDirectory(prefix="probe-", dir=_scratch_parent()) as workspace:
        sidecar = Path(workspace) / "readback"
        baseline, volatile = _baseline(spec, found, sidecar, timeout=timeout)
        enumeration = _enumerate(found, probe.enumerate_argv, timeout=timeout)
        options = probe.candidates(enumeration, baseline)
        if not options:
            raise CharacterisationError(
                f"{spec.name} named no options to probe, so the map would be empty "
                "and every key would read as unmapped"
            )

        entries: dict[str, MapEntry] = {}
        outcomes: dict[str, str] = {}
        for option in options:
            outcome, entry = _probe_one(
                spec, found, probe, option, sidecar, baseline, volatile, timeout=timeout
            )
            outcomes[option] = outcome.value
            if entry is not None:
                entries[option] = entry

    return Characterisation(
        engine=spec.name,
        version=version,
        entries=entries,
        outcomes=outcomes,
        baseline_key_count=len(baseline),
        volatile_keys=volatile,
    )


def _baseline(
    spec: EngineSpec, found: Discovery, sidecar: Path, *, timeout: float
) -> tuple[Mapping[str, str], tuple[str, ...]]:
    """The dump with nothing set, plus the keys that will not hold still.

    Run **twice**. A key that differs between two identical invocations differs
    under every option too, and attributing it to all of them would put a
    plausible fan-out on every entry in the map. D8 established that
    reproducibility is measured rather than assumed for the artifact; the same
    applies to the thing the whole map is diffed against.
    """
    first = _dump(spec, found, (), sidecar, timeout=timeout)
    second = _dump(spec, found, (), sidecar, timeout=timeout)
    if first is None or second is None:
        raise CharacterisationError(
            f"{spec.name} wrote no configuration for a request with nothing set, so "
            "there is no baseline to measure anything against"
        )
    volatile = tuple(sorted(k for k in set(first) | set(second) if first.get(k) != second.get(k)))
    return second, volatile


def _enumerate(found: Discovery, argv: tuple[str, ...], *, timeout: float) -> str:
    """Whatever the engine says when asked to list its options.

    Both streams, concatenated: which one an engine states its options on is a
    packaging detail, and an enumeration read from the wrong stream is an empty
    map rather than an error.
    """
    if not argv:
        return ""
    assert found.form is not None
    completed = run(argv_for(found.form, argv, ()), timeout=timeout)
    return completed.stdout + completed.stderr


def _probe_one(
    spec: EngineSpec,
    found: Discovery,
    probe: OptionProbe,
    option: str,
    sidecar: Path,
    baseline: Mapping[str, str],
    volatile: tuple[str, ...],
    *,
    timeout: float,
) -> tuple[ProbeOutcome, MapEntry | None]:
    """Cascade sentinel **pairs** until one shows which key carries the value.

    Two sentinels, not one, and the second is what separates a key the option
    *writes* from a key the engine *adjusted*. A key **tracks** when it holds
    sentinel A after the run with A and sentinel B after the run with B; only a
    key that follows the value can do that, and a dependent constraint cannot.
    Measured on 2.9.6:

    * ``--extruder`` at ``=2`` then ``=3`` -- all three of ``infill_extruder``,
      ``perimeter_extruder`` and ``solid_infill_extruder`` track. It is an
      aggregate, and all three members are the request.
    * ``--solid-layers`` at ``=2`` then ``=5`` -- ``bottom_solid_layers`` and
      ``top_solid_layers`` track; ``solid_layers`` reads ``0`` under both and is
      a side effect.
    * ``--spiral-vase`` at ``=1`` then ``=0`` -- only ``spiral_vase`` tracks.
      ``perimeters``, ``fill_density``, ``top_solid_layers`` and
      ``filament_retract_layer_change`` are the engine adjusting the print, and
      they are `notes/critique.md` G4's false red if a readback compares the
      authored value against them.

    So G4's dependent constraints fall out structurally, with no heuristic and no
    threshold. It also closes the residual false ``applied`` the collision search
    named: fan-out membership is now measured rather than assumed.

    Three earlier rules still hold, each because ignoring one turns silence into
    data. Options are typed, so a **rejection** is not an answer and the next pair
    is tried -- unless the engine says the option does not exist, where no value
    helps. **Accepted-and-moved-nothing** is not an answer either: D5's boolean
    options validate nothing, so ``--spiral-vase=SLICELABPROBE`` exits 0, resolves
    to the ``0`` already in the dump, and moves no key. Stopping there put 110
    real options in a bucket meaning the opposite of the truth. And a pair that
    produces only an **inexact** result is kept but not settled for, because a
    later pair of the right type may track exactly: ``--fill-density`` reads
    ``17%`` from ``0.17`` and ``37%`` from ``37%``, and only the second tracks.
    """
    assert found.form is not None
    accepted = False
    inexact: MapEntry | None = None

    for low, high in probe.sentinels:
        outcome, first = _one_run(
            spec, found, probe, option, low, sidecar, baseline, timeout=timeout
        )
        if outcome is not None:
            return outcome, None
        if first is None:
            continue
        outcome, second = _one_run(
            spec, found, probe, option, high, sidecar, baseline, timeout=timeout
        )
        if outcome is not None:
            return outcome, None
        if second is None:
            continue
        accepted = True

        moved = {
            key
            for key in set(first) | set(second) | set(baseline)
            if key not in volatile
            and (baseline.get(key) != first.get(key) or baseline.get(key) != second.get(key))
        }
        responded = {key for key in moved if first.get(key) != second.get(key)}
        tracks = {key for key in responded if first.get(key) == low and second.get(key) == high}

        if tracks:
            return ProbeOutcome.MAPPED, MapEntry(
                keys=tuple(sorted(tracks)),
                side_effects=tuple(sorted(moved - tracks)),
                tracking=Tracking.EXACT,
            )
        if responded and inexact is None:
            inexact = MapEntry(
                keys=tuple(sorted(responded)),
                side_effects=tuple(sorted(moved - responded)),
                tracking=Tracking.INEXACT,
            )

    if inexact is not None:
        return ProbeOutcome.MAPPED, inexact
    return (ProbeOutcome.NO_KEY_MOVED if accepted else ProbeOutcome.REJECTED), None


def _one_run(
    spec: EngineSpec,
    found: Discovery,
    probe: OptionProbe,
    option: str,
    sentinel: str,
    sidecar: Path,
    baseline: Mapping[str, str],
    *,
    timeout: float,
) -> tuple[ProbeOutcome | None, Mapping[str, str] | None]:
    """One probe invocation: a terminal outcome, a parsed dump, or neither.

    ``(None, None)`` means "this sentinel was refused, try another" -- the one
    result that is neither a verdict about the option nor a measurement.

    The namespace check belongs here rather than beside the comparison, because
    it is a property of **one** dump: if this run's configuration is missing keys
    the baseline had, the engine answered a different question and the run is not
    a data point to be paired with anything.
    """
    assert found.form is not None
    completed = run(
        argv_for(
            found.form,
            (f"--{option}={sentinel}", f"{spec.readback_flag}={sidecar}"),
            (str(sidecar),),
        ),
        timeout=timeout,
    )
    if completed.timed_out:
        return ProbeOutcome.TIMED_OUT, None
    if completed.exit_status != 0:
        said = (completed.stderr + completed.stdout).lower()
        if probe.unknown_option and probe.unknown_option in said:
            return ProbeOutcome.UNKNOWN_OPTION, None
        _discard(sidecar)
        return None, None
    text = _artifact_text(sidecar)
    if text is None:
        return ProbeOutcome.NO_ARTIFACT, None
    parsed = probe.read_config(text)
    _discard(sidecar)
    if set(baseline) - set(parsed):
        return ProbeOutcome.NAMESPACE_CHANGED, None
    return None, parsed


def _dump(
    spec: EngineSpec,
    found: Discovery,
    extra: tuple[str, ...],
    sidecar: Path,
    *,
    timeout: float,
) -> Mapping[str, str] | None:
    """One readback, or ``None`` if the engine did not write one."""
    assert found.form is not None
    probe = spec.option_probe
    assert probe is not None
    _discard(sidecar)
    run(
        argv_for(found.form, (*extra, f"{spec.readback_flag}={sidecar}"), (str(sidecar),)),
        timeout=timeout,
    )
    text = _artifact_text(sidecar)
    _discard(sidecar)
    return None if text is None else probe.read_config(text)


def _artifact_text(sidecar: Path) -> str | None:
    """The readback's text, or ``None`` when there is nothing to read.

    The exit status is deliberately not consulted and the *file* is. D7: ``--save``
    runs before the slice block and is not conditioned on it, so exit 0 says
    nothing about whether a configuration was written -- and a whole class of
    options makes 2.9.6 exit 0 having written none. An empty file counts as none:
    zero bytes parse to zero keys, and zero keys makes every baseline key look
    moved.
    """
    try:
        if sidecar.stat().st_size == 0:
            return None
        return sidecar.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _discard(sidecar: Path) -> None:
    """Remove the artifact, so the next probe cannot read the last one's."""
    with contextlib.suppress(OSError):
        sidecar.unlink()


def _read_cache(path: Path) -> dict[str, tuple[str, ...]] | None:
    """A previously measured map, or ``None`` if there is not a usable one.

    Every failure to read is a miss rather than an error: a truncated or
    hand-edited cache is re-measured, because the engine is the authority and the
    file is only a saved answer.
    """
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(document, dict) or document.get("schema") != SCHEMA:
        return None
    raw = document.get("entries")
    if not isinstance(raw, dict) or not raw:
        return None
    out: dict[str, tuple[str, ...]] = {}
    for option, entry in raw.items():
        if not isinstance(option, str) or not isinstance(entry, dict):
            return None
        keys = entry.get("keys")
        if not isinstance(keys, list) or not all(isinstance(key, str) for key in keys):
            return None
        out[option] = tuple(keys)
    return out


def _write_cache(path: Path, result: Characterisation) -> None:
    """Save the measurement, and never let failing to save fail the run.

    An unwritable cache costs the next caller a few hundred invocations. Raising
    here would cost them the answer they already have.
    """
    document = {
        "schema": SCHEMA,
        "engine": result.engine,
        "version": result.version,
        "baseline_key_count": result.baseline_key_count,
        "volatile_keys": list(result.volatile_keys),
        "entries": {
            option: {
                "keys": list(entry.keys),
                "side_effects": list(entry.side_effects),
                "tracking": entry.tracking.value,
            }
            for option, entry in sorted(result.entries.items())
        },
        "outcomes": dict(sorted(result.outcomes.items())),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(document, indent=2, sort_keys=False), encoding="utf-8")
    except OSError:
        pass


def _cache_root() -> Path:
    """``$XDG_CACHE_HOME/slicelab/characterisation``, or the spec's default.

    A relative ``XDG_CACHE_HOME`` "MUST be ignored" per the basedir spec, and
    honouring one here would scatter a cache directory wherever the user happened
    to be standing -- the same defect ``launch._scratch_roots`` is written about.
    """
    base = os.environ.get("XDG_CACHE_HOME") or ""
    root = Path(base) if base and Path(base).is_absolute() else Path.home() / ".cache"
    return root / "slicelab" / "characterisation"


def _scratch_parent() -> Path:
    """A directory the probe's sidecar can live in and a sandboxed engine can reach.

    Under the cache root deliberately, not under ``/tmp``. A Flatpak has its own
    ``/tmp``, and a host ``/tmp`` path handed to it is not refused -- ``bwrap``
    drops the request and starts the process in ``$HOME`` instead. Same reasoning
    as ``launch._scratch_roots``, same measurement behind it.
    """
    root = _cache_root() / "probe"
    try:
        root.mkdir(parents=True, exist_ok=True)
        return root
    except OSError:
        return Path(tempfile.gettempdir())


def _safe(version: str) -> str:
    """A version string as one path segment.

    A build states its own version and slicelab does not get to assume what is in
    it: ``2.9.6+flathub.org`` is a real one. Anything outside the allowed set
    becomes an underscore, so a version can never climb out of the cache
    directory or name a file it was not meant to.
    """
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-+"
    cleaned = "".join(ch if ch in allowed else "_" for ch in version.strip())
    return cleaned.strip(".") or "unknown"
