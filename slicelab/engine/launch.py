"""The only module in slicelab permitted to import ``subprocess``.

Enforced by ``tests/test_boundaries.py``. Everything an engine invocation needs
to be honest about is decided here, once, rather than at seven call sites.
"""

from __future__ import annotations

import os
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
    and removes. A caller that wants to *read* what the engine dropped -- the
    slice verb, promoting an artifact -- passes a directory it owns and keeps.

    **That directory must be one the engine can actually reach**, which is why
    it is not ``/tmp``. See ``_scratch_root``: the first version of this fix
    used ``tempfile``'s default, and a Flatpak silently relocated the process
    to ``$HOME`` instead, turning litter in the directory you were standing in
    into litter in your home directory -- persistent, global, and nowhere
    anyone would notice it.
    """
    if cwd is None:
        with tempfile.TemporaryDirectory(prefix="run-", dir=_scratch_root()) as scratch:
            return _spawn(argv, Path(scratch), timeout)
    return _spawn(argv, cwd, timeout)


def _scratch_root() -> Path | None:
    """Where a scratch working directory may live so an engine can see it.

    A Flatpak sandbox has its **own** ``/tmp``, so a host ``/tmp`` path cannot
    be translated into it. ``bwrap`` does not refuse: it drops the request and
    starts the process in ``$HOME``. Measured against both installed apps by
    writing a file from inside the sandbox and looking for it from the host ---
    a cwd under ``~/.cache`` is honoured and the file appears there; a cwd of
    ``/tmp/tmp.GRYOi6pQ0O`` puts the process in ``/home/cam`` instead.
    ``engine.yml`` had already written the reason down: "a Flatpak is a
    materially different execution environment -- sandboxed filesystem, its own
    /tmp, translated paths."

    So every candidate here is **inside the home directory**, which is the part
    a Flatpak can see. The ladder descends only as far as it must:

    1. ``XDG_CACHE_HOME``, but only when it is **absolute**. The basedir spec
       says a relative value "MUST be ignored", and honouring one was not
       harmless: ``mkdir(parents=True)`` resolved it against the process cwd
       and slicelab created ``./mycache/slicelab/engine-cwd`` in the directory
       the user was standing in. That is the litter this function exists to
       prevent, with slicelab as the author rather than the engine.
    2. ``~/.cache``, the spec's own default.
    3. The home directory itself, if neither of those can be created --- one
       stray file at ``~/.cache/slicelab`` is enough, and so is ``EACCES`` or a
       full disk. The scratch directory is still made and removed, so nothing
       persists; it is only less tidy.
    4. ``None``, handing ``tempfile`` its default, only when the home directory
       is unusable too.

    Step 4 is a real degradation and is named as one: under a Flatpak it puts
    the litter back in ``$HOME``. It is the last rung rather than the first
    because a host with no writable home breaks the engine long before it
    breaks this, and there is no better place left to point at. Every rung
    above it was previously step 4: ``except OSError: return None`` sent an
    ordinary stray file at ``~/.cache/slicelab`` straight to ``/tmp``, and
    ``slicelab which orcaslicer`` wrote into ``$HOME`` again at exit 0.
    """
    base = os.environ.get("XDG_CACHE_HOME") or ""
    candidates = []
    # Relative values are ignored, per the spec -- not resolved against cwd.
    if base and Path(base).is_absolute():
        candidates.append(Path(base) / "slicelab" / "engine-cwd")
    try:
        home = Path.home()
    except (OSError, RuntimeError):  # no home directory to resolve at all
        return None
    candidates.append(home / ".cache" / "slicelab" / "engine-cwd")
    candidates.append(home)

    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
        except OSError:
            continue
        return candidate
    return None


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
