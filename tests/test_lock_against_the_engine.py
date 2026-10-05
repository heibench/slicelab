"""A lock this engine's output actually produced, read back with `tomllib`.

`tests/test_lock.py` proves the emitter writes TOML. This proves the document is the
one #7 asks for, assembled from a real slice: every field sourced, the credential keys
redacted before they reach a file the README's git model says you commit, and the
binary-container case recording what it could not establish rather than omitting it.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest

from slicelab.adapters import EngineSpec
from slicelab.digest import CONTAINER_IS_BINARY
from slicelab.lock import SCHEMA_VERSION
from slicelab.vocab import FILAMENT_G, FILAMENT_MM, LAYERS, REPORTED_STATS
from tests.conftest import skip_or_fail
from tests.test_slice_against_the_engine import TRIPLE, _cube

#: An MK4IS triple, which emits a `GCDE` container (D10, [V7]). The profile names are
#: read from the engine rather than written here: the first attempt guessed
#: `0.20mm QUALITY @MK4IS 0.4 nozzle` and the engine had no such profile, which looks
#: like a broken test rather than a wrong name.
BINARY_PRINTER = "Original Prusa MK4 Input Shaper 0.4 nozzle"


def _engine(usable_engines: list[EngineSpec]) -> EngineSpec:
    for spec in usable_engines:
        if spec.compose_slice is not None and spec.read_artifact_stats is not None:
            return spec
    skip_or_fail("no engine that has declared how to be sliced and read is installed")


@pytest.fixture(scope="module")
def engine(usable_engines: list[EngineSpec]) -> EngineSpec:
    return _engine(usable_engines)


def _slice(tmp_path: Path, base: str = TRIPLE, overrides: str = "perimeters = 3") -> Path:
    _cube(tmp_path / "part.stl")
    intent = tmp_path / "slice.toml"
    intent.write_text(
        '[geometry]\nmodel = "part.stl"\n\n[output]\ngcode = "part.gcode"\n\n'
        + base
        + (f"\n[prusaslicer.set]\n{overrides}\n" if overrides else ""),
        encoding="utf-8",
    )
    done = subprocess.run(
        [sys.executable, "-m", "slicelab", "slice", str(intent)],
        capture_output=True,
        text=True,
        timeout=1800,
    )
    assert done.returncode == 0, f"{done.stdout}\n{done.stderr}"
    return tmp_path / "slice.lock"


def _read(lock: Path) -> dict[str, Any]:
    assert lock.is_file(), "no lock was written"
    return tomllib.loads(lock.read_text(encoding="utf-8"))


def test_a_generated_lock_round_trips_under_tomllib(engine, tmp_path: Path) -> None:
    """#7's done-condition, on a lock a real slice produced rather than a fixture."""
    document = _read(_slice(tmp_path))

    assert document["schema_version"] == SCHEMA_VERSION
    assert document["values_resolved"] is False, "D6: the engine exports a document"
    assert document["reproducibility"] == {
        "scope": "cross_machine",
        "state": "not_established",
        "reason": "one host, one build, one architecture; only a second machine can establish this",
    }
    assert len(document["effective_config"]) > 300, "the configuration document is embedded"


def test_every_reported_stat_carries_its_provenance(engine, tmp_path: Path) -> None:
    """#7: \"every reported stat carries its provenance\"."""
    stats = _read(_slice(tmp_path))["stats"]

    assert set(stats) <= REPORTED_STATS, "a field outside the closed set reached the lock"
    assert {FILAMENT_MM, FILAMENT_G, LAYERS} <= set(stats)
    for field, table in stats.items():
        assert table["source"], f"{field} has no source"
        assert table["key"], f"{field} does not name the engine's own key"
        assert ("value" in table) != ("reason" in table), f"{field}: {table}"


def test_the_layer_count_says_it_was_counted(engine, tmp_path: Path) -> None:
    """PrusaSlicer states no layer count, so the lock must not imply it did."""
    layers = _read(_slice(tmp_path))["stats"][LAYERS]
    assert layers["source"] == "slicer_marker_count"
    assert layers["key"] == ";LAYER_CHANGE"
    assert layers["value"] > 1


def test_a_zero_density_mass_reaches_the_lock_as_a_reason(engine, tmp_path: Path) -> None:
    """#7: \"`filament_g` is null when density is 0\". TOML has no null, so the field
    is present, carries no value, and says why -- and the gap is in `unknowns` too."""
    document = _read(_slice(tmp_path, overrides="filament-density = 0"))

    mass = document["stats"][FILAMENT_G]
    assert "value" not in mass, "the engine's 0.00 g reached the lock as a measurement"
    assert mass["reason"] == "filament_density_zero"
    assert document["stats"][FILAMENT_MM]["value"] > 0, "the extrusion is real"
    assert any(entry["code"] == "filament_density_zero" for entry in document["unknowns"])


def test_the_lock_carries_no_credential_value(engine, tmp_path: Path) -> None:
    """The lock embeds the configuration document, so it embeds whatever redaction
    left behind. The README's git model says you commit this file."""
    document = _read(_slice(tmp_path))

    redacted = document["readback"]["redacted_keys"]
    assert redacted, "this build emitted no credential-bearing key, so this proves nothing"
    for key in redacted:
        assert document["effective_config"][key] == "<redacted>", (
            f"{key} reached the lock unredacted"
        )


def test_both_hashes_are_present_and_different(engine, tmp_path: Path) -> None:
    artifact = _read(_slice(tmp_path))["artifact"]
    assert len(artifact["raw_sha256"]) == 64
    assert artifact["normalized"]["substitutions"] == 1
    assert artifact["normalized"]["sha256"] != artifact["raw_sha256"], (
        "the normalized hash is the raw hash, so nothing was normalized"
    )


def test_the_geometry_records_both_coordinate_systems(engine, tmp_path: Path) -> None:
    geometry = _read(_slice(tmp_path))["geometry"]

    assert geometry["mesh_bbox"]["max_mm"] == [20.0, 20.0, 20.0], "model coordinates"
    assert geometry["mesh_bbox"]["facets"] == 12
    assert len(geometry["mesh_sha256"]) == 64

    polygon = geometry["plated_footprint"]["objects"][0]["polygon"]
    assert len(polygon) == 4
    assert min(x for x, _ in polygon) > 0, "plate coordinates, not model coordinates"
    assert "bounding_box" not in geometry, "the two boxes are never one field"


def _binary_triple() -> str | None:
    """The MK4IS triple, with its print and filament profiles read from the engine."""
    done = subprocess.run(
        [
            "flatpak",
            "run",
            "--command=prusa-slicer",
            "com.prusa3d.PrusaSlicer",
            "--query-print-filament-profiles",
            "--printer-profile",
            BINARY_PRINTER,
        ],
        capture_output=True,
        text=True,
        timeout=600,
    )
    # Adjudicated on whether the JSON parses, never on the exit code (D17). Measured
    # here: this query returns **rc=1** while printing a complete profile listing,
    # which is [V5]'s shape -- the same status it returns for "printer profile not
    # found". A first version of this helper checked the status and skipped the test,
    # so #7's binary-container condition silently went unverified.
    if "{" not in done.stdout:
        return None
    try:
        parsed = json.loads(done.stdout[done.stdout.index("{") :])
    except json.JSONDecodeError:
        return None
    for entry in parsed.get("print_profiles", []):
        filaments = entry.get("filament_profiles") or []
        material = next((f for f in filaments if "PLA" in f), None)
        if entry["name"].startswith("0.20mm") and material is not None:
            return (
                "[prusaslicer.base]\n"
                f'printer-profile = "{BINARY_PRINTER}"\n'
                f'print-profile = "{entry["name"]}"\n'
                f'material-profile = "{material}"\n'
            )
    return None


def test_a_binary_container_records_what_it_cannot_establish(engine, tmp_path: Path) -> None:
    """#7: an MK4IS slice records `container = "bgcode"`, no normalized hash, and the
    container's own `unknowns` code -- never a silent `--binary-gcode=0` (D10).

    Measured 2026-10-05: the artifact is 30348 bytes beginning `GCDE`, with zero
    `prusaslicer_config` and zero `;LAYER_CHANGE`, and it does not decode as UTF-8.
    """
    triple = _binary_triple()
    if triple is None:
        skip_or_fail(f"this build offers no 0.20mm profile for {BINARY_PRINTER}")

    # An override is needed for this to be `sliced` at all: with none, the run is
    # `empty` and D24 gives it no lock. It is adjudicated against the engine's `--save`
    # ini, which is text whatever the artifact's container is -- so a binary artifact
    # still gets a verdict, and only the artifact-derived fields go missing.
    document = _read(_slice(tmp_path, base=triple, overrides="perimeters = 3"))

    assert document["artifact"]["container"] == "bgcode"
    assert "normalized" not in document["artifact"], "there is no text footer to normalize"
    assert document["stats"] == {}, "no stat can come from a container with no text"

    codes = [entry["code"] for entry in document["unknowns"]]
    assert CONTAINER_IS_BINARY in codes, codes
    entry = next(e for e in document["unknowns"] if e["code"] == CONTAINER_IS_BINARY)
    assert "artifact.normalized" in entry["fields"]
    assert "stats" in entry["fields"]

    # The container was the engine's choice, not slicelab's: the artifact is the one
    # the author asked for, bytes and all.
    assert (tmp_path / "part.gcode").read_bytes()[:4] == b"GCDE"
