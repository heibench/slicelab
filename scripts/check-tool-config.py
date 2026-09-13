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

import ast
import copy
import re
import shutil
import subprocess
import sys
import tempfile
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
#: `extend` is here because it points ruff at ANOTHER configuration file whose
#: `exclude` is merged in -- a file that need not be called `ruff.toml`, so the
#: nested-config check does not see it, and need not sit at the root, so the root
#: allowlist does not either. One line took 51 of 62 files out of both `just lint`
#: and `just fmt-check` with three live errors in the tree.
#: An allowlist of absence, so adding one is a diff someone can object to.
RUFF_SUBTRACTIONS = ("include", "exclude", "extend-exclude", "force-exclude", "extend")
#: The same, for mypy -- which has strictly less behind it than ruff. No hook runs
#: mypy and no workflow step does; `just typecheck` is the only invocation in the
#: repository, so `exclude = ["slicelab/adapters/"]` drops four files and every
#: instrument stays green.
MYPY_SUBTRACTIONS = ("exclude", "follow_imports", "ignore_missing_imports")

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
            why = (
                "it points ruff at another configuration file, whose exclusions are "
                "merged in from a path nothing here reads"
                if key == "extend"
                else "ruff stops looking at those paths"
            )
            found.append(f"[tool.ruff] {key} = {ruff[key]!r} -- {why}")
    for key in RUFF_SUBTRACTIONS:
        if key in ruff.get("format", {}):
            found.append(
                f"[tool.ruff.format] {key} = {ruff['format'][key]!r} -- the formatter "
                "stops looking at those paths"
            )
    for key in RUFF_LINT_SUBTRACTIONS:
        if key in ruff["lint"]:
            found.append(
                f"[tool.ruff.lint] {key} = {ruff['lint'][key]!r} -- rules are exempted "
                "somewhere no plant reaches"
            )

    mypy = tool["mypy"]
    for key in MYPY_SUBTRACTIONS:
        if key in mypy:
            found.append(
                f"[tool.mypy] {key} = {mypy[key]!r} -- `just typecheck` stops looking, "
                "and it is the only thing that runs mypy"
            )
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
    *(
        ("[tool.ruff.format] " + k, _weaken(("ruff",), "format", {k: ["slicelab"]}))
        for k in RUFF_SUBTRACTIONS
    ),
    *(("[tool.mypy] " + k, _weaken(("mypy",), k, ["slicelab/"])) for k in MYPY_SUBTRACTIONS),
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


#: Every test the gate file is expected to contain.
#:
#: The replica below plants defects and requires the gate to notice them, which proves
#: the tests those defects belong to are alive. It says nothing about the rest: deleting
#: twenty-eight of twenty-nine tests and keeping only the named one left `just check`
#: and the whole suite green. Nothing else in this repository adjudicates `ci.yml`, so a
#: deleted assertion there has nothing behind it.
#:
#: An allowlist, like the repository root's: removing a test means removing a line here,
#: in a diff someone can object to.
GATE_TESTS = frozenset(
    {
        "test_ci_invokes_the_hooks_rather_than_mentioning_them",
        "test_ci_invokes_the_recipes_this_file_pins",
        "test_every_hook_repository_is_pinned_to_an_immutable_revision",
        "test_large_file_check_looks_at_every_file_not_just_the_new_ones",
        "test_merge_conflict_check_looks_outside_an_active_merge",
        "test_no_gating_job_carries_an_environment_that_can_disable_a_hook",
        "test_no_top_level_filter_hides_the_tree_from_every_hook",
        "test_no_upstream_job_tolerates_its_own_failure",
        "test_something_scans_history_and_not_only_the_staged_index",
        "test_the_aggregator_fails_when_pre_commit_does",
        "test_the_config_parses_and_has_hooks",
        "test_the_hook_and_the_project_agree_on_one_ruff_version",
        "test_the_hooks_are_proved_to_catch_not_merely_to_be_configured",
        "test_the_hooks_that_were_already_right_are_still_there",
        "test_the_lint_hook_is_not_the_deprecated_alias",
        "test_the_local_recipe_runs_the_version_ci_runs",
        "test_the_matrix_covers_every_python_this_project_claims",
        "test_the_pre_commit_job_fetches_the_history_it_scans",
        "test_the_pre_commit_job_is_not_disabled_or_tolerated",
        "test_the_prover_plants_a_defect_for_every_hook_that_is_configured",
        "test_the_pull_request_trigger_keeps_no_branch_filter",
        "test_the_recipes_ci_invokes_still_run_what_they_claim",
        "test_the_repository_root_holds_nothing_stray",
        "test_the_tool_config_check_notices_a_gate_that_cannot_fail",
        "test_the_tool_config_check_proves_the_inventory_and_stub_checks_are_wired",
        "test_the_tool_config_check_acts_on_its_own_self_test",
        "test_the_tool_config_check_still_rejects_a_real_file",
        "test_the_tool_config_check_still_rejects_a_real_tree",
    }
)


def gate_inventory_problems(collected: str) -> list[str]:
    """Which of the gate's tests are gone, and which arrived without being declared.

    Takes the collect-only output rather than reading it, so the self-test can hand it
    a listing it knows the answer for.
    """
    seen = {
        node.split("::")[-1].split("[")[0]
        for node in re.findall(rf"{re.escape(GATE_TEST)}::[^\s]+", collected)
    }
    found = []
    if missing := sorted(GATE_TESTS - seen):
        found.append(f"{GATE_TEST} no longer contains {missing}")
    if extra := sorted(seen - GATE_TESTS):
        found.append(f"{GATE_TEST} contains undeclared tests {extra}; add them to GATE_TESTS")
    return found


#: One doctoring per lever the gate defends, each with the test that must catch it.
#:
#: A single plant proves a single assertion is alive. `test_no_upstream_job_tolerates_
#: its_own_failure` has two halves -- job-level and step-level `continue-on-error` --
#: and deleting the second half while planting a step-level one left everything green,
#: with the test count unchanged at twenty-nine, so the inventory above does not cover
#: it either. And `test_the_aggregator_fails_when_pre_commit_does` guards the only
#: thing that makes `ok` fail; deleting it and turning `run: exit 1` into an echo left
#: `just check` and all 359 tests green.
#:
#: Two doctorings of the same lever are one doctoring twice. The entries below are the
#: levers; this line deliberately does not count them.
GATE_PLANTS: tuple[tuple[str, str, str, str], ...] = (
    (
        "a `check` job that tolerates its own failure",
        "  check:\n",
        "  check:\n    continue-on-error: true\n",
        "test_no_upstream_job_tolerates_its_own_failure",
    ),
    (
        "a `check` STEP that tolerates its own failure",
        "      - run: just check\n",
        "      - run: just check\n        continue-on-error: true\n",
        "test_no_upstream_job_tolerates_its_own_failure",
    ),
    (
        "an aggregator that reports instead of failing",
        "        run: exit 1\n",
        "        run: echo 'an upstream job failed'\n",
        "test_the_aggregator_fails_when_pre_commit_does",
    ),
    # A fourth lever: the measurement that proves each prover self-test can fail the
    # step. It is four statements inside a test whose other assertions all pass without
    # it, so neither the inventory (which pins a name) nor `gate_stub_problems` (which
    # wants one assertion anywhere in the body) sees it go. Deleting it, or inverting
    # its platform guard by one character, left `just check` and the whole suite green
    # over a prover self-test whose `exit 1` had been deleted.
    #
    # THE LAST doctoring in that step, so the enumeration's upper bound is pinned with
    # it: an off-by-one in `range(1, invocations + 1)` is green against any earlier one,
    # and measured red against this one.
    (
        "a prover self-test that prints its error and passes anyway",
        'plants reach."\n            exit 1\n',
        'plants reach."\n',
        "test_the_hooks_are_proved_to_catch_not_merely_to_be_configured",
    ),
)


def gate_stub_problems(source: str) -> list[str]:
    """Declared tests whose body cannot fail.

    The inventory pins names, and a name is not an assertion. Replacing all but two of
    the declared bodies with `pass` left the listing identical, the count identical,
    and this check reporting the gate intact -- over a tree with a retargeted-PR filter
    and a shallow checkout planted in it. Worse than deleting a test, because the
    allowlist then actively asserts the file still contains all of them.

    Runtime is the only other signal (0.04s against 2.9s) and nothing reads it.

    This closes `pass`, not `assert True`. The second is a strictly more deliberate
    edit, and closing it would mean one planted defect per test.

    Takes the source rather than reading it, so the self-test can hand it one it knows
    the answer for.
    """
    hollow = sorted(
        node.name
        # `ast.walk`, not `.body`: `gate_inventory_problems` splits a node id on `::`
        # and takes the last segment, so it accepts `...::TestGate::test_foo` as
        # satisfying the declaration. Reading only module level would let the two
        # disagree -- the inventory reporting a class-nested test present while this
        # check quietly stopped covering it, file-wide and with no diagnostic.
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and node.name in GATE_TESTS
        and not any(isinstance(inner, ast.Assert | ast.Raise) for inner in ast.walk(node))
    )
    if hollow:
        return [f"{GATE_TEST} keeps {hollow} by name with nothing in them that can fail"]
    return []


def gate_did_not_catch(output: str, returncode: int, must_catch: str) -> bool:
    """Whether a run of the gate against a deliberately broken workflow failed as it should.

    `gate_did_not_pass` requires the gate to RUN. It cannot require the gate to be ABLE
    TO FAIL, because it reads what the run reports, and four lines can make the report
    lie in both channels at once:

        @pytest.hookimpl(wrapper=True)
        def pytest_runtest_makereport(item, call):
            report = yield
            if "test_pre_commit_gate" in item.nodeid:
                report.outcome = "passed"
            return report

    `pytest_runtest_makereport` rewrites the outcome BEFORE the session counts it, so
    the summary says 28 passed and the exit code is 0 -- both honest reports of a
    falsified result. Measured over a `ci.yml` whose `check` job tolerates its own
    failure: ruff clean, mypy clean, 359 passed, and this script printing success.

    And it need not come from `tests/conftest.py`: `[project.entry-points.pytest11]`
    registers the same hook from an installed module, one table above everything
    `problems()` reads. So an allowlist over conftest would not close it, and the only
    instrument that does is the one the rest of this change already uses -- plant a
    defect and require the detector to notice.
    """
    return returncode == 0 or must_catch not in output


def _replica(destination: Path) -> None:
    """Every tracked file, as a committed git repository the gate can adjudicate."""
    listing = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True
    ).stdout.decode()
    for relative in filter(None, listing.split("\0")):
        source = ROOT / relative
        if not source.is_file():
            continue
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    for command in (["init", "-q", "-b", "main", "."], ["add", "-A"]):
        subprocess.run(["git", *command], cwd=destination, check=True, capture_output=True)


def gate_catches_a_planted_defect(before: str, after: str) -> tuple[str, int]:
    """Run the gate against a replica whose workflow carries one planted defect.

    A replica rather than this tree, because the defect has to be planted somewhere the
    gate will read, and `just check` must not mutate the repository it is checking. The
    lie travels with the replica -- `tests/conftest.py` is tracked and an entry-point
    plugin is installed -- which is why this catches both spellings.

    Raises if the doctoring does not apply. A plant that failed to apply is otherwise
    indistinguishable from one the gate survived, and it would be reported against the
    gate: renaming the `check` job is legal, leaves the gate correct, and used to print
    "the gate can no longer fail".
    """
    with tempfile.TemporaryDirectory() as scratch:
        replica = Path(scratch)
        _replica(replica)
        workflow = replica / ".github" / "workflows" / "ci.yml"
        original = workflow.read_text(encoding="utf-8")
        doctored = original.replace(before, after, 1)
        if doctored == original:
            raise RuntimeError(
                f"the planted defect did not apply to ci.yml: {before!r} is not in it. "
                "This says nothing about the gate"
            )
        workflow.write_text(doctored, encoding="utf-8")
        done = subprocess.run(
            [sys.executable, "-m", "pytest", GATE_TEST, "-q", "-p", "no:cacheprovider"],
            cwd=replica,
            capture_output=True,
            text=True,
        )
        return done.stdout, done.returncode


def tree_problems() -> list[str]:
    """The two checks above, against this repository."""
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    # Reported in order, each group only if the ones before it passed. A tree that is
    # already known wrong makes every later verdict noise -- and the later checks run
    # the suite, which cannot say anything useful about a tree whose configuration is
    # the thing at fault. Probe before adjudicating, one more time.
    found = nested_ruff_configs(tracked)
    if found:
        return found

    collected = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if gate_is_missing_from(collected.stdout):
        return [
            f"{GATE_TEST} is not collected by a plain `pytest` run -- a `collect_ignore` "
            "or a conftest can remove it without touching any configuration table"
        ]

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
        return [f"{GATE_TEST} is collected but does not run and pass: {summary!r}"]

    # Every test it is supposed to contain, before asking whether any of them work.
    if inventory := gate_inventory_problems(collected.stdout):
        return inventory
    if hollow := gate_stub_problems((ROOT / GATE_TEST).read_text(encoding="utf-8")):
        return hollow

    # And it has to be ABLE TO FAIL. Everything above reads what a run reports.
    for label, before, after, must_catch in GATE_PLANTS:
        try:
            output, returncode = gate_catches_a_planted_defect(before, after)
        except RuntimeError as unplantable:
            # Could not tell, and said so, rather than reporting the gate as broken.
            # A legal rename of the `check` job leaves the gate correct and this plant
            # inapplicable, and the two must not look the same (org 2.2).
            found.append(f"cannot prove the gate catches {label}: {unplantable}")
            continue
        if gate_did_not_catch(output, returncode, must_catch):
            found.append(
                f"{GATE_TEST} does not catch {label} -- {must_catch} is gone or inert: "
                f"exit {returncode}, {output.strip().rsplit(chr(10), 1)[-1]!r}"
            )
    return found


#: Ratchet floor for the number of self-tested weakenings. Raise it when checks are
#: added; it exists so that removing one is loud.
WEAKENINGS_FLOOR = 28

#: And for the ruff rule families. Someone who finds `SIM` noisy edits `select`, is
#: told `select` is missing it, and repairs that by editing this set instead -- the
#: natural path, with nothing objecting.
REQUIRED_RULES_FLOOR = 6

#: And for the inventory. Deleting a test, its declaration here, and the thing it
#: guarded is one green diff otherwise -- measured on the matrix test and on the
#: retargeted-PR test, each of which the workflow argues at length for.
GATE_TESTS_FLOOR = 28


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
        # Each clause isolated. These two rows exist because every other row trips
        # `returncode != 0` first, so the `\d+ passed` clause was never reached and
        # deleting either one alone left the self-test green.
        ("the gate erroring behind a clean-looking summary", "28 passed in 1.1s", 2),
        ("the gate running nothing at exit 0", "no tests ran in 0.1s", 0),
        ("the gate failing", "27 passed, 1 failed in 1.1s", 1),
    ):
        if not gate_did_not_pass(summary, returncode):
            failures.append(f"no longer detects: {label}")
    named = next(iter(sorted(GATE_TESTS)))
    if gate_did_not_catch(f"FAILED {GATE_TEST}::{named}\n1 failed, 27 passed", 1, named):
        failures.append("reports a gate that DID catch the planted defect as unable to fail")
    for label, output, returncode in (
        ("a gate that reports everything as passing", "28 passed in 1.3s", 0),
        ("a gate that failed for an unrelated reason", f"FAILED {GATE_TEST}::test_other", 1),
    ):
        if not gate_did_not_catch(output, returncode, named):
            failures.append(f"no longer detects: {label}")
    if not GATE_PLANTS:
        failures.append("there are no defects to plant, so the gate is proved against nothing")
    # And the inventory, probe then adjudicate.
    every = "\n".join(f"{GATE_TEST}::{name}" for name in sorted(GATE_TESTS))
    if gate_inventory_problems(every):
        failures.append("reports a complete listing of the gate's tests as incomplete")
    if not gate_inventory_problems(every.split("\n", 1)[1]):
        failures.append("no longer detects: a test deleted from the gate")
    if not gate_inventory_problems(f"{every}\n{GATE_TEST}::test_undeclared"):
        failures.append("no longer detects: a test added to the gate without being declared")

    named = sorted(GATE_TESTS)[0]
    if gate_stub_problems(f"def {named}():\n    assert True\n"):
        failures.append("reports a test with an assertion in it as hollow")
    if not gate_stub_problems(f"def {named}():\n    pass\n"):
        failures.append("no longer detects: a declared test emptied to `pass`")

    # Ratchets, not equalities: they fire when a check loses its proof and never when
    # one is added. Trimming GATE_PLANTS back to a single lever reopened round 13's
    # defect verbatim with every instrument green and the printed count unmoved, and
    # WEAKENINGS is generated from the subtraction tuples, so removing a key removes
    # its own self-test with it.
    if len(GATE_PLANTS) < 4:
        failures.append(f"only {len(GATE_PLANTS)} plants: a lever this gate defends lost its proof")
    if len(REQUIRED_RULES) < REQUIRED_RULES_FLOOR:
        failures.append(
            f"only {len(REQUIRED_RULES)} required rule families: `select` is checked as a "
            "superset of this set, and `INTACT` derives its own select from it, so "
            "dropping one here shrinks the guard and its control together"
        )
    if len(GATE_TESTS) < GATE_TESTS_FLOOR:
        failures.append(
            f"only {len(GATE_TESTS)} declared gate tests: removing a test removes its "
            "own declaration with it"
        )
    if len(WEAKENINGS) < WEAKENINGS_FLOOR:
        failures.append(
            f"only {len(WEAKENINGS)} weakenings: a configuration check lost its self-test"
        )
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
