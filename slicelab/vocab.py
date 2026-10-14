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
    "FILAMENT_CM3",
    "FILAMENT_G",
    "FILAMENT_MM",
    "GCODE_FOOTER",
    "GCODE_KEY",
    "GEOMETRY_TABLE",
    "LAYERS",
    "LOCK_SUFFIX",
    "MESH_INFO",
    "MODEL_KEY",
    "OUTPUT_TABLE",
    "PRINT_TIME_S",
    "REPORTED_STATS",
    "RUN_TABLES",
    "SET_TABLE",
    "SLICER_MARKER_COUNT",
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
directory slicelab owns, and slicelab promotes on `sliced` or `empty` -- D7, and
D24's carve-out from it. An engine handed the author's own path writes it before the
slice block runs and leaves it there when the slice fails -- [V4] is exactly that,
rc=0 with a complete config and no G-code.
"""

RUN_TABLES: Final[frozenset[str]] = frozenset({GEOMETRY_TABLE, OUTPUT_TABLE})
"""Top-level tables that are slicelab's own rather than an engine's.

Everything else at top level names the engine, so these are subtracted before the
engine is identified. The cost is stated rather than discovered: an engine may not
be called `geometry` or `output`. Neither is a slicer.
"""

FILAMENT_MM: Final = "filament_mm"
FILAMENT_CM3: Final = "filament_cm3"
FILAMENT_G: Final = "filament_g"
PRINT_TIME_S: Final = "print_time_s"
LAYERS: Final = "layers"

REPORTED_STATS: Final[frozenset[str]] = frozenset(
    {FILAMENT_MM, FILAMENT_CM3, FILAMENT_G, PRINT_TIME_S, LAYERS}
)
"""The closed set of numbers `slice.lock` reports about a slice.

slicelab's own names, not an engine's, and that is the one place D2's rule is
inverted on purpose: these are a *lock* schema read by another tool (D22), so they
have to mean the same thing whichever engine produced them. The engine's own
spelling survives beside each number as its provenance key, which is what keeps the
translation checkable instead of asserted.

Closed because an open set is how a field nobody measured arrives: a reader of the
lock can ask whether a name is in here, and nothing can add one by writing it.
"""

GCODE_FOOTER: Final = "gcode_footer"
"""The engine's own `key = value` comments in a text artifact."""

SLICER_MARKER_COUNT: Final = "slicer_marker_count"
"""A count of a marker the engine emits per occurrence, because it reports no total.

PrusaSlicer 2.9.6 has no layer-count field: measured 2026-10-05, a 20 mm cube at
0.2 mm emits `;LAYER_CHANGE` 100 times and no key says 100. Counting is the only
source, and saying so is the difference between a measured number and one that
looks like the engine's.
"""

LOCK_SUFFIX: Final = ".lock"
"""What `slice` names its record, derived from the intent the way the readback is.

`slice.toml` gives `slice.lock`, the README's four-file layout. Deriving rather than
fixing the name is what keeps two intents in one directory from overwriting each
other's lock, and it is the rule the readback suffix already follows.
"""

MESH_INFO: Final = "mesh_info"
"""The engine's own report about the input mesh, in model coordinates.

A category, not a key. The engine's own key for a plated placement -- measured
2026-10-05, it is one of the 393 keys a PrusaSlicer artifact states -- stays in the
adapter and reaches the lock as a stat's `key`, because a core module naming it
would put an engine's vocabulary in slicelab's own (D26).
"""
