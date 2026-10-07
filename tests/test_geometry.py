"""Two coordinate systems, kept apart, and a mesh identity that needs no engine.

The lock records a mesh box in model coordinates and a plate footprint in plate
coordinates. They are different claims from different sources, and a reader who
mistakes one for the other gets a part in the wrong place with a lock that agrees
with them. So neither is called `bounding_box`, and nothing here combines the plate
polygon with a height into a box the engine never reported.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from slicelab.adapters.prusaslicer import _read_mesh_info, _read_placement
from slicelab.geometry import MeshFacts, Placement, mesh_sha256
from slicelab.vocab import GCODE_FOOTER, MESH_INFO

#: `--info`'s shape, written here rather than copied: what is under test is the
#: parse. The numbers are the ones measured on 2026-10-05 against a 20 mm cube.
INFO = """\
[cube.stl]
size_x = 20.000000
size_y = 20.000000
size_z = 20.000000
min_x = 0.000000
min_y = 0.000000
min_z = 0.000000
max_x = 20.000000
max_y = 20.000000
max_z = 20.000000
number_of_facets = 12
manifold = yes
number_of_parts =  1
volume = 8000.000488
"""

PLATED = (
    '; objects_info = {"objects":[{"name":"cube.stl id:0 copy 0",'
    '"polygon":[[135.000,115.000],[115.000,115.000],[115.000,95.000],[135.000,95.000]]}]}\n'
)


def test_the_mesh_box_is_read_in_model_coordinates() -> None:
    facts = _read_mesh_info(INFO)
    assert facts is not None
    assert facts.min_mm == (0.0, 0.0, 0.0)
    assert facts.max_mm == (20.0, 20.0, 20.0)
    assert facts.source == MESH_INFO
    assert facts.key == "--info"


def test_the_fingerprint_is_the_three_facts_that_identify_a_mesh() -> None:
    facts = _read_mesh_info(INFO)
    assert facts is not None
    assert facts.facets == 12
    assert facts.volume_mm3 == 8000.000488
    assert facts.manifold is True


def test_a_size_is_not_recorded_because_it_is_derivable() -> None:
    """`--info` states size_x as well as min_x and max_x. Recording a difference
    slicelab computed, beside the two numbers it came from, invites a reader to
    check one against the other and call the agreement evidence."""
    assert "size_mm" not in _read_mesh_info(INFO).as_table()  # type: ignore[union-attr]


@pytest.mark.parametrize("axis", ["min_x", "max_z", "min_y"])
def test_a_box_missing_one_bound_is_not_a_box(axis: str) -> None:
    """Five bounds and a gap is a shape nobody measured. Absent, not partial."""
    crippled = "\n".join(line for line in INFO.splitlines() if not line.startswith(f"{axis} ="))
    assert _read_mesh_info(crippled) is None


def test_a_mesh_described_with_no_fingerprint_is_still_a_described_mesh() -> None:
    bounds_only = "\n".join(
        line
        for line in INFO.splitlines()
        if line.startswith(("min_", "max_")) and not line.startswith("max_print")
    )
    facts = _read_mesh_info(bounds_only)
    assert facts is not None
    assert facts.facets is None
    assert facts.volume_mm3 is None
    assert facts.manifold is None
    assert "facets" not in facts.as_table()


@pytest.mark.parametrize(
    ("spelling", "expected"),
    [("yes", True), ("no", False), ("YES", True), ("maybe", None), ("", None)],
)
def test_manifold_is_unknown_rather_than_false_when_unrecognised(
    spelling: str, expected: bool | None
) -> None:
    """A mesh reported in a spelling slicelab does not know is not a mesh reported
    as open. `no` is a finding; anything else is silence."""
    text = INFO.replace("manifold = yes", f"manifold = {spelling}")
    assert _read_mesh_info(text).manifold is expected  # type: ignore[union-attr]


def test_an_unreadable_number_drops_that_field_and_keeps_the_box() -> None:
    text = INFO.replace("volume = 8000.000488", "volume = quite a lot")
    facts = _read_mesh_info(text)
    assert facts is not None
    assert facts.volume_mm3 is None
    assert facts.max_mm == (20.0, 20.0, 20.0)


def test_the_plate_footprint_is_the_engine_s_own_polygon() -> None:
    placement = _read_placement(PLATED)
    assert placement is not None
    assert placement.source == GCODE_FOOTER
    assert placement.key == "; objects_info"
    assert placement.objects == (
        ("cube.stl id:0 copy 0", ((135.0, 115.0), (115.0, 115.0), (115.0, 95.0), (135.0, 95.0))),
    )


def test_the_polygon_is_not_reduced_to_its_extent() -> None:
    """Four points stay four points. A bounding box computed from them would lose
    the one thing that tells a rotated part from an axis-aligned one."""
    table = _read_placement(PLATED).as_table()  # type: ignore[union-attr]
    assert len(table["objects"][0]["polygon"]) == 4  # type: ignore[index]


def test_an_artifact_that_states_no_placement_reads_as_none() -> None:
    assert _read_placement("; filament used [mm] = 1251.87\n") is None


def test_a_malformed_placement_is_none_rather_than_a_guess() -> None:
    assert _read_placement('; objects_info = {"objects":[\n') is None


def test_an_object_with_no_polygon_is_dropped_rather_than_placed_nowhere() -> None:
    """An empty footprint reads as "placed nowhere" instead of "the engine did not
    say", and the second is what happened."""
    document = {
        "objects": [{"name": "a.stl", "polygon": []}, {"name": "b.stl", "polygon": [[1, 2]]}]
    }
    placement = _read_placement(f"; objects_info = {json.dumps(document)}\n")
    assert placement is not None
    assert [name for name, _ in placement.objects] == ["b.stl"]


def test_the_mesh_hash_is_slicelabs_own_and_changes_with_the_bytes(tmp_path: Path) -> None:
    """The field that identifies the input when the engine describes nothing."""
    one = tmp_path / "one.stl"
    one.write_text("solid a\nendsolid a\n", encoding="utf-8")
    two = tmp_path / "two.stl"
    two.write_text("solid b\nendsolid b\n", encoding="utf-8")

    assert len(mesh_sha256(one)) == 64
    assert mesh_sha256(one) != mesh_sha256(two)
    assert mesh_sha256(one) == mesh_sha256(one)


def test_the_records_write_the_tables_the_lock_expects() -> None:
    facts = MeshFacts(
        source=MESH_INFO, key="--info", min_mm=(0.0, 0.0, 0.0), max_mm=(1.0, 2.0, 3.0), facets=4
    )
    assert facts.as_table() == {
        "source": MESH_INFO,
        "key": "--info",
        "min_mm": [0.0, 0.0, 0.0],
        "max_mm": [1.0, 2.0, 3.0],
        "facets": 4,
    }

    placement = Placement(
        source=GCODE_FOOTER, key="; objects_info", objects=(("a.stl", ((1.0, 2.0), (3.0, 4.0))),)
    )
    assert placement.as_table() == {
        "source": GCODE_FOOTER,
        "key": "; objects_info",
        "objects": [{"name": "a.stl", "polygon": [[1.0, 2.0], [3.0, 4.0]]}],
    }


def test_a_placement_whose_objects_are_all_unreadable_is_none() -> None:
    """`objects = []` would read as "placed nowhere", which is the reading the
    per-object dropping rule exists to avoid. None says the engine was not understood."""
    document = {"objects": [{"name": "a.stl", "polygon": []}, {"name": "b.stl", "polygon": []}]}
    assert _read_placement(f"; objects_info = {json.dumps(document)}\n") is None


def test_a_placement_with_three_dimensional_points_is_not_half_read() -> None:
    """What a build adding a plated Z would emit. Reading the first two numbers of each
    point would silently reinterpret the engine's output."""
    document = {"objects": [{"name": "a.stl", "polygon": [[1, 2, 3], [4, 5, 6]]}]}
    assert _read_placement(f"; objects_info = {json.dumps(document)}\n") is None
