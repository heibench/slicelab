#!/usr/bin/env bash
# Prove each hook EXISTS, RUNS, and CATCHES what it is named for.
#
# `tests/test_pre_commit_gate.py` reads `.pre-commit-config.yaml`, which keeps that
# suite offline but can only pin presence. This runs the hooks, so it pins effect.
#
# EVERY hook, not a chosen three. Proving three of ten left the other seven pinned for
# presence only, and one line each -- `exclude:`, `files:`, `stages: [manual]`,
# `--exit-zero` -- took any of them out with every assertion green and this script
# still exiting 0. Planting for all ten subsumes those four spellings in one
# instrument, because a hook that cannot see its plant cannot reject it.
#
# ONE HOOK PER INVOCATION, and PROBE BEFORE ADJUDICATING. `pre-commit` exits 1 if any
# hook fails, so an aggregate run proves only that one of them did; and
# `pre-commit run <unknown-id>` also exits 1, so a non-zero exit is not evidence of a
# catch until the hook has been shown to exist and pass on a clean tree.
#
# Usage: prove-hooks-catch.sh <config> <pyproject> [runner...]
#   exit 0 — every hook resolved, passed clean, and rejected its own planted defect
#   exit 1 — some hook is missing, or passed a defect it is named for
#
# `<pyproject>` is an argument rather than a fixed path so CI can hand this a doctored
# one and require the run to fail. It was a hardcoded `cp` of the repository's own
# file, and deleting that one line left every hook still catching, this script still
# exiting 0, and all three self-tests still red -- because every one of them doctors
# the pre-commit config, which was still being copied.
set -euo pipefail

config="${1:?usage: prove-hooks-catch.sh <config> <pyproject> [runner...]}"
pyproject="${2:?usage: prove-hooks-catch.sh <config> <pyproject> [runner...]}"
shift 2
runner=("${@:-pre-commit}")

# `gitleaks-staged` is adjudicated on its own below: its plant has to be staged and
# not committed, which is the whole difference between it and the history scan.
# `readonly`, because bash binds a name without `=` too. `read -r hooks <<< "${hooks/check-yaml/}"`
# is one line with no assignment operator, and it trimmed the list past every guard --
# `readonly` refuses `read`, `mapfile`, `for` and plain assignment alike, measured.
readonly hooks='gitleaks-staged gitleaks-history check-merge-conflict check-added-large-files
       check-yaml check-toml ruff-check trailing-whitespace end-of-file-fixer
       ruff-format'

scratch="$(mktemp -d)"
trap 'rm -rf "$scratch"' EXIT
cp "$config" "$scratch/.pre-commit-config.yaml"
# And the project configuration the hooks read. Without it ruff falls back to its own
# defaults in here, so narrowing `[tool.ruff.lint] select` to nothing blinded the
# `ruff-check` hook in the real tree while this script went on printing
# `ok: ruff-check rejected its planted defect`. A hook is only proved under the
# configuration it actually runs with.
cp "$pyproject" "$scratch/pyproject.toml"
cd "$scratch"
git init -q -b main .
git config user.email ci@example.invalid
git config user.name CI

# Under the same directory names the real tree uses, not at the root. A path-scoped
# `exclude:` or `files:` -- one line, at the top of the config or on a single hook --
# blinds a hook over the whole source tree, and a prover that plants everything at the
# root cannot see it: the plants stay visible, every hook still catches, and the config
# that hides slicelab/ and tests/ from the gate proves out clean.
mkdir -p slicelab tests
printf 'x = 1\n' > slicelab/clean.py
printf 'x = 1\n' > tests/clean.py
printf 'a: 1\n' > slicelab/clean.yaml
printf 'a = 1\n' > slicelab/clean.toml
git add -A && git commit -q -m 'a repository with nothing wrong with it'

# Probe. Bare commands under `set -e`: no accumulator to forget to increment, no `||`
# to swallow the result. A missing hook stops the script here, so it can never reach
# the adjudication and be counted as a catch.
probed=''
for hook in $hooks; do
  "${runner[@]}" run "$hook" --all-files
  probed="$probed $hook"
done
echo 'probe: every hook resolves and passes on a clean repository'

# One plant per hook, each named for the hook it is for.
head -c 2000000 /dev/urandom > slicelab/big.bin
printf 'a\n<<<<<<< HEAD\nb\n=======\nc\n>>>>>>> other\n' > tests/conflicted.txt
# Not `.py`. On `.py` these two are also what `ruff-format` reformats, so it
# reported catching with its own plant removed -- a hook proved by someone else's
# defect. Each plant now reaches only the hook it is named for.
printf 'x = 1   \n' > slicelab/trailing.txt
printf 'y = 2' > slicelab/noeol.txt
printf 'a: [1, 2\n' > slicelab/broken.yaml
printf 'a = [1, 2\n' > slicelab/broken.toml
printf 'import os\n' > slicelab/unused.py
printf 'z=3\n' > slicelab/misformatted.py
git add -A && git commit -q -m 'plant one defect for every file-based hook'

# gitleaks allowlists canonical example keys such as AKIAIOSFODNN7EXAMPLE, and its
# aws-access-token rule wants AKIA plus exactly sixteen characters from its alphabet.
# base32 emits A-Z2-7, already inside it.
newkey() {
  local key="AKIA$(head -c 20 /dev/urandom | base32 | tr -d = | head -c 16)"
  test ${#key} -eq 20 || { echo "::error::planted key is ${#key} chars, not 20"; exit 1; }
  printf %s "$key"
}
printf 'aws_access_key_id = %s\n' "$(newkey)" > slicelab/creds.txt
git add slicelab/creds.txt && git commit -q -m 'plant a secret'
git rm -q slicelab/creds.txt && git commit -q -m 'delete it again'

# Adjudicate. Also bare under `set -e`, inverted: a hook that PASSES its plant is the
# failure, and the `exit 1` inside the `if` makes that the script's failure too. No
# accumulator here either -- an earlier version kept one and it could simply stop
# being incremented.
#
# The tree is restored before each hook because four of these hooks are fixers: they
# rewrite the file and exit 1, so without the restore a later hook can pass on a
# defect an earlier hook already cleaned up, and the order of the list would silently
# decide the verdict.
adjudicated=''
for hook in $hooks; do
  git checkout -q -- .
  if [ "$hook" = gitleaks-staged ]; then
    # Its subject is the index, not the tree or the history: a secret that is staged
    # and not yet committed. Planting it the same way as the others would prove
    # nothing, which is exactly why this hook had no proof at all until now.
    printf 'aws_access_key_id = %s\n' "$(newkey)" > slicelab/staged-creds.txt
    git add slicelab/staged-creds.txt
  fi
  if "${runner[@]}" run "$hook" --all-files; then
    echo "::error::$hook passed its planted defect. That hook is decorative."
    exit 1
  fi
  echo "ok: $hook rejected its planted defect"
  if [ "$hook" = gitleaks-staged ]; then
    git rm -q -f --cached slicelab/staged-creds.txt && rm -f slicelab/staged-creds.txt
  fi
  adjudicated="$adjudicated $hook"
done

# Every hook in the list, REACHED. The list itself is pinned equal to the configuration
# by the suite, and the assignment is pinned by both a literal search and a
# command-anchored one -- but neither sees a trim at the USE site, and
# `for hook in ${hooks/check-added-large-files/}` needs no assignment at all. The probe
# half is the worse one: `pre-commit run <unresolvable-id>` exits 1 whether the tree is
# clean or broken, so a hook the probe never resolved is then adjudicated as catching,
# and the run prints ten `ok:` lines with no signal in any of them.
#
# An accumulator that stops being appended makes this FAIL, which is the direction that
# matters; the accumulator this file's history warns about counted failures and so
# failed open.
for reached in "$probed" "$adjudicated"; do
  test "$(echo $reached)" = "$(echo $hooks)" || {
    echo "::error::a loop skipped a hook: reached [$(echo $reached)], the list is [$(echo $hooks)]"
    exit 1
  }
done
echo 'proved: every hook in the list was probed and adjudicated'
