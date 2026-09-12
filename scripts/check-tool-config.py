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
import re
import subprocess
import sys
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"

#: Every rule family `just lint` and the `ruff-check` hook are expected to enforce.
#: A superset is fine; dropping one is not.
REQUIRED_RULES = {"E", "F", "I", "UP", "B", "SIM"}

#: Keys that SUBTRACT from what ruff looks at. `select` says what is enforced and is
#: checked as a superset; these say what is exempted, and one line of any of them takes
#: a whole subpackage out with every other instrument green -- the prover included,
#: because it plants at `slicelab/*.py` and cannot see a rule scoped below that.
#: `include` is here because an allowlist narrows: `include = ["slicelab/**"]` took
#: `tests/` and `scripts/` out of both `just lint` and `just fmt-check` while leaving
#: the prover's plants visible, so every instrument stayed green.
#: An allowlist of absence, so adding one is a diff someone can object to.
RUFF_SUBTRACTIONS = ("include", "exclude", "extend-exclude", "force-exclude")
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
    # `disable_error_code` reaches the same place quietly: with `["return-value"]` set,
    # mypy said "Success: no issues found in 50 source files" over a planted
    # `def f() -> int: return "not an int"`. No hook runs mypy, so `just typecheck` is
    # the only place it happens and there is nothing behind it.
    if mypy.get("disable_error_code"):
        found.append(
            f"[tool.mypy] disable_error_code = {mypy['disable_error_code']!r} -- "
            "`just typecheck` stops reporting those"
        )
    for override in mypy.get("overrides", []):
        for key in ("ignore_errors", "disable_error_code"):
            if override.get(key):
                found.append(
                    f"[[tool.mypy.overrides]] {key} for {override.get('module')!r} -- "
                    "`just typecheck` stops reporting for those modules"
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
    ("mypy disables an error code", _weaken(("mypy",), "disable_error_code", ["return-value"])),
    (
        "mypy ignores errors per module",
        _weaken(("mypy",), "overrides", [{"module": ["slicelab.*"], "ignore_errors": True}]),
    ),
    (
        "mypy disables an error code per module",
        _weaken(
            ("mypy",),
            "overrides",
            [{"module": ["slicelab.*"], "disable_error_code": ["return-value"]}],
        ),
    ),
    (
        "uv overrides the resolved ruff",
        _weaken((), "uv", {"override-dependencies": ["ruff==0.14.0"]}),
    ),
]


#: The suite file this whole change exists to keep running.
GATE_TEST = "tests/test_pre_commit_gate.py"


def nested_ruff_configs(tracked: list[str]) -> list[str]:
    """Every tracked file that ruff would prefer over the root configuration.

    Ruff resolves configuration hierarchically, so `slicelab/ruff.toml` holding
    `[lint] select = []` turns ruff off over the whole package -- past `just lint`, past
    the `ruff-check` hook, past the table checks above (the root file is untouched),
    past the root allowlist test (which reads only the first path segment), and past the
    prover (which copies two files into its scratch repository, and a nested one is not
    among them).

    Takes the file list rather than reading it, so the self-test below can hand it a
    tree it knows the answer for.
    """
    found = []
    for path in tracked:
        name = path.rsplit("/", 1)[-1]
        if name in {"ruff.toml", ".ruff.toml"} or (name == "pyproject.toml" and "/" in path):
            found.append(f"{path} is a second ruff configuration, and ruff prefers the nearest")
    return found


def gate_is_missing_from(collected: str) -> bool:
    """Whether a plain `pytest --collect-only` run left the gate out.

    `collect_ignore = ["test_pre_commit_gate.py"]` in `tests/conftest.py` removes it and
    leaves 331 of 357 tests passing -- the same number and the same outcome as the
    `--ignore` spelling the tables above refuse, from a file no table mentions.

    Collected the way `just test` collects: through `testpaths`, with no path argument.
    Naming the file explicitly BYPASSES `collect_ignore`, so that spelling would report
    the gate present either way and could not fail.
    """
    return f"{GATE_TEST}::" not in collected


def gate_did_not_pass(summary: str, returncode: int) -> bool:
    """Whether a run of the gate file actually passed, rather than merely existing.

    `gate_is_missing_from` closes `collect_ignore`, deselection and
    `pytest_ignore_collect`. It does not close a skip or an xfail, which leave the file
    collected and every assertion in it inert. Three lines in `tests/conftest.py` --

        def pytest_collection_modifyitems(config, items):
            for item in items:
                if "test_pre_commit_gate" in item.nodeid:
                    item.add_marker(pytest.mark.skip(reason="quarantined"))

    -- left `331 passed, 28 skipped` and every other instrument green. An autouse
    fixture calling `pytest.skip` does the same. A non-strict `xfail` is the quiet one:
    it skips nothing today and reports every future failure of this gate as green.

    A whitelist, not a denylist of words: the run has to say some tests passed and say
    nothing else about them.
    """
    if returncode != 0:
        return True
    if not re.search(r"\b\d+ passed\b", summary):
        return True
    return bool(re.search(r"\b\d+ (skipped|xfailed|xpassed|deselected|failed|error)", summary))


def tree_problems() -> list[str]:
    """The two checks above, against this repository."""
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    found = nested_ruff_configs(tracked)

    collected = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if gate_is_missing_from(collected.stdout):
        found.append(
            f"{GATE_TEST} is not collected by a plain `pytest` run -- a `collect_ignore` "
            "or a conftest can remove it without touching any configuration table"
        )

    # And it has to RUN. Named explicitly here, which is right for this question:
    # `collect_ignore` is already covered by the bare run above, and naming the file is
    # what keeps `pytest_collection_modifyitems` and an autouse skip in scope.
    ran = subprocess.run(
        [sys.executable, "-m", "pytest", GATE_TEST, "-q", "-p", "no:cacheprovider"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    summary = ran.stdout.strip().rsplit("\n", 1)[-1]
    if gate_did_not_pass(summary, ran.returncode):
        found.append(f"{GATE_TEST} is collected but does not run and pass: {summary!r}")
    return found


def self_test() -> list[str]:
    """This script's own gate: it must pass a clean configuration and reject each bad one."""
    failures: list[str] = []
    if not WEAKENINGS:
        return ["there are no weakenings to detect, so this script proves nothing"]
    clean = problems(copy.deepcopy(INTACT))
    if clean:
        return [f"a configuration with nothing wrong with it was reported as weakened: {clean}"]
    for label, damage in WEAKENINGS:
        tool = copy.deepcopy(INTACT)
        damage(tool)
        if not problems(tool):
            failures.append(f"no longer detects: {label}")

    # The tree checks get the same treatment, which is why they take their input rather
    # than reading it: deleting either one left this script printing success and every
    # assertion in the suite green, because nothing exercised them on a tree they should
    # reject. Probe first -- a tree and a collection with nothing wrong with them must
    # come back clean, or a detection below establishes nothing.
    if nested_ruff_configs(["pyproject.toml", "slicelab/cli.py", "tests/conftest.py"]):
        failures.append("reports a tree with no nested ruff configuration as having one")
    if gate_is_missing_from(f"{GATE_TEST}::test_x\ntests/test_other.py::test_y"):
        failures.append("reports the gate as uncollected when it is collected")
    for label, tracked in (
        ("a nested ruff.toml", ["pyproject.toml", "slicelab/ruff.toml"]),
        ("a nested .ruff.toml", ["pyproject.toml", "tests/.ruff.toml"]),
        ("a nested pyproject.toml", ["pyproject.toml", "slicelab/pyproject.toml"]),
    ):
        if not nested_ruff_configs(tracked):
            failures.append(f"no longer detects: {label}")
    if not gate_is_missing_from("tests/test_other.py::test_y\n2 tests collected"):
        failures.append("no longer detects: the gate missing from collection")
    if gate_did_not_pass("28 passed in 1.13s", 0):
        failures.append("reports a clean run of the gate as not having passed")
    for label, summary, returncode in (
        ("the gate skipped", "5 passed, 28 skipped in 1.1s", 0),
        ("the gate xfailed", "5 passed, 28 xpassed in 1.1s", 0),
        ("the gate deselected", "no tests ran in 0.1s", 5),
        ("the gate failing", "27 passed, 1 failed in 1.1s", 1),
    ):
        if not gate_did_not_pass(summary, returncode):
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

    # The tables, then the tree. Reported separately and in that order, so a run
    # against a directory holding only a doctored `pyproject.toml` says why it failed
    # without the tree checks' noise -- which is how the suite proves this script still
    # rejects a real file, and not merely that `problems()` still works in isolation.
    found = problems(tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["tool"])
    for problem in found:
        print(f"error: {problem}", file=sys.stderr)
    if found:
        print(f"{PYPROJECT.name} weakens a check that is otherwise gated", file=sys.stderr)
        return 1

    in_tree = tree_problems()
    for problem in in_tree:
        print(f"error: {problem}", file=sys.stderr)
    if in_tree:
        print("the tree weakens a check that is otherwise gated", file=sys.stderr)
        return 1

    print(
        f"tool configuration intact, the gate is collected, and this check still "
        f"rejects {len(WEAKENINGS)} configurations it is written to reject"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
