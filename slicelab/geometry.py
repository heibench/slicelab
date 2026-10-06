"""What was sliced, in the two coordinate systems that are not the same thing.

A lock that records one box called `bounding_box` invites the reader to assume it is
the other one. There is no single source for a plated 3D extent, and the two sources
that exist answer different questions:

* `--info` describes the **mesh**, in model coordinates, before the engine has
  placed anything. Measured on 2026-10-05, PrusaSlicer 2.9.6, a 20 mm cube:
  `min_x..max_x = 0..20` on every axis, `number_of_facets = 12`,
  `volume = 8000.000488`, `manifold = yes`.
* the artifact's own `; objects_info` describes where each object **landed on the
  plate**, as an XY polygon and nothing else. The same cube:
  `[[135,115],[115,115],[115,95],[135,95]]` -- a 20 mm square centred at
  (125, 105), which is the middle of an MK3S bed and tells you nothing about Z.

So both are recorded, each named for what it is, and the plated height is a third field
of its own -- `plated_height_mm`, from the engine's own `; max_layer_z` -- rather than a
Z axis bolted onto a footprint the engine reported in two dimensions. Synthesising one
plated 3D box out of a 2D polygon and a separate height would produce a number that is
partly measured and partly
derived with nothing marking which half.

The mesh's identity does not depend on the engine at all: `mesh_sha256` is slicelab
hashing the file it handed over. That is why a lock still identifies its input when
`--info` fails or an engine declares no way to be asked.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Final

__all__ = ["MeshFacts", "Placement", "mesh_sha256"]

#: Why there is no mesh_bbox or fingerprint.
MESH_NOT_DESCRIBED: Final = "engine_described_no_mesh"

#: Why there is no plated footprint.
PLACEMENT_NOT_STATED: Final = "artifact_stated_no_placement"


def mesh_sha256(model: Path) -> str:
    """sha256 of the mesh file, as slicelab read it.

    Not the engine's answer to anything. A facet count and a volume describe what an
    engine made of the bytes; this is the bytes, and it is the field that makes two
    locks comparable when the engines differ.
    """
    with model.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


@dataclass(frozen=True)
class MeshFacts:
    """The engine's description of the input mesh, in model coordinates.

    `facets`, `volume_mm3` and `manifold` are the fingerprint: enough to tell one
    mesh from another and to notice a mesh the engine considers open, which is a
    print failure that no amount of correct configuration fixes. Each is optional
    because an engine may describe some of them and not others, and a missing one is
    absent rather than guessed.
    """

    source: str
    key: str
    min_mm: tuple[float, float, float]
    max_mm: tuple[float, float, float]
    facets: int | None = None
    volume_mm3: float | None = None
    manifold: bool | None = None

    def as_table(self) -> dict[str, object]:
        table: dict[str, object] = {
            "source": self.source,
            "key": self.key,
            "min_mm": list(self.min_mm),
            "max_mm": list(self.max_mm),
        }
        if self.facets is not None:
            table["facets"] = self.facets
        if self.volume_mm3 is not None:
            table["volume_mm3"] = self.volume_mm3
        if self.manifold is not None:
            table["manifold"] = self.manifold
        return table


@dataclass(frozen=True)
class Placement:
    """Where each object landed on the plate: an XY polygon per object, no Z.

    The polygon is the engine's own, point for point. Not a bounding box computed
    from it -- the engine reported a shape, and reducing it to its extent here would
    throw away the one thing that distinguishes a rotated part from an axis-aligned
    one, which is exactly what a reader checking placement wants.
    """

    source: str
    key: str
    objects: tuple[tuple[str, tuple[tuple[float, float], ...]], ...]

    def as_table(self) -> dict[str, object]:
        return {
            "source": self.source,
            "key": self.key,
            "objects": [
                {"name": name, "polygon": [list(point) for point in polygon]}
                for name, polygon in self.objects
            ],
        }
