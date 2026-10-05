"""Two slices of one input, hashed both ways.

This is the measurement D9 rests on, made rather than cited: the raw hashes of two
identical runs must differ, the normalized hashes must agree, and the substitution
count must be 1. If normalization were too narrow the second would fail; if it were
too broad the hash would stop identifying the artifact, which is why
`tests/test_digest.py` pins a changed toolpath against it.

**One host, one build, one architecture.** That two runs agree here says nothing
about a second machine, which is why D8 has `slice` record `not_established` rather
than `reproducible`.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from slicelab.adapters import EngineSpec
from slicelab.digest import normalized_sha256, raw_sha256
from tests.conftest import skip_or_fail
from tests.test_slice_against_the_engine import TRIPLE, _cube


def _engine(usable_engines: list[EngineSpec]) -> EngineSpec:
    for spec in usable_engines:
        if spec.compose_slice is not None and spec.normalize_artifact is not None:
            return spec
    skip_or_fail("no engine that has declared how to be sliced and normalized is installed")


@pytest.fixture(scope="module")
def engine(usable_engines: list[EngineSpec]) -> EngineSpec:
    return _engine(usable_engines)


def _slice_into(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    _cube(directory / "part.stl")
    intent = directory / "slice.toml"
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
    return directory / "part.gcode"


def test_two_runs_differ_raw_and_agree_normalized(engine, tmp_path: Path) -> None:
    first = _slice_into(tmp_path / "first")
    second = _slice_into(tmp_path / "second")

    assert raw_sha256(first) != raw_sha256(second), (
        "the two runs produced byte-identical files, so this proves nothing about "
        "normalization -- the engine stopped stamping a timestamp"
    )

    one = normalized_sha256(
        first.read_text(encoding="utf-8", errors="replace"), engine.normalize_artifact
    )
    two = normalized_sha256(
        second.read_text(encoding="utf-8", errors="replace"), engine.normalize_artifact
    )

    assert one.substitutions == 1, f"the header was not found: {one.as_table()}"
    assert one.sha256 is not None
    assert one.sha256 == two.sha256, "normalization did not remove the run-to-run variation"


def test_the_artifact_this_engine_writes_is_still_the_format_the_rule_assumes(
    engine, tmp_path: Path
) -> None:
    """A guard on the fixtures in `tests/test_digest.py`.

    Those are hand-written headers. If this build stops emitting that shape they keep
    passing while the normalizer silently stops matching anything real, so the live
    artifact is checked for a substitution of exactly one.
    """
    artifact = _slice_into(tmp_path / "only")
    text = artifact.read_text(encoding="utf-8", errors="replace")

    rewritten, count = engine.normalize_artifact(text)
    assert count == 1, f"expected one timestamp line, replaced {count}"
    assert rewritten != text
    assert "<date>" in rewritten and "<time>" in rewritten
