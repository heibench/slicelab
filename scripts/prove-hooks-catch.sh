#!/usr/bin/env bash
# Prove each hook EXISTS, RUNS, and CATCHES what it is named for.
#
# `tests/test_pre_commit_gate.py` reads `.pre-commit-config.yaml`, which keeps that
# suite offline but can only pin presence. This runs the hooks, so it pins effect.
#
# ONE HOOK PER INVOCATION, and PROBE BEFORE ADJUDICATING. `pre-commit` exits 1 if any
# hook fails, so an aggregate run proves only that one of them did; and
# `pre-commit run <unknown-id>` also exits 1, so a non-zero exit is not evidence of a
# catch until the hook has been shown to exist and pass on a clean tree.
#
# Usage: prove-hooks-catch.sh <config> [runner...]
#   exit 0 — every hook resolved, passed clean, and rejected its own planted defect
#   exit 1 — some hook is missing, or passed a defect it is named for
set -euo pipefail

config="${1:?usage: prove-hooks-catch.sh <config> [runner...]}"
shift
runner=("${@:-pre-commit}")

hooks='gitleaks-history check-merge-conflict check-added-large-files'

scratch="$(mktemp -d)"
trap 'rm -rf "$scratch"' EXIT
cp "$config" "$scratch/.pre-commit-config.yaml"
cd "$scratch"
git init -q -b main .
git config user.email ci@example.invalid
git config user.name CI
# Under the same directory names the real tree uses, not at the root. A path-scoped
# `exclude:` or `files:` -- one line above `repos:` -- blinds every file-based hook
# over the whole source tree, and a prover that plants everything at the root cannot
# see it: the plants stay visible, every hook still catches, and the config that
# hides slicelab/ and tests/ from the gate proves out clean. Mirroring the layout
# makes a path filter fail here, by effect rather than by spelling.
mkdir -p slicelab tests
echo clean > clean.txt
echo clean > slicelab/clean.py
echo clean > tests/clean.py
git add -A && git commit -q -m 'a repository with nothing wrong with it'

# Probe. Bare commands under `set -e`: no accumulator to forget to increment, no `||`
# to swallow the result. A missing hook stops the script here, so it can never reach
# the adjudication and be counted as a catch.
for hook in $hooks; do
  "${runner[@]}" run "$hook" --all-files
done
echo 'probe: every hook resolves and passes on a clean repository'

head -c 2000000 /dev/urandom > slicelab/big.bin
printf 'a\n<<<<<<< HEAD\nb\n=======\nc\n>>>>>>> other\n' > tests/conflicted.txt
git add -A && git commit -q -m 'plant a large file and a conflict marker'

# gitleaks allowlists canonical example keys such as AKIAIOSFODNN7EXAMPLE, and its
# aws-access-token rule wants AKIA plus exactly sixteen characters from its alphabet.
# base32 emits A-Z2-7, already inside it.
key="AKIA$(head -c 20 /dev/urandom | base32 | tr -d = | head -c 16)"
test ${#key} -eq 20 || { echo "::error::planted key is ${#key} chars, not 20"; exit 1; }
printf 'aws_access_key_id = %s\n' "$key" > slicelab/creds.txt
git add slicelab/creds.txt && git commit -q -m 'plant a secret'
git rm -q slicelab/creds.txt && git commit -q -m 'delete it again'

# Adjudicate. Also bare under `set -e`, inverted: a hook that PASSES its plant is the
# failure, and `!` makes that the script's failure too. No accumulator here either --
# an earlier version kept one and it could simply stop being incremented.
for hook in $hooks; do
  if "${runner[@]}" run "$hook" --all-files; then
    echo "::error::$hook passed its planted defect. That hook is decorative."
    exit 1
  fi
  echo "ok: $hook rejected its planted defect"
done
