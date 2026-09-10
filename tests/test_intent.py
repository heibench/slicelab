"""What a `slice.toml` may say, and what is refused rather than ignored.

Every refusal here happens **before the engine is reached**, which is D15's
pre-flight `refused` at exit 1. The tests are named for the claim they make, and
each one exists because the alternative -- accepting it and finding out later, or
accepting it and never finding out -- is the defect this project is named after.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from slicelab.intent import Intent, IntentError, read_intent

VALID = """
[prusaslicer.base]
printer-profile = "Original Prusa i3 MK3S & MK3S+"
print-profile = "0.20mm QUALITY @MK3"
material-profile = "Prusament PLA"

[prusaslicer.set]
perimeters = 4
"""


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "slice.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_a_valid_intent_reads_back_what_was_written(tmp_path: Path) -> None:
    intent = read_intent(write(tmp_path, VALID))
    assert intent.engine == "prusaslicer"
    assert intent.base["printer-profile"] == "Original Prusa i3 MK3S & MK3S+"
    assert intent.overrides == {"perimeters": 4}
    assert not intent.subject_set_is_empty


def test_an_override_keeps_its_authored_type(tmp_path: Path) -> None:
    """Types are preserved, and the boolean is why.

    PrusaSlicer 2.9.6 accepts `--spiral-vase=1` and resolves `--spiral-vase=true` to
    `0` -- silently, at exit 0, the opposite of what the author wrote. Stringifying
    here would hand the adapter a `"true"` it could no longer tell from a deliberate
    string, so the decision stays where the engine knowledge is.
    """
    intent = read_intent(
        write(
            tmp_path,
            VALID + '\nspiral-vase = true\nlayer-height = 0.15\nnotes = "hello"\n',
        )
    )
    assert intent.overrides["spiral-vase"] is True
    assert intent.overrides["layer-height"] == 0.15
    assert intent.overrides["notes"] == "hello"


def test_no_set_table_is_an_empty_subject_set(tmp_path: Path) -> None:
    """The first file anyone writes, and it must not read as a checked run (G1, D24)."""
    base_only = VALID.split("[prusaslicer.set]")[0]
    intent = read_intent(write(tmp_path, base_only))
    assert intent.overrides == {}
    assert intent.subject_set_is_empty


def test_an_unknown_table_is_refused(tmp_path: Path) -> None:
    """Not ignored. The engine drops an unknown key from a --load'ed ini at exit 0
    with zero bytes on stderr [V2]; doing that one layer up is the joke telling
    itself."""
    with pytest.raises(IntentError, match="options"):
        read_intent(write(tmp_path, VALID + "\n[prusaslicer.options]\nx = 1\n"))


def test_a_missing_base_is_refused(tmp_path: Path) -> None:
    """Zero of three is accepted by the engine at exit 0, yielding generic built-ins."""
    with pytest.raises(IntentError, match="required"):
        read_intent(write(tmp_path, "[prusaslicer.set]\nperimeters = 4\n"))


def test_a_base_table_with_no_presets_is_refused(tmp_path: Path) -> None:
    """Zero presets is accepted by the engine at exit 0, yielding generic built-ins.

    WHICH names are required is the adapter's (`EngineSpec.base_keys`) and is checked
    at pre-flight, D15's home for a refusal slicelab's own argv would have caused.
    The parser owns the shape only.
    """
    with pytest.raises(IntentError, match="empty"):
        read_intent(write(tmp_path, "[prusaslicer.base]\n[prusaslicer.set]\nx = 1\n"))


def test_a_base_key_written_as_a_flag_is_refused(tmp_path: Path) -> None:
    bad = VALID.replace("printer-profile =", '"--printer-profile" =')
    with pytest.raises(IntentError, match="leading dashes"):
        read_intent(write(tmp_path, bad))


def test_an_empty_preset_name_is_refused(tmp_path: Path) -> None:
    with pytest.raises(IntentError, match="empty"):
        read_intent(write(tmp_path, VALID.replace('"Prusament PLA"', '"  "')))


def test_an_empty_override_value_is_refused(tmp_path: Path) -> None:
    """D5's boundary, and it is a class rather than one option: --post-process=,
    --filament-notes= and --bed-custom-texture= all answer 'No value supplied'.
    "Clear this key" is refused with a reason, never a silent no-op."""
    with pytest.raises(IntentError, match="not\n?\\s*expressible|expressible"):
        read_intent(write(tmp_path, VALID + '\npost-process = ""\n'))


def test_an_override_written_as_a_flag_is_refused(tmp_path: Path) -> None:
    """`"--perimeters" = 4` would emit `----perimeters=4`. Refuse the shape rather
    than quietly stripping it, because stripping is a name transformation and G2 is
    about what those cost."""
    with pytest.raises(IntentError, match="leading dashes"):
        read_intent(write(tmp_path, VALID + '\n"--spiral-vase" = 1\n'))


def test_an_override_of_the_wrong_type_is_refused(tmp_path: Path) -> None:
    with pytest.raises(IntentError, match="list"):
        read_intent(write(tmp_path, VALID + "\nthumbnails = [1, 2]\n"))


def test_two_engine_tables_are_refused(tmp_path: Path) -> None:
    """One run drives one engine. Guessing which would be a §2.3 substitution."""
    with pytest.raises(IntentError, match="more than one engine"):
        read_intent(write(tmp_path, VALID + '\n[orcaslicer.base]\nprinter-profile = "x"\n'))


def test_an_empty_file_is_refused(tmp_path: Path) -> None:
    with pytest.raises(IntentError, match="no engine table"):
        read_intent(write(tmp_path, "\n"))


def test_invalid_toml_is_refused_with_the_parser_s_own_words(tmp_path: Path) -> None:
    """tomllib knows why it failed; inventing a reason would be the substitution."""
    with pytest.raises(IntentError, match="not valid TOML"):
        read_intent(write(tmp_path, "[prusaslicer.base\n"))


def test_a_missing_file_is_refused(tmp_path: Path) -> None:
    with pytest.raises(IntentError, match="cannot read"):
        read_intent(tmp_path / "nope.toml")


def test_the_parser_does_not_execute_anything(tmp_path: Path) -> None:
    """D13's load-bearing constraint: `tomllib.load` plus a validator and nothing else.

    TOML has no expression, include, interpolation or tag syntax, so a string that
    looks like one stays a string. If this ever fails, org section 4 applies to
    `slice.toml` and D13's adjudication is void.
    """
    intent = read_intent(write(tmp_path, VALID + '\nstart-gcode = "${HOME} $(whoami) {{x}}"\n'))
    assert intent.overrides["start-gcode"] == "${HOME} $(whoami) {{x}}"


def test_intent_is_frozen() -> None:
    """A validated request must not be edited after the fact by a later phase."""
    intent = Intent(engine="e", base={}, overrides={}, source=Path("x"))
    with pytest.raises(AttributeError):
        intent.engine = "other"  # type: ignore[misc]
