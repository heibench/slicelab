"""The only module in slicelab permitted to import ``subprocess``.

Enforced by ``tests/test_boundaries.py``. Everything an engine invocation needs
to be honest about is decided here, once, rather than at seven call sites.
"""

from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["Completed", "run"]

DEFAULT_TIMEOUT_S = 120.0


@dataclass(frozen=True)
class Completed:
    """What a finished engine invocation established.

    ``exit_status`` and ``signal`` are **separate fields** (D15). A process
    killed by a signal has no exit status, and Python's single negative
    ``returncode`` conflates the two -- so a caller cannot tell exit 11 from
    signal 11 without unpacking it. A partial preset triple gives SIGSEGV with
    zero bytes on both streams (``notes/evidence.md`` V6), and that observation
    carries no cause: it must reach the caller as a fact, not a guess.
    """

    argv: list[str] = field(default_factory=list)
    exit_status: int | None = None
    signal: int | None = None
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False

    @property
    def died_by_signal(self) -> bool:
        return self.signal is not None

    @property
    def is_silent(self) -> bool:
        """True when the engine said nothing at all on either stream.

        Worth naming: a silent non-zero exit is the shape that carries no
        diagnostic, and a caller must not invent one.
        """
        return not self.stdout and not self.stderr


def run(
    argv: list[str],
    *,
    cwd: Path | None = None,
    timeout: float = DEFAULT_TIMEOUT_S,
) -> Completed:
    """Invoke an engine and report what happened, without interpreting it.

    Four choices, each load-bearing:

    ``stdin=DEVNULL`` -- PrusaSlicer 2.9.6 prints ``Continue(Y/N)?`` to stdout
    and blocks on stdin when the resolved config carries a post-processing
    script, headless, at exit 0, producing nothing (``notes/evidence.md`` V15).
    An inherited stdin makes that a hang instead of a fast, readable failure.

    ``errors="replace"`` on both streams -- a byte we cannot decode must not
    raise before the result can be inspected, or an undecodable character
    becomes a verdict on a run that succeeded (prusaslicer-py D5).

    A ``timeout`` at all -- an engine that never returns is an environment
    fault, not a hang in slicelab.

    A scratch ``cwd`` by default -- OrcaSlicer writes into the process working
    directory, and ``cwd=None`` meant *the directory the user ran slicelab
    from*. Measured, not read: ``slicelab which orcaslicer`` in an empty
    directory left a 180-byte ``result.json`` behind, at exit 0. V13 recorded
    the litter only for failing runs; a successful discovery probe does it too.
    An identical file reached this repository that way and was committed (D11).

    So a caller that names no directory gets a temporary one this function owns
    and removes, rather than the user's. A caller that wants to *read* what the
    engine dropped -- the slice verb, promoting an artifact -- passes a
    directory it owns and keeps.

    SECURITY.md said the implemented verbs write nothing. That was false for as
    long as this defaulted to ``None``.
    """
    if cwd is None:
        with tempfile.TemporaryDirectory(prefix="slicelab-") as scratch:
            return _spawn(argv, Path(scratch), timeout)
    return _spawn(argv, cwd, timeout)


def _spawn(argv: list[str], cwd: Path, timeout: float) -> Completed:
    try:
        proc = subprocess.run(  # noqa: S603 - argv is a list; never shell=True
            argv,
            capture_output=True,
            text=True,
            errors="replace",
            stdin=subprocess.DEVNULL,
            cwd=cwd,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as expired:
        return Completed(
            argv=list(argv),
            exit_status=None,
            signal=None,
            stdout=_as_text(expired.stdout),
            stderr=_as_text(expired.stderr),
            timed_out=True,
        )

    # POSIX reports a signal death as a negative returncode. Split it, rather
    # than passing on a number that means two different things.
    if proc.returncode < 0:
        return Completed(
            argv=list(argv),
            exit_status=None,
            signal=-proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
        )
    return Completed(
        argv=list(argv),
        exit_status=proc.returncode,
        signal=None,
        stdout=proc.stdout,
        stderr=proc.stderr,
    )


def _as_text(raw: str | bytes | None) -> str:
    if raw is None:
        return ""
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace")
    return raw
