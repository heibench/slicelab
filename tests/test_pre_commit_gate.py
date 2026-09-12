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

import re
import subprocess
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
        rf"\./{re.escape(PROVER)} {re.escape(CONFIG.name)} uvx pre-commit@[\d.]+"
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
    assert checkout[0].get("with", {}).get("fetch-depth") == 0, (
        "the pre-commit job uses a shallow clone, so the history scan sees one commit"
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
    for name in workflow["jobs"]["ok"]["needs"]:
        job = workflow["jobs"][name]
        assert "env" not in job, (
            f"the `{name}` job sets environment variables, which is how a hook is "
            f"turned off without touching its configuration: env: {job['env']!r}"
        )
        for step in job.get("steps", []):
            assert "env" not in step, (
                f"a step in `{name}` sets environment variables: "
                f"{step.get('name') or step.get('run')} -- env: {step['env']!r}"
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
    for line in recipe:
        assert line.startswith(PINNED_RUNNER), (
            f"the local hook recipe does not pin the runner CI pins: {line!r}"
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
                recipes[current] = [line.split(":", 1)[1].strip()]
        elif line.strip() and current is not None:
            recipes[current].append(line.strip())

    assert recipes.get("test") == ["", "uv run pytest"], (
        "the `test` recipe CI runs is not a plain, unfiltered pytest -- a `-k` or "
        f"`--ignore` deselects the gate and CI stays green: {recipes.get('test')}"
    )
    assert recipes.get("check") == ["fmt-check lint typecheck"], (
        "the `check` recipe CI runs no longer depends on all three of fmt-check, lint "
        f"and typecheck: {recipes.get('check')}"
    )
    # `--locked` is the third of these, and the justfile calls it load-bearing rather
    # than tidiness: plain `uv sync` reconciles a stale lock and rewrites it at exit 0
    # with no diagnostic, so the committed lockfile is never tested.
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


@pytest.mark.parametrize("recipe", ["check", "test"])
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
        rev = str(repo["rev"])
        assert re.fullmatch(r"v?\d[\w.\-]*|[0-9a-f]{40}", rev), (
            f"{repo['repo']} is pinned to {rev!r}, which can move under a green run. "
            "Use a version tag or a full commit sha"
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
    listed = re.search(r"^hooks='([^']*)'", source, re.MULTILINE | re.DOTALL)
    assert listed, f"{PROVER} declares no list of hooks to prove"
    proved = set(listed.group(1).split())
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
