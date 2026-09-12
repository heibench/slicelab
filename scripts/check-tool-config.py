#!/usr/bin/env python3
"""Verify the tool configuration the recipes read, and prove this file still can.

Every other guard in this repository pins an *invocation* -- a justfile recipe, a
workflow step, a pre-commit hook. `pyproject.toml` reaches the same outcomes from a
file none of them inspected.

This lives outside pytest ON PURPOSE: `addopts` gaining `--co` collects the whole
suite, runs none of it and exits 0, so an assertion inside the suite is the thing that
weakening switches off. `just check` runs this, and `just check` does not go through
pytest.

And it self-tests, for the reason everything else in this change does. `return found`
edited to `return []` left this script printing success over a `pyproject.toml` with
`--co` in it -- one line, surviving ruff, ruff-format and mypy (which does not cover
`scripts/`), with `just check`, `just test` and the whole suite green. So before it
adjudicates anything it is handed a configuration with nothing wrong with it, which it
must pass, and then one deliberately weakened configuration per check, each of which it
must reject. Probe before adjudicating, the same shape `prove-hooks-catch.sh` uses.
"""

from __future__ import annotations

import copy
import sys
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"

#: Every rule family `just lint` and the `ruff-check` hook are expected to enforce.
#: A superset is fine; dropping one is not.
REQUIRED_RULES = {"E", "F", "I", "UP", "B", "SIM"}

#: Keys that SUBTRACT from what ruff looks at. `select` says what is enforced and is
#: checked as a superset; these say what is exempted, and one line of any of them takes
#: a whole subpackage out with every other instrument green -- the prover included,
#: because it plants at `slicelab/*.py` and cannot see a rule scoped below that.
#: An allowlist of absence, so adding one is a diff someone can object to.
RUFF_SUBTRACTIONS = ("exclude", "extend-exclude", "force-exclude")
RUFF_LINT_SUBTRACTIONS = (
    "ignore",
    "extend-ignore",
    "exclude",
    "extend-exclude",
    "per-file-ignores",
    "extend-per-file-ignores",
)


def problems(tool: dict[str, Any]) -> list[str]:
    """Every way this configuration weakens a check that is otherwise gated."""
    found: list[str] = []

    pytest_cfg = tool["pytest"]["ini_options"]
    if pytest_cfg.get("addopts") != ["-ra"]:
        found.append(
            f"addopts = {pytest_cfg.get('addopts')!r} -- pytest's own configuration can "
            "deselect the suite, or collect it without running it, while `just test` exits 0"
        )
    if pytest_cfg.get("testpaths") != ["tests"]:
        found.append(f"testpaths = {pytest_cfg.get('testpaths')!r} -- the suite is not collected")

    ruff = tool["ruff"]
    selected = set(ruff["lint"]["select"])
    if not selected >= REQUIRED_RULES:
        found.append(
            f"ruff select is missing {sorted(REQUIRED_RULES - selected)} -- `just lint` "
            "and the `ruff-check` hook both read this"
        )
    for key in RUFF_SUBTRACTIONS:
        if key in ruff:
            found.append(f"[tool.ruff] {key} = {ruff[key]!r} -- ruff stops looking at those paths")
    for key in RUFF_LINT_SUBTRACTIONS:
        if key in ruff["lint"]:
            found.append(
                f"[tool.ruff.lint] {key} = {ruff['lint'][key]!r} -- rules are exempted "
                "somewhere no plant reaches"
            )

    mypy = tool["mypy"]
    if mypy.get("ignore_errors"):
        found.append("[tool.mypy] ignore_errors is set -- `just typecheck` reports nothing")
    for override in mypy.get("overrides", []):
        if override.get("ignore_errors"):
            found.append(
                f"[[tool.mypy.overrides]] ignores errors for {override.get('module')!r} -- "
                "`just typecheck` reports nothing for those modules"
            )

    if "uv" in tool:
        found.append(
            f"[tool.uv] {sorted(tool['uv'])} -- `override-dependencies` there resolves a "
            "different ruff than the dev group declares, and `--locked` accepts it"
        )
    return found


#: A configuration with nothing wrong with it. The probe: this must come back clean, or
#: nothing below establishes anything.
INTACT: dict[str, Any] = {
    "pytest": {"ini_options": {"addopts": ["-ra"], "testpaths": ["tests"]}},
    "ruff": {"lint": {"select": sorted(REQUIRED_RULES)}},
    "mypy": {"python_version": "3.11"},
}


def _weaken(path: tuple[str, ...], key: str, value: Any) -> Callable[[dict[str, Any]], None]:
    def damage(tool: dict[str, Any]) -> None:
        target = tool
        for part in path:
            target = target[part]
        target[key] = value

    return damage


#: One weakening per check above, each of which this script must reject.
WEAKENINGS: list[tuple[str, Callable[[dict[str, Any]], None]]] = [
    (
        "addopts collects without running",
        _weaken(("pytest", "ini_options"), "addopts", ["-ra", "--co"]),
    ),
    (
        "addopts deselects the gate",
        _weaken(("pytest", "ini_options"), "addopts", ["-ra", "--ignore=tests"]),
    ),
    ("testpaths collects nothing", _weaken(("pytest", "ini_options"), "testpaths", [])),
    ("ruff enforces no rules", _weaken(("ruff", "lint"), "select", [])),
    *(("[tool.ruff] " + k, _weaken(("ruff",), k, ["slicelab"])) for k in RUFF_SUBTRACTIONS),
    *(
        ("[tool.ruff.lint] " + k, _weaken(("ruff", "lint"), k, ["F401"]))
        for k in RUFF_LINT_SUBTRACTIONS
    ),
    ("mypy ignores every error", _weaken(("mypy",), "ignore_errors", True)),
    (
        "mypy ignores errors per module",
        _weaken(("mypy",), "overrides", [{"module": ["slicelab.*"], "ignore_errors": True}]),
    ),
    (
        "uv overrides the resolved ruff",
        _weaken((), "uv", {"override-dependencies": ["ruff==0.14.0"]}),
    ),
]


def self_test() -> list[str]:
    """This script's own gate: it must pass a clean configuration and reject each bad one."""
    failures: list[str] = []
    clean = problems(copy.deepcopy(INTACT))
    if clean:
        return [f"a configuration with nothing wrong with it was reported as weakened: {clean}"]
    for label, damage in WEAKENINGS:
        tool = copy.deepcopy(INTACT)
        damage(tool)
        if not problems(tool):
            failures.append(f"no longer detects: {label}")
    return failures


def main() -> int:
    broken = self_test()
    for failure in broken:
        print(f"error: {failure}", file=sys.stderr)
    if broken:
        print(
            "this script no longer detects configurations it is written to reject, so "
            "its verdict on the real one means nothing",
            file=sys.stderr,
        )
        return 1

    found = problems(tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["tool"])
    for problem in found:
        print(f"error: {problem}", file=sys.stderr)
    if found:
        print(f"{PYPROJECT.name} weakens a check that is otherwise gated", file=sys.stderr)
        return 1

    print(
        f"tool configuration intact, and this check still rejects {len(WEAKENINGS)} "
        "configurations it is written to reject"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
