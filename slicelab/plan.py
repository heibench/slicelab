"""Turning a validated intent into an argv, and recording what was asked for.

Pure: no I/O, no subprocess, no clock, no environment. A `Plan` can be built,
printed and compared without an engine installed, which is what makes the argv
reviewable before anything runs — and what lets the whole of this module be tested
on a machine that has no slicer at all.

The `requested` mapping is the other half, and it is the half the mechanism needs.
It records **the exact string emitted for each authored key**, so the readback diff
compares like with like rather than re-deriving what it thinks was sent. Re-deriving
is where the defect lives: `notes/critique.md` G2 produced a false `absent` on a
perfectly applied key by transforming a name, and the same trap exists one level
down for values.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from slicelab.adapters import EngineSpec
from slicelab.intent import Intent
from slicelab.preflight import render

__all__ = ["Plan", "PlanError", "plan_resolve"]


class PlanError(Exception):
    """slicelab cannot compose an argv for this engine. `refused`, exit 1."""


@dataclass(frozen=True)
class Plan:
    """An argv slicelab is willing to run, and what it means by it."""

    argv: tuple[str, ...]
    requested: dict[str, str]
    sidecar: Path
    paths: frozenset[str]
    """Host paths this run touches, for a sandboxed engine to be granted.

    D19: computed from the plan's whole path set, never a fixed pair. A path the
    driver forgot to grant surfaces as an *engine* error about a file the author
    can see, which is a fault slicelab caused reported as one the engine found.
    """

    @property
    def keys_checked(self) -> int:
        """How many keys this run will adjudicate.

        The number D24 turns on. Zero means the run verifies nothing and is `empty`
        at exit 3 -- never `sliced`, because "every requested key was applied" is
        vacuously true over an empty set (`notes/critique.md` G1). Carried as a
        count rather than inferred from an empty list, so the report can say it.
        """
        return len(self.requested)


def plan_resolve(intent: Intent, spec: EngineSpec, sidecar: Path) -> Plan:
    """Compose the argv for `resolve`: ask the engine what it would resolve.

    No geometry, no `--export-gcode`, no output. `--save` alone answers the whole
    question, and it answers it in ~0.2 s because nothing is sliced.

    Measured 2026-09-10 on 2.9.6: a preset triple plus `--save` and no model file
    exits 0, writes a 376-key configuration, puts zero bytes on stderr, and carries
    the authored override. That `resolve` previews `slice` faithfully is a separate
    claim, and `notes/critique.md` G7.2 makes it a test rather than an assumption --
    it is a per-build fact that can regress silently.

    Ordering is deterministic: base keys in the engine's own declared order, then
    overrides sorted. A `Plan` is compared in tests and printed to humans, and an
    argv that reorders between runs is one nobody can diff.
    """
    argv: list[str] = []
    for key in spec.base_keys:
        argv.append(f"--{key}={intent.base[key]}")

    requested: dict[str, str] = {}
    for key in sorted(intent.overrides):
        value = render(intent.overrides[key], spec)
        requested[key] = value
        argv.append(f"--{key}={value}")

    if spec.readback_flag is None:
        raise PlanError(
            f"{spec.name} has no measured way to dump its resolved configuration, so "
            "there is nothing to diff a request against"
        )
    argv.append(f"{spec.readback_flag}={sidecar}")
    return Plan(
        argv=tuple(argv),
        requested=requested,
        sidecar=sidecar,
        paths=frozenset({str(sidecar)}),
    )
