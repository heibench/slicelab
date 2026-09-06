"""slicelab exports no public Python names, and that is a contract.

heibench AGENTS.md section 5: "The stable surface is the artifact and the exit
code, never the Python API." A package that quietly grows an importable surface
acquires a second, weaker interface that consumers pin to and that the exit-code
contract does not cover. This test is the mechanism for that intention.

Its red state has been observed: adding any public name to slicelab/__init__.py
fails the first test, and removing __version__ fails the second.
"""

import slicelab


def test_package_exports_no_public_names() -> None:
    """Everything slicelab offers is behind the CLI, not behind an import."""
    public = {name for name in dir(slicelab) if not name.startswith("_")}
    assert public == set(), (
        f"slicelab grew a public Python surface: {sorted(public)}. "
        "Depend on the CLI and slice.lock, not on importable names (org AGENTS.md 5)."
    )


def test_version_is_the_one_exported_name() -> None:
    """__version__ is the single exception, so a caller can report what it ran."""
    assert slicelab.__all__ == ["__version__"]
    assert isinstance(slicelab.__version__, str)
    assert slicelab.__version__
