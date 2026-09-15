"""No engine's config-key vocabulary may reach slicelab's core.

`test_boundaries.py` confines engine **identifiers** -- executable names and
Flatpak application ids, six strings computed from `REGISTRY`. That is a
different and much narrower claim than the one `AGENTS.md` makes and than the one
D1's supersede clause is adjudicated by. Under the identifier test alone,
``if "wall_loops" in readback:`` inside a core module is green, and the clause
that decides whether this project should exist goes untested.

`notes/refuted.md`'s "Fatal flaws (judge panel)" section asked for a **stoplist**
of the FFF config-key namespace -- the ~411 `--help-fff` option names. D26 records why this
is a whitelist instead: a list of PrusaSlicer's key names, committed here, is
engine-derived data, and D11 forbids shipping any. Naming slicelab's own
vocabulary costs a dozen entries and refuses everything else by construction.

The rule: a string literal in a core module is either **prose** -- it contains
whitespace -- or it is a term slicelab itself defined and declared below. An
engine config key is neither, because config keys are short and have no spaces.
"""

from __future__ import annotations

import ast
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent.parent / "slicelab"

#: Modules that adjudicate, and so must know no engine's vocabulary. The adapters
#: package is deliberately absent: engine names are exactly what it is for.
CORE_MODULE_NAMES = (
    "status.py",
    "report.py",
    "presets.py",
    "intent.py",
    "digest.py",
    "plan.py",
    "preflight.py",
    "promote.py",
    "container.py",
    "readback.py",
    "redact.py",
    "resolve.py",
    "slicing.py",
    "vocab.py",
)

#: slicelab's own vocabulary, and the only non-prose literals its core may contain.
#: D26: every entry is a term slicelab defined, or a language/encoding constant that
#: names no engine concept. Adding an entry is a decision, made in review, in public.
#: An engine's key name can never be added -- that is what the test exists to refuse.
DECLARED_VOCABULARY = frozenset(
    {
        # Outcome words (D14, D24) and per-key statuses.
        "sliced",
        "refused",
        "incomplete",
        "empty",
        "error",
        "applied",
        "coerced",
        "absent",
        "unsupported",
        "unvalidated",
        # Preset-enumeration verdicts (D17, and G3's fix).
        "enumerated",
        "unparseable",
        "malformed",
        # `UnknownCode` members: what a run could not establish about itself.
        "cross_machine_reproducibility_unestablished",
        "reproducibility_not_established",
        "binary_container_no_normalized_hash",
        # Readback provenance labels (D4's trigger) -- the SHAPE of a readback,
        # never a key inside one.
        "unavailable",
        # Intent-file structure: the table names slicelab defines, and the fields
        # of the validated request. Not any engine's option names -- those live on
        # EngineSpec.base_keys, under adapters/.
        "base",
        "set",
        # What is being sliced and where the result goes (#7). slicelab's own words:
        # both engines take a mesh as a positional argument and neither has an option
        # name for it, which is why these are top-level rather than beside `base` and
        # `set`. Checked against both engines' real key universes before being
        # declared -- zero matches for any of the four in OrcaSlicer 2.4.2's 636-key
        # configured dump or PrusaSlicer 2.9.6's 376-key dump from a real slice, with
        # `layer_height` as the control that the comparison finds anything at all.
        "geometry",
        "model",
        "output",
        "gcode",
        "argv",
        "requested",
        "sidecar",
        "paths",
        # Where a readback lives while it is being made safe, and where it ends up
        # (D7, D31). slicelab's own file plumbing, and checked against both engines'
        # real key universes before being declared: zero matches for either name in
        # PrusaSlicer 2.9.6's dump or OrcaSlicer 2.4.2's, with `layer_height` as the
        # control that the comparison finds anything at all. Both dumps were taken
        # under a preset triple -- the counts are profile-dependent (PrusaSlicer 343
        # bare, 376 stock triple, 381 with the credential family loaded; Orca 616
        # bare, 626 Creality, 639 Artillery) so no single number describes either.
        "staged",
        "destination",
        # The same two, for the artifact rather than the readback (#7, D7). slicelab's
        # own plumbing: where the ENGINE writes the G-code, and where slicelab promotes
        # it on `sliced`. Checked against both engines' key universes -- zero matches
        # for either name, with `layer_height` as the control.
        "staged_artifact",
        "artifact_destination",
        # What `slice` established about one run (#7, D7, D10). slicelab's own record
        # vocabulary: the thing produced, the shape it is in, what stood at the
        # destination before it, and what the engine said on stdout. Checked against
        # both engines' key universes -- zero matches for any of the four, with
        # `layer_height` as the control.
        "artifact",
        "container",
        "destination_prehash",
        "withheld",
        # The attribute a fault carries its withheld artifact's path on. Prefixed
        # with the tool's own name because it is set on exceptions raised elsewhere,
        # where a bare `withheld` would be slicelab writing an unnamespaced attribute
        # onto someone else's object.
        "_slicelab_withheld_artifact",
        "slicelab-readback-",
        # Where the engine slices before slicelab decides whether to hand it over
        # (D7). The same shape as the readback prefix above, and named for this
        # tool rather than for anything an engine says.
        "slicelab-slice-",
        # The suffix on the half-written readback, between the write and the rename
        # (D31). Spelled with the tool's own name rather than a bare `.part`, because
        # `part` is a substring of OrcaSlicer's `part_cooling_fan_min_pwm` and a
        # reader hitting this list should not have to work out which it is.
        ".slicelab-partial",
        # POSIX stream names. `_diagnosis` labels which stream the engine spoke on,
        # because "it said nothing on either stream" and "slicelab dropped it" have
        # to be tellable apart. Neither is a config key on either engine.
        "stderr",
        "stdout",
        # The adjudicated result: one verdict per authored override, and the keys
        # it was compared against. Slicelab's own report vocabulary, not an
        # engine's -- the engine's key names travel in the VALUES of `compared`,
        # which is data, and never as literals here.
        "verdicts",
        "option",
        "status",
        "compared",
        "observed",
        "adjudication",
        "text",
        # D4's word for the engine's own configuration dump, and the mechanism
        # named after it. slicelab's term, not any engine's.
        "readback",
        # Container words (D10). slicelab's report vocabulary for the SHAPE of an
        # artifact, not a key inside one -- `bgcode` is the format's own name and
        # `gcode` says only that a file is not the declared binary magic. Checked
        # against both engines' key universes: zero matches for either, with
        # `layer_height` as the control.
        "bgcode",
        "undetermined",
        # The marker a removed credential leaves. Deliberately not empty, because
        # empty is a value the engine also writes -- a reader must be able to tell
        # "slicelab took this" from "the engine wrote nothing here".
        "<redacted>",
        "overrides",
        "source",
        # Report/lock structural field names slicelab owns.
        "verdict",
        "entries",
        "outcome",
        "reason",
        "keys",
        "keys_checked",
        "unknowns",
        "engine",
        "readback_source",
        "effective_config",
        "values_resolved",
        # Encoding and digest constants. These name no engine concept -- `sha256` is
        # the algorithm `hashlib` is asked for, in the same category as `utf-8`.
        "sha256",
        "utf-8",
        "replace",
        "strict",
        "r",
        "w",
        "rb",
        "wb",
    }
)


def _core_modules() -> list[Path]:
    return [p for name in CORE_MODULE_NAMES if (p := PACKAGE / name).exists()]


def _exempt_nodes(tree: ast.AST) -> set[int]:
    """Ids of Constant nodes that are prose or export plumbing.

    **Docstrings** are prose by definition. **`__all__` entries** are export
    declarations that must equal names defined in the same module; requiring every
    export to be re-declared here would make the vocabulary a duplicate of
    `__all__` and go red on every new public name, which is noise rather than a
    boundary. The narrow abuse -- a public symbol named after an engine key -- is
    caught by the schema-name scan below, not by re-scanning `__all__`.
    """
    out: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            first = node.body[0] if node.body else None
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                out.add(id(first.value))
        elif isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets
        ):
            out.update(id(n) for n in ast.walk(node.value) if isinstance(n, ast.Constant))
    return out


def _declared(text: str) -> bool:
    """Whether a term is prose, punctuation, or something slicelab declared."""
    if any(ch.isspace() for ch in text):
        return True
    if not any(ch.isalnum() for ch in text):
        return True
    return text.strip("_").lower() in DECLARED_VOCABULARY


def _schema_names(tree: ast.AST) -> list[str]:
    """Names in the two class-body positions that carry a data vocabulary.

    Scanning string literals alone is not enough, and the gap is not exotic --
    it is this codebase's own dominant idiom. ``Outcome``, ``KeyStatus``,
    ``UnknownCode`` and ``PresetsVerdict`` are all ``StrEnum``, and in a
    ``StrEnum`` ``WALL_LOOPS = auto()`` has the *value* ``"wall_loops"`` with no
    such literal anywhere in the file. A dataclass field ``wall_loops: int`` is
    the same leak in the shape a readback struct most wants to take.

    Deliberately NOT every identifier. Function and module names are slicelab's
    own plumbing and scanning them would turn the vocabulary into the dumping
    ground D26's supersede clause warns about. Class-body assignments and
    annotated fields are where a *data* vocabulary lands.
    """
    out: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for stmt in node.body:
            if isinstance(stmt, ast.Assign):
                out += [tgt.id for tgt in stmt.targets if isinstance(tgt, ast.Name)]
            elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                out.append(stmt.target.id)
    return out


def undeclared_terms(source: str, filename: str = "<test>") -> list[str]:
    """Every non-prose string literal in `source` that slicelab has not declared.

    Prose is anything containing whitespace: an error message, a sentence, a hint.
    A config key is short and unspaced, so it cannot hide as prose, and it cannot
    pass as vocabulary without someone adding it to DECLARED_VOCABULARY in a diff.
    """
    tree = ast.parse(source, filename=filename)
    skip = _exempt_nodes(tree)
    found: list[str] = []
    for name in _schema_names(tree):
        if not _declared(name):
            found.append(name)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant):
            continue
        if isinstance(node.value, bytes):
            # `b"wall_loops" in readback` is the same decision as the str form.
            decoded = node.value.decode("utf-8", errors="replace")
            if not _declared(decoded):
                found.append(decoded)
            continue
        if not isinstance(node.value, str):
            continue
        if id(node) in skip:
            continue
        text = node.value
        if any(ch.isspace() for ch in text):
            continue
        # Punctuation and separators carry no concept, engine-derived or otherwise.
        if not any(ch.isalnum() for ch in text):
            continue
        if text in DECLARED_VOCABULARY:
            continue
        found.append(text)
    return sorted(set(found))


def test_no_engine_vocabulary_in_core_modules() -> None:
    """The claim D1's supersede clause is actually adjudicated by."""
    offenders: list[str] = []
    for path in _core_modules():
        terms = undeclared_terms(path.read_text(encoding="utf-8"), str(path))
        offenders += [f"{path.name} names {term!r}" for term in terms]
    assert offenders == [], (
        "undeclared non-prose terms reached slicelab's core: "
        + "; ".join(offenders)
        + ". If one is an engine's config key, it belongs under slicelab/adapters/. "
        "If it is slicelab's own, add it to DECLARED_VOCABULARY and say so in review."
    )


def test_the_checker_catches_an_engine_key() -> None:
    """Red-capability, proven here rather than asserted.

    Org contract §2.4: a check whose red state you have not observed is not a
    check. This one's red state cannot be observed by breaking the source tree,
    because the whole point is that the source tree is clean -- so the checker is
    run against a module that is deliberately dirty.

    `wall_loops` is OrcaSlicer's; `perimeters` is PrusaSlicer's. Both appear here,
    in a test, which is not a core module -- that is the seam being exercised.
    """
    dirty = 'def f(readback):\n    return "wall_loops" in readback or readback["perimeters"]\n'
    assert undeclared_terms(dirty) == ["perimeters", "wall_loops"]


def test_the_checker_catches_the_forms_a_literal_scan_misses() -> None:
    """The three bypasses an earlier revision of this file shipped.

    A literal-only scan is not enough, and the gap is this codebase's own
    dominant idiom rather than an exotic one: every status vocabulary here is a
    ``StrEnum``, and ``WALL_LOOPS = auto()`` has the value ``"wall_loops"`` with
    no such literal in the file. Measured against both installed engines,
    ``wall_loops`` is a real OrcaSlicer key and ``perimeters`` a real
    PrusaSlicer one.
    """
    enum_form = "from enum import StrEnum, auto\nclass K(StrEnum):\n    WALL_LOOPS = auto()\n"
    field_form = "from dataclasses import dataclass\n@dataclass\nclass R:\n    wall_loops: int\n"
    bytes_form = 'def f(rb: bytes) -> bool:\n    return b"wall_loops" in rb\n'
    assert undeclared_terms(enum_form) == ["WALL_LOOPS"]
    assert undeclared_terms(field_form) == ["wall_loops"]
    assert undeclared_terms(bytes_form) == ["wall_loops"]


def test_slicelabs_own_enums_and_fields_are_not_flagged() -> None:
    """A guard on the guard: the schema scan must not be red on our own vocabulary."""
    ours = 'from enum import StrEnum\nclass Outcome(StrEnum):\n    SLICED = "sliced"\n'
    assert undeclared_terms(ours) == []


def test_prose_is_not_flagged() -> None:
    """A guard on the guard: the rule must not be red on every error message."""
    prose = 'def f():\n    raise ValueError("the engine wrote no configuration")\n'
    assert undeclared_terms(prose) == []


def test_the_core_module_list_is_not_vacuous() -> None:
    """`_core_modules` filters to what exists, so an empty list would pass silently."""
    present = _core_modules()
    assert present, "no core module was found; the boundary test is checking nothing"
    assert (PACKAGE / "status.py") in present


def test_every_module_that_exists_and_should_be_core_is_scanned() -> None:
    """The `.exists()` filter is how a new core module arrives unscanned in silence.

    `CORE_MODULE_NAMES` names modules issue #5 and #6 have not created yet, so it
    cannot be a required set outright. What it CAN be is closed against the
    package: any module directly under `slicelab/` that is not named here and not
    on the deliberate-exclusion list is a module nobody decided about.

    `cli.py` is excluded deliberately, not by oversight: it is argparse plumbing
    and scanning it flags nine terms that are all slicelab's own verb and flag
    names. `__init__.py` and `__main__.py` hold no vocabulary.
    """
    excluded = {"cli.py", "__init__.py", "__main__.py"}
    on_disk = {p.name for p in PACKAGE.glob("*.py")}
    undecided = on_disk - set(CORE_MODULE_NAMES) - excluded
    assert undecided == set(), (
        f"modules under slicelab/ that are neither scanned nor deliberately excluded: "
        f"{sorted(undecided)}. Add each to CORE_MODULE_NAMES or to the exclusion list "
        "with a reason."
    )
