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

Everything else is preserved exactly as the engine wrote it. That was a claim in
this docstring and is now a check: after the adapter substitutes, the result is read
back through the adapter's own reader and compared key by key against the original.
Every non-secret key must be identical and every secret key must read as the marker,
or nothing is written.

**The substitution is the adapter's, because the format is.** This module used to
split every line on `" = "` -- PrusaSlicer's ini, in a core module. OrcaSlicer's
readback is JSON, so that removed nothing and returned a `Redacted` whose `keys` said
so: an honest empty list, about a file that still held the credentials. Measured on
2.4.2, the dump carries seven of them in cleartext once a machine profile configures
upload. The verification below is what makes that failure loud instead of silent, and
it is why the check exists rather than a second format branch.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # `EngineSpec` is used in an annotation only, and this module has
    # `from __future__ import annotations`, so nothing needs it at run time. Imported
    # unconditionally it is a cycle: `adapters/__init__` loads `orcaslicer`, which
    # imports `REDACTED` from here -- before this module has defined it. Masked in
    # practice because every entry point imports `slicelab.adapters` first, so
    # `import slicelab.redact` on a cold bytecode cache was the only way to see it.
    from slicelab.adapters.base import EngineSpec

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


def redact(text: str, spec: EngineSpec) -> Redacted:
    """Replace the values of this engine's credential keys, and prove nothing else moved.

    `secret_keys` of `None` is **unmeasured**, not "none": an engine whose
    credential-bearing keys nobody has established cannot be promised safe, so the
    readback is refused rather than written. Guessing that an engine has no
    credentials because nobody looked is the substitution this project refuses, and
    it would be the one case where getting it wrong writes a secret to a file
    someone commits.
    """
    if spec.secret_keys is None:
        raise RedactionError(
            "this engine's credential-bearing keys have not been measured, so its "
            "configuration dump cannot be promised free of them"
        )
    if not spec.secret_keys:
        return Redacted(text=text, keys=())
    if spec.redact_readback is None or spec.read_readback is None:
        raise RedactionError(
            f"{spec.name} declares credential-bearing keys and no measured way to "
            "remove them from its own dump format"
        )

    before = spec.read_readback(text)
    out = spec.redact_readback(text, spec.secret_keys)
    after = spec.read_readback(out)

    # The verification, and the reason this is a function rather than a call. A
    # substitution written for the wrong format removes nothing and raises nothing --
    # it returns a clean-looking file and a truthful "I removed no keys", which is
    # indistinguishable from an engine that emitted no credentials. So the result is
    # read back and compared, and a redaction that did not take is an error.
    wanted = set(spec.secret_keys)
    survived = sorted(k for k in wanted if k in after and after[k] != REDACTED)
    if survived:
        raise RedactionError(
            f"{spec.name}'s readback still carries {', '.join(survived)} after "
            "redaction, so the dump cannot be promised free of credentials"
        )
    # `k not in after` catches a key the redactor DELETED, including a secret one --
    # which `survived` cannot see, because a deleted key is neither present-and-wrong
    # nor present-and-marked. Without it a redactor that drops `printhost_apikey`
    # entirely passes, and `Redacted.keys` still reports it as found and removed. The
    # marker exists precisely so a reader can tell "slicelab took this" from "the
    # engine wrote nothing here", and a deletion says neither.
    disturbed = sorted(
        k for k, v in before.items() if k not in after or (k not in wanted and after[k] != v)
    )
    if disturbed or set(after) - set(before):
        # Not pedantry: the sidecar is evidence, and evidence slicelab silently
        # rewrote is not the engine's answer. A redactor that reformats or drops a
        # key would otherwise pass unnoticed, because nothing else reads this file.
        raise RedactionError(
            f"redacting {spec.name}'s readback changed keys it was not asked to: "
            f"{', '.join(disturbed + sorted(set(after) - set(before))) or 'keys were lost'}"
        )
    return Redacted(text=out, keys=tuple(k for k in before if k in wanted))
