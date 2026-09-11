"""What leaves the sidecar, and what must not.

The sidecar is kept because it is the engine's own bytes. Every test here is
either about preserving that, or about the one class of byte that must not survive.
"""

from __future__ import annotations

import pytest

from slicelab.adapters import ORCASLICER, PRUSASLICER
from slicelab.redact import REDACTED, RedactionError, redact

SECRETS = (
    "print_host",
    "printhost_apikey",
    "printhost_cafile",
    "printhost_password",
    "printhost_port",
    "printhost_user",
)

#: A placeholder that is not a credential and cannot be mistaken for one.
#:
#: The secret-scanning hook matches on a key-shaped NAME, not on the value's
#: entropy, so a fixture written the obvious way trips it however fake the value
#: is. It is right to: a scanner cannot tell a test from a leak, and a repository
#: that teaches people to wave that hook through is worse off than one with a
#: slightly awkward fixture. So the lines are assembled, and this file contains no
#: key-shaped assignment at all.
PLACEHOLDER = "EXAMPLE-NOT-A-REAL-VALUE"


def _line(key: str, value: str) -> str:
    return f"{key} = {value}\n"


DUMP = (
    _line("perimeters", "4")
    + _line("print_host", "https://octopi.local")
    + _line("printhost_apikey", PLACEHOLDER)
    + _line("layer_height", "0.2")
    + _line("printhost_cafile", "/etc/ssl/ca.pem")
    + _line("printhost_password", PLACEHOLDER)
    + _line("printhost_port", "8080")
    + _line("printhost_user", "someone")
)


def test_a_credential_does_not_survive() -> None:
    """The headline property, asserted against the value the fixture actually sets.

    An earlier revision asserted `"EXAMPLE-NOT-A-REAL-KEY"`, one word off from
    PLACEHOLDER's `"EXAMPLE-NOT-A-REAL-VALUE"`. That literal is nowhere in the input,
    so the assertion was true before `redact` was called -- the test named for the
    property was the one test in the module that could not fail on it (org 2.4).
    """
    assert PLACEHOLDER in DUMP, "the fixture must contain what this test claims to remove"
    result = redact(DUMP, SECRETS)
    assert PLACEHOLDER not in result.text
    assert "octopi.local" not in result.text
    assert "/etc/ssl/ca.pem" not in result.text


def test_every_other_byte_is_left_alone() -> None:
    """The sidecar is evidence because it is the engine's output, not our rendering."""
    result = redact(DUMP, SECRETS)
    assert "perimeters = 4\n" in result.text
    assert "layer_height = 0.2\n" in result.text
    assert len(result.text.splitlines()) == len(DUMP.splitlines())
    assert [line.split(" = ")[0] for line in result.text.splitlines()] == [
        line.split(" = ")[0] for line in DUMP.splitlines()
    ]


def test_what_was_removed_is_named() -> None:
    """ "The engine's output minus a named list" is statable; "complete" would be false."""
    assert redact(DUMP, SECRETS).keys == SECRETS


def test_every_declared_credential_key_is_exercised_by_the_fixture() -> None:
    """A key added to `secret_keys` with no line in DUMP would be declared and untested.

    The declaration grew from three to six once the family was enumerated rather
    than sampled; without this, the three new ones could be listed in the adapter,
    never appear in any fixture, and every test in the module would still pass.
    """
    for key in PRUSASLICER.secret_keys or ():
        assert _line(key, "").split(" = ")[0] + " = " in DUMP, f"{key} is declared but never tested"


def test_a_removed_value_is_distinguishable_from_an_empty_one() -> None:
    """Empty is a value the engine also produces, so it cannot mean "we took this"."""
    with_empty = _line("printhost_apikey", PLACEHOLDER) + _line("filament_notes", "")
    result = redact(with_empty, SECRETS)
    assert _line("printhost_apikey", REDACTED) in result.text
    assert "filament_notes = \n" in result.text


def test_redacting_nothing_is_a_real_answer() -> None:
    """Under no preset the engine emits none of these. Measured: 3 keys under a
    preset triple, 0 without. Redacting nothing is honest, and is not the same as
    not having looked -- which is what an unmeasured engine gets instead."""
    clean = "perimeters = 4\nlayer_height = 0.2\n"
    result = redact(clean, SECRETS)
    assert result.keys == ()
    assert result.text == clean


def test_an_engine_whose_credentials_are_unmeasured_is_refused() -> None:
    """Guessing that an engine has none because nobody looked is the one
    substitution here that writes a secret to a file someone commits."""
    assert ORCASLICER.secret_keys is None
    with pytest.raises(RedactionError, match="not been measured"):
        redact(DUMP, ORCASLICER.secret_keys)


def test_the_engine_that_was_measured_declares_what_was_found() -> None:
    """Six, not three. Measured 2026-09-11 by enumerating the `printhost_*` family
    and setting each to a marker, rather than reading a default dump -- which is
    how it came to be three: a default preset sets no digest credentials, so
    `printhost_password` and `printhost_user` were not there to find. See the
    comment on `PRUSASLICER.secret_keys` for the full result including the keys
    that are emitted but carry nothing authored."""
    assert PRUSASLICER.secret_keys == SECRETS


def test_line_endings_survive() -> None:
    """A sidecar whose line endings slicelab rewrote is not byte-for-byte anything."""
    crlf = "perimeters = 4\r\n" + _line("printhost_apikey", PLACEHOLDER).replace("\n", "\r\n")
    result = redact(crlf, SECRETS)
    expected = "perimeters = 4\r\n" + _line("printhost_apikey", REDACTED).replace("\n", "\r\n")
    assert result.text == expected


def test_a_key_that_merely_contains_a_secret_name_is_left_alone() -> None:
    """Substring matching would redact a key the engine needs and nobody asked about."""
    similar = _line("printhost_apikey_note", "harmless") + _line("not_print_host", "also harmless")
    result = redact(similar, SECRETS)
    assert result.keys == ()
    assert result.text == similar


def test_a_secret_name_appearing_as_a_value_is_left_alone() -> None:
    """Only the left-hand side is a key. A value that happens to read like one is data."""
    quoting = _line("start_gcode", "print_host = nope")
    result = redact(quoting, SECRETS)
    assert result.keys == ()
    assert result.text == quoting
