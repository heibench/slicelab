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
from typing import NoReturn

import pytest

from slicelab.adapters import REGISTRY, EngineSpec
from slicelab.engine.discover import ExitFidelity, discover

REQUIRE_ENV = "SLICELAB_REQUIRE_ENGINE"


def _required() -> frozenset[str]:
    """Which engines this runner has declared must be present.

    `1` (or any other truthy word) means every engine in the registry, which is what
    a host with all of them should say. A comma-separated list names them instead,
    for a leg that installs some and not others.

    That distinction is why this is a set rather than the boolean it was. The engine
    matrix sets the flag for every job but only its Flatpak leg installs OrcaSlicer,
    so the macOS and Windows legs demanded an engine they never install and the five
    OrcaSlicer tests errored at setup -- measured on run 38497422988, five errors on
    each of those two legs. "This leg has no OrcaSlicer" is a true statement about
    the leg, not a finding about the code, and a skip is the honest answer to it.
    The flag still exists to stop a MISSING engine passing for a tested one, and on
    a leg that names the engine it still does exactly that.
    """
    value = os.environ.get(REQUIRE_ENV, "")
    if value in ("", "0", "false", "False"):
        return frozenset()
    if "," in value or value in REGISTRY:
        return frozenset(name.strip() for name in value.split(",") if name.strip())
    return frozenset(REGISTRY)


def skip_or_fail(message: str, *, engine: str | None = None) -> NoReturn:
    """Skip, unless a runner has declared this engine is supposed to be here.

    Exported because every engine-backed module needs it and the ones that rolled
    their own bare `pytest.skip` were the ones that went quiet: a host where the only
    usable engine lacks the fields a module requires skipped every test in it and
    reported green, which is the shape this file's docstring names as the enemy.

    `engine` names the one this call is about, where there is one. Without it the
    question is "is any engine required here", which is the right question for a
    fixture that would take any of them.
    """
    required = _required()
    if required and (engine is None or engine in required):
        pytest.fail(f"{REQUIRE_ENV} is set but {message}")
    pytest.skip(message)


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
    skip_or_fail("no usable engine found: " + "; ".join(reasons))


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
    skip_or_fail("no usable engine found: " + "; ".join(reasons))
