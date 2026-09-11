"""The mechanism, end to end, against a real engine.

`test_readback.py` is pure and would pass against a map that describes no engine
at all. This file builds its map by **probing the installed build** — only the
options under test, because a full characterisation is minutes — then plans, runs,
reads back, and diffs. It is the only place the whole chain is exercised at once.

Skips loudly with no engine, and fails rather than skips under
`SLICELAB_REQUIRE_ENGINE`: a skipped test is not a passing test (org 2.4).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from slicelab.adapters import EngineSpec
from slicelab.engine.characterise import MapEntry, _baseline, _probe_one
from slicelab.engine.discover import Discovery, argv_for, discover
from slicelab.engine.launch import run
from slicelab.intent import Intent, IntentValue
from slicelab.plan import plan_resolve
from slicelab.preflight import preflight
from slicelab.readback import diff
from slicelab.status import KeyStatus, Outcome

TRIPLE = {
    "printer-profile": "Original Prusa i3 MK3S & MK3S+",
    "print-profile": "0.20mm QUALITY @MK3",
    "material-profile": "Prusament PLA",
}


def _engine(usable_engines: list[EngineSpec]) -> EngineSpec:
    for spec in usable_engines:
        if spec.base_keys and spec.option_probe and spec.readback_flag:
            return spec
    pytest.skip("no engine that has declared its preset flags and probe is installed")


@pytest.fixture(scope="module")
def probed(
    usable_engines: list[EngineSpec], tmp_path_factory: pytest.TempPathFactory
) -> tuple[EngineSpec, Discovery, dict[str, MapEntry]]:
    """A real map for two options, measured on this host.

    Module-scoped because each option costs several engine invocations, and
    `_baseline` costs two more. Probing all 416 would be minutes; probing the two
    under test is seconds and is still a measurement rather than a fixture someone
    wrote down.
    """
    spec = _engine(usable_engines)
    found = discover(spec)
    assert found.form is not None
    assert spec.option_probe is not None
    scratch = tmp_path_factory.mktemp("probe")
    sidecar = scratch / "probe.ini"
    baseline, volatile = _baseline(spec, found, sidecar, timeout=60.0)
    name_map: dict[str, MapEntry] = {}
    for option in ("perimeters", "spiral-vase"):
        name_map[option] = _probe_one(
            spec, found, spec.option_probe, option, sidecar, baseline, volatile, timeout=60.0
        )
    return spec, found, name_map


def _resolve(
    spec: EngineSpec, found: Discovery, overrides: dict[str, IntentValue], sidecar: Path
) -> tuple[dict[str, str], dict[str, str]]:
    """Plan, run, and read the sidecar back. Returns (requested, resolved)."""
    intent = Intent(engine=spec.name, base=dict(TRIPLE), overrides=overrides, source=sidecar.parent)
    plan = plan_resolve(intent, preflight(intent), sidecar)
    assert found.form is not None
    completed = run(argv_for(found.form, plan.argv, plan.paths))
    assert completed.signal is None
    assert completed.exit_status == 0, completed.stderr
    resolved: dict[str, str] = {}
    for line in sidecar.read_text(encoding="utf-8", errors="replace").splitlines():
        key, sep, value = line.partition(" = ")
        if sep and not key.startswith(("#", "[")):
            resolved[key.strip()] = value
    return plan.requested, resolved


def test_the_probe_measured_what_the_options_actually_write(
    probed: tuple[EngineSpec, Discovery, dict[str, MapEntry]],
) -> None:
    """The map under test is measured here, so its content is worth asserting.

    `perimeters` writes itself. `spiral-vase` writes `spiral_vase` and *adjusts*
    `perimeters`, `fill_density` and `top_solid_layers` — the dependent constraints
    that made a correct slice report as a finding before the probe told them apart.
    """
    _, _, name_map = probed
    assert name_map["perimeters"].keys == ("perimeters",)
    assert name_map["spiral-vase"].keys == ("spiral_vase",)
    assert "perimeters" in name_map["spiral-vase"].side_effects


def test_an_honoured_request_reads_as_applied(
    probed: tuple[EngineSpec, Discovery, dict[str, MapEntry]], tmp_path: Path
) -> None:
    spec, found, name_map = probed
    requested, resolved = _resolve(spec, found, {"perimeters": 4}, tmp_path / "ok.ini")
    r = diff(requested, resolved, name_map)
    assert r.verdicts[0].status is KeyStatus.APPLIED
    assert r.outcome is Outcome.SLICED


def test_v1_end_to_end_the_run_this_project_exists_for(
    probed: tuple[EngineSpec, Discovery, dict[str, MapEntry]], tmp_path: Path
) -> None:
    """`--perimeters=4.7` resolves to `4`, at exit 0, with zero bytes on stderr.

    The engine says nothing. Everything upstream of the diff reports success. This
    is the first point in the whole system where anything notices.
    """
    spec, found, name_map = probed
    requested, resolved = _resolve(spec, found, {"perimeters": 4.7}, tmp_path / "v1.ini")
    assert requested["perimeters"] == "4.7"
    assert resolved["perimeters"] == "4"

    r = diff(requested, resolved, name_map)
    verdict = r.verdicts[0]
    assert verdict.status is KeyStatus.COERCED
    assert verdict.compared == ("perimeters",)
    assert verdict.observed == ("4",)
    assert r.outcome is Outcome.INCOMPLETE
    assert r.outcome is not Outcome.SLICED


def test_g4_a_correct_slice_is_not_reported_as_a_finding(
    probed: tuple[EngineSpec, Discovery, dict[str, MapEntry]], tmp_path: Path
) -> None:
    """The false red that D27 and the two-sentinel probe exist to prevent.

    `--spiral-vase=1` is honoured exactly, and the engine then adjusts `perimeters`
    to 1, `top_solid_layers` to 0 and `fill_density` to 0% — documented dependent
    constraints, none of them requested. Adjudicating the authored value against
    them reported a correct slice as a finding. The probe puts them in
    `side_effects`, so the diff never looks at them.
    """
    spec, found, name_map = probed
    requested, resolved = _resolve(spec, found, {"spiral-vase": True}, tmp_path / "g4.ini")
    assert requested["spiral-vase"] == "1"
    assert resolved["spiral_vase"] == "1"

    # The constraints must actually FIRE, or this test passes for the wrong reason:
    # a run where the engine adjusted nothing would also report `applied`, and would
    # prove only that the diff works on an option with no side effects at all.
    constrained = {k: resolved[k] for k in ("perimeters", "top_solid_layers", "fill_density")}
    assert constrained["perimeters"] == "1", constrained
    assert constrained["top_solid_layers"] == "0", constrained

    r = diff(requested, resolved, name_map)
    assert r.verdicts[0].status is KeyStatus.APPLIED
    assert r.verdicts[0].compared == ("spiral_vase",)
    assert r.outcome is Outcome.SLICED
