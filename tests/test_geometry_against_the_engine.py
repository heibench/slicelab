"""The geometry readers, against what this engine says about a mesh it just read.

`tests/test_geometry.py` drives both parses with output written by hand. Those
fixtures are a claim about the engine's shape, and a hand-written fixture outlives
the shape it was copied from. The cube is slicelab's own and its dimensions are
known exactly, which is what lets the mesh box be asserted as numbers here rather
than as "greater than zero".
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from slicelab.adapters import EngineSpec
from slicelab.engine.discover import argv_for, discover
from slicelab.geometry import mesh_sha256
from slicelab.vocab import GCODE_FOOTER, MESH_INFO
from tests.conftest import skip_or_fail
from tests.test_slice_against_the_engine import TRIPLE, _cube

#: The cube the suite writes, in mm. Asserted rather than read back, because a test
#: that takes its expected value from the thing under test checks nothing.
EDGE = 20.0


def _engine(usable_engines: list[EngineSpec]) -> EngineSpec:
    for spec in usable_engines:
        if spec.compose_mesh_info is not None and spec.read_mesh_info is not None:
            return spec
    skip_or_fail("no engine that has declared how to describe a mesh is installed")


@pytest.fixture(scope="module")
def engine(usable_engines: list[EngineSpec]) -> EngineSpec:
    return _engine(usable_engines)


def test_the_engine_s_mesh_box_is_the_cube_the_suite_wrote(engine, tmp_path: Path) -> None:
    """Model coordinates: a cube written at the origin reads 0..20 on every axis.

    The plate footprint in the next test is the same cube at (125, 105). The two
    numbers disagreeing is the whole reason both fields exist.
    """
    mesh = _cube(tmp_path / "part.stl")
    found = discover(engine)
    if found.form is None:
        skip_or_fail(f"{engine.name} did not start: {found.reason}")

    invocation = engine.compose_mesh_info(mesh)
    done = subprocess.run(
        argv_for(found.form, invocation.argv, invocation.paths),
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert done.returncode == 0, f"{done.stdout}\n{done.stderr}"

    facts = engine.read_mesh_info(done.stdout)
    assert facts is not None, f"the engine described nothing slicelab could read: {done.stdout!r}"
    assert facts.source == MESH_INFO
    assert facts.min_mm == (0.0, 0.0, 0.0)
    assert facts.max_mm == (EDGE, EDGE, EDGE)
    assert facts.facets == 12, "a cube is 12 triangles"
    assert facts.volume_mm3 == pytest.approx(EDGE**3, rel=1e-6)
    assert facts.manifold is True
    assert len(mesh_sha256(mesh)) == 64


def test_a_sliced_artifact_states_where_the_cube_landed(engine, tmp_path: Path) -> None:
    """Plate coordinates, from the artifact rather than the mesh.

    The polygon is a square of the cube's own edge length somewhere on the bed, and
    its position is the printer profile's business, not this test's -- so the shape
    is asserted and the location is not.
    """
    if engine.read_placement is None:
        skip_or_fail(f"{engine.name} has declared no way to read a placement")

    _cube(tmp_path / "part.stl")
    intent = tmp_path / "slice.toml"
    intent.write_text(
        '[geometry]\nmodel = "part.stl"\n\n[output]\ngcode = "part.gcode"\n\n'
        + TRIPLE
        + "\n[prusaslicer.set]\nperimeters = 2\n",
        encoding="utf-8",
    )
    done = subprocess.run(
        [sys.executable, "-m", "slicelab", "slice", str(intent)],
        capture_output=True,
        text=True,
        timeout=1800,
    )
    assert done.returncode == 0, f"{done.stdout}\n{done.stderr}"

    artifact = tmp_path / "part.gcode"
    placement = engine.read_placement(artifact.read_text(encoding="utf-8", errors="replace"))
    assert placement is not None, "the artifact stated no placement"
    assert placement.source == GCODE_FOOTER
    assert len(placement.objects) == 1

    name, polygon = placement.objects[0]
    assert "part.stl" in name, f"the engine named the object {name!r}"
    assert len(polygon) == 4, "a cube's footprint is a quadrilateral"

    xs = {round(x, 3) for x, _ in polygon}
    ys = {round(y, 3) for _, y in polygon}
    assert max(xs) - min(xs) == pytest.approx(EDGE, abs=0.01)
    assert max(ys) - min(ys) == pytest.approx(EDGE, abs=0.01)
    assert min(xs) > 0 and min(ys) > 0, "plate coordinates, not model coordinates"
