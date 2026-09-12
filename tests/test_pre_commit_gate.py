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
PYPROJECT = ROOT / "pyproject.toml"


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
    # The pinned invocation, not a substring. `echo 'pre-commit run --all-files
    # (skipped)'` satisfied "contains pre-commit and contains run", and this
    # repository's own tree would then never be scanned while CI reported success.
    here = [
        str(step.get("run", ""))
        for step in job["steps"]
        if PINNED_RUNNER in str(step.get("run", ""))
        and " run " in str(step.get("run", ""))
        and "mktemp" not in str(step.get("run", ""))
        and not str(step.get("run", "")).strip().startswith("echo")
    ]
    # `|| true` on the one step that scans THIS repository leaves every assertion in
    # this file green and nothing scanning the tree. Same for `; true` and `|| :`.
    for step in job["steps"]:
        command = str(step.get("run", ""))
        if PINNED_RUNNER not in command:
            continue
        for swallow in ("|| true", "|| :", "; true", "|| exit 0"):
            assert swallow not in command, (
                f"a pre-commit invocation swallows its own failure with {swallow!r}: "
                f"{command.strip()[:80]}"
            )
    assert here, (
        "no step runs pre-commit against this repository; every invocation is inside "
        f"a scratch directory. The job's run steps are "
        f"{[str(s.get('run', ''))[:60] for s in job['steps'] if s.get('run')]}"
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

    `gitleaks git` swapped for `gitleaks dir`, or `--maxkb` added beside
    `--enforce-all`, leaves every other test here green and the hook blind. The CI job
    has network and already runs the hooks, so it plants one defect per hook and
    requires `pre-commit` to reject them. This asserts that step still exists, because
    deleting it would restore exactly the gap the rest of this file cannot see.
    """
    _, job = _pre_commit_job()
    proofs = [
        str(step.get("run", ""))
        for step in job["steps"]
        if "git init" in str(step.get("run", "")) and "pre-commit" in str(step.get("run", ""))
    ]
    assert proofs, "no CI step plants a defect and requires the hooks to reject it"
    script = proofs[0]
    for plant, why in (
        ("urandom", "a large file"),
        ("<<<<<<<", "a conflict marker"),
        ("AKIA", "a secret in history"),
    ):
        assert plant in script, f"the proof step plants no {why}"
    # ONE HOOK PER INVOCATION. The aggregate exit code of a single
    # `pre-commit run --all-files` proves at least one hook fired, not that each did:
    # blinding the history scan alone still exits 1 because the other two fail, and
    # the step printed success. Measured, in the step this replaced.
    for hook in ("gitleaks-history", "check-merge-conflict", "check-added-large-files"):
        assert hook in script, f"the proof step does not name {hook}"
    # TWO per-hook invocations, with the plant between them -- not "contains
    # `run \"$hook\"`". A presence check was satisfied by the probe loop alone once the
    # probe was added, so the adjudication loop could revert to one aggregate
    # `run --all-files` with every assertion here still green. That is the round-2
    # defect restored by the round-3 fix, and it is why this asserts an ordering
    # rather than another substring.
    per_hook = [i for i in range(len(script)) if script.startswith('run "$hook"', i)]
    assert len(per_hook) == 2, (
        f"expected one per-hook invocation to probe and one to adjudicate, found "
        f"{len(per_hook)}: a single one means the adjudication reads an aggregate exit "
        "code, and a blind hook hides behind the other hooks' failures"
    )
    planted = script.find("git rm -q creds.txt")
    assert planted != -1, "the proof step never commits and removes the planted secret"
    assert per_hook[0] < planted < per_hook[1], (
        "the plant does not sit between the probe and the adjudication, so one of them "
        "is running against the wrong repository state"
    )
    # PROBE BEFORE ADJUDICATING. `pre-commit run <unknown-id>` exits 1 just as a
    # caught defect does, so without a clean-repo probe, deleting one `alias:` line
    # made the step report three hooks catching while none of them ran.
    # The probe is a bare command under `set -e`. Asserting its diagnostic string was
    # not enough twice over: the `exit 1` beneath an `::error::` could be deleted (an
    # annotation fails nothing), and the accumulator it fed could stop being
    # incremented -- each leaving the message in place and a missing hook counted as a
    # catch. What is asserted now is the shell's own strictness, which has nothing to
    # forget.
    assert "set -euo pipefail" in script, (
        "the proof step does not abort on the first failing command, so a probe "
        "failure can be printed and then ignored"
    )
    assert "does not resolve or did not pass on a clean repository" in script or (
        "did not resolve or did not pass on a clean repository" in script
    ), "the proof step does not explain a probe failure"
    # And it must act on the tally. `exit 1` alone is not the property: the key-length
    # guard also exits 1, so that substring survives deleting the check that matters.
    assert 'test "$failures" -eq 0' in script, (
        "the proof step counts hooks that passed a planted defect and does nothing with the count"
    )
    assert "::error::" in script, "the proof step reports nothing when a hook is blind"


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

    # Whole names, not substrings: `test` occurs inside `test-windows`, so a
    # condition naming only the latter satisfies a substring check for both.
    named = set(re.findall(r"needs(?:\.|\[')([A-Za-z0-9_-]+)", condition))
    missing = sorted(set(ok["needs"]) - named)
    assert missing == [], (
        f"`ok` waits for {missing} and does not require them to succeed; a job listed "
        "in needs: but absent from the condition can be red while ok is green"
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


@pytest.mark.parametrize("hook_id", ["trailing-whitespace", "end-of-file-fixer", "check-toml"])
def test_the_hooks_that_were_already_right_are_still_there(hook_id: str) -> None:
    """Correcting three of them is not a licence to lose the rest."""
    assert _hook(hook_id)
