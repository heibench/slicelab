# slicelab task runner

set dotenv-load := false

# Show available recipes
default:
    @just --list

# Install dependencies and set up the environment
setup:
    uv sync

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

# Format-check + lint + typecheck -- the CI-equivalent gate
check: fmt-check lint typecheck

# Run tests. Engine-dependent tests skip when no slicer is installed.
test:
    uv run pytest

# Run tests and FAIL (rather than skip) if no engine is installed.
# CI sets this on the engine matrix so a failed engine install is loud.
test-engine:
    SLICELAB_REQUIRE_ENGINE=1 uv run pytest

# Run every pre-commit hook against the whole tree
hooks:
    pre-commit run --all-files

# Remove build and tool caches
clean:
    rm -rf .venv dist .pytest_cache .ruff_cache .mypy_cache
    find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
