"""Rendering an outcome for a human.

One rule, and it is a test rather than a style note: **the first token of
output is always the outcome word.**

A past-tense verb leading a non-zero run reads green to someone skimming CI
logs. One of the architectures proposed during research printed
``sliced part.gcode 100 layers 24m42s 1 override coerced`` on a run that exited
2 -- every fact in that line true, and the line as a whole a lie about the run.
See ``docs/DECISIONS.md`` D14.
"""

from __future__ import annotations

from slicelab.status import Outcome

__all__ = ["render"]


def render(outcome: Outcome, summary: str = "", detail: list[str] | None = None) -> str:
    """Render an outcome as text whose first token is the outcome word.

    Args:
        outcome: what slicelab is willing to say about the run.
        summary: a short clause completing the first line. No leading capital;
            it follows a colon.
        detail: further lines, indented two spaces under the first.
    """
    head = outcome.value if not summary else f"{outcome.value}: {summary}"
    lines = [head]
    lines.extend(f"  {line}" for line in detail or ())
    return "\n".join(lines)
