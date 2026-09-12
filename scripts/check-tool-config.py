#!/usr/bin/env python3
"""Verify the tool configuration the other recipes read.

Every other guard in this repository pins an *invocation* -- a justfile recipe, a
workflow step, a pre-commit hook. `pyproject.toml` reaches the same outcomes from a
file none of them inspects: `addopts = ["-ra", "--co"]` makes `uv run pytest` collect
the whole suite, run none of it and exit 0; `select = []` blinds both `just lint` and
the `ruff-check` hook; `ignore_errors = true` makes `just typecheck` report success
over every type error.

This lives outside pytest ON PURPOSE. The `--co` spelling disables the suite, so an
assertion inside the suite cannot catch it -- it is the one weakening that silences its
own guard. `just check` runs this, and `just check` does not go through pytest.
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"

#: Every rule family `just lint` and the `ruff-check` hook are expected to enforce.
#: A superset is fine; dropping one is not.
REQUIRED_RULES = {"E", "F", "I", "UP", "B", "SIM"}


def problems() -> list[str]:
    tool = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["tool"]
    pytest_cfg = tool["pytest"]["ini_options"]
    found: list[str] = []

    if pytest_cfg.get("addopts") != ["-ra"]:
        found.append(
            f"addopts = {pytest_cfg.get('addopts')!r} -- pytest's own configuration can "
            "deselect the suite, or collect it without running it, while `just test` "
            "exits 0"
        )
    if pytest_cfg.get("testpaths") != ["tests"]:
        found.append(f"testpaths = {pytest_cfg.get('testpaths')!r} -- the suite is not collected")

    selected = set(tool["ruff"]["lint"]["select"])
    if not selected >= REQUIRED_RULES:
        found.append(
            f"ruff select is missing {sorted(REQUIRED_RULES - selected)} -- `just lint` "
            "and the `ruff-check` hook both read this"
        )
    if tool["mypy"].get("ignore_errors"):
        found.append("mypy ignore_errors is set -- `just typecheck` reports nothing")
    return found


def main() -> int:
    found = problems()
    for problem in found:
        print(f"error: {problem}", file=sys.stderr)
    if found:
        print(f"{PYPROJECT.name} weakens a check that is otherwise gated", file=sys.stderr)
        return 1
    print("tool configuration intact: pytest collects and runs, ruff and mypy report")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
