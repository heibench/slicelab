"""Removing credentials from a readback before it is written anywhere.

The engine's configuration dump is the evidence a run happened as described, so
slicelab keeps it beside the report. It also contains credentials: PrusaSlicer's
`--save` emits `printhost_apikey` and `print_host` in cleartext, and the G-code
footer — the same configuration reached another way — strips exactly those. One
artifact of the same engine is safe to keep and another is not.

**This is secret hygiene and nothing else.** The frozen dossier refuted the
licensing rationale and flags it as a trap not to reintroduce: the committed G-code
already carries the same vendor payload, so withholding a sidecar removes no bytes
from anyone's repository. Diff noise, lock size and credentials are the reasons
that survived.

Everything else is preserved exactly as the engine wrote it — same lines, same
order, same spacing. A sidecar that reformatted its input would be slicelab's
rendering of the engine's answer rather than the answer, and the whole point of
keeping it is that it is the engine's own bytes.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

__all__ = ["REDACTED", "Redacted", "RedactionError", "redact"]

REDACTED = "<redacted>"
"""What a removed value is replaced with.

A marker rather than an empty value, because empty is a value the engine can also
produce. A reader of the sidecar must be able to tell "slicelab removed this" from
"the engine wrote nothing here", and an empty string says neither.
"""


class RedactionError(Exception):
    """slicelab will not write a readback it cannot promise is safe."""


@dataclass(frozen=True)
class Redacted:
    """A readback with its credentials removed, and the record of which."""

    text: str
    keys: tuple[str, ...]
    """The keys actually found and removed, in the order they appeared.

    Recorded because "the sidecar is complete" would be false and "the sidecar is
    the engine's output" would be misleading. It is the engine's output minus a
    named list, and naming the list is what makes the difference statable rather
    than something a reader has to notice.

    Empty is a real answer: under no preset the engine emits none of these, so a
    run can honestly redact nothing. That is not the same as not having looked.
    """


def redact(text: str, secret_keys: Iterable[str] | None) -> Redacted:
    """Replace the values of `secret_keys`, leaving every other byte alone.

    `secret_keys` of `None` is **unmeasured**, not "none": an engine whose
    credential-bearing keys nobody has established cannot be promised safe, so the
    readback is refused rather than written. Guessing that an engine has no
    credentials because nobody looked is the substitution this project refuses, and
    it would be the one case where getting it wrong writes a secret to a file
    someone commits.
    """
    if secret_keys is None:
        raise RedactionError(
            "this engine's credential-bearing keys have not been measured, so its "
            "configuration dump cannot be promised free of them"
        )

    wanted = set(secret_keys)
    if not wanted:
        return Redacted(text=text, keys=())

    removed: list[str] = []
    lines = text.splitlines(keepends=True)
    for index, line in enumerate(lines):
        key, separator, _ = line.partition(" = ")
        if not separator or key.strip() not in wanted:
            continue
        ending = line[len(line.rstrip("\r\n")) :]
        lines[index] = f"{key}{separator}{REDACTED}{ending}"
        removed.append(key.strip())
    return Redacted(text="".join(lines), keys=tuple(removed))
