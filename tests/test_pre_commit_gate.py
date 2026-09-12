"""The hooks, and whether each can actually fail.

`.pre-commit-config.yaml` is a gate, and this repository's rule is that a check which
cannot fail is not a check. Three of these hooks were configured and passed on the
inputs they were added to reject:

* `check-added-large-files` inspects only files added in the current commit, so a
  large file already tracked is never seen again. It needs ``--enforce-all``.
* `check-merge-conflict` declines to look unless a merge is in progress, so a
  committed conflict marker passes. It needs ``--assume-in-merge``.
* `gitleaks`'s stock entry is ``gitleaks git --staged``. On a fresh checkout -- every
  CI run -- nothing is staged, so it reads zero bytes and passes. The second hook
  here scans history instead, which is why the CI job checks out with
  ``fetch-depth: 0``.

Reproduced before this file existed: a 2 MB binary and a file full of conflict
markers, both tracked, and every hook passed.

These tests read the configuration rather than running pre-commit, because running it
needs network to clone each hook repository and this suite must work offline.

**The limit that matters is not the one that first suggests itself.** "Upstream stops
honouring `--enforce-all`" is remote; the near risk is that this configuration can be
edited into a permanently green state with every assertion here still passing --
`gitleaks git` swapped for `gitleaks dir`, or `--maxkb` set beside `--enforce-all`,
both of which leave the flag spelled correctly and the hook blind. Several assertions
below exist for exactly those shapes, and they were written after a review demonstrated
each one against the real hooks.

What closes the rest is in CI, not here: the `pre-commit` job plants one defect per
hook in a scratch repository and requires `pre-commit` to reject them. That job has
network and already runs the hooks, so it is the cheap place to prove effect rather
than presence. `test_the_hooks_are_proved_to_catch_not_merely_to_be_configured` is what
stops that step being quietly deleted.

These assertions match strings in a shell script, which is a weaker instrument than it
looks -- two earlier attempts matched substrings that survived the very mutation they
were written for. Each one is pinned to the exact token its mutation removes, and the
real proof is the step itself: blinding the history scan makes it fail, measured rather
than argued.
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / ".pre-commit-config.yaml"
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"

#: The history scan's command, in full. Asserted exactly rather than by what it must
#: not contain -- see `test_something_scans_history_and_not_only_the_staged_index`.
HISTORY_SCAN_ENTRY = "gitleaks git --redact --verbose"

#: The alias the CI proof step targets, and the runner it targets it with. The alias
#: is in the CONFIG, not only in the script: `pre-commit run <unknown-id>` exits 1 just
#: as a caught defect does, so deleting this line made the proof report three hooks
#: catching while none ran.
HISTORY_SCAN_ALIAS = "gitleaks-history"
PINNED_RUNNER = "uvx pre-commit@"

#: The script CI runs to prove each hook catches, and that CI also runs against
#: broken configurations to prove the script still notices.
PROVER = "scripts/prove-hooks-catch.sh"

#: The tool-configuration check, which runs from `just check` rather than from pytest
#: because one of the weakenings it catches switches the suite off.
TOOL_CONFIG_CHECK = "scripts/check-tool-config.py"
PYPROJECT = ROOT / "pyproject.toml"


def _shell(step: dict[str, Any]) -> str:
    """A step's `run:` with its comment lines removed.

    Every assertion below looks for a command inside a shell body, and a `#` line
    explaining why that command is there satisfies a substring check for it just as
    well. Measured: replacing `sed '/--assume-in-merge/d'` with a sed that matches
    nothing left this file green, because the comment above it still said
    `--assume-in-merge`. A guard defeated by its own rationale.
    """
    return "\n".join(
        line for line in str(step.get("run", "")).splitlines() if not line.lstrip().startswith("#")
    )


def _config() -> dict[str, Any]:
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


def _hooks() -> list[dict[str, Any]]:
    return [hook for repo in _config()["repos"] for hook in repo["hooks"]]


def _hook(hook_id: str) -> dict[str, Any]:
    found = [h for h in _hooks() if h["id"] == hook_id]
    assert found, f"no {hook_id!r} hook is configured; {[h['id'] for h in _hooks()]}"
    return found[0]


def test_the_config_parses_and_has_hooks() -> None:
    """The control. Every test below reads this, and a config that parsed to nothing
    would make all of them vacuously true."""
    ids = [h["id"] for h in _hooks()]
    assert len(ids) >= 10, ids
    # Named, not counted: a threshold below the current set lets hooks be deleted
    # quietly, and `check-yaml` was asserted by nothing at all.
    for required in ("check-yaml", "check-toml", "trailing-whitespace", "end-of-file-fixer"):
        assert required in ids, f"{required} is gone and nothing else here would notice"


def test_large_file_check_looks_at_every_file_not_just_the_new_ones() -> None:
    """Without `--enforce-all` a 2 MB binary already tracked passes forever."""
    args = _hook("check-added-large-files").get("args", [])
    assert "--enforce-all" in args
    # `--maxkb=100000` beside it passes a 2 MB file while the flag is still spelled
    # right, so presence of the flag is not the property.
    assert not [a for a in args if a.startswith("--maxkb")], (
        f"a size limit is set beside --enforce-all, which is how it stops catching: {args}"
    )


def test_merge_conflict_check_looks_outside_an_active_merge() -> None:
    """Without `--assume-in-merge` a committed conflict marker passes forever."""
    assert "--assume-in-merge" in _hook("check-merge-conflict").get("args", [])


def test_something_scans_history_and_not_only_the_staged_index() -> None:
    """The staged hook reads zero bytes on a fresh checkout, which is every CI run.

    A secret committed and then deleted stays in history and stays extractable; the
    hook that would find it is the one that does not depend on anything being staged.
    """
    scanners = [h for h in _hooks() if h["id"] == "gitleaks"]
    assert len(scanners) == 2, f"expected a staged scan and a history scan: {scanners}"
    history = [h for h in scanners if h.get("always_run")]
    assert history, "no gitleaks hook runs unconditionally, so CI scans an empty index"
    # An EXACT entry, not a list of things it must not contain. A denylist was the
    # first attempt and it is the shape this file is about: it rejected
    # `--exit-code 0` and sailed past `--exit-code=0`, which is the same flag in the
    # spelling cobra also accepts and which makes gitleaks report the leak and exit 0
    # anyway. `--log-opts=-1` (scan one commit) and `--baseline-path` (the documented
    # way to grandfather a finding) are two more, and there is no reason to think that
    # list was ever complete. Both evasions were measured against the real hook.
    #
    # Changing this string deliberately is a one-line diff somebody can object to.
    assert history[0].get("entry") == HISTORY_SCAN_ENTRY, (
        f"the history scan's command changed: {history[0].get('entry')!r}. If that is "
        "deliberate, update HISTORY_SCAN_ENTRY and say why -- a flag added here can "
        "make it report a leak and pass anyway."
    )
    assert history[0].get("alias") == HISTORY_SCAN_ALIAS, (
        f"the history scan's alias changed to {history[0].get('alias')!r}. CI runs this "
        "hook by that name, and `pre-commit run` on a name that does not exist exits 1 "
        "exactly as a caught defect does."
    )
    assert history[0].get("pass_filenames") is False, (
        "a history scan handed a file list is scanning the worktree, not the history"
    )


def test_the_lint_hook_is_not_the_deprecated_alias() -> None:
    """`ruff` still resolves and prints `ruff (legacy alias)` on every run."""
    ids = [h["id"] for h in _hooks()]
    assert "ruff-check" in ids, ids
    assert "ruff" not in ids, "the deprecated alias is back; it is spelled ruff-check"


def test_the_hook_and_the_project_agree_on_one_ruff_version() -> None:
    """Two versions of a formatter is a CI failure nobody can reproduce locally.

    They were five minors apart: the hook pinned v0.11.12 while the project resolved
    0.16.6, so `pre-commit` and `just lint` were free to format differently.
    """
    pinned = [repo["rev"] for repo in _config()["repos"] if "ruff-pre-commit" in repo["repo"]]
    assert len(pinned) == 1, pinned
    hook_version = pinned[0].lstrip("v")

    dev = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["dependency-groups"]["dev"]
    ruff = [spec for spec in dev if spec.startswith("ruff")]
    assert ruff == [f"ruff=={hook_version}"], (
        f"the hook pins {hook_version} and the dev group says {ruff}; one exact "
        "version, or the two can drift into different formatters"
    )


def _pre_commit_job() -> tuple[str, dict[str, Any]]:
    """The job that actually invokes the hooks, by what it runs rather than its name."""
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    for name, job in workflow["jobs"].items():
        if any("pre-commit" in str(step.get("run", "")) for step in job.get("steps", [])):
            return name, job
    raise AssertionError(f"no job runs pre-commit; jobs are {sorted(workflow['jobs'])}")


def test_ci_invokes_the_hooks_rather_than_mentioning_them() -> None:
    """`run: echo 'pre-commit skipped'` satisfied the substring this used to look for.

    So did `uv tool install pre-commit`, which installs it and never runs it. The
    check has to be that something executes `pre-commit run`.
    """
    _, job = _pre_commit_job()
    # Against THIS repository. The proof step below also runs `pre-commit run`, but
    # inside a scratch repo it creates -- so a filter that merely looks for the
    # command passes on a tree where the real invocation has been replaced by an
    # echo and nothing checks this repository at all.
    # THE WHOLE INVOCATION, not a substring of it and not a denylist of swallows.
    #
    # This is the only step that ever looks at this repository's tree -- the prover
    # and its self-tests both work inside a scratch directory and cannot see it. It
    # was guarded by "contains the pinned runner, and contains none of `|| true`,
    # `|| :`, `; true`, `|| exit 0`", and three one-line edits walked past that with
    # all sixteen tests green:
    #
    #   - dropping `--all-files`, which makes `pre-commit` scan the staged diff. On a
    #     clean checkout that is nothing, so nine of ten hooks report Skipped and the
    #     step exits 0. That is section 2.4 in one word: a check handed nothing.
    #   - `|| echo skipped`, which is not in the list -- and `|| echo` is named as a
    #     prior defeat in this function's own docstring two screens down.
    #   - naming a single hook id, so one hook runs and the rest never do.
    #
    # A denylist has to guess the next spelling. `fullmatch` does not: anything
    # appended, removed or substituted fails it.
    scan = re.compile(r"uvx pre-commit@[\d.]+ run --all-files --show-diff-on-failure")
    here = [r for r in (_shell(s).strip() for s in job["steps"]) if scan.fullmatch(r)]
    assert here, (
        "no step runs the pinned `pre-commit ... --all-files` against this repository, "
        "so nothing scans the tree this gate exists to gate. The job's run steps are "
        f"{[str(s.get('run', ''))[:70] for s in job['steps'] if s.get('run')]}"
    )


def test_the_pre_commit_job_is_not_disabled_or_tolerated() -> None:
    """`if: false` and `continue-on-error: true` are how a job goes green unrun.

    Both are measured elsewhere in this org: org AGENTS.md 8.1 records a sibling
    repository whose aggregator passed with the typechecker never having run. Neither
    leaves a trace in the job's steps, so nothing above notices them, and
    `continue-on-error` survives even a correct aggregator because the job still
    reports success.
    """
    name, job = _pre_commit_job()
    assert "if" not in job, f"the {name} job is conditional: if: {job.get('if')!r}"
    assert not job.get("continue-on-error"), (
        f"the {name} job tolerates its own failure, so it cannot fail the build"
    )
    for step in job["steps"]:
        assert not step.get("continue-on-error"), (
            f"a step in {name} tolerates its own failure: {step.get('name') or step.get('run')}"
        )
        # Step-level `if` is the gap the job-level assertion above leaves open:
        # `if: github.event_name == 'push'` on the run step means the hooks never run
        # on a pull request, and the job still reports success.
        assert "if" not in step, (
            f"a step in {name} is conditional, so it can skip while the job passes: "
            f"{step.get('name') or step.get('run')} -- if: {step.get('if')!r}"
        )


def test_the_hooks_are_proved_to_catch_not_merely_to_be_configured() -> None:
    """The assertions in this file read configuration, which pins presence not effect.

    `gitleaks git` swapped for `gitleaks dir`, or `--maxkb` beside `--enforce-all`,
    leaves every other test here green and the hook blind. CI has network and runs the
    hooks, so the proving happens there.

    What this can honestly assert about a shell script is that it is INVOKED, and that
    something checks it still works. Four review rounds defeated substring guesses at
    its semantics one spelling at a time -- a deleted `exit 1` under an `::error::`
    that fails nothing, an accumulator that stopped being incremented, `|| echo` where
    `|| true` was rejected, `set +e` above the loop. Each left a blind hook reported as
    catching, with every assertion here green.

    So the prover lives in a script, and CI runs it against the real configuration and
    then against configurations broken in ways it is required to notice -- each aimed
    at a different hook, because two doctorings of the same hook are one doctoring
    twice. Weakening the prover fails there, whatever the spelling. The doctorings
    asserted below are the list; this sentence deliberately does not count them.
    """
    _, job = _pre_commit_job()
    runs = [_shell(step) for step in job["steps"]]

    assert (ROOT / PROVER).is_file(), f"{PROVER} is referenced by CI and not in the tree"

    self_tests = [r for r in runs if PROVER in r and "::error::the prover passed" in r]
    # The real configuration, in a step that is not one of the self-tests. `any(PROVER
    # in r)` was satisfied by the self-test step alone, so deleting the invocation that
    # proves THIS repository's hooks catch -- the only one that gates anything -- left
    # all sixteen tests green. Measured.
    real = [r for r in runs if PROVER in r and r not in self_tests]
    assert real, (
        f"every CI step running {PROVER} is a self-test against a doctored config; "
        "nothing proves this repository's own hooks catch anything"
    )
    # THE WHOLE INVOCATION, as with the repo scan above. This was `f"{PROVER}
    # {CONFIG.name}" in r`, and appending `|| true` to it left the step reporting
    # success over a config the self-test one line below declares unacceptable --
    # with all nineteen assertions green, because the self-test invokes the prover
    # inside an `if`, so the whole prove-the-prover apparatus stayed happy while the
    # one invocation that adjudicates THIS repository's hooks adjudicated nothing.
    # `|| echo` is named as a prior defeat in this function's docstring; it was
    # closed for one step and not the other.
    invocation = re.compile(
        rf"\./{re.escape(PROVER)} {re.escape(CONFIG.name)} {re.escape(PYPROJECT.name)} "
        rf"uvx pre-commit@[\d.]+"
    )
    assert any(invocation.fullmatch(r.strip()) for r in real), (
        f"{PROVER} is never run against {CONFIG.name} as a bare, pinned command: "
        f"{[r.strip() for r in real]}"
    )
    assert self_tests, (
        "nothing runs the prover against a broken configuration and requires it to "
        "fail, so the prover could stop proving anything and no one would know"
    )
    broken = self_tests[0]
    # Each self-test must END IN `exit 1`. The step runs under `set -euo pipefail` and
    # each block is `if <prover>; then echo "::error::..."; exit 1; fi` -- delete the
    # `exit 1` and `echo` returns 0, so the step passes over a prover that accepted a
    # configuration it must reject. That is the defect this function's own docstring
    # names as a prior defeat, closed for the prover script and left open for the step
    # that proves it. (`|| true` on the invocation is not the hole: it inverts the `if`
    # and makes CI permanently red.)
    assert broken.count("exit 1") >= 4, (
        "a prover self-test prints `::error::` and does not fail the step, so that "
        f"doctoring proves nothing: {broken.count('exit 1')} of 4 end in `exit 1`"
    )
    # WHICH ARGUMENT IS DOCTORED. Three of these hand the prover a doctored pre-commit
    # config and the real `pyproject.toml`; the fourth is the other way round. Swapping
    # the fourth's two positionals leaves it passing the real config twice, which the
    # prover rejects for the wrong reason and every assertion here still allows.
    doctored_hooks = len(
        re.findall(rf'\./{re.escape(PROVER)} "\$doctored" {re.escape(PYPROJECT.name)} ', broken)
    )
    doctored_project = len(
        re.findall(rf'\./{re.escape(PROVER)} {re.escape(CONFIG.name)} "\$doctored" ', broken)
    )
    assert doctored_hooks >= 3 and doctored_project >= 1, (
        "the self-tests do not doctor both configurations the prover reads: "
        f"{doctored_hooks} doctor the hooks, {doctored_project} doctor the project"
    )
    for doctoring, what in (
        ("alias: gitleaks-history", "a hook that does not exist"),
        ("gitleaks dir", "a blind history scan"),
        # A THIRD, aimed at a different hook. The first two both break
        # `gitleaks-history`, so they are one doctoring twice: neither notices the
        # prover's own subject list being trimmed, and trimming it to one hook left
        # this file at sixteen passed with both self-tests still exiting 1.
        # `check-merge-conflict` returns 0 without looking when the repository is not
        # mid-merge, so deleting `--assume-in-merge` blinds it in every CI run.
        ("assume-in-merge", "a merge-conflict check that returns before it looks"),
        # A FOURTH, aimed at the project configuration rather than the hook
        # configuration. The prover reads `[tool.ruff]` only because it copies
        # `pyproject.toml` into its scratch repository, and deleting that one line left
        # every hook still catching with all three doctorings above still failing --
        # they all doctor the other file.
        ("select = []", "a ruff configuration that enforces nothing"),
    ):
        assert doctoring in broken, f"the prover is never tested against {what}"


def test_the_pre_commit_job_fetches_the_history_it_scans() -> None:
    """`fetch-depth: 0`, or the history hook is handed one commit and passes.

    This is the line that makes the history scan mean anything, and it is in a
    different file from the hook that needs it -- which is exactly how it would be
    dropped by someone tidying the workflow.
    """
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    job = next(
        job
        for job in workflow["jobs"].values()
        if any("pre-commit" in str(step.get("run", "")) for step in job.get("steps", []))
    )
    checkout = [s for s in job["steps"] if "actions/checkout" in str(s.get("uses", ""))]
    assert checkout, "the pre-commit job does not check out the repository"
    # EVERY checkout in this job, not the first. The key allowlist one test down says
    # a checkout may carry nothing but `fetch-depth`; it says nothing about the value,
    # and nothing at all about a checkout carrying no `with:`. So a second, bare
    # checkout here satisfied both -- and `git fetch --depth=1` truncates an
    # already-complete clone (measured: 5 commits down to 1, `shallow` file present),
    # so the history hook this line exists for scans one commit and passes forever.
    for step in checkout:
        assert step.get("with", {}).get("fetch-depth") == 0, (
            "a checkout in the pre-commit job is shallow, so the history scan sees one "
            f"commit: with: {step.get('with')!r}"
        )
    # And NOTHING ELSE. `fetch-depth` was the only option anyone thought to pin, so
    # one line beside it -- `sparse-checkout: scripts` -- left thirteen of seventy-two
    # tracked paths on disk and every assertion here green. Cone mode keeps root-level
    # files, so the config, the justfile and the prover all survived and every step
    # still passed, over a tree with no `slicelab/` and no `tests/` in it. This is the
    # effect the top-level `exclude:` test exists for, reached from the other file.
    assert set(checkout[0].get("with", {})) == {"fetch-depth"}, (
        "the checkout takes options beyond `fetch-depth`, and what is checked out "
        "decides what the gate is allowed to see: "
        f"with: {checkout[0].get('with')!r}"
    )


def test_the_aggregator_fails_when_pre_commit_does() -> None:
    """`needs:` makes `ok` WAIT; the `if` is what makes it count.

    This asserted only membership in `needs:` once, and passed on a tree where
    `pre-commit` was in `needs:` and absent from the failure condition -- so `ok`
    reported success beside a red hook, which is the hole org AGENTS.md 8.1 spells
    out and the one this whole change exists to close.

    Every job in `needs:` must be named in the condition, so the two are compared
    rather than `pre-commit` being special-cased: adding a fourth job and forgetting
    it is the same defect again.
    """
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    ok = workflow["jobs"]["ok"]
    gate = [s for s in ok["steps"] if "!= 'success'" in str(s.get("if", ""))]
    assert gate, "`ok` has no step that fails on an upstream job's result"
    condition = str(gate[0]["if"])

    # EVERY job in the workflow, not every job in `needs:`. Comparing the condition
    # against `needs:` is symmetric in the wrong direction -- it catches a job that is
    # waited for and not required, and says nothing about one that is neither. Both
    # measured green before this line: deleting `pre-commit` from `needs:` AND from
    # the condition restored verbatim the defect this change was written to fix, and
    # adding a fourth job whose only step is `exit 1` left `ok` green beside it. Org
    # AGENTS.md 8.1 says every OTHER job, and that is what this now reads.
    assert set(ok["needs"]) == set(workflow["jobs"]) - {"ok"}, (
        "`ok` does not wait for every job: "
        f"{sorted(set(workflow['jobs']) - {'ok'} - set(ok['needs']))} feed nothing, and "
        f"{sorted(set(ok['needs']) - set(workflow['jobs']))} are waited for and do not exist"
    )
    # Whole names, and the CLAUSE SHAPE around each one. `test` occurs inside
    # `test-windows`, so a condition naming only the latter satisfies a substring check
    # for both -- and extracting bare names let one clause be rewritten to
    # `== 'failure'`, which keeps the name present and stops counting `skipped` and
    # `cancelled` for that job. Both are what section 8.1 is about.
    named = set(re.findall(r"needs(?:\.|\[')([A-Za-z0-9_-]+)'?\]?\.result != 'success'", condition))
    missing = sorted(set(ok["needs"]) - named)
    assert missing == [], (
        f"`ok` waits for {missing} and does not require each to SUCCEED; a job absent "
        "from the condition -- or named in a clause that only counts `failure` -- can "
        f"be red, skipped or cancelled while ok is green: if: {condition!r}"
    )
    # And the step has to DO something about it. Changing `run: exit 1` to an echo
    # leaves the condition correct, this test green, and `ok` passing with every
    # upstream job red -- the same defect one line further down.
    assert gate[0].get("run", "").strip() == "exit 1", (
        f"the gate step does not fail the job: run: {gate[0].get('run')!r}"
    )
    assert ok.get("if") == "always()", (
        "`ok` must run even when an upstream job fails, or the gate step never runs "
        f"and the aggregator is skipped rather than red: if: {ok.get('if')!r}"
    )
    assert not ok.get("continue-on-error"), "`ok` tolerates its own failure"
    # And its STEPS. The job-level checks above were the ones this file learned to
    # make for `pre-commit`, and `ok` -- the job branch protection actually requires
    # -- did not get them. Both of these leave the condition correct and the gate
    # inert: `continue-on-error` on the gate step makes the step fail and the job
    # pass, and an extra clause like `&& github.event_name == 'push'` skips it on
    # every pull request.
    for step in ok["steps"]:
        assert not step.get("continue-on-error"), (
            f"a step in `ok` tolerates its own failure: {step.get('name') or step.get('run')}"
        )
    # `||`, not `&&`. Every clause is "this job did not succeed", so joining them with
    # `&&` means one green job makes the whole condition false, the gate step is
    # skipped, and `ok` passes with the others red. One character, and every other
    # assertion here still holds.
    assert "&&" not in condition, (
        "the gate's clauses are joined with `&&`, so it fires only when EVERY upstream "
        f"job failed: if: {condition!r}"
    )
    assert not set(re.findall(r"\b(github|env|inputs|vars)\.", condition)), (
        "the gate is conditional on something other than the upstream results, so it "
        f"can be skipped while those results are red: if: {condition!r}"
    )


def test_no_upstream_job_tolerates_its_own_failure() -> None:
    """`continue-on-error` on any job `ok` waits for makes that job report success.

    The condition compares `needs.<job>.result`, and a tolerated failure sets that to
    `success`. So the aggregator is correct, the test above passes, and the job was
    red. Org AGENTS.md 8.1 names this; it applies to every job in `needs:`, not only
    to the one this change added.
    """
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    tolerant = [
        name
        for name in workflow["jobs"]["ok"]["needs"]
        if workflow["jobs"][name].get("continue-on-error")
    ]
    assert tolerant == [], f"{tolerant} report success whatever happens in them"

    # And at STEP level, for every one of them. The job-level check above was written
    # for `pre-commit` and applied only there, so `continue-on-error` or `if: false` on
    # `- run: just check` left the job green with no typechecker -- which is verbatim
    # the incident org AGENTS.md 8.1 cites.
    for name in workflow["jobs"]["ok"]["needs"]:
        for step in workflow["jobs"][name].get("steps", []):
            label = step.get("name") or step.get("run") or step.get("uses")
            assert not step.get("continue-on-error"), (
                f"a step in `{name}` tolerates its own failure: {label}"
            )
            assert "if" not in step, (
                f"a step in `{name}` is conditional, so it can skip while the job "
                f"passes: {label} -- if: {step.get('if')!r}"
            )


def test_no_top_level_filter_hides_the_tree_from_every_hook() -> None:
    """One line above `repos:` blinds every file-based hook at once.

        exclude: ^(slicelab|tests|docs|notes|scripts)/

    leaves this file at sixteen passed, the prover at exit 0, and both CI self-tests
    still failing their doctored configs -- while a committed 2 MB binary and a
    committed conflict marker both scan clean. The proof apparatus cannot see it
    because the prover plants its defects in a scratch repository; the plants now sit
    under the same directory names this excludes, which closes the hook-level spelling
    by effect. This closes the top-level one by shape, which no plant can reach.
    """
    config = _config()
    for key in ("exclude", "files"):
        assert key not in config, (
            f"a top-level `{key}:` decides what EVERY file-based hook is allowed to "
            f"see, so one line disables the whole gate: {key}: {config[key]!r}"
        )


def test_no_gating_job_carries_an_environment_that_can_disable_a_hook() -> None:
    """`SKIP` is pre-commit's own documented off switch, and it is one line of YAML.

        env:
          SKIP: trailing-whitespace,end-of-file-fixer,check-yaml,check-toml

    on the job left every assertion here green and those four hooks unrun, back when
    the prover planted for three hooks of ten and the rest could go quiet. It now
    plants for all of them and inherits the job's environment, so a `SKIP` naming any
    configured hook also fails the prover -- but that is the prover's answer, arriving
    after a scratch repository and ten hook runs. This is the cheap one, and it is an
    allowlist rather than a check for `SKIP`, because the next off switch will have a
    different name: adding an `env:` here means adding it in a diff someone can object
    to.
    """
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    # WORKFLOW level first. Every `workflow[...]` access in this file was
    # `workflow["jobs"]`, so a top-level `env:` -- which every job inherits -- sat one
    # scope above everything that looked. Measured: `SKIP:` there reported six of ten
    # hooks Skipped and the job exited 0, and the prover and every self-test noticed
    # nothing, because the six were not among the three it then planted for.
    # `defaults:` is the same class of inherited override and is refused with it.
    for key in ("env", "defaults"):
        assert key not in workflow, (
            f"a workflow-level `{key}:` is inherited by every job, so one line there "
            f"reaches inside all of them: {key}: {workflow[key]!r}"
        )
    # `ok` ITSELF, not only the jobs it waits for. The loop was written for the jobs
    # that do the work, and the aggregator -- the job branch protection requires -- was
    # not in its own `needs:`.
    for name in [*workflow["jobs"]["ok"]["needs"], "ok"]:
        job = workflow["jobs"][name]
        # `defaults:` at job level is what `defaults:` at workflow level was refused
        # for: `defaults.run.shell` is a command template in which `{0}` is the
        # generated script, so `shell: cat {0}` prints the step and runs none of it at
        # exit 0. The workflow-level loop refused it; the job-level loop refused only
        # `env`.
        for key in ("env", "defaults"):
            assert key not in job, (
                f"the `{name}` job sets `{key}:`, which reaches inside every step "
                f"in it: {key}: {job[key]!r}"
            )
        for step in job.get("steps", []):
            for key in ("env", "shell"):
                assert key not in step, (
                    f"a step in `{name}` sets `{key}:`: "
                    f"{step.get('name') or step.get('run')} -- {key}: {step[key]!r}"
                )
            # And the same lever with a different syntax. The allowlist above is over
            # the YAML key, and a plain `run:` writing to `$GITHUB_ENV` sets the
            # environment for every later step in the job without ever using it.
            # `PYTEST_ADDOPTS=--co` there makes `just test` collect 356 tests, run
            # none and exit 0. The `pre-commit` job has a backstop -- a `SKIP` written
            # this way is inherited by the prover, whose adjudication then fires --
            # and `check` and `test` have none.
            # Both of GitHub's environment files, not just the one. `$GITHUB_PATH`
            # has the same reach -- every later step in the job -- and putting a shim
            # ahead of `just` on PATH makes the pinned `- run: just test` exit 0 having
            # run nothing. It is not a hypothetical spelling here: this repository's
            # own engine workflow writes to it twice, so it reads as established
            # practice rather than as an attack.
            for lever in ("GITHUB_ENV", "GITHUB_PATH"):
                assert lever not in _shell(step), (
                    f"a step in `{name}` writes to `${lever}`, which reaches every "
                    f"later step: {step.get('name') or step.get('run')}"
                )
            # EVERY checkout, not the first one of the `pre-commit` job. What is
            # checked out decides what all of this adjudicates, and `ref:` is a
            # documented `actions/checkout` input -- one line points `just check`,
            # `just test` and the configuration check at a commit the pull request does
            # not contain. The existing guard reads `checkout[0]` of one job, so a
            # SECOND checkout inside that same job walks past it: a re-clone into the
            # workspace (`clean` defaults true) leaves the hooks and the prover
            # adjudicating main's tree.
            #
            # `<=`, not `==`: the `check` and `test` checkouts legitimately carry no
            # `with:` at all.
            if "actions/checkout" in str(step.get("uses", "")):
                assert set(step.get("with", {})) <= {"fetch-depth"}, (
                    f"a checkout in `{name}` takes options beyond `fetch-depth`, and "
                    f"what is checked out decides what the gate sees: "
                    f"with: {step.get('with')!r}"
                )
            # And no local action. `.github` is a whole allowed segment in the root
            # allowlist, and a composite action's own steps take `env:` and `shell:` --
            # both refused here -- and can write those environment files. Factoring the
            # repeated checkout/setup preamble into `./.github/actions/prep` is an
            # ordinary refactor, and it moves every lever into a file no assertion here
            # reads. This is the justfile `import` finding, one directory over.
            assert not str(step.get("uses", "")).startswith("./"), (
                f"a step in `{name}` runs a local action, whose own steps carry keys "
                f"that are refused here: uses: {step['uses']!r}"
            )


@pytest.mark.parametrize("hook_id", ["trailing-whitespace", "end-of-file-fixer", "check-toml"])
def test_the_hooks_that_were_already_right_are_still_there(hook_id: str) -> None:
    """Correcting three of them is not a licence to lose the rest."""
    assert _hook(hook_id)


def test_the_local_recipe_runs_the_version_ci_runs() -> None:
    """`just hooks` and CI must resolve the same hooks.

    CI pins the runner because an unpinned one can change how hooks resolve with no
    diff in this repository. The same applies to the recipe a developer runs before
    pushing: an unpinned local runner means the tree can pass here and fail there, or
    the reverse, with nothing in the diff to explain it. This is the divergence
    `test_the_hook_and_the_project_agree_on_one_ruff_version` prevents one layer down.
    """
    recipe = [
        line.strip()
        for line in (ROOT / "justfile").read_text(encoding="utf-8").splitlines()
        if "pre-commit" in line and not line.lstrip().startswith("#")
    ]
    assert recipe, "no justfile recipe runs the hooks"
    # AND THE INTERPRETER THE BODIES ARE HANDED TO. Every recipe body in this file is
    # pinned and the shell running them was not:
    #
    #     set shell := ["bash", "-c", "true;"]
    #
    # makes `just` echo each line and run none of it -- the body arrives as `$0`. All
    # three commands CI runs go to exit 0 with ruff, mypy, the config check and every
    # test never executing. The working idiom, `["bash", "-euo", "pipefail", "-c"]`,
    # differs from that only in argument order, so an allowlist of absence is the
    # honest instrument: adding a setting means adding it here.
    settings = [
        line.strip()
        for line in (ROOT / "justfile").read_text(encoding="utf-8").splitlines()
        # `\s`, not a literal space. `just` accepts a TAB in that position, and
        # `set\tshell := ["bash", "-c", "true;"]` was invisible to this allowlist --
        # every recipe body echoed and none run, both CI steps at exit 0, nothing in
        # the repository red. One character, reaching the exact defect the assertion
        # below describes. The `import` guard three lines down already anchors this way.
        if re.match(r"set\s", line)
    ]
    # `export` is not a `set ` line, and it sets the environment of every recipe body.
    # `export PYTEST_ADDOPTS := "--ignore=tests/test_usage_exit_64.py"` dropped six
    # tests from CI with `just check` green and this file green -- the same lever the
    # workflow refuses three ways (`env:` at workflow, job and step level, and
    # `$GITHUB_ENV`), one file over.
    exports = [
        line.strip()
        for line in (ROOT / "justfile").read_text(encoding="utf-8").splitlines()
        # Same tab. `export\tPYTEST_ADDOPTS := "--ignore=..."` dropped 94 tests with
        # everything green -- `just check` only catches the spelling that targets the
        # gate file itself, because that is the one file it re-runs.
        if re.match(r"export\s", line)
    ]
    assert exports == [], f"the justfile exports into every recipe's environment: {exports}"
    # And no `import`. Both allowlists above are built from this file alone, and a just
    # `import` pulls settings in from another -- which has no `set `/`export ` prefix to
    # match, no colon for the recipe parser to see, and may live under `scripts/`, which
    # the root allowlist permits. Two lines made `just setup`, `just check` and
    # `just test` echo their bodies and run none of them, at exit 0, over a live ruff
    # error, a live type error and a failing test.
    directives = [
        line.strip()
        for line in (ROOT / "justfile").read_text(encoding="utf-8").splitlines()
        # No trailing `\s`: just accepts `import'scripts/ci.just'` with no space, which
        # slipped straight past the first version of this guard. The negative lookahead
        # keeps a recipe named `import-docs:` or `importantly:` out of it.
        if re.match(r"\s*(!include|import\??)(?![A-Za-z0-9_-])", line)
    ]
    assert directives == [], (
        "the justfile pulls in another file, whose `set` and `export` lines neither "
        f"allowlist here can see: {directives}"
    )
    assert settings == ["set dotenv-load := false"], (
        "the justfile sets an interpreter-level option, and a pinned recipe body is "
        f"only worth what the shell running it does: {settings}"
    )
    # Fullmatch, not a prefix. The CI-side twin of this learned that a round ago;
    # this one kept `startswith`, so `uvx pre-commit@4.2.0 run || true` satisfied it --
    # `--all-files` gone, so on a clean tree the hooks are handed nothing, and the
    # exit code swallowed on top.
    # The SAME version, not merely a pinned one. This function's docstring says the two
    # must resolve the same hooks and cites the ruff test, which asserts equality; this
    # one matched each side against the pattern independently, so bumping one of the
    # seven occurrences and missing the others was green -- which is the maintenance
    # case, and it also has the prover's self-tests adjudicating a different runner than
    # the one gating the tree.
    pinned = set(
        re.findall(r"uvx pre-commit@([\d.]+)", WORKFLOW.read_text(encoding="utf-8"))
    ) | set(re.findall(r"uvx pre-commit@([\d.]+)", (ROOT / "justfile").read_text(encoding="utf-8")))
    assert len(pinned) == 1, (
        f"the pre-commit runner is pinned to more than one version, so the tree can "
        f"pass locally and fail in CI with nothing in the diff to explain it: {sorted(pinned)}"
    )
    for line in recipe:
        assert re.fullmatch(r"uvx pre-commit@[\d.]+ run --all-files", line), (
            f"the local hook recipe is not the pinned invocation CI runs: {line!r}"
        )


def test_the_recipes_ci_invokes_still_run_what_they_claim() -> None:
    """CI runs `just check` and `just test`; the recipes behind them were unpinned.

    `test: uv run pytest -k "not pre_commit"` left `317 passed, 19 deselected` -- every
    assertion in this file, the entire subject of this change, stops executing in CI
    and CI stays green. `check: fmt-check` alone drops mypy and ruff the same way.

    A guard whose own runner can be edited out in one line is the shape this whole
    change is about, so it is pinned where the hook recipe already is.
    """
    lines = [
        line.rstrip()
        for line in (ROOT / "justfile").read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    ]
    recipes: dict[str, list[str]] = {}
    current: str | None = None
    for line in lines:
        if line and not line[0].isspace():
            current = line.split(":")[0].strip() if ":" in line else None
            if current is not None:
                # `just` refuses a plain duplicate but ACCEPTS a platform-attributed
                # pair and picks by host. A `[linux]` copy first and the pinned
                # `[windows]` copy second left this reading the pinned body while CI's
                # ubuntu runner ran the other one -- `just check` at exit 0 with no
                # ruff, no mypy and no configuration check, and `- run: just check`
                # still sitting in the workflow. It also mis-fires the other way round,
                # so refusing the repeat is right in both directions.
                assert current not in recipes, (
                    f"the justfile defines `{current}` twice -- `just` picks by "
                    "platform attribute and this reads the last one, so the recipe CI "
                    "runs need not be the one pinned here"
                )
                recipes[current] = [line.split(":", 1)[1].strip()]
        elif line.strip() and current is not None:
            recipes[current].append(line.strip())

    assert recipes.get("test") == ["", "uv run pytest"], (
        "the `test` recipe CI runs is not a plain, unfiltered pytest -- a `-k` or "
        f"`--ignore` deselects the gate and CI stays green: {recipes.get('test')}"
    )
    assert recipes.get("check") == ["fmt-check lint typecheck config-check"], (
        "the `check` recipe CI runs no longer depends on all four of fmt-check, lint, "
        f"typecheck and config-check: {recipes.get('check')}"
    )
    # `--locked` is the third of these, and the justfile calls it load-bearing rather
    # than tidiness: plain `uv sync` reconciles a stale lock and rewrites it at exit 0
    # with no diagnostic, so the committed lockfile is never tested.
    # AND THE CONFIGURATION THOSE RECIPES READ -- checked from OUTSIDE pytest.
    #
    # Every guard in this file gates an invocation: a recipe, a workflow step, a hook.
    # `pyproject.toml` reaches the same outcomes from a file none of them inspected.
    # `addopts = ["-ra", "--ignore=tests/test_pre_commit_gate.py"]` left 331 of 356
    # tests running -- 356 minus the assertions here. `select = []` blinded `just lint`
    # AND the `ruff-check` hook. `ignore_errors = true` silenced `just typecheck`.
    #
    # And one of them cannot be caught from in here at all: `addopts = [..., "--co"]`
    # collects the whole suite and runs none of it at exit 0, so an assertion inside
    # the suite is the thing it switches off. That check therefore lives in
    # `scripts/check-tool-config.py`, which `just check` runs and pytest cannot reach.
    # What is asserted here is that `check` still depends on it -- and the script is
    # run, so a local pytest run reports the same thing CI does.
    assert (ROOT / TOOL_CONFIG_CHECK).is_file(), f"{TOOL_CONFIG_CHECK} is gone"
    assert recipes.get("config-check") == ["", f"uv run python {TOOL_CONFIG_CHECK}"], (
        f"the recipe that checks the tool configuration is not the pinned invocation: "
        f"{recipes.get('config-check')}"
    )
    # Its TABLE checks, run in-process against this repository's real `pyproject.toml`.
    #
    # Not as a subprocess: the script now runs the gate suite itself, to catch a gate
    # that is collected and then skipped, and this file is that gate -- invoking it here
    # would recurse without end. Calling `problems()` directly asks the same question
    # about the same file and terminates. The tree half comes from `just check`, which
    # CI is required to invoke two tests down.
    checker = _checker()
    assert checker.self_test() == [], checker.self_test()
    weakened = checker.problems(tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["tool"])
    assert weakened == [], f"pyproject.toml weakens a check that is otherwise gated: {weakened}"
    # AND THE THREE `check` DEPENDS ON. `check` was pinned to name them and their
    # bodies were not, so `uv run mypy slicelab/ tests/ || true` left `just check` at
    # exit 0 over a real type error -- and no pre-commit hook runs mypy, so that recipe
    # is the only mypy invocation in the repository. Org AGENTS.md 8.1 verbatim, one
    # layer below where this change closed it. `lint` has the `ruff-check` hook as a
    # backstop in CI; `typecheck` has nothing.
    for name, body in (
        ("fmt-check", "uv run ruff format --check ."),
        ("lint", "uv run ruff check ."),
        ("typecheck", "uv run mypy slicelab/ tests/"),
    ):
        assert recipes.get(name) == ["", body], (
            f"the `{name}` recipe `just check` depends on is not {body!r}: {recipes.get(name)}"
        )
    assert recipes.get("setup") == ["", "uv sync --locked"], (
        f"the `setup` recipe CI runs no longer fails on a stale lockfile: {recipes.get('setup')}"
    )


def test_the_pull_request_trigger_keeps_no_branch_filter() -> None:
    """The workflow explains why `pull_request:` carries no `branches:` filter.

    A stacked pull request is based on its parent branch rather than on main, and
    retargeting one fires `edited`, which is not a default activity type -- so a
    `branches: [main]` filter means a retargeted PR gets no checks. That reasoning
    lives in a comment, and a comment is not a check.

    What happens downstream of "no checks ran" -- pending or green -- depends on branch
    protection, which is configured outside this repository and is not asserted here.
    The filter's absence is the part the repository owns.

    (`on:` is YAML 1.1's boolean `True` after `safe_load`, which is why this looks for
    both spellings rather than the obvious one.)
    """
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    triggers = workflow.get("on", workflow.get(True))
    assert triggers and "pull_request" in triggers, "CI does not run on pull requests"
    # NO options at all, not merely no `branches:`. `paths-ignore: ['**']` and
    # `types: [labeled]` reach the same place -- no checks ran -- and both left every
    # assertion here green. The `ok` job's own comment leans on this trigger having no
    # path filtering, so what is pinned is the whole mapping being empty.
    on_pr = triggers["pull_request"] or {}
    assert on_pr == {}, (
        "the pull_request trigger takes options, and every one of them decides which "
        f"pull requests get checked at all: pull_request: {on_pr!r}"
    )


@pytest.mark.parametrize("recipe", ["setup", "check", "test"])
def test_ci_invokes_the_recipes_this_file_pins(recipe: str) -> None:
    """Pinning what a recipe does is worth nothing if nothing runs it.

    The test above asserts `test` is a plain `uv run pytest` and `check` depends on
    all three of fmt-check, lint and typecheck. Its docstring opens "CI runs
    `just check` and `just test`" -- a premise asserted nowhere. Five ways past it,
    each leaving this file green: either step replaced with an echo, either step given
    `|| true`, either step deleted, and either job removed entirely from `jobs:`,
    `needs:` and the `ok` condition together -- which keeps the needs/jobs equality
    satisfied, because the job is gone from both sides.

    Deleting the `test` job is the severe one: the whole pytest suite, this file
    included, stops running in CI while `ok` reports success. That is the org
    AGENTS.md 8.1 incident verbatim, one job over from where this change closed it.

    Bare equality rather than a substring, so `just test || true` fails it too.
    """
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    runs = [
        _shell(step).strip() for job in workflow["jobs"].values() for step in job.get("steps", [])
    ]
    assert f"just {recipe}" in runs, (
        f"no CI step runs `just {recipe}` as a bare command, so the recipe this file "
        f"pins is never invoked: {runs}"
    )


def test_every_hook_repository_is_pinned_to_an_immutable_revision() -> None:
    """`rev: v8.27.2` -> `rev: master` leaves every assertion here green.

    The workflow pins its runner because an unpinned one can change how hooks resolve
    with no diff in this repository. A `rev:` on a moving branch is the same failure
    one layer down, and worse: the hook's code changes under a green CI run with
    nothing in the history to point at.
    """
    for repo in _config()["repos"]:
        # `local` and `meta` carry no `rev` by design, and adding one is ordinary
        # maintenance. Skipping them beats a `KeyError` where the question does not
        # apply; a local hook is proved by effect like every other, because the prover
        # and the configuration must name the same set.
        if repo["repo"] in {"local", "meta"}:
            continue
        rev = str(repo["rev"])
        assert re.fullmatch(r"v?\d[\w.\-]*|[0-9a-f]{40}", rev), (
            f"{repo['repo']} is pinned to {rev!r}, which can move under a green run. "
            "Use a version tag or a full commit sha"
        )


def test_the_tool_config_check_still_rejects_a_real_file(tmp_path: Path) -> None:
    """Its self-test proves `problems()` works. Nothing proved it is still WIRED UP.

    The suite asserts the script exits 0 on this repository, and the script asserts it
    still detects sixteen weakened configurations. Between those two is one line reading
    the real file, and severing it satisfies both:

        found = problems({**tomllib.loads(...)["tool"], **INTACT})

    left `just check` at exit 0 printing its reassuring line over a `pyproject.toml`
    carrying `--co`, with `just test` collecting 357 tests and running none. (The
    blunter `found = []` is caught, but only incidentally, by ruff noticing `tomllib`
    became unused. That is luck, not a guard.)

    So: hand the script a directory whose `pyproject.toml` is weakened and require it
    to say so. `PYPROJECT` is derived from the script's own location, which is what
    makes this possible without a flag the script could be made to ignore.

    Asserted on the DIAGNOSTIC, not only the exit code -- the bypass above can still
    exit 1 for an unrelated reason, and `addopts` appearing in the message is what says
    the real file was read.
    """
    sandbox = tmp_path / "scripts"
    sandbox.mkdir()
    (sandbox / "check-tool-config.py").write_bytes((ROOT / TOOL_CONFIG_CHECK).read_bytes())
    (tmp_path / "pyproject.toml").write_text(
        PYPROJECT.read_text(encoding="utf-8").replace(
            'addopts = ["-ra"]', 'addopts = ["-ra", "--co"]'
        ),
        encoding="utf-8",
    )
    done = subprocess.run(
        [sys.executable, str(sandbox / "check-tool-config.py")], capture_output=True, text=True
    )
    assert done.returncode == 1, (
        f"a weakened pyproject.toml was accepted: {done.stdout}{done.stderr}"
    )
    assert "addopts" in done.stderr, (
        "the check failed, but not on the weakening it was handed -- it is no longer "
        f"reading the file it reports on: {done.stderr}"
    )


def _sandbox(tmp_path: Path) -> Path:
    """A directory the tool-config check will adjudicate as if it were the repository.

    `PYPROJECT` and `ROOT` are both derived from the script's own location, so copying
    it into `<tmp>/scripts/` is what redirects it -- no flag, and nothing the script
    could be edited to ignore.
    """
    (tmp_path / "scripts").mkdir(parents=True)
    (tmp_path / "scripts" / "check-tool-config.py").write_bytes(
        (ROOT / TOOL_CONFIG_CHECK).read_bytes()
    )
    (tmp_path / "pyproject.toml").write_text(
        PYPROJECT.read_text(encoding="utf-8"), encoding="utf-8"
    )
    for command in (["init", "-q", "-b", "main", "."], ["add", "-A"]):
        subprocess.run(["git", *command], cwd=tmp_path, check=True, capture_output=True)
    return tmp_path


def _adjudicate(sandbox: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(sandbox / "scripts" / "check-tool-config.py")],
        capture_output=True,
        text=True,
    )


def test_the_tool_config_check_still_rejects_a_real_tree(tmp_path: Path) -> None:
    """Its self-test proves the tree predicates work. This proves they are WIRED UP.

    Same defect as the one above, one level in: `nested_ruff_configs` and
    `gate_is_missing_from` are each exercised on inputs they must reject, and
    `tree_problems` is what hands them the real ones. Replacing either call --
    `found = []`, `if False:` -- left the script printing success and all 27 assertions
    here green, because nothing ran it against a tree it should refuse.

    Two sandboxes rather than one, and asserted on the DIAGNOSTIC, so each says which
    check fired: a tree with a nested ruff configuration and a collectable gate, and a
    tree with neither.
    """
    nested = _sandbox(tmp_path / "a")
    (nested / "slicelab").mkdir()
    (nested / "slicelab" / "ruff.toml").write_text("[lint]\nselect = []\n", encoding="utf-8")
    (nested / "tests").mkdir()
    (nested / "tests" / "test_pre_commit_gate.py").write_text(
        "def test_placeholder() -> None:\n    pass\n", encoding="utf-8"
    )
    subprocess.run(["git", "add", "-A"], cwd=nested, check=True, capture_output=True)
    done = _adjudicate(nested)
    assert done.returncode == 1, f"a second ruff configuration was accepted: {done.stdout}"
    assert "second ruff configuration" in done.stderr, (
        f"the nested ruff configuration was not the finding: {done.stderr}"
    )

    quarantined = _sandbox(tmp_path / "c")
    (quarantined / "tests").mkdir()
    (quarantined / "tests" / "test_pre_commit_gate.py").write_text(
        "def test_placeholder() -> None:\n    pass\n", encoding="utf-8"
    )
    (quarantined / "tests" / "conftest.py").write_text(
        "import pytest\n\n\n"
        "def pytest_collection_modifyitems(config, items):\n"
        "    for item in items:\n"
        '        item.add_marker(pytest.mark.skip(reason="quarantined"))\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "-A"], cwd=quarantined, check=True, capture_output=True)
    done = _adjudicate(quarantined)
    assert done.returncode == 1, f"a quarantined gate was accepted: {done.stdout}"
    assert "does not run and pass" in done.stderr, (
        f"the gate being collected and then skipped was not the finding: {done.stderr}"
    )
    assert "is not collected" not in done.stderr, (
        f"this gate IS collected -- it is skipped, which is a different thing: {done.stderr}"
    )

    uncollected = _sandbox(tmp_path / "b")
    done = _adjudicate(uncollected)
    assert done.returncode == 1, f"a tree with no collectable gate was accepted: {done.stdout}"
    assert "is not collected" in done.stderr, f"the missing gate was not the finding: {done.stderr}"
    assert "second ruff configuration" not in done.stderr, (
        f"this tree has no nested ruff configuration and one was reported: {done.stderr}"
    )


def _checker() -> Any:
    """The tool-configuration check, loaded as a module.

    Not as a subprocess: it runs the gate suite, and this file is that gate.
    """
    spec = importlib.util.spec_from_file_location("check_tool_config", ROOT / TOOL_CONFIG_CHECK)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


#: A workflow carrying every string the check's plants doctor, none of them yet broken.
_REPLICA_WORKFLOW = """\
name: CI
on:
  pull_request:
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - run: just check
  ok:
    runs-on: ubuntu-latest
    needs: [check]
    if: always()
    steps:
      - name: Fail unless every upstream job succeeded
        if: needs.check.result != 'success'
        run: exit 1
"""

#: The three assertions the check's plants require, and a stub for every other name the
#: inventory declares. A stand-in rather than a copy of this file: a copy would build
#: its own replica, without end.
_REPLICA_GATE_HEAD = """\
from pathlib import Path

import yaml

WORKFLOW = Path(__file__).resolve().parent.parent / ".github/workflows/ci.yml"


def _jobs():
    return yaml.safe_load(WORKFLOW.read_text())["jobs"]


def test_no_upstream_job_tolerates_its_own_failure() -> None:
    for name, job in _jobs().items():
        assert not job.get("continue-on-error"), name
        for step in job.get("steps", []):
            assert not step.get("continue-on-error"), f"{name}: {step}"


def test_the_aggregator_fails_when_pre_commit_does() -> None:
    gate = [s for s in _jobs()["ok"]["steps"] if "result" in str(s.get("if", ""))]
    assert gate, "no gate step"
    assert gate[0].get("run", "").strip() == "exit 1", gate[0]
"""

#: Four lines that make every assertion in a gate file inert while the run reports
#: everything passing at exit 0. `pytest_runtest_makereport` rewrites the outcome before
#: the session counts it, so neither the summary nor the exit code registers a failure.
_A_GATE_THAT_CANNOT_FAIL = """\
import pytest


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item, call):
    report = yield
    report.outcome = "passed"
    report.longrepr = None
    return report
"""


def _replica_sandbox(
    tmp_path: Path, conftest: str | None, *, stub_body: str = "assert _jobs()", drop: str = ""
) -> Path:
    sandbox = _sandbox(tmp_path)
    (sandbox / ".github" / "workflows").mkdir(parents=True)
    (sandbox / ".github" / "workflows" / "ci.yml").write_text(_REPLICA_WORKFLOW, encoding="utf-8")
    (sandbox / "tests").mkdir()
    implemented = {
        "test_no_upstream_job_tolerates_its_own_failure",
        "test_the_aggregator_fails_when_pre_commit_does",
    }
    stubs = "".join(
        # An assertion, not `pass`: the check refuses a declared test with nothing in
        # it that can fail, and this stand-in has to satisfy the same rule the real
        # gate does.
        f"\n\ndef {name}() -> None:\n    {stub_body}\n"
        for name in sorted(_checker().GATE_TESTS - implemented - {drop})
    )
    (sandbox / "tests" / "test_pre_commit_gate.py").write_text(
        _REPLICA_GATE_HEAD + stubs, encoding="utf-8"
    )
    if conftest is not None:
        (sandbox / "tests" / "conftest.py").write_text(conftest, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=sandbox, check=True, capture_output=True)
    return sandbox


def test_the_tool_config_check_notices_a_gate_that_cannot_fail(tmp_path: Path) -> None:
    """Everything else reads what a run REPORTS. This reads what it can still catch.

    Four lines of `pytest_runtest_makereport` rewrite the outcome before the session
    counts it, so the gate runs, collects, and reports everything passing at exit 0 over
    a workflow whose `check` job tolerates its own failure -- with ruff clean, mypy clean
    and the check printing success. `[project.entry-points.pytest11]` registers the same
    hook from an installed module, one table above anything `problems()` reads, so
    refusing it in `tests/conftest.py` would close one spelling of two.

    So the check plants defects in a replica and requires the gate to notice them by
    name -- the instrument the rest of this change already uses. What is proved here is
    that those plants are still WIRED: the predicates are self-tested one file over, and
    replacing the calls would otherwise leave everything green.
    """
    lying = _replica_sandbox(tmp_path / "d", _A_GATE_THAT_CANNOT_FAIL)
    done = _adjudicate(lying)
    assert done.returncode == 1, f"a gate that cannot fail was accepted: {done.stdout}"
    assert "does not catch" in done.stderr, (
        f"the gate being unable to fail was not the finding: {done.stderr}"
    )

    # The control. Without it this asserts only that something failed, and a check that
    # fires on every input is not a check.
    honest = _replica_sandbox(tmp_path / "e", None)
    done = _adjudicate(honest)
    assert done.returncode == 0, (
        f"a replica with nothing wrong with it was rejected: {done.stdout}{done.stderr}"
    )


def test_the_matrix_covers_every_python_this_project_claims() -> None:
    """The workflow argues at length that 3.14 "is not optional cover" and nothing pins it.

    That argument was written because a real defect existed only on 3.14 and the matrix
    stopped at 3.13, so the test for it could not fail in the gate. Reducing the matrix
    to `["3.11"]` today leaves every assertion here green -- a comment is not a check.

    Pinned against the classifiers rather than a literal list, so the two cannot drift:
    claiming support for an interpreter nothing runs on is the same defect from the
    other side.
    """
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    tested = {
        str(version)
        for job in workflow["jobs"].values()
        for version in job.get("strategy", {}).get("matrix", {}).get("python-version", [])
    }
    # Minus whatever `exclude:` drops. GitHub applies it on partial match, so one line
    # removes the 3.14 job this workflow argues at length is not optional cover, with
    # the classifiers left claiming an interpreter nothing runs on -- the drift this
    # test exists to prevent, reached from the sibling key. (`include:` is conservative
    # in the safe direction: a version added only that way fails the equality.)
    tested -= {
        str(combination["python-version"])
        for job in workflow["jobs"].values()
        for combination in job.get("strategy", {}).get("matrix", {}).get("exclude", [])
        if "python-version" in combination
    }
    claimed = {
        line.rsplit(" :: ", 1)[-1]
        for line in tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["classifiers"]
        if line.startswith("Programming Language :: Python :: 3.")
    }
    assert tested == claimed, (
        f"the test matrix and the declared interpreters disagree. Claimed and untested: "
        f"{sorted(claimed - tested)}. Tested and unclaimed: {sorted(tested - claimed)}"
    )


def test_the_tool_config_check_proves_the_inventory_and_stub_checks_are_wired(
    tmp_path: Path,
) -> None:
    """The two newest tree checks were self-tested as predicates and called by nothing.

    Three of the five tree checks have a sandbox that drives them: a nested ruff
    configuration, an uncollected gate, a quarantined one. The inventory and the stub
    check had none -- the stand-in declares every name and gives every stub a real
    assertion, so both passed in every sandbox that existed, and `self_test()` reaches
    the predicates without reaching the call.

    Severing either was measured green end to end. Without the stub call, gutting
    twenty-four of twenty-six bodies left `just check` clean over a `ci.yml` carrying a
    retargeted-PR branch filter and a shallow checkout -- both of which live tests exist
    for. Without the inventory call, deleting a test outright did the same.

    That is this change's own recurring defect: a verified predicate, wired up by a line
    nothing exercises.
    """
    incomplete = _replica_sandbox(
        tmp_path / "f", None, drop="test_the_pre_commit_job_fetches_the_history_it_scans"
    )
    done = _adjudicate(incomplete)
    assert done.returncode == 1, f"a gate missing a declared test was accepted: {done.stdout}"
    assert "no longer contains" in done.stderr, (
        f"the missing test was not the finding: {done.stderr}"
    )

    hollow = _replica_sandbox(tmp_path / "g", None, stub_body="pass")
    done = _adjudicate(hollow)
    assert done.returncode == 1, f"a gate of empty tests was accepted: {done.stdout}"
    assert "nothing in them that can fail" in done.stderr, (
        f"the emptied tests were not the finding: {done.stderr}"
    )


def test_the_tool_config_check_acts_on_its_own_self_test(tmp_path: Path) -> None:
    """The self-test's verdict reaching `main()` is the last unexercised wiring.

    `self_test()` is called in-process by the suite, so a broken predicate is caught
    while pytest runs. But the whole point of that script is to hold the checks pytest
    cannot hold, and `broken = self_test()[:0]` in `main()` costs it exactly that
    independence with everything green.

    So: a sandbox whose copy of the script has one predicate broken, which must be
    refused by the script itself rather than by anything here.
    """
    sandbox = _replica_sandbox(tmp_path / "h", None)
    script = sandbox / "scripts" / "check-tool-config.py"
    source = script.read_text(encoding="utf-8")
    blinded = source.replace('return f"{GATE_TEST}::" not in collected', "return False", 1)
    assert blinded != source, "the predicate this test blinds is no longer there"
    script.write_text(blinded, encoding="utf-8")

    done = _adjudicate(sandbox)
    assert done.returncode == 1, f"a script with a blind predicate was accepted: {done.stdout}"
    assert "no longer detects" in done.stderr, (
        f"the blinded predicate was not the finding: {done.stderr}"
    )


def test_the_prover_plants_a_defect_for_every_hook_that_is_configured() -> None:
    """Three of ten hooks were proved; the other seven were pinned for presence only.

    One hook-level line each -- `exclude:`, `files:`, `stages: [manual]`,
    `--exit-zero` -- took any of the seven out with every assertion green and the
    prover still exiting 0, because a hook the prover never names cannot fail it.

    Planting for all ten closes those four spellings at once, and this is what keeps
    the two lists equal: a hook added to the configuration with no plant is as
    invisible as one deleted from the prover, and neither shows up in a diff that only
    touches one file.
    """
    declared = {str(hook.get("alias") or hook["id"]) for hook in _hooks()}
    source = (ROOT / PROVER).read_text(encoding="utf-8")
    # EXACTLY ONE assignment. This took the first match and bash takes the last, so a
    # second `hooks='...'` line trimming the list to the four hooks the CI self-tests
    # happen to target passed everything -- which is the state planting for all ten
    # closed.
    listed = re.findall(r"^hooks='([^']*)'", source, re.MULTILINE | re.DOTALL)
    assert len(listed) == 1, (
        f"{PROVER} assigns `hooks=` {len(listed)} times; bash takes the last and this "
        "takes the first"
    )
    # And exactly one assignment of any shape. The line above counts single-quoted
    # literals, not what `$hooks` holds when the loops read it, so a command
    # substitution or a `${hooks/ruff-format/}` filtering the list down walked past it
    # -- leaving six hooks proved by presence only, which is the state planting for all
    # ten closed.
    # Anchored to the start of a LINE, not to column 0, and allowing the declaration
    # keywords. The first version of this was the tab finding one file over: an
    # indented second assignment -- which is what a convenience override looks like,
    # `if [ -n "${PROVE_FAST:-}" ]; then hooks='...'; fi` -- was counted by neither
    # this nor the literal search above, and bash takes the last one. Measured: the
    # trimmed prover then reports `ok:` over a `stages: [manual]` on a hook it no
    # longer names, and all four CI self-tests still pass because they target hooks
    # inside the trimmed list.
    # Comment lines removed first, for the reason `_shell` removes them: a rationale
    # that spells out the construction it forbids satisfies a search for that
    # construction, and the comment above has to quote `; then hooks=` to explain
    # itself.
    code = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("#"))
    assignments = re.findall(
        # Anchored to the start of a COMMAND, not of a line. The previous anchor was
        # written for an indented override and did not catch the one-line spelling of
        # that same override -- `if [ -n "${PROVE_FAST:-}" ]; then hooks='...'; fi`,
        # the example its own commit message gave. `&&`, `||` and a bare `;` reach the
        # same place.
        r"(?:^|[;&|(])[ \t]*(?:(?:then|do|else)[ \t]+)?"
        r"(?:(?:declare|typeset|readonly|export|local)[ \t]+(?:-\w+[ \t]+)*)?"
        r"hooks[ \t]*[+:]?=",
        code,
        re.MULTILINE,
    )
    assert len(assignments) == 1, (
        f"{PROVER} assigns `hooks` {len(assignments)} times in some form; bash takes the last"
    )
    proved = set(listed[0].split())
    assert proved == declared, (
        f"the prover and the configuration disagree about which hooks exist. "
        f"Configured and never proved: {sorted(declared - proved)}. "
        f"Proved and not configured: {sorted(proved - declared)}"
    )


def test_the_repository_root_holds_nothing_stray() -> None:
    """Seven zero-byte scratch files were committed by the change that added this file.

    They came from a mutation sweep and a `git add -A`, and nothing noticed:
    `check-added-large-files` has no opinion about a 0-byte file, and no test looked at
    the tree. In a change whose subject is a pre-commit gate, the gate let the author's
    own debris through.

    An allowlist rather than a pattern, because the failure was files nobody would
    think to exclude — named `1a probe-deleted`, `2c coe-on-check-job`. Adding a real
    top-level file means adding it here, in a diff someone can object to.
    """
    tracked = {
        line.split("/")[0]
        for line in subprocess.run(
            ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.splitlines()
    }
    allowed = {
        ".editorconfig",
        ".github",
        ".gitignore",
        ".pre-commit-config.yaml",
        "AGENTS.md",
        "CHANGELOG.md",
        "CONTRIBUTING.md",
        "LICENSE",
        "README.md",
        "SECURITY.md",
        "docs",
        "justfile",
        "notes",
        "pyproject.toml",
        "scripts",
        "slicelab",
        "tests",
        "uv.lock",
    }
    stray = sorted(tracked - allowed)
    assert stray == [], (
        f"{stray} are tracked at the repository root and not declared here. If one is "
        "meant to be there, add it to `allowed`; if it is debris, it should never have "
        "been committed."
    )
