"""The core normalized vocabulary, which is empty, and the shape of an intent file.

D2: authored keys are the engine's **own native names** under an engine-namespaced
table, and slicelab defines no cross-engine vocabulary in v0.1.0. 135 of
PrusaSlicer's 343 config keys share a name with an Orca key and at least five of the
first dozen adjudicated are traps -- `gcode_label_objects` is an enum in one and a
bool in the other, `bed_temperature` has no single Orca counterpart at all. A
vocabulary written from one engine *is* the PrusaSlicer-shaped abstraction this
project exists to avoid.

So `CORE_KEYS` is empty, and it is empty **by assertion**, not by nobody having got
round to filling it. A key enters only through D3's recorded admission procedure.
"""

from __future__ import annotations

from typing import Final

__all__ = [
    "BASE_TABLE",
    "CORE_KEYS",
    "ENGINE_TABLES",
    "GEOMETRY_TABLE",
    "MODEL_KEY",
    "OUTPUT_TABLE",
    "RUN_TABLES",
    "SET_TABLE",
    "GCODE_KEY",
]

CORE_KEYS: Final[frozenset[str]] = frozenset()
"""The normalized cross-engine setting vocabulary. Empty, and asserted so (D2)."""

BASE_TABLE: Final = "base"
"""The preset triple: which stored configuration the run starts from."""

SET_TABLE: Final = "set"
"""The authored delta. The mechanism adjudicates these and only records the base."""

ENGINE_TABLES: Final[frozenset[str]] = frozenset({BASE_TABLE, SET_TABLE})
"""Everything an engine table may contain. Anything else is refused, not ignored."""

GEOMETRY_TABLE: Final = "geometry"
"""What is being sliced. Top-level, because it is not an engine's vocabulary.

A model is slicelab's word for the thing on the plate, and it is deliberately not
under the engine table: both engines take a mesh path as a positional argument and
neither has an option name for it, so putting it beside `base` and `set` -- which
hold the engine's own CLI option names (D28) -- would be the one key there that is
not one.
"""

MODEL_KEY: Final = "model"
"""The mesh to slice, relative to the intent file unless absolute.

Relative to the INTENT, not to the process working directory. The README's git model
is four files in one directory -- `part.stl`, `slice.toml`, `slice.lock`,
`part.gcode` -- and an intent that means a different file depending on where you
stood when you ran it is not a record of anything.
"""

OUTPUT_TABLE: Final = "output"
"""Where the result goes. Top-level for the same reason as `geometry`."""

GCODE_KEY: Final = "gcode"
"""Where the sliced artifact is promoted to, relative to the intent file.

slicelab writes this and the engine never does: the engine slices into a scratch
directory slicelab owns, and slicelab promotes on `sliced` and only on `sliced`
(D7). An engine handed the author's own path writes it before the slice block runs
and leaves it there when the slice fails -- [V4] is exactly that, rc=0 with a
complete config and no G-code.
"""

RUN_TABLES: Final[frozenset[str]] = frozenset({GEOMETRY_TABLE, OUTPUT_TABLE})
"""Top-level tables that are slicelab's own rather than an engine's.

Everything else at top level names the engine, so these are subtracted before the
engine is identified. The cost is stated rather than discovered: an engine may not
be called `geometry` or `output`. Neither is a slicer.
"""
