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
needs network to clone each hook repository and this suite must work offline. That is
a real limit: they establish that the flags are present, not that upstream still
honours them. The flags were verified by planting each defect in a scratch repository
and watching the hook fail; what these tests defend is somebody quietly removing one.
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
    assert len(_hooks()) >= 8, [h["id"] for h in _hooks()]


def test_large_file_check_looks_at_every_file_not_just_the_new_ones() -> None:
    """Without `--enforce-all` a 2 MB binary already tracked passes forever."""
    assert "--enforce-all" in _hook("check-added-large-files").get("args", [])


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


def test_ci_runs_pre_commit_at_all() -> None:
    """The hooks ran only where somebody had installed them, which is not a gate."""
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    jobs = workflow["jobs"]
    runners = [
        name
        for name, job in jobs.items()
        if any("pre-commit" in str(step.get("run", "")) for step in job.get("steps", []))
    ]
    assert runners, f"no job runs pre-commit; jobs are {sorted(jobs)}"


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


def test_the_aggregator_waits_for_pre_commit() -> None:
    """A job nothing depends on can fail without failing the pull request."""
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    needs = workflow["jobs"]["ok"]["needs"]
    assert "pre-commit" in needs, f"`ok` does not wait for pre-commit: {needs}"


@pytest.mark.parametrize("hook_id", ["trailing-whitespace", "end-of-file-fixer", "check-toml"])
def test_the_hooks_that_were_already_right_are_still_there(hook_id: str) -> None:
    """Correcting three of them is not a licence to lose the rest."""
    assert _hook(hook_id)
