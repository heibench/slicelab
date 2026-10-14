"""Which engines a runner has declared must be present.

`SLICELAB_REQUIRE_ENGINE` exists so a missing engine cannot pass for a tested one: a
skipped test is not a passing test (org 2.4). It was a single boolean, which made it
unusable on a matrix where the legs install different engines -- the engine matrix set
it for every job and only its Flatpak leg installs OrcaSlicer, so the macOS and
Windows legs demanded an engine they never install and the five OrcaSlicer tests
errored at setup rather than skipping.

"This leg has no OrcaSlicer" is a true statement about the leg, not a finding about
the code. Naming the engines keeps the flag's teeth where they belong.
"""

from __future__ import annotations

import pytest

from slicelab.adapters import REGISTRY
from tests.conftest import REQUIRE_ENV, _required, skip_or_fail


def test_nothing_is_required_when_the_variable_is_unset_or_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(REQUIRE_ENV, raising=False)
    assert _required() == frozenset()
    for off in ("", "0", "false", "False"):
        monkeypatch.setenv(REQUIRE_ENV, off)
        assert _required() == frozenset(), off


def test_a_bare_truthy_value_requires_every_registered_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """What a host with all of them should say, and what it meant before it took names."""
    monkeypatch.setenv(REQUIRE_ENV, "1")
    assert _required() == frozenset(REGISTRY)
    assert len(REGISTRY) > 1, "a single-engine registry would make this vacuous"


def test_naming_engines_requires_those_and_not_the_others(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(REQUIRE_ENV, "prusaslicer")
    assert _required() == frozenset({"prusaslicer"})
    monkeypatch.setenv(REQUIRE_ENV, "prusaslicer, orcaslicer")
    assert _required() == frozenset({"prusaslicer", "orcaslicer"})


def test_an_engine_the_runner_did_not_name_skips_rather_than_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The macOS and Windows legs: PrusaSlicer required, OrcaSlicer absent and not
    claimed. Five errors per leg before this, on run 38497422988."""
    monkeypatch.setenv(REQUIRE_ENV, "prusaslicer")

    with pytest.raises(BaseException) as raised:
        skip_or_fail("orcaslicer did not start", engine="orcaslicer")
    assert raised.typename == "Skipped", raised.typename


def test_an_engine_the_runner_did_name_still_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The flag's whole purpose, which naming engines must not weaken."""
    monkeypatch.setenv(REQUIRE_ENV, "prusaslicer")

    with pytest.raises(BaseException) as raised:
        skip_or_fail("prusaslicer did not start", engine="prusaslicer")
    assert raised.typename == "Failed", raised.typename


def test_an_unnamed_call_fails_whenever_anything_is_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`any_engine` asks "is any engine required here", because it would take any of
    them -- so a leg that declared one and has none is a failure, not a skip."""
    monkeypatch.setenv(REQUIRE_ENV, "prusaslicer")

    with pytest.raises(BaseException) as raised:
        skip_or_fail("no usable engine found")
    assert raised.typename == "Failed", raised.typename
