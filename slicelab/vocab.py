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

__all__ = ["BASE_TABLE", "CORE_KEYS", "ENGINE_TABLES", "SET_TABLE"]

CORE_KEYS: Final[frozenset[str]] = frozenset()
"""The normalized cross-engine setting vocabulary. Empty, and asserted so (D2)."""

BASE_TABLE: Final = "base"
"""The preset triple: which stored configuration the run starts from."""

SET_TABLE: Final = "set"
"""The authored delta. The mechanism adjudicates these and only records the base."""

ENGINE_TABLES: Final[frozenset[str]] = frozenset({BASE_TABLE, SET_TABLE})
"""Everything an engine table may contain. Anything else is refused, not ignored."""
