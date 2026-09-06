"""Preset enumeration is adjudicated on the artifact, never the exit code.

``notes/evidence.md`` V5: ``--query-printer-models`` returns exit **1** with
6550 bytes of valid JSON and nothing on stderr -- the same code it returns for
"that printer was not found". An adapter branching on ``rc == 0`` treats every
successful vendor query as an error.

And parseability alone is not enough (``notes/critique.md`` G3).
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from slicelab.adapters import ORCASLICER, PRUSASLICER, EngineSpec
from slicelab.presets import PresetsVerdict, adjudicate

ROOT = "printer_models"


def test_a_real_enumeration_is_accepted() -> None:
    payload = json.dumps({ROOT: [{"id": "MK4IS", "name": "Original Prusa MK4 Input Shaper"}]})
    result = adjudicate(payload, ROOT)
    assert result.ok
    assert result.verdict is PresetsVerdict.ENUMERATED
    assert result.entries[0]["id"] == "MK4IS"


def test_an_empty_list_is_not_success() -> None:
    """G3. Parsing is not enumerating.

    Reporting 0 here is a green from the one verb whose entire job is
    establishing that a ``[base]`` name is nameable.
    """
    result = adjudicate(json.dumps({ROOT: []}), ROOT)
    assert not result.ok
    assert result.verdict is PresetsVerdict.EMPTY
    assert "no presets" in result.reason


def test_the_g3_payload_shape_is_caught() -> None:
    """The exact shape G3 reports: the key present, holding an empty STRING.

    SYNTHETIC. G3 records this from a datadir carrying the vendor bundle with
    no models installed; I have not reproduced it against a real engine, and
    this fixture is the payload as reported, not one I measured. A fully empty
    datadir gives something different -- a log line on stdout, which the
    unparseable test below covers and which I did reproduce.

    It must not be conflated with an empty list: both mean "nothing", but only
    one is the type we were promised, and merging them would hide a schema
    change behind an empty result.
    """
    result = adjudicate(json.dumps({ROOT: ""}), ROOT)
    assert not result.ok
    assert result.verdict is PresetsVerdict.MALFORMED
    assert "not a list" in result.reason


def test_non_json_stdout_is_unparseable() -> None:
    """Reproduced 2026-09-06: an empty --datadir makes PrusaSlicer write a log
    line to STDOUT rather than JSON, still at exit 1."""
    noise = (
        "[2026-09-06 15:51:19] [error]   Configuration wasn't found. Check your 'datadir' value."
    )
    result = adjudicate(noise, ROOT)
    assert result.verdict is PresetsVerdict.UNPARSEABLE
    assert "not JSON" in result.reason


def test_silence_is_unparseable_not_empty() -> None:
    """An engine that said nothing has not told us there are no presets."""
    assert adjudicate("", ROOT).verdict is PresetsVerdict.UNPARSEABLE
    assert adjudicate("   \n", ROOT).verdict is PresetsVerdict.UNPARSEABLE


def test_a_missing_root_key_is_malformed() -> None:
    assert adjudicate(json.dumps({"something_else": []}), ROOT).verdict is PresetsVerdict.MALFORMED


def test_a_json_scalar_is_malformed() -> None:
    assert adjudicate("42", ROOT).verdict is PresetsVerdict.MALFORMED


def test_prusaslicer_declares_a_preset_query_and_orcaslicer_does_not() -> None:
    """The asymmetry is a measurement, not an omission.

    OrcaSlicer 2.4.2's --help has --load-settings and --load-filaments, which
    CONSUME profile files, and nothing that reports which presets exist.
    slicelab could read its profile directories and present that as the
    engine's answer; that would be slicelab's inventory, not the engine's.
    """
    assert PRUSASLICER.preset_query is not None
    assert PRUSASLICER.preset_query.root_key == "printer_models"
    assert ORCASLICER.preset_query is None


def _cli(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "slicelab", *args], capture_output=True, text=True, check=False
    )


def test_an_engine_without_the_verb_exits_2_not_1_and_not_0() -> None:
    """Needs no engine installed: the capability check precedes discovery."""
    proc = _cli(["presets", "orcaslicer"])
    assert proc.returncode == 2, (
        "an engine that cannot enumerate presets is a could-not-tell. Exit 1 "
        "would claim something was wrong with the request; exit 0 with an "
        "empty list would report our ignorance as the engine's inventory."
    )
    assert "engine_has_no_preset_query" in proc.stderr
    assert proc.stdout == "", "a non-answer must not write to stdout"


def test_a_real_engine_enumerates_at_exit_zero_while_the_engine_returns_one(
    any_engine: EngineSpec,
) -> None:
    if any_engine.preset_query is None:
        pytest.skip(f"{any_engine.name} has no preset-enumeration verb")
    proc = _cli(["presets", any_engine.name])
    assert proc.returncode == 0, proc.stderr
    document = json.loads(proc.stdout)
    assert document[any_engine.preset_query.root_key], "enumerated nothing at exit 0"
