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
        with _scratch() as scratch:
            return _spawn(argv, Path(scratch), timeout)
    return _spawn(argv, cwd, timeout)


def _scratch() -> tempfile.TemporaryDirectory[str]:
    """A working directory for an engine, in the first location that works.

    Descends ``_scratch_roots`` and stops at the first one that both exists and
    accepts a new directory. Creating the directory *is* the usability test:
    ``mkdir(exist_ok=True)`` succeeds on a directory that is already there and
    unwritable, so a ladder that only called ``mkdir`` would settle on a root it
    could not use and let the ``PermissionError`` escape from the launch rather
    than descending to the next rung.

    The final fallback is ``tempfile``'s own default, which under a Flatpak
    means the engine starts in ``$HOME``. That is a real degradation, named
    here as one: it is reached only when nothing inside the home directory can
    hold a directory, which breaks the engine long before it breaks this.
    """
    for root in _scratch_roots():
        try:
            root.mkdir(parents=True, exist_ok=True)
            return tempfile.TemporaryDirectory(prefix="run-", dir=root)
        except OSError:
            continue
    return tempfile.TemporaryDirectory(prefix="slicelab-run-")


def _scratch_roots() -> list[Path]:
    """Places an engine's working directory may go, best first.

    A Flatpak sandbox has its **own** ``/tmp``, so a host ``/tmp`` path cannot
    be translated into it. ``bwrap`` does not refuse: it drops the request and
    starts the process in ``$HOME``. Measured against both installed apps by
    writing a file from inside the sandbox and looking for it from the host ---
    a cwd under ``~/.cache`` is honoured and the file appears there, a cwd of
    ``/tmp/tmp.GRYOi6pQ0O`` puts the process in ``/home/cam`` and the file
    lands there instead. ``engine.yml`` had already written the reason down:
    "a Flatpak is a materially different execution environment -- sandboxed
    filesystem, its own /tmp, translated paths."

    So a candidate qualifies only if it is **under the home directory after
    resolution**. Three rounds of review went into that sentence and each part
    of it is load-bearing:

    * *Absolute* is not enough. ``XDG_CACHE_HOME=/tmp/xdg`` is an ordinary
      setting, and it put ``result.json`` back in ``$HOME`` at exit 0.
    * *Lexically inside* is not enough either. ``~/cache-link -> /tmp/...`` is
      inside ``$HOME`` by string and outside it by inode, and only
      ``resolve()`` can tell. So can ``~/.cache/../../../tmp``.
    * The **home directory must be absolute before it is resolved**.
      ``Path.home()`` hands back ``$HOME`` verbatim, so ``HOME=relhome`` gives
      ``Path("relhome")`` --- and resolving *that* anchors it to the process
      working directory, which is exactly the litter this function exists to
      prevent. Measured: it created ``./relhome/.cache/slicelab/engine-cwd``
      where the user was standing.

    An empty list means no home-visible location exists, and the caller falls
    through to ``tempfile``'s default.
    """
    raw_home = Path.home()
    if not raw_home.is_absolute():
        # A relative $HOME resolves against the process working directory.
        # There is no home-visible location to offer, and inventing one out of
        # the user's cwd is the defect rather than the fallback.
        return []
    home = raw_home.resolve()

    candidates = []
    base = os.environ.get("XDG_CACHE_HOME") or ""
    if base and Path(base).is_absolute():
        # The basedir spec: a relative value "MUST be ignored".
        candidates.append(Path(base) / "slicelab" / "engine-cwd")
    candidates.append(home / ".cache" / "slicelab" / "engine-cwd")
    candidates.append(home)

    resolved = (_resolved(c) for c in candidates)
    return [c for c in resolved if c is not None and _under(c, home)]


def _resolved(path: Path) -> Path | None:
    try:
        return path.resolve()
    except OSError:  # a symlink loop, or a path we cannot walk
        return None


def _under(path: Path, home: Path) -> bool:
    return path == home or home in path.parents


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
