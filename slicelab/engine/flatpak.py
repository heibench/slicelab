"""Flatpak: where an app's files really are, and what it can reach.

Adapted from prusaslicer-py's ``_flatpak_roots`` / ``_to_engine_path`` /
``_sandbox_grants`` (Apache-2.0, heibench/prusaslicer-py, D9), with one
deliberate change -- see :func:`to_engine_path`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

__all__ = ["Translation", "grants_for", "is_installed", "roots_for", "to_engine_path"]


def roots_for(app_id: str) -> list[Path]:
    """Host locations where this Flatpak's own files are mounted."""
    return [
        Path("/var/lib/flatpak/app") / app_id / "current/active/files",
        Path.home() / ".local/share/flatpak/app" / app_id / "current/active/files",
    ]


def is_installed(app_id: str) -> bool:
    """Whether any root for this app resolves on disk.

    Cheap and filesystem-only. Confirming the app actually *runs* is the
    discovery probe's job, not this function's.
    """
    for root in roots_for(app_id):
        try:
            if root.resolve().is_dir():
                return True
        except OSError:
            continue
    return False


@dataclass(frozen=True)
class Translation:
    """A host path as the engine will see it, and whether it moved."""

    path: str
    translated: bool


def to_engine_path(app_id: str, path: str) -> Translation:
    """Translate a host path into the sandbox's view of it.

    Inside the sandbox a Flatpak's own files are mounted at ``/app``, not at
    the host path they occupy on disk. A bundled file under
    ``/var/lib/flatpak/.../files/share/...`` is therefore real to us and absent
    to the engine, which answers "No such file" for a path that plainly exists.

    **The change from prusaslicer-py (D19):** this returns whether translation
    happened, instead of silently returning the host path when it could not.
    A path under a known Flatpak root that failed to translate is a
    could-not-tell, and passing the untranslated path on dressed as a
    translation hands the engine something it cannot open and calls that the
    engine's problem.

    Paths outside the app's own tree are the caller's files and pass through
    unchanged, reported as ``translated=False``. Those are reachable via
    :func:`grants_for`.
    """
    resolved = Path(path).expanduser().resolve()
    for root in roots_for(app_id):
        try:
            # resolve() follows `current/active`, a symlink into a hashed
            # deployment directory -- comparing against the unresolved root
            # never matches.
            real_root = root.resolve()
        except OSError:
            continue
        try:
            relative = resolved.relative_to(real_root)
        except ValueError:
            continue
        return Translation(str(Path("/app") / relative), translated=True)
    return Translation(path, translated=False)


def grants_for(paths: set[str]) -> list[str]:
    """``--filesystem`` arguments for exactly the directories involved.

    Computed from the caller's whole path set, never a fixed pair.
    prusaslicer-py grants exactly two directories, so a config file elsewhere
    surfaces as an *engine* error for a grant the driver forgot (D19).

    Never ``--filesystem=host``: this runs inside other people's build
    pipelines, and a driver should not hand the engine the whole filesystem to
    slice one part.
    """
    directories = {str(Path(p).expanduser().resolve().parent) for p in paths}
    return [f"--filesystem={d}" for d in sorted(directories)]
