"""The lock's TOML, and the two ways writing it by hand goes wrong quietly.

The first is escaping. The values are an engine's configuration, so they carry double
quotes and literal backslash-n pairs, and a writer that gets them wrong either
produces a file that will not parse -- loud, fine -- or one that parses into
something other than what was measured, which is a lock that lies.

The second is ordering. TOML binds a bare key to the most recently opened table, so a
scalar emitted after a sub-table silently joins it. The file still parses. Every test
here that writes a scalar after a table is about that.

Everything is asserted by parsing the output with `tomllib`, never by comparing
strings: what matters is what a reader gets back, and `tomllib` is what D13 says the
intent parser is, so it is the reader this has to satisfy.
"""

from __future__ import annotations

import tomllib
from typing import Any

import pytest

from slicelab.lock import SCHEMA_VERSION, dumps


def _round_trip(document: dict[str, object]) -> dict[str, Any]:
    """Write the document and read it back with the parser D13 names.

    `Any`, deliberately: `tomllib` returns `Any` and these tests index into nested
    tables. Annotating it `object` bought a `type: ignore` on nearly every assertion,
    and an ignore that stops matching the real error is how a type gap hides.
    """
    return tomllib.loads(dumps(document) + "\n")


def test_the_version_is_the_first_key_in_the_file() -> None:
    """A reader checks it before trusting the rest, so it must not be inside a table."""
    text = dumps({"schema_version": SCHEMA_VERSION, "artifact": {"container": "gcode"}})
    assert text.splitlines()[0] == "schema_version = 1"


def test_a_scalar_declared_after_a_table_stays_at_the_top_level() -> None:
    """The ordering bug, in its smallest form. Written naively this parses with
    `values_resolved` nested inside `[stats]`, and nothing complains."""
    parsed = _round_trip(
        {
            "stats": {"filament_mm": 1251.87},
            "values_resolved": False,
            "schema_version": 1,
        }
    )
    assert parsed["values_resolved"] is False
    assert "values_resolved" not in parsed["stats"]


def test_a_scalar_after_a_sub_table_stays_in_its_own_table() -> None:
    """The same hazard one level down: `source` belongs to `mesh_bbox`, not to the
    sub-table that precedes it."""
    parsed = _round_trip(
        {"geometry": {"inner": {"a": 1}, "source": "mesh_info"}},
    )
    assert parsed["geometry"]["source"] == "mesh_info"
    assert "source" not in parsed["geometry"]["inner"]


@pytest.mark.parametrize(
    "value",
    [
        'M862.3 P "[printer_model]"',
        "G90\\nG21\\nM83",
        'a "quoted" and a \\ backslash',
        "tab\there",
        "newline\nhere",
        "carriage\rreturn",
        "bell\x07and\x00null",
        "del\x7fchar",
        "unicode: é中\U0001f600",
        "",
    ],
)
def test_a_value_survives_the_round_trip_whatever_is_in_it(value: str) -> None:
    assert _round_trip({"effective_config": {"k": value}})["effective_config"]["k"] == value


def test_a_key_that_is_not_bare_is_quoted_and_still_round_trips() -> None:
    parsed = _round_trip({"effective_config": {"filament used [mm]": "1251.87", "a.b": "x"}})
    assert parsed["effective_config"]["filament used [mm]"] == "1251.87"
    assert parsed["effective_config"]["a.b"] == "x"


def test_a_boolean_is_not_written_as_a_number() -> None:
    """`isinstance(True, int)` is true in Python, so a writer that checks int first
    emits `1` and the reader gets an integer where the schema says boolean."""
    parsed = _round_trip({"values_resolved": False, "manifold": True})
    assert parsed["values_resolved"] is False
    assert parsed["manifold"] is True


def test_numbers_keep_their_type_and_precision() -> None:
    parsed = _round_trip({"stats": {"layers": 100, "volume_mm3": 8000.000488}})
    assert parsed["stats"]["layers"] == 100
    assert isinstance(parsed["stats"]["layers"], int)
    assert parsed["stats"]["volume_mm3"] == 8000.000488


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_a_number_that_is_not_a_measurement_is_refused(value: float) -> None:
    """TOML can spell these. A lock has no use for them: each one means the code that
    produced it did arithmetic on something absent."""
    with pytest.raises(ValueError, match="not a measurement"):
        dumps({"stats": {"x": value}})


def test_an_object_a_lock_does_not_record_is_refused_loudly() -> None:
    with pytest.raises(TypeError, match="not something a lock records"):
        dumps({"when": object()})


def test_nested_arrays_survive_as_nested_arrays() -> None:
    """The plate polygon's shape: a list of points, each a list of two numbers."""
    polygon = [[135.0, 115.0], [115.0, 115.0], [115.0, 95.0], [135.0, 95.0]]
    parsed = _round_trip({"geometry": {"polygon": polygon}})
    assert parsed["geometry"]["polygon"] == polygon


def test_an_array_of_tables_round_trips_in_order() -> None:
    unknowns = [
        {"code": "container_carries_no_text_footer", "fields": ["normalized_sha256"]},
        {"code": "filament_density_zero", "fields": ["stats.filament_g"]},
    ]
    parsed = _round_trip({"unknowns": unknowns})
    assert parsed["unknowns"] == unknowns


def test_an_empty_unknowns_list_is_an_empty_list_not_a_missing_key() -> None:
    """A run with nothing unestablished still says so: a reader that cannot tell an
    empty list from an absent key has to guess whether anything was checked."""
    parsed = _round_trip({"unknowns": []})
    assert parsed["unknowns"] == []


def test_an_empty_table_is_still_a_table() -> None:
    assert _round_trip({"stats": {}})["stats"] == {}


def test_a_document_of_every_shape_the_lock_uses_round_trips() -> None:
    """One document carrying each construct at once, because the constructs interact:
    the ordering rule only bites when a scalar follows a table."""
    document: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "values_resolved": False,
        "reproducibility": {"scope": "cross_machine", "state": "not_established"},
        "artifact": {
            "container": "gcode",
            "raw_sha256": "a" * 64,
            "normalized": {"substitutions": 1, "sha256": "b" * 64},
        },
        "geometry": {
            "mesh_sha256": "c" * 64,
            "mesh_bbox": {"source": "mesh_info", "min_mm": [0.0, 0.0, 0.0], "manifold": True},
            "plated_footprint": {
                "source": "gcode_footer",
                "objects": [{"name": 'cube "0"', "polygon": [[1.0, 2.0]]}],
            },
        },
        "stats": {"filament_g": {"source": "gcode_footer", "reason": "filament_density_zero"}},
        "unknowns": [{"code": "filament_density_zero", "fields": ["stats.filament_g"]}],
        "effective_config": {"start_gcode": 'M862.3 P "[printer_model]"\\nG90'},
    }

    parsed = _round_trip(document)
    assert parsed == document, "the lock did not read back as what was written"
