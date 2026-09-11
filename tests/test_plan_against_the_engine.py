"""The planned argv, run against a real engine.

Everything in `test_plan.py` is pure and would pass against an argv the engine
rejects. This is the file that says the composition is right, and it is the only
claim in this slice that a machine without a slicer cannot make.

Skips loudly when no engine is present, and fails instead of skipping under
`SLICELAB_REQUIRE_ENGINE` -- a skipped test is not a passing test (org 2.4).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from slicelab.adapters import EngineSpec
from slicelab.engine.discover import argv_for, discover
from slicelab.engine.launch import run
from slicelab.intent import Intent
from slicelab.plan import plan_resolve
from slicelab.preflight import preflight

TRIPLE = {
    "printer-profile": "Original Prusa i3 MK3S & MK3S+",
    "print-profile": "0.20mm QUALITY @MK3",
    "material-profile": "Prusament PLA",
}


def _prusaslicer(usable_engines: list[EngineSpec]) -> EngineSpec:
    for spec in usable_engines:
        if spec.base_keys:
            return spec
    pytest.skip("no engine that has declared its preset flags is installed")


def _readback(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        key, sep, value = line.partition(" = ")
        if sep and not key.startswith(("#", "[")):
            out[key.strip()] = value
    return out


def test_the_planned_argv_makes_the_engine_state_what_it_resolved(
    usable_engines: list[EngineSpec], tmp_path: Path
) -> None:
    """`resolve`'s whole premise, end to end, with no geometry and no artifact.

    Measured on Flathub PrusaSlicer 2.9.6: a preset triple plus the readback flag
    and no model file exits 0, writes a 376-key configuration and puts zero bytes on
    stderr. The 343-key default dump does not carry the preset ids, so the larger
    number is the evidence the triple was honoured rather than ignored.
    """
    spec = _prusaslicer(usable_engines)
    found = discover(spec)
    assert found.form is not None

    sidecar = tmp_path / "effective.ini"
    intent = Intent(
        engine=spec.name, base=dict(TRIPLE), overrides={"perimeters": 4}, source=tmp_path
    )
    plan = plan_resolve(intent, preflight(intent), tmp_path / "promoted.ini", sidecar)

    completed = run(argv_for(found.form, plan.argv, plan.paths))

    assert completed.signal is None, f"engine died by signal {completed.signal}"
    assert completed.exit_status == 0, completed.stderr
    assert sidecar.exists(), "the engine exited 0 and wrote no configuration"
    resolved = _readback(sidecar)
    assert len(resolved) > 300, f"only {len(resolved)} keys came back"
    assert resolved["perimeters"] == "4"


def test_an_override_the_engine_coerces_comes_back_changed(
    usable_engines: list[EngineSpec], tmp_path: Path
) -> None:
    """V1, through the planned argv rather than a hand-typed command line.

    `--perimeters=4.7` resolves to `4`, at exit 0, with zero bytes on stderr. This
    is the defect the whole project exists to catch, and this test is the first
    place slicelab's own composition produces it. The diff that turns this into a
    `coerced` key is the next slice; what is established here is that the request
    and the result genuinely differ and that nothing says so.
    """
    spec = _prusaslicer(usable_engines)
    found = discover(spec)
    assert found.form is not None

    sidecar = tmp_path / "coerced.ini"
    intent = Intent(
        engine=spec.name, base=dict(TRIPLE), overrides={"perimeters": 4.7}, source=tmp_path
    )
    plan = plan_resolve(intent, preflight(intent), tmp_path / "promoted.ini", sidecar)
    completed = run(argv_for(found.form, plan.argv, plan.paths))

    assert completed.signal is None
    assert completed.exit_status == 0
    assert completed.stderr == ""
    resolved = _readback(sidecar)
    assert plan.requested["perimeters"] == "4.7"
    assert resolved["perimeters"] == "4"
    assert resolved["perimeters"] != plan.requested["perimeters"]


def test_a_boolean_reaches_the_engine_as_the_engine_spells_it(
    usable_engines: list[EngineSpec], tmp_path: Path
) -> None:
    """The measurement `bool_words` exists for, run rather than remembered.

    Emitting Python's `str(True)` would send `--spiral-vase=True`, which this engine
    resolves to `0` -- the opposite of the request, at exit 0, silently. Boolean
    options validate nothing, so nothing else in the system would catch it.
    """
    spec = _prusaslicer(usable_engines)
    found = discover(spec)
    assert found.form is not None

    sidecar = tmp_path / "bool.ini"
    intent = Intent(
        engine=spec.name,
        base=dict(TRIPLE),
        overrides={"spiral-vase": True},
        source=tmp_path,
    )
    plan = plan_resolve(intent, preflight(intent), tmp_path / "promoted.ini", sidecar)
    assert plan.requested["spiral-vase"] == "1"

    completed = run(argv_for(found.form, plan.argv, plan.paths))
    assert completed.signal is None
    assert completed.exit_status == 0
    assert _readback(sidecar)["spiral_vase"] == "1"
