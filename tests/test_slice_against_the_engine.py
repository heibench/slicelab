"""`slicelab slice`, end to end, against a real engine.

The verb exists to refuse, and the two measurements that make the artifact gate
non-negotiable are both reproduced here rather than cited.

[V4] `--scale 30` puts the object outside the print volume: 2.9.6 exits **0**, writes
no G-code, and writes a complete configuration anyway, because `--save` runs before
the slice block and is not conditioned on it.

[V15] a post-processing script in the resolved configuration makes it print
`Continue(Y/N)?` to stdout and block on stdin, headless: exit **0**, nothing written
at all, zero bytes on stderr. Reached here through `[set]`, which composes the flag;
the evidence records that a `--load`ed file carrying `post_process` reproduces it
identically, because the engine is reacting to the resolved configuration either way.

Everything runs the console script, because org contract section 5 makes the exit
code the stable surface rather than the Python API.

**The model is generated, not committed.** D11: slicelab ships zero engine-derived
bytes, and a cube this test writes itself is slicelab's own -- it is also the only way
the geometry is knowable enough to assert anything about.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from slicelab.adapters import EngineSpec
from tests.conftest import skip_or_fail

TRIPLE = """[prusaslicer.base]
printer-profile = "Original Prusa i3 MK3S & MK3S+"
print-profile = "0.20mm QUALITY @MK3"
material-profile = "Prusament PLA"
"""


def _engine(usable_engines: list[EngineSpec]) -> EngineSpec:
    for spec in usable_engines:
        if spec.compose_slice is not None and spec.base_keys and spec.secret_keys:
            return spec
    skip_or_fail("no engine that has declared how to be asked for a slice is installed")


def _cube(path: Path) -> Path:
    """A 20 mm ASCII-STL cube, written here rather than committed (D11)."""
    corners = [
        (0, 0, 0),
        (20, 0, 0),
        (20, 20, 0),
        (0, 20, 0),
        (0, 0, 20),
        (20, 0, 20),
        (20, 20, 20),
        (0, 20, 20),
    ]
    faces = [
        (0, 3, 2),
        (0, 2, 1),
        (4, 5, 6),
        (4, 6, 7),
        (0, 1, 5),
        (0, 5, 4),
        (1, 2, 6),
        (1, 6, 5),
        (2, 3, 7),
        (2, 7, 6),
        (3, 0, 4),
        (3, 4, 7),
    ]
    out = ["solid cube"]
    for a, b, c in faces:
        out += ["facet normal 0 0 0", "  outer loop"]
        out += [f"    vertex {corners[i][0]} {corners[i][1]} {corners[i][2]}" for i in (a, b, c)]
        out += ["  endloop", "endfacet"]
    out.append("endsolid cube")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return path


def _intent(tmp_path: Path, overrides: str = "") -> Path:
    _cube(tmp_path / "part.stl")
    intent = tmp_path / "slice.toml"
    intent.write_text(
        '[geometry]\nmodel = "part.stl"\n\n[output]\ngcode = "part.gcode"\n\n'
        + TRIPLE
        + (f"\n[prusaslicer.set]\n{overrides}\n" if overrides else ""),
        encoding="utf-8",
    )
    return intent


def _slice(intent: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "slicelab", "slice", str(intent)],
        capture_output=True,
        text=True,
        timeout=1800,
    )


@pytest.fixture(scope="module")
def engine(usable_engines: list[EngineSpec]) -> EngineSpec:
    return _engine(usable_engines)


def _discard_what_was_withheld(report: str) -> None:
    """Remove the scratch a withholding run deliberately kept (D7).

    `tmp_path` does not cover it: the point of keeping it is that it outlives the
    run, so a test that provokes one has to clean up after itself or the suite
    litters the system temp directory once per case.
    """
    for line in report.splitlines():
        if "kept at" in line:
            shutil.rmtree(Path(line.split("kept at ")[1].strip()).parent, ignore_errors=True)


def test_a_stock_triple_slices_and_the_artifact_is_promoted(engine, tmp_path: Path) -> None:
    """The ordinary path, which is what makes the refusals below mean something."""
    intent = _intent(tmp_path, "perimeters = 4")
    done = _slice(intent)

    assert done.returncode == 0, f"{done.stdout}\n{done.stderr}"
    assert done.stdout.startswith("sliced"), done.stdout
    assert "perimeters: applied" in done.stdout, done.stdout

    artifact = tmp_path / "part.gcode"
    assert artifact.is_file(), sorted(p.name for p in tmp_path.iterdir())
    assert artifact.stat().st_size > 0
    assert (tmp_path / "slice.readback.ini").is_file()


def test_an_object_outside_the_print_volume_hands_over_nothing(engine, tmp_path: Path) -> None:
    """[V4]: exit 0, a complete configuration, and no G-code.

    The engine's own exit status says the run succeeded. The gate asks the FILE.
    """
    intent = _intent(tmp_path, "scale = 30")
    previous = tmp_path / "part.gcode"
    previous.write_text("PREVIOUS-ARTIFACT\n", encoding="utf-8")

    done = _slice(intent)

    assert done.returncode == 2, f"{done.stdout}\n{done.stderr}"
    assert done.stderr.startswith("incomplete"), done.stderr
    assert "wrote no artifact" in done.stderr, done.stderr
    # The engine's own words, carried rather than discarded (D28).
    assert "print volume" in done.stderr, done.stderr
    # D7: non-destructive. The destination is never deleted and never half-written.
    assert previous.read_text(encoding="utf-8") == "PREVIOUS-ARTIFACT\n", (
        "a run that reached no verdict overwrote the author's artifact"
    )


def test_a_post_processing_script_hands_over_nothing(engine, tmp_path: Path) -> None:
    """[V15]: exit 0, nothing written at all, zero bytes on stderr.

    The engine prints an interactive prompt to stdout and blocks on stdin, headless.
    slicelab's stdin is `DEVNULL`, so it gets EOF and gives up -- and reports exit 0
    having produced neither artifact nor configuration.
    """
    intent = _intent(tmp_path, 'post-process = "/bin/true"')
    previous = tmp_path / "part.gcode"
    previous.write_text("PREVIOUS-ARTIFACT\n", encoding="utf-8")

    done = _slice(intent)

    assert done.returncode == 2, f"{done.stdout}\n{done.stderr}"
    assert done.stderr.startswith("incomplete"), done.stderr
    # Captured from STDOUT, which is where it said it, and where a reader would not
    # think to look. The artifact carries none of this.
    assert "Continue" in done.stderr, done.stderr
    assert previous.read_text(encoding="utf-8") == "PREVIOUS-ARTIFACT\n"


def test_the_container_is_sniffed_from_the_artifact_not_from_the_flag(
    engine, tmp_path: Path
) -> None:
    """D10, and the reason it is not cosmetic.

    `binary_gcode = 1` is the stock default for the entire current Prusa line [V7], so
    this is the ordinary path rather than an edge case -- it is forced here only
    because this host's MK3S triple defaults the other way. A `GCDE` container has no
    text footer to read, which is what the lock has to know before it tries.
    """
    intent = _intent(tmp_path, "binary-gcode = 1")
    done = _slice(intent)

    assert done.returncode == 0, f"{done.stdout}\n{done.stderr}"
    assert "container = bgcode" in done.stdout, done.stdout
    assert (tmp_path / "part.gcode").read_bytes()[:4] == b"GCDE"


def test_what_the_promotion_displaced_is_reported(engine, tmp_path: Path) -> None:
    """D7's `destination_prehash`: "this file is here" is not "this run wrote it".

    The alternative -- an mtime check -- was measured and rejected: 198 of 200 tmpfs
    writes had identical `st_mtime_ns`.
    """
    intent = _intent(tmp_path, "perimeters = 4")
    (tmp_path / "part.gcode").write_text("DISPLACED\n", encoding="utf-8")

    done = _slice(intent)

    assert done.returncode == 0, f"{done.stdout}\n{done.stderr}"
    # sha256 of b"DISPLACED\n", first 16 characters as the report prints them.
    import hashlib

    expected = hashlib.sha256(b"DISPLACED\n").hexdigest()[:16]
    assert expected in done.stdout, f"the displaced file is not named: {done.stdout}"
    assert (tmp_path / "part.gcode").read_bytes()[:4] != b"DISPL"


def test_a_coerced_key_produces_an_artifact_that_is_not_handed_over(engine, tmp_path: Path) -> None:
    """D7's central rule, and the one the gate tests above cannot reach.

    Both gate tests refuse before the promotion is considered, so neither notices if
    the promotion stops being conditional -- measured: replacing
    `if adjudication.outcome is Outcome.SLICED` with `if True` left all of them green.
    This is the case that pins it, and it is the project's founding example [V1].

    The engine takes `perimeters = 4.7`, silently resolves it to `4`, exits 0, and
    writes a complete and perfectly printable G-code file. Nothing is broken. The
    artifact is real and the run is still one slicelab will not stand behind, so the
    author keeps whatever they had.
    """
    intent = _intent(tmp_path, "perimeters = 4.7")
    previous = tmp_path / "part.gcode"
    previous.write_text("PREVIOUS-ARTIFACT\n", encoding="utf-8")

    done = _slice(intent)

    assert done.returncode == 2, f"{done.stdout}\n{done.stderr}"
    assert "perimeters: coerced" in done.stderr, done.stderr
    assert "requested '4.7'" in done.stderr and "came back '4'" in done.stderr, done.stderr
    # The artifact existed. The engine wrote one, and the container was sniffed from
    # it -- so this is not "nothing happened", it is "something happened and slicelab
    # will not pass it on".
    assert "container = gcode" in done.stderr, done.stderr
    assert "no artifact was handed over" in done.stderr, done.stderr
    assert previous.read_text(encoding="utf-8") == "PREVIOUS-ARTIFACT\n", (
        "an artifact from a run slicelab could not stand behind reached the author (D7)"
    )
    # The readback IS promoted, because it is the evidence for the verdict (D31).
    assert (tmp_path / "slice.readback.ini").is_file()
    _discard_what_was_withheld(done.stderr)


def test_an_intent_with_no_overrides_is_empty_and_still_hands_over_the_artifact(
    engine, tmp_path: Path
) -> None:
    """D24's carve-out from D7, which is the default path rather than a corner.

    An intent with a preset triple and no `[set]` asserts nothing, so there is
    nothing to verify and the outcome is `empty` at exit 3 -- but a valid G-code file
    was produced and nothing was found wrong with it. Withholding it would punish an
    author for not having written an override yet, and it is the first file anybody
    writes. `sliced` and `empty` are the two outcomes whose artifact is handed over;
    every other one keeps it.
    """
    intent = _intent(tmp_path)

    done = _slice(intent)

    assert done.returncode == 3, f"{done.stdout}\n{done.stderr}"
    assert done.stderr.startswith("empty"), done.stderr
    artifact = tmp_path / "part.gcode"
    assert artifact.is_file(), sorted(p.name for p in tmp_path.iterdir())
    assert artifact.read_bytes().startswith(b"; generated by"), "not the engine's G-code"


def test_a_withheld_artifact_is_kept_and_named(engine, tmp_path: Path) -> None:
    """D7: the artifact a run produced and slicelab would not hand over is named in
    the report, and the path names a file that is still there.

    Otherwise `incomplete` is undiagnosable: the author is told the engine resolved
    their intent to something else, and has nothing to look at. The scratch survives
    only in this case -- a run that produced no artifact leaves nothing worth
    keeping, and keeping it unannounced would be litter nobody was told about.
    """
    intent = _intent(tmp_path, "perimeters = 4.7")

    done = _slice(intent)

    assert done.returncode == 2, f"{done.stdout}\n{done.stderr}"
    kept = [line for line in done.stderr.splitlines() if "kept at" in line]
    assert kept, done.stderr
    staged = Path(kept[0].split("kept at ")[1].strip())
    try:
        assert staged.is_file(), f"the report names {staged}, which is not there"
        assert staged.stat().st_size > 0
    finally:
        _discard_what_was_withheld(done.stderr)


def test_a_run_that_hands_over_leaves_no_scratch_behind(engine, tmp_path: Path) -> None:
    """The control for the one above, and D20: a run that succeeds cleans up after
    itself. A gate that keeps every scratch directory would pass that test too."""
    before = set(Path(tempfile.gettempdir()).glob("slicelab-slice-*"))

    done = _slice(_intent(tmp_path, "perimeters = 4"))

    assert done.returncode == 0, f"{done.stdout}\n{done.stderr}"
    assert not set(Path(tempfile.gettempdir()).glob("slicelab-slice-*")) - before
