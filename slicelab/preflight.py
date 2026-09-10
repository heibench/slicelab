"""Everything slicelab can refuse before the engine is reached.

D15 draws the line: where **slicelab composed the offending argv**, it refuses
pre-flight at exit 1 rather than launching and reporting what came back. That is not
tidiness. A partial `[base]` triple is a deterministic SIGSEGV on 2.9.6 -- `rc=139`,
zero bytes on stdout *and* stderr, for every action including `--info` [V6] -- and
the byte-identical signature was also reproduced from an unrelated flag. So the
observation carries no cause, and reporting it as a finding about the author's
preset names would attribute a crash slicelab caused to a design it never read.

This is `refused`'s remaining home. D27 routes a coerced key to `incomplete`, so
after it the only readback-derived route to exit 1 is `unsupported`, which D2 makes
unreachable while the core vocabulary is empty. What still refuses is this: requests
slicelab will not compose.
"""

from __future__ import annotations

from slicelab.adapters import EngineSpec, spec_for
from slicelab.intent import Intent, IntentValue

__all__ = ["PreflightError", "preflight"]


class PreflightError(Exception):
    """slicelab will not compose this request. `refused`, exit 1, engine untouched."""


def preflight(intent: Intent) -> EngineSpec:
    """Resolve the adapter for an intent, or refuse with a named reason."""
    spec = spec_for(intent.engine)
    if spec is None:
        raise PreflightError(
            f"no adapter for {intent.engine!r}; {intent.source} names an engine "
            "slicelab does not drive"
        )
    _check_base(intent, spec)
    _check_override_types(intent, spec)
    return spec


def _check_base(intent: Intent, spec: EngineSpec) -> None:
    """The preset table must be exactly what this engine addresses presets with."""
    if not spec.base_keys:
        raise PreflightError(
            f"{spec.name} has not declared what a [{spec.name}.base] table contains, "
            "so slicelab cannot check one. Falling back to another engine's preset "
            "flags would assume a mapping that does not exist"
        )

    authored = set(intent.base)
    required = set(spec.base_keys)
    missing = [k for k in spec.base_keys if k not in authored]
    extra = sorted(authored - required)

    if extra:
        raise PreflightError(
            f"[{intent.engine}.base] has no {', '.join(repr(k) for k in extra)}; "
            f"{spec.name} addresses presets with {', '.join(spec.base_keys)}"
        )
    if missing:
        raise PreflightError(
            f"[{intent.engine}.base] is missing {', '.join(missing)}. All of "
            f"{', '.join(spec.base_keys)} are required: on PrusaSlicer 2.9.6 any "
            "proper non-empty subset crashes the engine with no diagnostic on either "
            "stream, so slicelab refuses rather than composing a run whose failure it "
            "could not then attribute"
        )


def _check_override_types(intent: Intent, spec: EngineSpec) -> None:
    """Refuse a value this engine has not told us how to spell."""
    if spec.bool_words is not None:
        return
    booleans = [k for k, v in intent.overrides.items() if isinstance(v, bool)]
    if booleans:
        raise PreflightError(
            f"boolean overrides {', '.join(sorted(booleans))}: how {spec.name} "
            "spells true on the command line has not been measured. Guessing is the "
            "one thing that must not happen here: on the engine that HAS been "
            "measured, a boolean option validates nothing and any value that is not "
            "its true-word resolves to false, silently, at exit 0"
        )


def render(value: IntentValue, spec: EngineSpec) -> str:
    """One authored value as this engine's command line spells it.

    Everything but a boolean is `str()`. D5 established `--key=value` carries every
    type -- int, float, percent, enum, comma-list, semicolon-list, multiline G-code
    and bracket template -- so no per-key type knowledge is needed and no option
    catalogue has to be vendored (D11).

    A boolean is the exception, and `bool_words` is why: `str(True)` is `"True"`,
    which PrusaSlicer resolves to **false**.
    """
    if isinstance(value, bool):
        if spec.bool_words is None:  # pragma: no cover - preflight refuses first
            raise PreflightError(f"{spec.name} has no measured spelling for a boolean")
        true_word, false_word = spec.bool_words
        return true_word if value else false_word
    return str(value)
