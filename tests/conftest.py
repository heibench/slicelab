"""Engine-dependent tests skip, unless the environment says they must not.

A missing engine is an environment fault, not a verdict on this code (org
contract 2.2). But a skipped test is not a passing test (2.4), so CI sets
``SLICELAB_REQUIRE_ENGINE=1`` on runners that install an engine, and a skip
there becomes a hard failure.

Gating is **per test**, never at module import. ``pytest.importorskip`` at
module scope raises during collection: the file reports as ONE skipped line and
takes every test in it -- including the ones needing nothing -- out of the
count. partspec once reported 195 passed / 23 skipped in CI where those 23 were
the entire end-to-end path.
"""

from __future__ import annotations

import os

import pytest

from slicelab.adapters import REGISTRY, EngineSpec
from slicelab.engine.discover import ExitFidelity, discover

REQUIRE_ENV = "SLICELAB_REQUIRE_ENGINE"


def _require() -> bool:
    return os.environ.get(REQUIRE_ENV, "") not in ("", "0", "false", "False")


def _usable(spec: EngineSpec) -> tuple[bool, str]:
    found = discover(spec)
    if found.fidelity is ExitFidelity.ESTABLISHED:
        return True, ""
    return False, f"{spec.name}: {found.fidelity.value} -- {found.reason}"


@pytest.fixture(scope="session")
def any_engine() -> EngineSpec:
    """Any engine whose exit status can be believed, or skip.

    With SLICELAB_REQUIRE_ENGINE set, this FAILS instead, naming every engine
    it looked for and why each was unusable -- so "the engine was missing"
    cannot masquerade as a green run.
    """
    reasons = []
    for spec in REGISTRY.values():
        ok, why = _usable(spec)
        if ok:
            return spec
        reasons.append(why)
    message = "no usable engine found: " + "; ".join(reasons)
    if _require():
        pytest.fail(f"{REQUIRE_ENV} is set but {message}")
    pytest.skip(message)


@pytest.fixture(scope="session")
def usable_engines() -> list[EngineSpec]:
    """*Every* engine whose exit status can be believed, or skip.

    ``any_engine`` returns the first one that works, which is the right fixture
    for "does this verb behave". It is the wrong one for "does no engine
    misbehave": the litter that motivated the cwd guarantee comes from
    OrcaSlicer, and a host where PrusaSlicer is found first would pass such a
    test having never launched the engine that writes the file.
    """
    usable = []
    reasons = []
    for spec in REGISTRY.values():
        ok, why = _usable(spec)
        if ok:
            usable.append(spec)
        else:
            reasons.append(why)
    if usable:
        return usable
    message = "no usable engine found: " + "; ".join(reasons)
    if _require():
        pytest.fail(f"{REQUIRE_ENV} is set but {message}")
    pytest.skip(message)
