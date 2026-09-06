"""Which engine build is this, exactly.

A version string is not an identity. Two hosts can both say "2.9.6" and run
different builds -- one Flathub, one distro-packaged, one built from source --
and ``notes/evidence.md`` V10 shows those builds differ in behaviour that
matters. So identity carries how the engine was reached and a digest of the
thing that will actually run.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from slicelab.adapters import EngineSpec
from slicelab.engine.discover import Discovery, LaunchKind
from slicelab.engine.launch import run

__all__ = ["Identity", "identify"]

#: Both installed engines print ``Name-VERSION`` somewhere near the top of
#: ``--help``. Neither supports a ``--version`` flag: one answers "Unknown
#: option --version" and the other "Invalid option --version", so ``--help`` is
#: the only place either states its version.
_VERSION_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*-(\d+\.\d+(?:\.\d+)?)")

IDENTITY_TIMEOUT_S = 90.0


@dataclass(frozen=True)
class Identity:
    """What slicelab established about the build it is talking to."""

    engine: str
    kind: str
    version: str | None
    banner: str | None
    digest: str | None
    digest_of: str | None

    @property
    def exact(self) -> bool:
        """Whether a version was actually read from the engine.

        ``False`` is a value a caller can branch on, in the shape orlab's
        ``profile_exact`` established (silence.html case 3): a version we could
        not read must not be reported as one we could.
        """
        return self.version is not None


def identify(
    spec: EngineSpec, discovery: Discovery, *, timeout: float = IDENTITY_TIMEOUT_S
) -> Identity:
    """Read the engine's identity, or say honestly that it could not be read."""
    if discovery.form is None:
        return Identity(spec.name, "absent", None, None, None, None)

    banner, version = _read_banner(discovery, timeout=timeout)

    digest, digest_of = _digest(spec, discovery)
    return Identity(
        engine=spec.name,
        kind=discovery.form.kind.value,
        version=version,
        banner=banner,
        digest=digest,
        digest_of=digest_of,
    )


#: How far into --help to look for a version line before giving up. The banner
#: is near the top on every engine measured; a large window would start
#: matching option help text that happens to contain a version number.
_BANNER_WINDOW = 10


def _read_banner(discovery: Discovery, *, timeout: float) -> tuple[str | None, str | None]:
    """Return (banner, version), either of which may be None.

    **The version is not always the first line.** The native Windows console
    build opens its ``--help`` with ``System OpenGL library successfully
    released`` and states its version below that; taking the first non-empty
    line reported the version as unreadable on an engine that had just told us
    (engine matrix, 2026-09-06). The Linux Flatpak has no such preamble, which
    is why one host was not enough to find this.

    So: scan a small window for a line that looks like a version, and fall back
    to the first non-empty line as the banner. A banner with no parseable
    version leaves ``version`` None and ``Identity.exact`` False -- a version we
    could not read is never reported as one we could.
    """
    assert discovery.form is not None
    completed = run([*discovery.form.argv_prefix, "--help"], timeout=timeout)
    if completed.timed_out or completed.died_by_signal:
        return None, None

    first: str | None = None
    for stream in (completed.stdout, completed.stderr):
        for line in stream.splitlines()[:_BANNER_WINDOW]:
            stripped = line.strip()
            if not stripped:
                continue
            if first is None:
                first = stripped
            match = _VERSION_RE.match(stripped)
            if match:
                return stripped, match.group(1)
    return first, None


def _digest(spec: EngineSpec, discovery: Discovery) -> tuple[str | None, str | None]:
    """A digest of what will actually run, and a note of what was hashed.

    For a PATH binary that is the executable. For a Flatpak it is **not** --
    the launcher on PATH is ``flatpak`` itself, and hashing it would digest the
    launcher rather than the engine, producing a value that is identical across
    every Flatpak app on the machine. The deployment commit is the honest
    analogue, and ``digest_of`` says which was used so nobody compares two
    incomparable values.
    """
    assert discovery.form is not None
    if discovery.form.kind is LaunchKind.PATH:
        binary = Path(discovery.form.argv_prefix[0])
        try:
            return hashlib.sha256(binary.read_bytes()).hexdigest(), f"executable {binary}"
        except OSError:
            return None, None

    app_id = spec.flatpak_app_id
    if app_id is None:
        return None, None
    info = run(["flatpak", "info", app_id], timeout=30.0)
    if info.exit_status != 0:
        return None, None
    for line in info.stdout.splitlines():
        key, _, value = line.partition(":")
        if key.strip().lower() == "commit":
            return value.strip(), f"flatpak deployment commit for {app_id}"
    return None, None
