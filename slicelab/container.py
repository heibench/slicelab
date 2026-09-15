"""What container an artifact is in, decided from its own first bytes.

D10: the output container is **sniffed**, never assumed from a flag slicelab passed
or from a file extension. Both would be slicelab's record of what it asked for rather
than of what it got, and the two differ -- `binary_gcode = 1` is the stock default for
the entire current Prusa line [V7], so the binary container is the ordinary path and
not an edge case.

The consequence is not cosmetic. A `GCDE` container has no text footer to read: a
real MK3S slice carries two `prusaslicer_config` markers and 369 footer keys, and a
real binary slice of the same model carries **zero**, measured on 2.9.6. So the
config-footer half of any artifact-derived record exists only for ASCII output, and
`normalized_sha256` has nothing to normalize. That is an `unknowns` code and a null
hash, never a silent fallback to hashing raw bytes (D9).

slicelab **never** forces `--binary-gcode=0` to make its own job easier, because that
changes the artifact the author asked for.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

__all__ = ["Container", "sniff"]


class Container(StrEnum):
    """Which container an artifact turned out to be in."""

    BGCODE = "bgcode"
    """The engine's binary container. No text footer, so no normalized hash (D9, D10)."""

    GCODE = "gcode"
    """The engine's ordinary text container.

    Says what this is NOT -- the declared binary magic -- rather than asserting an
    encoding. A text G-code file has no magic of its own to check: 2.9.6's begins
    `; ge`, but that is a comment the engine happened to write first, and treating it
    as a signature would make a file starting with a bare `G1` unrecognisable.
    """

    UNDETERMINED = "undetermined"
    """The engine declared no binary magic, so slicelab cannot tell the two apart.

    Not `gcode`. An adapter that has not measured what its engine's binary container
    looks like cannot have "this is not it" concluded on its behalf -- that is the
    could-not-tell org contract 2.2 keeps separate from a finding.
    """


def sniff(artifact: Path, magic: bytes | None) -> Container:
    """Read the leading bytes and say which container they are.

    `magic` is the engine's own binary signature, from its adapter, or `None` where
    nobody has measured one. The rule is slicelab's and the signature is the
    engine's, for the reason D1's seam exists: a core that knows `GCDE` is a core
    that knows one engine's file formats.

    A file too short to hold the magic is not the binary container -- it cannot be --
    so a truncated artifact reads as `GCODE` here and is caught by the gate that asks
    whether the engine wrote anything worth reading.
    """
    if magic is None:
        return Container.UNDETERMINED
    with artifact.open("rb") as handle:
        return Container.BGCODE if handle.read(len(magic)) == magic else Container.GCODE
