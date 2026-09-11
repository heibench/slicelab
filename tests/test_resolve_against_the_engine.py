"""`slicelab resolve`, end to end, as a real process against a real engine.

Everything below runs the console script, so what is asserted is the **exit code a
consumer branches on** — org contract §5 makes that the stable surface, not the
Python API. A test that called `resolve()` directly would not establish that the
verb returns what the table says.

The option map is seeded into an isolated `XDG_CACHE_HOME` by probing the two
options under test. A full characterisation is ~1100 s; two options is seconds, and
seeding a measured map is still a measurement. Every other option is then absent
from the map, which `readback` reports as `unvalidated` rather than `absent` — so
the tests only author the two that were probed.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from slicelab.adapters import EngineSpec
from slicelab.engine.characterise import SCHEMA, _baseline, _probe_one, cache_path_for
from slicelab.engine.discover import discover
from slicelab.engine.identity import identify

PRESETS = {
    "printer-profile": "Original Prusa i3 MK3S & MK3S+",
    "print-profile": "0.20mm QUALITY @MK3",
    "material-profile": "Prusament PLA",
}

TRIPLE = """[prusaslicer.base]
printer-profile = "Original Prusa i3 MK3S & MK3S+"
print-profile = "0.20mm QUALITY @MK3"
material-profile = "Prusament PLA"
"""


def _engine(usable_engines: list[EngineSpec]) -> EngineSpec:
    for spec in usable_engines:
        if spec.base_keys and spec.option_probe and spec.secret_keys:
            return spec
    pytest.skip("no engine with declared preset flags, probe and secret keys is installed")


@pytest.fixture(scope="module")
def seeded(usable_engines: list[EngineSpec], tmp_path_factory: pytest.TempPathFactory):
    """An isolated cache holding a map measured for two options on this host."""
    spec = _engine(usable_engines)
    found = discover(spec)
    if found.form is None:
        # Observed here on 2026-09-11: discovery reported `--help exited 1` and the
        # same command succeeded four times a second later. D30 records this
        # transient. An engine that would not start is an environment fault, not a
        # verdict on the code under test (org 2.2) -- erroring would attribute a
        # machine problem to this branch. `SLICELAB_REQUIRE_ENGINE` still turns it
        # into a failure where an engine is supposed to be present.
        pytest.skip(f"{spec.name} did not start: {found.reason}")
    assert spec.option_probe is not None
    who = identify(spec, found)
    if who.version is None:
        pytest.skip(f"{spec.name} did not state a readable version")

    home = tmp_path_factory.mktemp("xdg")
    env = dict(os.environ, XDG_CACHE_HOME=str(home))

    scratch = tmp_path_factory.mktemp("probe")
    sidecar = scratch / "probe.ini"
    baseline, volatile = _baseline(spec, found, sidecar, timeout=60.0)
    entries = {}
    for option in ("perimeters", "spiral-vase"):
        entry = _probe_one(
            spec, found, spec.option_probe, option, sidecar, baseline, volatile, timeout=60.0
        )
        entries[option] = {
            "keys": list(entry.keys),
            "side_effects": list(entry.side_effects),
            "tracking": entry.tracking.value if entry.tracking else None,
            "outcome": entry.outcome.value,
        }

    original = os.environ.get("XDG_CACHE_HOME")
    os.environ["XDG_CACHE_HOME"] = str(home)
    try:
        destination = cache_path_for(spec, who.version)
    finally:
        if original is None:
            del os.environ["XDG_CACHE_HOME"]
        else:
            os.environ["XDG_CACHE_HOME"] = original
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(
            {
                "schema": SCHEMA,
                "engine": spec.name,
                "version": who.version,
                "baseline_key_count": len(baseline),
                "volatile_keys": list(volatile),
                "entries": entries,
                "inconclusive": 0,
            }
        ),
        encoding="utf-8",
    )
    return env, spec, found


def _run(seeded: tuple, intent: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "slicelab", "resolve", str(intent)],
        capture_output=True,
        text=True,
        env=seeded[0],
        timeout=300,
    )


def test_an_honoured_intent_exits_zero(seeded, tmp_path: Path) -> None:
    intent = tmp_path / "slice.toml"
    intent.write_text(TRIPLE + "\n[prusaslicer.set]\nperimeters = 4\n", encoding="utf-8")
    done = _run(seeded, intent)
    assert done.returncode == 0, done.stderr
    assert done.stdout.startswith("sliced")


def test_v1_exits_two_and_names_both_values(seeded, tmp_path: Path) -> None:
    """The run this whole project exists for, as a process.

    `--perimeters=4.7` resolves to `4` at engine exit 0 with zero bytes on stderr.
    slicelab exits **2**, not 0 -- and not 1, because it cannot tell the engine
    ignoring the request from the engine applying a dependent constraint (D27).
    """
    intent = tmp_path / "slice.toml"
    intent.write_text(TRIPLE + "\n[prusaslicer.set]\nperimeters = 4.7\n", encoding="utf-8")
    done = _run(seeded, intent)
    assert done.returncode == 2, done.stdout + done.stderr
    assert done.stderr.startswith("incomplete")
    assert "4.7" in done.stderr
    assert "coerced" in done.stderr


def test_a_base_only_intent_exits_three(seeded, tmp_path: Path) -> None:
    """G1/D24: the first file anyone writes verifies nothing, and must not say `sliced`."""
    intent = tmp_path / "slice.toml"
    intent.write_text(TRIPLE, encoding="utf-8")
    done = _run(seeded, intent)
    assert done.returncode == 3, done.stdout + done.stderr
    assert done.stderr.startswith("empty")


def test_an_unknown_key_in_the_intent_exits_one(seeded, tmp_path: Path) -> None:
    """Refused before the engine is reached. Never silently dropped, which is what
    the engine itself does to an unknown key in a --load'ed ini [V2]."""
    intent = tmp_path / "slice.toml"
    intent.write_text(TRIPLE + "\n[prusaslicer.nonsense]\nx = 1\n", encoding="utf-8")
    done = _run(seeded, intent)
    assert done.returncode == 1, done.stdout + done.stderr
    assert done.stderr.startswith("refused")


def test_a_partial_preset_triple_exits_one_without_touching_the_engine(
    seeded, tmp_path: Path
) -> None:
    """D15. Any proper non-empty subset is a deterministic SIGSEGV with zero bytes
    on both streams, so slicelab refuses rather than reporting a crash it caused."""
    intent = tmp_path / "slice.toml"
    intent.write_text(
        '[prusaslicer.base]\nprinter-profile = "Original Prusa i3 MK3S & MK3S+"\n',
        encoding="utf-8",
    )
    done = _run(seeded, intent)
    assert done.returncode == 1, done.stdout + done.stderr
    assert "print-profile" in done.stderr


def test_the_readback_is_written_and_its_credentials_are_not(seeded, tmp_path: Path) -> None:
    """The sidecar is the engine's own bytes, minus a named list.

    Measured: a preset triple makes `--save` emit `print_host`,
    `printhost_apikey` and `printhost_cafile` in cleartext. A bare `--save` emits
    none of them, so a guard written against the default dump would have found
    nothing and reported the file clean.
    """
    intent = tmp_path / "slice.toml"
    intent.write_text(TRIPLE + "\n[prusaslicer.set]\nperimeters = 4\n", encoding="utf-8")
    done = _run(seeded, intent)
    assert done.returncode == 0, done.stderr

    written = tmp_path / "slice.readback.ini"
    assert written.is_file()
    body = written.read_text(encoding="utf-8")
    assert "perimeters = 4" in body
    for secret in ("print_host", "printhost_apikey", "printhost_cafile"):
        assert f"{secret} = <redacted>" in body, body[:400]
    assert "redacted" in done.stdout


def _cube(path: Path) -> Path:
    """A 20 mm ASCII-STL cube, generated rather than committed (D11)."""
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
    body = ["solid cube"]
    for face in faces:
        body.append("facet normal 0 0 0\n  outer loop")
        body += [f"    vertex {' '.join(str(c) for c in corners[i])}" for i in face]
        body.append("  endloop\nendfacet")
    body.append("endsolid cube")
    path.write_text("\n".join(body) + "\n", encoding="utf-8")
    return path


def test_resolve_matches_slice_config(seeded, tmp_path: Path) -> None:
    """`resolve` previews `slice` faithfully. G7.2 makes this a test, not an assumption.

    `resolve` asks the engine to dump its configuration without slicing, and the
    whole verb rests on that dump being the one a real slice would resolve. That was
    measured once during research and then relied on -- but it is a **per-build fact
    that can regress silently**, which is precisely the class of claim this project
    refuses to carry on a memory.

    Compared here on the same triple and the same override, with and without
    geometry, including the spiral-vase normalisation that makes the comparison
    worth doing: a run where the engine adjusts nothing would prove nothing.
    """
    from slicelab.engine.discover import argv_for
    from slicelab.engine.launch import run

    found = seeded[2]
    model = _cube(tmp_path / "cube.stl")
    triple = [f"--{k}={v}" for k, v in PRESETS.items()]
    overrides = ["--spiral-vase=1", "--perimeters=4"]

    without = tmp_path / "without.ini"
    with_geometry = tmp_path / "with.ini"
    gcode = tmp_path / "out.gcode"

    a = run(argv_for(found.form, [*triple, *overrides, f"--save={without}"], {str(without)}))
    b = run(
        argv_for(
            found.form,
            [
                *triple,
                *overrides,
                "--export-gcode",
                str(model),
                "-o",
                str(gcode),
                f"--save={with_geometry}",
            ],
            {str(with_geometry), str(model), str(gcode)},
        )
    )
    assert a.exit_status == 0, a.stderr
    assert b.exit_status == 0, b.stderr
    assert without.is_file() and with_geometry.is_file()

    left = without.read_text(encoding="utf-8").splitlines()
    right = with_geometry.read_text(encoding="utf-8").splitlines()
    assert len(left) == len(right), (len(left), len(right))

    differing = [(x, y) for x, y in zip(left, right, strict=True) if x != y]

    # Every CONFIG line is identical. The only difference the engine produces is
    # its own generation timestamp, in a comment:
    #   # generated by PrusaSlicer 2.9.6 on 2026-09-11 at 05:15:20 UTC
    #   # generated by PrusaSlicer 2.9.6 on 2026-09-11 at 05:15:22 UTC
    # Asserted as a comment rather than filtered away, because it is also the
    # reason the dump is NOT byte-stable across two runs of the same intent --
    # which anything hashing the sidecar has to know before it hashes it.
    assert all(x.startswith("#") for x, _ in differing), differing[:5]
    config_left = [line for line in left if not line.startswith("#")]
    config_right = [line for line in right if not line.startswith("#")]
    assert config_left == config_right

    # The comparison is only worth making because the engine DID adjust things.
    resolved = dict(line.split(" = ", 1) for line in left if " = " in line)
    assert resolved["spiral_vase"] == "1"
    assert resolved["perimeters"] == "1", "spiral vase did not constrain perimeters"
