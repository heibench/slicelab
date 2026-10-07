"""The reported-stat reader, against an artifact this engine just produced.

`tests/test_stats.py` drives the parse with footers written by hand, which is the
only way to reach a weightless-filament case without a profile that has one. Those
fixtures are a claim about the engine's output shape, and a hand-written fixture is
exactly the thing that keeps passing after the engine stops producing that shape.

So this slices for real and asserts the same two outcomes on the bytes the engine
wrote: a stock run reports a mass, and a run whose filament has no density does not.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from slicelab.adapters import EngineSpec
from slicelab.stats import DENSITY_ZERO
from slicelab.vocab import FILAMENT_G, FILAMENT_MM, LAYERS, PRINT_TIME_S, SLICER_MARKER_COUNT
from tests.conftest import skip_or_fail
from tests.test_slice_against_the_engine import TRIPLE, _cube


def _engine(usable_engines: list[EngineSpec]) -> EngineSpec:
    for spec in usable_engines:
        if spec.compose_slice is not None and spec.read_artifact_stats is not None:
            return spec
    skip_or_fail("no engine that has declared how to be sliced and read is installed")


@pytest.fixture(scope="module")
def engine(usable_engines: list[EngineSpec]) -> EngineSpec:
    return _engine(usable_engines)


def _slice(tmp_path: Path, overrides: str) -> Path:
    """Slice a cube through the console script and hand back the promoted artifact."""
    _cube(tmp_path / "part.stl")
    intent = tmp_path / "slice.toml"
    intent.write_text(
        '[geometry]\nmodel = "part.stl"\n\n[output]\ngcode = "part.gcode"\n\n'
        + TRIPLE
        + f"\n[prusaslicer.set]\n{overrides}\n",
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
    assert artifact.is_file()
    return artifact


def test_a_real_artifact_reports_the_numbers_the_fixtures_claim(engine, tmp_path: Path) -> None:
    """Every field the hand-written stock footer produces, produced by the engine.

    Values are asserted as kinds rather than quantities -- the cube is slicelab's
    own and the profile is the machine's, so pinning 1251.87 here would pin this
    host's preset rather than the reader.
    """
    stats = engine.read_artifact_stats(
        _slice(tmp_path, "perimeters = 2").read_text(encoding="utf-8", errors="replace")
    )

    assert stats[FILAMENT_MM].value > 0
    assert stats[FILAMENT_G].value > 0, "a stock profile has a density, so there is a mass"
    assert stats[PRINT_TIME_S].value > 0
    assert stats[LAYERS].value > 1
    assert stats[LAYERS].source == SLICER_MARKER_COUNT
    assert all(stat.measured for stat in stats.values())
    for stat in stats.values():
        assert stat.key, "a number with no key is not checkable against the artifact"


def test_a_real_weightless_filament_withholds_the_mass(engine, tmp_path: Path) -> None:
    """The founding case for the class, on real bytes.

    With `filament_density = 0` the engine drops its per-filament mass line and
    still prints `total filament used [g] = 0.00` beside an unchanged extrusion.
    Anything reading that zero learns the print weighs nothing.
    """
    stats = engine.read_artifact_stats(
        _slice(tmp_path, "filament-density = 0").read_text(encoding="utf-8", errors="replace")
    )

    assert stats[FILAMENT_MM].value > 0, "the extrusion is real"
    assert stats[FILAMENT_G].value is None, "the engine's 0.00 g reached the lock"
    assert stats[FILAMENT_G].reason == DENSITY_ZERO
