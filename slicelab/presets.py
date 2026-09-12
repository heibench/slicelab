"""Adjudicating a preset enumeration.

Parseability is not the test. ``notes/critique.md`` G3: a datadir carrying the
vendor bundle but no installed models answers ``{"printer_models": ""}``, which
parses perfectly and enumerates nothing. Reporting success there would be a
green from the one verb whose entire job is establishing that a ``[base]`` name
is nameable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum

__all__ = ["Enumeration", "PresetsVerdict", "adjudicate"]


class PresetsVerdict(StrEnum):
    """What the enumeration established."""

    ENUMERATED = "enumerated"
    """Parsed, correctly shaped, and non-empty."""

    UNPARSEABLE = "unparseable"
    """stdout was not JSON. The engine said something, but not an answer."""

    MALFORMED = "malformed"
    """Parsed, but the root key is missing or is not a list."""

    EMPTY = "empty"
    """Parsed, correctly shaped, and an empty list.

    **Not G3.** G3's payload is ``{"printer_models": ""}``, and ``""`` is a str where a
    list was promised, so it lands in :attr:`MALFORMED` -- deliberately, because
    conflating the two would hide a schema change behind an empty result. This line
    said "contains nothing. G3" for long enough that a numbered decision was written
    from it, by reading this docstring instead of running ``adjudicate``.
    """

    UNSUPPORTED = "unsupported"
    """This engine has no preset-enumeration verb at all."""


@dataclass(frozen=True)
class Enumeration:
    verdict: PresetsVerdict
    entries: list[dict[str, object]]
    reason: str

    @property
    def ok(self) -> bool:
        return self.verdict is PresetsVerdict.ENUMERATED


def adjudicate(stdout: str, root_key: str) -> Enumeration:
    """Decide what an engine's preset query actually established.

    Three failure shapes, all observed or reported, all distinct because they
    call for different actions:

    * ``unparseable`` -- a datadir with no configuration at all makes
      PrusaSlicer 2.9.6 write a log line to **stdout** instead of JSON
      (reproduced 2026-09-06).
    * ``empty`` -- the key is a well-formed but empty list, ``[]``. The engine
      enumerated and found nothing.
    * ``malformed`` -- the key is absent, or is not a list. **This is where G3
      lands**: a vendor bundle with no installed models answers
      ``{"printer_models": ""}``, and ``""`` is a str, not a list. The two are kept
      apart a few lines below on purpose, and this list said the opposite for long
      enough that a numbered decision copied it (``notes/critique.md`` G3; exercised
      with a synthetic payload, not reproduced against a real engine).

    The exit code is deliberately not an input. It is 1 on success (V5).
    """
    text = stdout.strip()
    if not text:
        return Enumeration(PresetsVerdict.UNPARSEABLE, [], "the engine wrote nothing to stdout")
    try:
        document = json.loads(text)
    except json.JSONDecodeError as exc:
        head = text.splitlines()[0][:120] if text.splitlines() else ""
        return Enumeration(
            PresetsVerdict.UNPARSEABLE,
            [],
            f"stdout is not JSON ({exc.msg}); it begins {head!r}",
        )

    if not isinstance(document, dict) or root_key not in document:
        return Enumeration(PresetsVerdict.MALFORMED, [], f"the JSON has no {root_key!r} key")

    entries = document[root_key]
    if not isinstance(entries, list):
        # The G3 shape lands here when the payload is "" rather than []. Both
        # are "nothing", but only one of them is the type we were promised, and
        # conflating them would hide a schema change behind an empty result.
        return Enumeration(
            PresetsVerdict.MALFORMED,
            [],
            f"{root_key!r} is {type(entries).__name__}, not a list (value {entries!r})",
        )
    if not entries:
        return Enumeration(
            PresetsVerdict.EMPTY,
            [],
            f"{root_key!r} is an empty list: the engine enumerated no presets",
        )
    return Enumeration(
        PresetsVerdict.ENUMERATED,
        [e for e in entries if isinstance(e, dict)],
        f"{len(entries)} entries",
    )
