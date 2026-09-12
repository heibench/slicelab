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
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / ".pre-commit-config.yaml"
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
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
    entry = history[0].get("entry", "")
    assert "--staged" not in entry, f"the history scan is still index-scoped: {entry}"
    # `gitleaks dir` satisfies "not --staged" and scans the worktree, not the history,
    # which restores the exact defect this hook was added for. And a baseline or a
    # forced exit code makes it report a leak and pass anyway -- `--baseline-path` is
    # the documented way to grandfather a finding, so it is the realistic one.
    assert entry.split()[1:2] == ["git"], f"the history scan is not scanning git history: {entry}"
    for defeat in ("--baseline-path", "--exit-code 0", "--no-git"):
        assert defeat not in entry, f"the history scan cannot fail: {entry}"
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
    here = [
        str(step.get("run", ""))
        for step in job["steps"]
        if "pre-commit" in str(step.get("run", ""))
        and " run" in str(step.get("run", ""))
        and "mktemp" not in str(step.get("run", ""))
    ]
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

    missing = [job for job in ok["needs"] if job not in condition]
    assert missing == [], (
        f"`ok` waits for {missing} and does not require them to succeed; a job listed "
        "in needs: but absent from the condition can be red while ok is green"
    )


@pytest.mark.parametrize("hook_id", ["trailing-whitespace", "end-of-file-fixer", "check-toml"])
def test_the_hooks_that_were_already_right_are_still_there(hook_id: str) -> None:
    """Correcting three of them is not a licence to lose the rest."""
    assert _hook(hook_id)
