"""OrcaSlicer."""

from __future__ import annotations

import json
from collections.abc import Mapping

from slicelab.adapters.base import (
    ConfigLocation,
    EngineSpec,
    Invocation,
    OptionProbe,
    RunRecord,
)
from slicelab.redact import REDACTED


def _options_from_settings_keys(listing: str, baseline: Mapping[str, str]) -> tuple[str, ...]:
    """Candidate option names, derived from the keys Orca dumps.

    ``listing`` is always empty: Orca 2.4.2 has no ``--help-fff`` and its
    ``--help`` describes about fifty driver options and not one config option.
    But its help also states "setting values from the command line (highest
    priority)", and that is measured true -- ``--wall-loops=3`` exits 0, writes a
    settings dump -- 616 keys with no profile loaded, which is the configuration the
    probe baselines against -- and ``wall_loops`` is the single key that moved.

    So the candidates come from the dump's own keys instead, dashed. **That
    transform is a guess about what to try, never a claim about what it writes.**
    The distinction is the whole of G2: the probe sets the option and watches
    which key moves, so a candidate that is misspelled, aliased, or writes some
    entirely different key costs one rejected invocation and produces no map
    entry. A transform used as the answer is what reported a correct run as
    ``absent``; a transform used as a list of things to ask about cannot.

    The cost of that is a real limit rather than a hedge: an option whose name is
    *not* the dashed form of any key is never asked about, so this list can
    under-produce where PrusaSlicer's cannot. Orca states no option list, and
    inventing entries for one would be substituting slicelab's inventory for an
    answer the engine never gave.
    """
    del listing
    return tuple(key.replace("_", "-") for key in sorted(baseline))


def _read_settings_json(text: str) -> Mapping[str, str]:
    """An Orca ``--export-settings`` dump as key/value pairs.

    Values are ``str`` or ``list[str]`` -- the per-extruder keys are lists -- and
    a list is rendered as JSON rather than joined, so that ``["1", "0"]`` and
    ``["1,0"]`` stay different. The readback diff compares these for equality and
    a rendering that collapses two states into one string would report a key as
    unchanged that changed.
    """
    seen: list[str] = []

    def keep_every_pair(pairs: list[tuple[str, object]]) -> dict[str, object]:
        seen.extend(key for key, _ in pairs)
        return dict(pairs)

    document = json.loads(text, object_pairs_hook=keep_every_pair)
    if not isinstance(document, dict):
        return {}

    # DETECTED, not tolerated. JSON permits a repeated key and `json.loads` keeps the
    # last one without a word, so a dump carrying `wipe_tower_x` twice -- as `15.000`
    # and as `15` -- parses to one value and loses the other silently. Which one
    # survives is then an artifact of file order, and a readback diff comparing
    # against it reports `applied` or `coerced` depending on nothing the author can
    # see.
    #
    # Not reproduced on 2.4.2: a 616-key bare dump and a 634-key configured one both
    # parse with zero repeats, checked by counting the pairs the hook saw against the
    # dict it built. That is why this refuses rather than resolving -- there is no
    # measured case saying which of two values the engine meant, so inventing a rule
    # would be a guess about an engine that has never done this.
    if len(seen) != len(document):
        repeated = sorted({key for key in seen if seen.count(key) > 1})
        raise ValueError(
            f"the settings dump repeats {', '.join(repeated)}, and which value a "
            "parser keeps is an artifact of file order rather than anything the "
            "engine stated"
        )

    return {
        key: value if isinstance(value, str) else json.dumps(value, sort_keys=True)
        for key, value in document.items()
    }


#: The three profiles an Orca run loads, in the order its flags take them.
#: slicelab's own words for the three kinds, NOT preset names: Orca has no
#: preset-enumeration verb (`preset_query=None`), so naming a preset would mean
#: slicelab locating a file the engine never told it about -- org contract 2.3.
#: These are paths, and the author states them.
_BASE_KEYS = ("machine", "process", "filament")


def _load_profiles(base: Mapping[str, str]) -> Invocation:
    """`[orcaslicer.base]` -> the argv that loads those three profiles.

    PrusaSlicer takes one flag per preset and names them; Orca takes
    ``--load-settings`` for process and machine and ``--load-filaments`` for
    filament, with file paths. Measured on 2.4.2: the flag REPEATS -- two
    ``--load-settings`` are both honoured, and the dump carries the machine's
    ``printer_settings_id`` and the process's ``layer_height`` together -- so the
    documented ``"a.json;b.json"`` form is not needed, and a separator inside a TOML
    value is not forced on the author.

    Inheritance is Orca's to resolve and it does: every stock profile here carries
    ``inherits``, and a triple naming three of them resolves at rc=0 with the
    inherited values present. Reimplementing that resolution is forbidden by org
    contract 3, and this measurement is why it never has to be.

    The paths are returned alongside the argv because they are what the engine must
    be granted (D19). A profile slicelab failed to grant does not fail loudly: with
    an ungranted path, 2.4.2 exits **0**, writes nothing, and says nothing on either
    stream -- this org's founding failure shape, measured on this host.
    """
    return Invocation(
        argv=(
            f"--load-settings={base[_BASE_KEYS[0]]}",
            f"--load-settings={base[_BASE_KEYS[1]]}",
            f"--load-filaments={base[_BASE_KEYS[2]]}",
        ),
        paths=frozenset(base[key] for key in _BASE_KEYS),
    )


def _redact_settings_json(text: str, secret_keys: tuple[str, ...]) -> str:
    """Replace the values of `secret_keys` in an Orca settings dump.

    Parsed and re-serialised rather than edited line by line. Every credential Orca
    carries happens to be a single-line string today, so a line edit would work and
    would keep the bytes -- but 185 of the dump's keys hold lists spanning several
    lines, and a line-based rule silently misses one the day a credential is list-
    valued. `redact.py` verifies the result, so such a miss would be loud rather than
    silent; it is still not a rule worth writing.

    The cost is stated rather than hidden: Orca's promoted readback is slicelab's
    re-serialisation of the engine's JSON, not the engine's bytes. Key order and every
    value survive -- `redact.py` checks that key by key -- and JSON carries no comments
    to lose. The tab indent matches what 2.4.2 writes.
    """
    document = json.loads(text)
    wanted = set(secret_keys)
    for key in document:
        if key in wanted:
            document[key] = REDACTED
    return json.dumps(document, indent="\t", ensure_ascii=False) + "\n"


def _read_result_json(text: str) -> tuple[int | None, str]:
    """Orca's `result.json` -> its own return code and error string.

    Measured on 2.4.2, and the reason this is read at all: the shell sees the code
    truncated to a byte. An internal `-3` -- "The input files to the slicer are not
    found." -- arrives as 253, and `-5` -- "The input preset file is invalid and can
    not be parsed." -- as 251. Reporting 253 attributes to the engine a number it
    never chose.

    Written on success too: a clean run leaves `{"return_code": 0, "error_string":
    "Success.", ...}` in the working directory, which is why it is also the litter
    D20 requires be recorded rather than silently swept.

    A record that will not parse yields `(None, ...)` rather than a code: a file
    slicelab could not read establishes nothing about the run, and inventing a code
    for it is the substitution org contract 2.3 refuses.
    """
    try:
        document = json.loads(text)
    except (TypeError, ValueError):
        return None, "the engine's run record could not be parsed"
    if not isinstance(document, dict):
        return None, "the engine's run record was not an object"
    code = document.get("return_code")
    message = document.get("error_string")
    return (
        code if isinstance(code, int) else None,
        message if isinstance(message, str) else "",
    )


PROBE = OptionProbe(
    # Orca's spellings for the same eight shapes PrusaSlicer's probe uses. A
    # percent and a bare number are both real Orca value forms: `accel_to_decel_factor`
    # is `50%` and `wall_loops` is `2` in the default dump.
    sentinels=(
        ("SLICELABPROBE", "SLICELABOTHER"),
        ("7", "3"),
        ("0.17", "0.29"),
        ("37%", "61%"),
        ("1", "0"),
        ("3x4", "5x6"),
        ("0x0,7x0,7x7,0x7", "0x0,9x0,9x9,0x9"),
        ("0.37,0.37", "0.53,0.53"),
    ),
    # Empty, and that is a measurement rather than an omission. Orca 2.4.2 answers
    # `setup params error` at rc=254 for BOTH an option it does not have and a bad
    # value for one it does, having written no artifact either time. The two cases
    # are indistinguishable from outside, so the probe cascades its sentinels over
    # an option that does not exist and records the honest `rejected` -- slower
    # than PrusaSlicer, and not a claim Orca never made.
    unknown_option="",
    candidates=_options_from_settings_keys,
)

SPEC = EngineSpec(
    name="orcaslicer",
    posix_exec="orca-slicer",
    windows_exec="orca-slicer.exe",
    flatpak_app_id="com.orcaslicer.OrcaSlicer",
    macos_exec=("OrcaSlicer", "orca-slicer"),
    # OrcaSlicer 2.4.2 has NO preset-enumeration verb. Measured against its
    # --help: it has --load-settings and --load-filaments, which CONSUME
    # profile files, and nothing that reports which presets exist.
    #
    # None is the honest answer. slicelab could enumerate its profile
    # directories and present the result as "Orca's presets", and that would be
    # slicelab's inventory rather than the engine's -- a plausible substitute
    # for an answer the engine never gave (org contract 2.3).
    preset_query=None,
    # V11's measurement, wired. The ini-versus-JSON split is the fact that makes
    # the readback seam real rather than a PrusaSlicer trick (base.py), and it
    # cannot be exercised while the flag that produces the JSON is unset.
    # Measured 2026-09-10 on 2.4.2: rc=0, a 616-key dump with no profile loaded,
    # and the requested key is the only one that moved. Under a profile the dump is
    # larger and the count varies by profile -- 626 for V11's Creality triple, 639
    # for an Artillery one -- so the figure is stated with what it counts.
    # Measured on this host: ~/.var/app/com.orcaslicer.OrcaSlicer/config/OrcaSlicer/,
    # with `OrcaSlicer.conf` written once configured. Same reasoning as PrusaSlicer's:
    # only the form that is installed here is declared.
    config_location=ConfigLocation(marker="OrcaSlicer.conf", flatpak="OrcaSlicer"),
    readback_flag="--export-settings",
    readback_suffix=".readback.json",
    run_record=RunRecord(name="result.json", read=_read_result_json),
    read_readback=_read_settings_json,
    redact_readback=_redact_settings_json,
    # Measured on 2.4.2, not inherited from PrusaSlicer's list. A stock Sovol triple
    # emits none of these -- 625 keys, zero credential-bearing -- so a guard written
    # against that dump would have found nothing and reported the engine clean. A
    # machine profile with upload configured resolves to a dump carrying all seven
    # verbatim, which is the same value-dependent key set PrusaSlicer has.
    #
    # Established against the ENGINE'S OWN criterion rather than by judgement: the
    # G-code footer is the same configuration reached another way, and what it strips
    # is what this engine treats as unsafe to keep. Measured on 2.4.2 with a machine
    # profile setting all eleven host keys -- the footer strips exactly these seven.
    #
    # `host_type`, `printhost_authorization_type`, `printhost_ssl_ignore_revoke` and
    # `bbl_use_printhost` survive into the footer, so the engine keeps them and so does
    # slicelab: they state how the printer is reached, not a secret for reaching it.
    # `flashforge_serial_number` is the same -- it lands in the dump and the footer
    # keeps it.
    secret_keys=(
        "print_host",
        # Orca's "Device UI" field, and NOT a PrusaSlicer key -- 2.9.6's binary has no
        # such spelling. It was missed because this list was built by name-matching
        # against PrusaSlicer's, which is a method that cannot find a key the other
        # engine does not have. It holds a URL rendered in an embedded webview with no
        # separate credential field, so `http://user:pass@host/` is the ordinary way to
        # give it auth, and 2.4.2 carries that verbatim into the dump.
        "print_host_webui",
        "printhost_apikey",
        "printhost_cafile",
        "printhost_password",
        "printhost_port",
        "printhost_user",
    ),
    base_keys=_BASE_KEYS,
    compose_base=_load_profiles,
    option_probe=PROBE,
)
