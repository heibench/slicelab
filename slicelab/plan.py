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
    staged: Path
    """Where the ENGINE writes its dump. A path slicelab owns and destroys (D7, D31).

    Never the author's path. The engine's dump is unredacted -- on PrusaSlicer 2.9.6
    a preset triple emits `print_host`, `printhost_apikey`, `printhost_password`,
    `printhost_port` and `printhost_user` in cleartext -- so writing it where the
    author keeps their `slice.toml` puts those bytes in the directory the README's
    git model says you commit, and leaves them there on every failure between the
    engine's write and slicelab's redacted overwrite.
    """

    destination: Path
    """Where the REDACTED copy is promoted, once there is one. Written only by slicelab.

    The engine is never granted this path, so a sandboxed engine cannot write it
    even if it tried.
    """

    paths: frozenset[str]
    """Host paths this run touches, for a sandboxed engine to be granted.

    D19: computed from the plan's whole path set, never a fixed pair. A path the
    driver forgot to grant surfaces as an *engine* error about a file the author
    can see, which is a fault slicelab caused reported as one the engine found.

    Holds `staged` and NOT `destination`: the engine has no business writing the
    author's file, and the grant list is the place that is enforced.
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


def plan_resolve(intent: Intent, spec: EngineSpec, destination: Path, staged: Path) -> Plan:
    """Compose the argv for `resolve`: ask the engine what it would resolve.

    No geometry, no `--export-gcode`, no output. `--save` alone answers the whole
    question, and it answers it without slicing.

    **What that costs, measured, rather than "fast".** On this host, 2.9.6 via the
    Flatpak `--command=` form, median of three: a bare `--save` with no presets is
    0.20 s, and a `--save` with a preset triple -- which is every run `resolve` will
    actually make, because `base_keys` requires one -- is 1.82 s. Loading the triple
    is the whole of the difference. The first run against a build is slower again by
    the option-map probe (D30), which is measured once and cached per build.

    `staged` is where the engine is told to write. `destination` is where slicelab
    promotes the redacted copy afterwards and is not in the argv at all; see D31 and
    :class:`Plan`.

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

    # Both paths are resolved against slicelab's cwd HERE, once, because two
    # different directories would otherwise claim them. `grants_for` resolves a
    # relative path against this process's cwd, while `launch.run` runs the engine
    # inside a scratch directory it deletes on exit -- so a relative path is granted
    # in one place, written in another, and destroyed. Measured: exit 0, zero
    # stderr, and no file at either location. An exit-0 run that produced nothing is
    # the failure this project is named after, so the paths are made unambiguous
    # before they can become one.
    staged = staged.resolve()
    destination = destination.resolve()

    if spec.readback_flag is None:
        raise PlanError(
            f"{spec.name} has no measured way to dump its resolved configuration, so "
            "there is nothing to diff a request against"
        )
    argv.append(f"{spec.readback_flag}={staged}")
    return Plan(
        argv=tuple(argv),
        requested=requested,
        staged=staged,
        destination=destination,
        paths=frozenset({str(staged)}),
    )
