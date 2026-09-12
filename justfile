# slicelab task runner

set dotenv-load := false

# Show available recipes
default:
    @just --list

# --locked is load-bearing, not tidiness. Plain `uv sync` reconciles a stale
# uv.lock and rewrites it at exit 0 with no diagnostic, and CI runs this same
# recipe -- so the committed lockfile was never once tested and a drifted lock
# reached main green. A gate that cannot fail is not a gate.
#
# If setup fails because you changed dependencies, that is the recipe working:
# run `just lock` and commit the result. `lock` is deliberately separate, so
# updating the lockfile is always something someone chose to do rather than a
# side effect of setting up.

# Install dependencies from the committed lockfile; fails if the lock is stale
setup:
    uv sync --locked

# Update the lockfile after changing dependencies in pyproject.toml
lock:
    uv lock

# Format code and apply lint fixes (mutates the working tree)
fmt:
    uv run ruff format .
    uv run ruff check --fix .

# Verify formatting without mutating (CI)
fmt-check:
    uv run ruff format --check .

# Lint
lint:
    uv run ruff check .

# Type-check
typecheck:
    uv run mypy slicelab/ tests/

# Verify pyproject.toml does not weaken the checks the other recipes run.
# Deliberately not a test: `addopts = [..., "--co"]` collects the suite without
# running it, so an assertion inside the suite cannot catch that one.
config-check:
    uv run python scripts/check-tool-config.py

# Format-check + lint + typecheck + config -- the CI-equivalent gate
check: fmt-check lint typecheck config-check

# Run tests. Engine-dependent tests skip when no slicer is installed.
test:
    uv run pytest

# CI sets this on the engine matrix so a failed engine install is loud rather
# than a silent skip.

# Run tests and FAIL (rather than skip) if no engine is installed
test-engine:
    SLICELAB_REQUIRE_ENGINE=1 uv run pytest

# Run every pre-commit hook against the whole tree
# Pinned to the version CI runs. An unpinned runner can resolve hooks differently
# with no diff here, which is the local/CI divergence the ruff version pin exists
# one layer down to prevent.
hooks:
    uvx pre-commit@4.2.0 run --all-files

# Remove build and tool caches
clean:
    rm -rf .venv dist .pytest_cache .ruff_cache .mypy_cache
    find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
