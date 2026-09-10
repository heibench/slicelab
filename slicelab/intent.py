"""Reading a `slice.toml`, and refusing everything about it that is not understood.

D13: the parser is `tomllib.load` plus a validator and **nothing else**. No
expressions, no includes, no interpolation, no tags. The moment this file can
compute, org contract section 4 applies to it and D13's adjudication is void --
`slicelab resolve part.slice.toml` would be executing the author's code to decide a
wall thickness, which is netspec D24's process-isolation cost imported for nothing.

The vocabulary is closed and typed, and an unknown key is **refused at exit 1**,
never ignored. That is the whole reason a `slice.toml` can be trusted to say what it
means: PrusaSlicer itself drops an unrecognised key from a `--load`ed ini at exit 0
with zero bytes on stderr [V2], and slicelab exists because that is not acceptable.
Doing the same thing one layer up would be the joke telling itself.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import TypeAlias

from slicelab.vocab import BASE_TABLE, ENGINE_TABLES, SET_TABLE

__all__ = ["Intent", "IntentError", "IntentValue", "read_intent"]

IntentValue: TypeAlias = str | int | float | bool
"""What an authored override may be.

Types are **preserved**, not stringified here. How a value reaches an engine is a
fact about that engine and lives in its adapter: PrusaSlicer 2.9.6 accepts
`--spiral-vase=1` and resolves `--spiral-vase=true` to `0` -- silently, at exit 0,
giving the author the opposite of what they wrote. A parser that flattened `true` to
`"true"` would hand the adapter a decision it could no longer see.
"""


class IntentError(Exception):
    """The intent file was not understood, so no run is attempted.

    `refused` at exit 1: slicelab established the request cannot be honoured as
    written. This is the pre-flight refusal D15 describes -- it happens before the
    engine is touched, and it is the outcome word's remaining home now that D27
    routes a coerced key to `incomplete`.
    """


@dataclass(frozen=True)
class Intent:
    """One authored request, validated but not yet planned."""

    engine: str
    base: dict[str, str]
    overrides: dict[str, IntentValue]
    source: Path

    @property
    def subject_set_is_empty(self) -> bool:
        """Whether this run will verify nothing (D24, `notes/critique.md` G1).

        A `[base]` triple with no overrides produces a real artifact and adjudicates
        **zero** keys, so "every requested key was applied" is vacuously true. That
        run is `empty` at exit 3, never `sliced`.
        """
        return not self.overrides


def _require_mapping(value: object, what: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise IntentError(f"{what} must be a table, not {type(value).__name__}")
    return value


def read_intent(path: Path) -> Intent:
    """Parse and validate a `slice.toml`, or refuse it with a named reason."""
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise IntentError(f"cannot read {path}: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise IntentError(f"{path} is not valid TOML: {exc}") from exc

    engines = sorted(raw)
    if not engines:
        raise IntentError(f"{path} declares no engine table")
    if len(engines) > 1:
        raise IntentError(
            f"{path} declares more than one engine table ({', '.join(engines)}); "
            "one run drives one engine"
        )
    engine = engines[0]

    table = _require_mapping(raw[engine], f"[{engine}]")
    unknown = sorted(set(table) - ENGINE_TABLES)
    if unknown:
        raise IntentError(
            f"[{engine}] has no {', '.join(repr(k) for k in unknown)} "
            f"({', '.join(sorted(ENGINE_TABLES))} are the only tables)"
        )

    base = _read_base(table.get(BASE_TABLE), engine)
    overrides = _read_overrides(table.get(SET_TABLE), engine)
    return Intent(engine=engine, base=base, overrides=overrides, source=path)


def _read_base(value: object, engine: str) -> dict[str, str]:
    """Validate the SHAPE of the preset table. Which keys belong is the adapter's.

    `[base]` must exist, be a table, and carry non-empty string values. It must not
    be empty: zero presets is accepted by PrusaSlicer at exit 0 and yields generic
    Slic3r built-ins -- `layer_height 0.3`, `gcode_flavor reprap`, an empty
    `printer_model` -- the defaults trap arriving as a success (D16).

    **Which** names are required is engine knowledge and lives on `EngineSpec.base_keys`,
    checked at pre-flight (D15). PrusaSlicer addresses a triple by name; OrcaSlicer has
    no such flag and takes file paths instead, so a constant here naming PrusaSlicer's
    three would be the abstraction D2 refuses -- and `test_names_confined.py` refuses it
    structurally, which is how this landed in the adapter rather than in the core.
    """
    if value is None:
        raise IntentError(
            f"[{engine}.{BASE_TABLE}] is required. Naming no presets at all is "
            "accepted by the engine and yields generic built-ins, which is the "
            "defaults trap arriving as a success"
        )
    table = _require_mapping(value, f"[{engine}.{BASE_TABLE}]")
    if not table:
        raise IntentError(f"[{engine}.{BASE_TABLE}] is empty")

    named: dict[str, str] = {}
    for key in sorted(table):
        if key.startswith("-"):
            raise IntentError(
                f"[{engine}.{BASE_TABLE}] {key!r} is written as a flag; author the "
                "option name without leading dashes"
            )
        name = table[key]
        if not isinstance(name, str):
            raise IntentError(
                f"[{engine}.{BASE_TABLE}] {key} must be a preset name, not {type(name).__name__}"
            )
        if not name.strip():
            raise IntentError(f"[{engine}.{BASE_TABLE}] {key} is empty")
        named[key] = name
    return named


def _read_overrides(value: object, engine: str) -> dict[str, IntentValue]:
    """The authored delta. May be absent or empty -- that run is `empty`, not wrong."""
    if value is None:
        return {}
    table = _require_mapping(value, f"[{engine}.{SET_TABLE}]")

    out: dict[str, IntentValue] = {}
    for key in sorted(table):
        if key.startswith("-"):
            raise IntentError(
                f"[{engine}.{SET_TABLE}] {key!r} is written as a flag; author the "
                "option name without leading dashes"
            )
        raw = table[key]
        if isinstance(raw, bool):
            out[key] = raw
        elif isinstance(raw, str):
            if not raw:
                raise IntentError(
                    f"[{engine}.{SET_TABLE}] {key} is empty, and an empty value is not "
                    "expressible: the engine answers 'No value supplied'. Clearing a "
                    "key is refused here rather than silently doing nothing (D5)"
                )
            out[key] = raw
        elif isinstance(raw, int | float):
            out[key] = raw
        else:
            raise IntentError(
                f"[{engine}.{SET_TABLE}] {key} is {type(raw).__name__}; an override is "
                "a string, number or boolean"
            )
    return out
