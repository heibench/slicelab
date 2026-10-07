"""A lock this engine's output actually produced, read back with `tomllib`.

`tests/test_lock.py` proves the emitter writes TOML. This proves the document is the
one #7 asks for, assembled from a real slice: every field sourced, the credential keys
redacted before they reach a file the README's git model says you commit, and the
binary-container case recording what it could not establish rather than omitting it.
"""

from __future__ import annotations

import hashlib
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
    # `stats.*` rather than `stats`: the field paths name what is missing, and `stats`
    # itself is present as an empty table. Two of the doc's three absence cases would
    # otherwise be identical on the wire.
    assert "artifact.normalized" in entry["fields"]
    assert "stats.*" in entry["fields"]

    # The container was the engine's choice, not slicelab's: the artifact is the one
    # the author asked for, bytes and all.
    assert (tmp_path / "part.gcode").read_bytes()[:4] == b"GCDE"


def test_the_engine_s_own_output_is_kept_because_the_artifact_does_not_carry_it(
    engine, tmp_path: Path
) -> None:
    """#7: "engine warnings live on stdout and not in the G-code, so they must be
    captured at slice time or they are gone".

    Measured 2026-10-05: `perimeters = 0` with `fill-density = 0` exits 0, writes a
    real artifact, and says `print warning: Empty layer between 0.8 and 19.` on stdout.
    The engine honoured the intent exactly as authored, so the outcome stays `sliced` --
    slicelab's question is whether the request was honoured, not whether the result is
    a good idea. What it owes the author is not losing what the engine said.
    """
    # `fill-density = "0%"`, not `0`: the engine resolves a bare `0` to `0%` and the
    # run is then `incomplete` with no lock to carry anything (measured -- another
    # instance of the coercion family [V1] is named for). Asking in the engine's own
    # spelling is applied cleanly, which is what D28 is about.
    lock = _slice(tmp_path, overrides='perimeters = 0\nfill-density = "0%"')
    document = _read(lock)

    assert document["artifact"]["raw_sha256"], "this run did produce an artifact"
    streams = document["engine_output"]
    warned = [line for line in streams["stdout"] if "warning" in line.lower()]
    assert warned, f"the engine's warning was not captured: {streams}"
    assert "Empty layer" in " ".join(streams["stdout"])

    # The artifact itself says nothing about it, which is why the lock has to.
    artifact = (tmp_path / "part.gcode").read_text(encoding="utf-8", errors="replace")
    assert "Empty layer" not in artifact
    assert "print warning" not in artifact


def test_a_clean_run_records_both_streams_including_an_empty_one(engine, tmp_path: Path) -> None:
    """An empty stderr is a real answer and not a missing field: a reader that cannot
    tell "the engine said nothing" from "slicelab did not look" has to guess."""
    streams = _read(_slice(tmp_path))["engine_output"]
    assert streams["stdout"], "a slice prints progress at least"
    assert streams["stderr"] == []
    assert not any("warning" in line.lower() for line in streams["stdout"])


def test_the_lock_names_what_the_promotion_displaced(engine, tmp_path: Path) -> None:
    """D7's `destination_prehash`, in the lock rather than only in the report.

    "This file is here" does not establish "this run wrote it", and the lock is the
    record that has to survive the terminal scrolling. An mtime check was measured and
    rejected for this: 198 of 200 tmpfs writes had identical `st_mtime_ns`.
    """
    _cube(tmp_path / "part.stl")
    previous = tmp_path / "part.gcode"
    previous.write_bytes(b"PREVIOUS-ARTIFACT\n")
    expected = hashlib.sha256(previous.read_bytes()).hexdigest()

    document = _read(_slice(tmp_path))

    assert document["artifact"]["destination_prehash"] == expected
    assert document["artifact"]["raw_sha256"] != expected, "the new artifact replaced it"


def test_a_lock_for_a_fresh_destination_records_no_prehash(engine, tmp_path: Path) -> None:
    """The control. Absent means nothing was there, which is a different claim from
    "something was there and slicelab did not look"."""
    assert "destination_prehash" not in _read(_slice(tmp_path))["artifact"]


def test_a_re_slice_that_writes_no_lock_removes_the_one_that_described_the_old_artifact(
    engine, tmp_path: Path
) -> None:
    """The stale-lock hazard D31 closed for the readback, closed for the lock.

    Measured before the fix: run one with an override is `sliced` and locks artifact A;
    run two with the override removed is `empty`, promotes artifact B, writes no lock
    (D24) -- and the lock still claimed A, sitting beside the file it did not describe.
    Re-running one `slice.toml` in one directory is the ordinary workflow, which is
    exactly what D31 says armed it.
    """
    lock = _slice(tmp_path)
    first = hashlib.sha256((tmp_path / "part.gcode").read_bytes()).hexdigest()
    assert _read(lock)["artifact"]["raw_sha256"] == first

    # The same intent with nothing asserted: `empty`, exit 3, artifact promoted.
    intent = tmp_path / "slice.toml"
    intent.write_text(
        intent.read_text(encoding="utf-8").split("[prusaslicer.set]")[0], encoding="utf-8"
    )
    done = subprocess.run(
        [sys.executable, "-m", "slicelab", "slice", str(intent)],
        capture_output=True,
        text=True,
        timeout=1800,
    )
    assert done.returncode == 3, f"{done.stdout}\n{done.stderr}"

    second = hashlib.sha256((tmp_path / "part.gcode").read_bytes()).hexdigest()
    assert second != first, "the artifact was replaced, which is what makes the lock stale"
    assert not lock.exists(), (
        "a lock describing the artifact this run replaced survived beside the new one"
    )
    assert "removed" in done.stderr, done.stderr


def test_the_lock_records_which_keys_were_actually_adjudicated(engine, tmp_path: Path) -> None:
    """G1: the mechanism adjudicates the authored delta and only records the base, and
    the design must say so. Without this a lock from a one-key intent and one from a
    forty-key intent are indistinguishable while `effective_config` carries 393 keys."""
    document = _read(_slice(tmp_path, overrides="perimeters = 3\nlayer-height = 0.15"))

    verdicts = document["verdicts"]
    assert {entry["option"] for entry in verdicts} == {"perimeters", "layer-height"}
    for entry in verdicts:
        assert entry["status"] == "applied"
        assert entry["requested"]
        assert entry["compared"], "G2: a reader must be able to check the comparison"
        assert entry["observed"]
    assert len(document["effective_config"]) > 300, "the base is recorded, not adjudicated"


def test_the_plated_height_is_its_own_field(engine, tmp_path: Path) -> None:
    """Claimed in four places before it existed. The engine reports the footprint as a
    2D polygon and the height separately, so they stay separate."""
    geometry = _read(_slice(tmp_path))["geometry"]

    height = geometry["plated_height_mm"]
    assert height["key"] == "; max_layer_z"
    assert height["value"] > 0
    assert "polygon" not in height, "the footprint and the height are not one box"


def test_a_file_slicelab_did_not_write_is_not_removed(engine, tmp_path: Path) -> None:
    """The lock's path is DERIVED from the intent's name, not chosen by the author, so a
    file of their own can be sitting at it. Measured before the guard: deleted."""
    lock = _slice(tmp_path)
    assert lock.is_file()
    mine = "# my own notes about this part, nothing to do with slicelab\n"
    lock.write_text(mine, encoding="utf-8")

    intent = tmp_path / "slice.toml"
    intent.write_text(
        intent.read_text(encoding="utf-8").split("[prusaslicer.set]")[0], encoding="utf-8"
    )
    done = subprocess.run(
        [sys.executable, "-m", "slicelab", "slice", str(intent)],
        capture_output=True,
        text=True,
        timeout=1800,
    )

    assert done.returncode == 3, f"{done.stdout}\n{done.stderr}"
    assert lock.read_text(encoding="utf-8") == mine, "a file slicelab never wrote was removed"
    assert "removed" not in done.stderr


def test_a_lock_describing_a_different_artifact_is_not_removed(engine, tmp_path: Path) -> None:
    """A lock for `v1.gcode` still describes a file that may be sitting there intact.

    Measured before the guard: a second run writing `v2.gcode` deleted it, reporting that
    it "described the artifact this run replaced" -- which replaced nothing.
    """
    _cube(tmp_path / "part.stl")
    first = tmp_path / "slice.toml"
    first.write_text(
        '[geometry]\nmodel = "part.stl"\n\n[output]\ngcode = "v1.gcode"\n\n'
        + TRIPLE
        + "\n[prusaslicer.set]\nperimeters = 3\n",
        encoding="utf-8",
    )
    assert (
        subprocess.run(
            [sys.executable, "-m", "slicelab", "slice", str(first)],
            capture_output=True,
            text=True,
            timeout=1800,
        ).returncode
        == 0
    )
    lock = tmp_path / "slice.lock"
    recorded = lock.read_bytes()
    assert "v1.gcode" in _read(lock)["artifact"]["path"]

    # Same intent file, a different output, nothing asserted: `empty`.
    first.write_text(
        '[geometry]\nmodel = "part.stl"\n\n[output]\ngcode = "v2.gcode"\n\n' + TRIPLE,
        encoding="utf-8",
    )
    done = subprocess.run(
        [sys.executable, "-m", "slicelab", "slice", str(first)],
        capture_output=True,
        text=True,
        timeout=1800,
    )

    assert done.returncode == 3, f"{done.stdout}\n{done.stderr}"
    assert (tmp_path / "v1.gcode").is_file(), "the artifact it describes is still there"
    assert lock.read_bytes() == recorded, "a lock describing an untouched artifact was removed"
