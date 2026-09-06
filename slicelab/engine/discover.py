"""Find an engine, and establish whether its exit code means anything.

The second half is the point. An engine whose exit status carries no
information is not a usable engine, and treating one as usable installs this
project's founding defect at the very bottom of the stack (D18).
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from enum import StrEnum

from slicelab.adapters import EngineSpec
from slicelab.engine import flatpak
from slicelab.engine.launch import run

__all__ = ["Discovery", "ExitFidelity", "LaunchForm", "discover"]

#: A flag no slicer will ever accept. Deliberately namespaced, so that if some
#: engine ever grows it, the collision is ours and obvious rather than silent.
INVALID_FLAG = "--definitely-not-a-slicelab-option"

PROBE_TIMEOUT_S = 90.0


class ExitFidelity(StrEnum):
    """Whether this engine's exit status can be believed."""

    ESTABLISHED = "established"
    """A launch form was found that reports failure as a non-zero status."""

    UNUSABLE = "unusable"
    """No available launch form could be driven honestly -- either it returned
    0 for a flag it rejects, or it never reached the engine at all."""

    ABSENT = "absent"
    """No launch form exists on this host."""


class LaunchKind(StrEnum):
    PATH = "path"
    FLATPAK = "flatpak"
    FLATPAK_BYPASS = "flatpak-command-bypass"


@dataclass(frozen=True)
class LaunchForm:
    kind: LaunchKind
    argv_prefix: list[str]
    description: str


@dataclass(frozen=True)
class Discovery:
    """What discovery established -- including what it ruled out and why."""

    engine: str
    form: LaunchForm | None
    fidelity: ExitFidelity
    reason: str
    rejected: list[tuple[LaunchForm, str]] = field(default_factory=list)


def candidate_forms(spec: EngineSpec) -> list[LaunchForm]:
    """Every way this engine might be invocable on this host.

    Order is preference, not correctness: the probe decides. A PATH binary is
    tried first because it is the plain case with no sandbox to translate
    across.
    """
    forms: list[LaunchForm] = []

    for candidate in spec.exec_names:
        on_path = shutil.which(candidate)
        if on_path:
            forms.append(
                LaunchForm(LaunchKind.PATH, [on_path], f"{candidate} on PATH at {on_path}")
            )

    app_id = spec.flatpak_app_id
    if app_id and shutil.which("flatpak") and flatpak.is_installed(app_id):
        flatpak_bin = shutil.which("flatpak") or "flatpak"
        # The packager's own entrypoint FIRST. It carries their fixes --
        # OrcaSlicer's sets LC_NUMERIC=C, and bypassing it throws that away
        # (notes/evidence.md V10). The --command= bypass is a fallback for the
        # case where the entrypoint's exit status cannot be believed, which is
        # PrusaSlicer's situation and not a property of Flatpak.
        forms.append(
            LaunchForm(
                LaunchKind.FLATPAK,
                [flatpak_bin, "run", app_id],
                f"Flatpak {app_id} via its default entrypoint",
            )
        )
        forms.append(
            LaunchForm(
                LaunchKind.FLATPAK_BYPASS,
                [flatpak_bin, "run", f"--command={spec.exec_name}", app_id],
                f"Flatpak {app_id} via --command={spec.exec_name}",
            )
        )
    return forms


def discover(spec: EngineSpec, *, timeout: float = PROBE_TIMEOUT_S) -> Discovery:
    """Pick a launch form whose exit status can be believed.

    Each candidate is handed a flag it must reject. **Any form that answers 0
    is discarded**, because a launcher that always succeeds makes every
    subsequent verdict meaningless.

    This is not hypothetical. PrusaSlicer's Flathub entrypoint ends in a
    backgrounded child, so it returns 0 for everything, while the
    ``--command=`` bypass returns 1. OrcaSlicer's wrapper does not, and
    bypassing it discards the packager's ``LC_NUMERIC=C`` fix. The right answer
    differs per package, so it is measured per package
    (``notes/evidence.md`` V10).

    Two probes, in order, because one is not enough. A launcher that fails
    *before* the engine starts also exits non-zero, so a bad-flag probe alone
    reports "exit fidelity established" for an engine that never ran.
    """
    forms = candidate_forms(spec)
    if not forms:
        return Discovery(
            engine=spec.name,
            form=None,
            fidelity=ExitFidelity.ABSENT,
            reason=(
                f"none of {list(spec.exec_names)} on PATH, and no Flatpak "
                f"{spec.flatpak_app_id} installed"
            ),
        )

    rejected: list[tuple[LaunchForm, str]] = []
    for form in forms:
        # FIRST: does this form reach the engine at all? A launcher that fails
        # before the engine starts also exits non-zero, and reading THAT as
        # "the engine rejected the flag" concludes an engine is driveable from
        # a run where it never ran. Observed: with an unwritable HOME, `flatpak
        # run` exits non-zero with "mkdirat: Permission denied" having started
        # nothing, and a probe that only checked for non-zero called that
        # exit fidelity established.
        #
        # An engine that cannot answer a request for its own help is not one we
        # are talking to, whatever its exit codes look like.
        hello = run([*form.argv_prefix, "--help"], timeout=timeout)
        if hello.timed_out:
            rejected.append((form, f"did not answer --help within {timeout:g}s"))
            continue
        if hello.exit_status != 0 or hello.is_silent:
            how = (
                f"exited {hello.exit_status}"
                if hello.exit_status is not None
                else f"died on signal {hello.signal}"
            )
            silent = " with no output" if hello.is_silent else ""
            rejected.append((form, f"did not reach the engine: --help {how}{silent}"))
            continue

        # SECOND: now that the engine is known to be answering, does its exit
        # status discriminate?
        probe = run([*form.argv_prefix, INVALID_FLAG], timeout=timeout)
        if probe.timed_out:
            rejected.append((form, f"probe timed out after {timeout:g}s"))
            continue
        if probe.died_by_signal:
            rejected.append((form, f"probe died by signal {probe.signal}"))
            continue
        if probe.exit_status == 0:
            rejected.append(
                (
                    form,
                    "returned 0 for a flag it does not accept, so its exit "
                    "status carries no information",
                )
            )
            continue
        return Discovery(
            engine=spec.name,
            form=form,
            fidelity=ExitFidelity.ESTABLISHED,
            reason=(
                f"rejected {INVALID_FLAG} with exit {probe.exit_status}, "
                "so failure is distinguishable from success"
            ),
            rejected=rejected,
        )

    return Discovery(
        engine=spec.name,
        form=None,
        fidelity=ExitFidelity.UNUSABLE,
        reason="no launch form both reached the engine and reported failure as failure",
        rejected=rejected,
    )
