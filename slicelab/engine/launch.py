"""The only module in slicelab permitted to import ``subprocess``.

Enforced by ``tests/test_boundaries.py``. Everything an engine invocation needs
to be honest about is decided here, once, rather than at every call site.
"""

from __future__ import annotations

import contextlib
import os
import signal
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
    fault, not a hang in slicelab. And a timeout that kills the **whole process
    group**, because the direct child is usually a launcher: ``flatpak run``
    spawns ``bwrap`` spawns the slicer, and killing only the launcher leaves a
    GUI process alive forever. See :func:`_spawn`.

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
    try:
        raw_home = Path.home()
    except (OSError, RuntimeError):
        # Python 3.13+ raises RuntimeError when neither $HOME nor the passwd
        # entry yields a home directory. An earlier draft guarded this; the
        # rewrite that added the containment check dropped the guard, which
        # would have turned "this host has no home directory" into an unhandled
        # traceback out of `run` rather than a launch that carries on in a
        # temporary directory.
        return []
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


KILL_GRACE_S = 5.0
"""How long a timed-out process group gets to die politely before SIGKILL."""


def _spawn(argv: list[str], cwd: Path, timeout: float) -> Completed:
    """Run to completion, or kill the **whole process tree** and say it timed out.

    ``subprocess.run(timeout=...)`` kills only the direct child, and the direct
    child is very often not the engine. ``flatpak run`` spawns ``bwrap``, which
    spawns the slicer; killing the launcher orphans both, and an orphaned GUI
    process never exits on its own. Measured on this host: repeated
    characterisation sweeps left **75** orphaned engine processes alive, the
    oldest 8 h 17 m old, at a fifteen-minute load average of 60.

    That is the timeout doing the opposite of its job. It exists so one hung
    option cannot hang the machine; without a group kill it converts one hang
    into several permanent ones per sweep, cumulatively, and the second sweep on
    that machine then measures a host under load rather than an engine.

    So the child gets its own session, and a timeout signals the **group**:
    SIGTERM, a grace period, then SIGKILL. POSIX only -- ``setsid`` and
    ``killpg`` do not exist on Windows, where this degrades to the old
    single-process kill. That is a real gap and it is named rather than papered
    over; the Flatpak launcher this is written for is POSIX-only, so the leak it
    fixes cannot arise there.
    """
    posix = os.name == "posix"
    with subprocess.Popen(  # noqa: S603 - argv is a list; never shell=True
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        text=True,
        errors="replace",
        cwd=cwd,
        start_new_session=posix,
    ) as proc:
        # Read off the live pipes, before `communicate` closes them. The timeout
        # paths get raw bytes from `TimeoutExpired` and have to decode them the
        # way the normal path would; hardcoding UTF-8 there makes a timed-out run
        # disagree with a completed one under any other locale.
        encoding, errors = _pipe_text_config(proc)
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            _terminate_tree(proc, posix=posix)
            # Drain what the tree managed to say before it died, and **bound the
            # drain**. The write ends of these pipes are inherited by every
            # descendant, so an unbounded `communicate` waits for the last one to
            # let go -- which is precisely the orphan this function just tried to
            # kill. Measured: with the group kill disabled, the drain blocked for
            # the orphan's full 120 s lifetime and then returned normally, so the
            # leak surfaced as a slow success rather than as a failure.
            try:
                stdout, stderr = proc.communicate(timeout=KILL_GRACE_S)
            except subprocess.TimeoutExpired as drained:
                # Something in the tree still holds the pipes. Fall back to what
                # was captured rather than blocking -- and take it from the
                # SECOND exception, not the first. CPython accumulates into the
                # same per-stream buffer across `communicate` calls, so the
                # second carries everything the first did plus whatever arrived
                # during the grace period. Measured: first `b'FIRST\n'`, second
                # `b'FIRST\nSECOND\n'`. That window is exactly when a tree being
                # SIGKILLed emits its last diagnostic, and two earlier revisions
                # threw it away -- one returning empty strings, one reading the
                # first snapshot. Losing what a hung engine managed to say is the
                # failure prusaslicer-py D5 exists to prevent.
                stdout = _as_text(drained.stdout, encoding=encoding, errors=errors)
                stderr = _as_text(drained.stderr, encoding=encoding, errors=errors)
            return Completed(
                argv=list(argv),
                exit_status=None,
                signal=None,
                stdout=_as_text(stdout, encoding=encoding, errors=errors),
                stderr=_as_text(stderr, encoding=encoding, errors=errors),
                timed_out=True,
            )
        returncode = proc.returncode

    # POSIX reports a signal death as a negative returncode. Split it, rather
    # than passing on a number that means two different things.
    if returncode < 0:
        return Completed(
            argv=list(argv),
            exit_status=None,
            signal=-returncode,
            stdout=_as_text(stdout),
            stderr=_as_text(stderr),
        )
    return Completed(
        argv=list(argv),
        exit_status=returncode,
        signal=None,
        stdout=_as_text(stdout),
        stderr=_as_text(stderr),
    )


def _terminate_tree(proc: subprocess.Popen[str], *, posix: bool) -> None:
    """Kill the timed-out process and everything it started.

    Three things this gets wrong if written the obvious way, and all three were
    written the obvious way first.

    **The group id is read from the live process** rather than assumed to equal
    its pid: if the child has already been reaped there is no group to signal,
    and signalling pid 0 means *this* process's group.

    **A group that is our own is never signalled.** Guarding pid 0 is not enough.
    This is a module-level function taking any ``Popen``, and nothing in its
    signature says the child was started with ``start_new_session=True`` -- that
    happens twenty lines away in :func:`_spawn`. A child sharing our group is
    therefore reachable, and ``killpg`` on it terminates slicelab and whatever
    launched slicelab. Measured, by flipping ``start_new_session`` to ``False``:
    the process doing the killing died at exit 143 on SIGTERM. The guard also
    makes that flag safe to mutation-test, which it was not.

    **SIGKILL after the grace period is unconditional.** Waiting on the *direct
    child* and escalating only if that wait times out reintroduces the original
    defect one level in: a launcher that dies politely on SIGTERM while a
    descendant ignores it makes the wait return immediately, the escalation never
    fires, and the descendant survives -- which is the exact shape ``flatpak run``
    has. Signalling an already-dead group is a no-op, so there is nothing to save
    by asking first.

    **Two limits, named because they are limits and not oversights.** The
    same-group fallback and the Windows branch both call ``proc.kill()``, which
    ends the direct child only -- a tree started that way is orphaned exactly as
    before, with nothing recorded to say so. Neither is reachable from
    :func:`_spawn` on a POSIX host, which is the only place slicelab launches an
    engine; they are reachable by a future caller, which is why this function
    documents what it does not do. And ``PermissionError`` is suppressed on both
    signals, so a kill that fails outright still returns ``timed_out=True`` with
    no field distinguishing "killed it" from "could not". Closing that means a
    channel on :class:`Completed`, which is a wider change than this one.
    """
    if not posix:  # pragma: no cover - exercised only on Windows runners
        proc.kill()
        return
    try:
        group = os.getpgid(proc.pid)
    except (ProcessLookupError, PermissionError):  # pragma: no cover - it is already gone
        proc.kill()
        return
    if group == os.getpgrp():
        # The child never left our group, so there is no tree to signal that does
        # not also contain us. Kill the one process we are certain about.
        proc.kill()
        return
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(group, signal.SIGTERM)
    with contextlib.suppress(subprocess.TimeoutExpired):
        proc.wait(timeout=KILL_GRACE_S)
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(group, signal.SIGKILL)


def _pipe_text_config(proc: subprocess.Popen[str]) -> tuple[str, str]:
    """The encoding and error policy the normal path decodes with.

    Taken from the live stream objects, because ``communicate`` closes them and a
    closed ``TextIOWrapper`` will not answer. Falls back to this module's own
    contract -- UTF-8 and ``replace`` -- if the pipes cannot say.
    """
    stream = proc.stdout or proc.stderr
    encoding = getattr(stream, "encoding", None) or "utf-8"
    errors = getattr(stream, "errors", None) or "replace"
    return encoding, errors


def _as_text(raw: str | bytes | None, *, encoding: str = "utf-8", errors: str = "replace") -> str:
    """Bytes from a timeout, decoded the way a completed run's output would be.

    ``TimeoutExpired`` carries **bytes** even from a text-mode ``Popen``, because
    it is raised before the decode step. Decoding it differently from the normal
    path -- a hardcoded UTF-8, no newline translation -- means a timed-out run
    and a completed one disagree about the same bytes under any other locale, and
    on the one path where the caller is least able to check.
    """
    if raw is None:
        return ""
    if isinstance(raw, bytes):
        raw = raw.decode(encoding, errors=errors)
    return raw.replace("\r\n", "\n").replace("\r", "\n")
