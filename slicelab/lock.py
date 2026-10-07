"""`slice.lock`: what produced this artifact, written only for a run slicelab stands behind.

The lock is read by another tool as a **file** (D22), which decides three things about
how it is written here.

It is self-contained. `effective_config` holds the engine's configuration document
rather than a path to it, because a premise with a dangling reference is not a
premise: the readback beside the intent is rewritten by the next run, so a lock that
pointed at it would start disagreeing with itself while nothing about its own slice
had changed. The readback file stays (D31) -- it is the engine's own bytes, and this
is slicelab's transcription of them.

It says `values_resolved = false`, which is D6. Both engines export a resolved
*document*, not resolved values: PrusaSlicer reports `extrusion_width = 0` and
`first_layer_extrusion_width = 200%` while the toolpaths were generated at 0.45 mm
and 0.70 mm. Calling the document "the resolved settings" is the plausible-substitute
failure one level above the one the lock exists to catch.

And it is written by hand. slicelab has no runtime dependencies and `tomllib` only
reads, so the emitter below is the whole TOML writer. It lives here rather than in a
module of its own because the lock is its only consumer; the risk is entirely in
escaping, and what the lock carries is an engine's configuration -- values holding
double quotes and literal backslash-n pairs, `start_gcode = M862.3 P
"[printer_model]" ... \\nG90`. Measured against this host's own 393-key dump: every
value round-trips through `tomllib` unchanged, the longest being 1328 characters.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Final, TypeGuard

__all__ = ["SCHEMA_VERSION", "dumps"]

#: The lock's own version, first key in the file. A reader checks this before
#: trusting anything else, so it is top level and not inside a table: a consumer
#: should not have to enter a structure to find out whether it understands it.
SCHEMA_VERSION: Final = 1

#: Keys that need no quoting. Anything else is quoted rather than assumed safe -- an
#: engine key is bare today and a lock that silently emitted an invalid key would
#: fail at the reader, far from the cause.
_BARE_KEY: Final = re.compile(r"^[A-Za-z0-9_-]+$")

_ESCAPES: Final[Mapping[str, str]] = {
    '"': '\\"',
    "\\": "\\\\",
    "\n": "\\n",
    "\t": "\\t",
    "\r": "\\r",
    "\b": "\\b",
    "\f": "\\f",
}


def _string(text: str) -> str:
    """A TOML basic string.

    The control-character arm is not decoration: a `\\x00` or a stray `\\x1f` in a
    value would otherwise be emitted raw and make the file unparseable, and the
    values here come from an engine rather than from slicelab.
    """
    out: list[str] = ['"']
    for character in text:
        escape = _ESCAPES.get(character)
        if escape is not None:
            out.append(escape)
        elif 0xD800 <= ord(character) <= 0xDFFF:
            # A lone surrogate, which the artifact's `surrogateescape` decode produces
            # from an undecodable byte. TOML has no spelling for it and this document is
            # encoded as UTF-8, so emitting it raised from `encode` AFTER the artifact had
            # been handed over -- a traceback where a stated refusal belongs.
            raise ValueError(
                f"a lock does not record an unpaired surrogate (U+{ord(character):04X}): "
                "the engine wrote a byte slicelab cannot represent as text"
            )
        elif ord(character) < 0x20 or ord(character) == 0x7F:
            out.append(f"\\u{ord(character):04X}")
        else:
            out.append(character)
    out.append('"')
    return "".join(out)


def _key(name: str) -> str:
    return name if _BARE_KEY.match(name) else _string(name)


def _value(value: object) -> str:
    # bool before int, deliberately: `isinstance(True, int)` is true in Python, and
    # a boolean emitted as `1` would read back as an integer.
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return _string(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise ValueError(f"a lock does not record {value!r}: it is not a measurement")
        return repr(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return "[" + ", ".join(_value(item) for item in value) + "]"
    raise TypeError(f"not something a lock records: {value!r}")


def _is_table(value: object) -> TypeGuard[Mapping[str, object]]:
    return isinstance(value, Mapping)


def _is_table_array(value: object) -> TypeGuard[Sequence[Mapping[str, object]]]:
    """A non-empty sequence of tables, which TOML writes as `[[name]]` blocks.

    A `TypeGuard` rather than a `bool` so the caller is narrowed by it: the
    alternative was a pair of `type: ignore` comments asserting what this already
    checks, and an ignore that stops matching the real error is how a type gap hides.
    """
    return (
        isinstance(value, Sequence)
        and not isinstance(value, (str, bytes))
        and len(value) > 0
        and all(_is_table(item) for item in value)
    )


def dumps(document: Mapping[str, object], _path: str = "") -> str:
    """TOML for a document of scalars, arrays, tables and arrays of tables.

    Scalars are emitted before tables at every level, which is not a style choice:
    TOML binds a bare key to the most recently opened table, so a scalar written
    after a sub-table would silently become part of that sub-table and the file would
    parse -- into the wrong shape. That is the failure this ordering prevents, and
    `tests/test_lock.py` pins it.
    """
    scalars: list[str] = []
    tables: list[str] = []

    for name, value in document.items():
        if _is_table(value):
            prefix = f"{_path}{_key(name)}"
            body = dumps(value, f"{prefix}.")
            tables.append(f"[{prefix}]\n{body}".rstrip("\n"))
        elif _is_table_array(value):
            prefix = f"{_path}{_key(name)}"
            for item in value:
                body = dumps(item, f"{prefix}.")
                tables.append(f"[[{prefix}]]\n{body}".rstrip("\n"))
        else:
            scalars.append(f"{_key(name)} = {_value(value)}")

    return "\n\n".join(part for part in ["\n".join(scalars), *tables] if part)
