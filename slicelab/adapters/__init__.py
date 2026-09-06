"""Per-engine facts. Nothing outside this package names an engine.

The core knows there are engines; only these modules know what they are called,
where they live, or what their flags look like. ``tests/test_boundaries.py``
enforces it for the strings that matter.
"""

from __future__ import annotations

from slicelab.adapters.base import EngineSpec
from slicelab.adapters.orcaslicer import SPEC as ORCASLICER
from slicelab.adapters.prusaslicer import SPEC as PRUSASLICER

__all__ = ["ORCASLICER", "PRUSASLICER", "EngineSpec", "REGISTRY", "spec_for"]

REGISTRY: dict[str, EngineSpec] = {
    PRUSASLICER.name: PRUSASLICER,
    ORCASLICER.name: ORCASLICER,
}


def spec_for(name: str) -> EngineSpec | None:
    """Look up an engine by name.

    Returns ``None`` rather than raising: an unknown engine name is a real
    answer the CLI turns into an outcome, not a ``KeyError`` for a caller to
    trip over (D1).
    """
    return REGISTRY.get(name)
