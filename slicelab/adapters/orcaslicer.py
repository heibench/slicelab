"""OrcaSlicer."""

from __future__ import annotations

import json
from collections.abc import Mapping

from slicelab.adapters.base import EngineSpec, OptionProbe


def _options_from_settings_keys(listing: str, baseline: Mapping[str, str]) -> tuple[str, ...]:
    """Candidate option names, derived from the keys Orca dumps.

    ``listing`` is always empty: Orca 2.4.2 has no ``--help-fff`` and its
    ``--help`` describes about fifty driver options and not one config option.
    But its help also states "setting values from the command line (highest
    priority)", and that is measured true -- ``--wall-loops=3`` exits 0, writes a
    616-key settings dump, and ``wall_loops`` is the single key that moved.

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
    document = json.loads(text)
    if not isinstance(document, dict):
        return {}
    return {
        key: value if isinstance(value, str) else json.dumps(value, sort_keys=True)
        for key, value in document.items()
    }


PROBE = OptionProbe(
    # Orca's spellings for the same eight shapes PrusaSlicer's probe uses. A
    # percent and a bare number are both real Orca value forms: `accel_to_decel_factor`
    # is `50%` and `wall_loops` is `2` in the default dump.
    sentinels=("SLICELABPROBE", "7", "0.17", "37%", "1", "3x4", "0x0,7x0,7x7,0x7", "0.37,0.37"),
    # Empty, and that is a measurement rather than an omission. Orca 2.4.2 answers
    # `setup params error` at rc=254 for BOTH an option it does not have and a bad
    # value for one it does, having written no artifact either time. The two cases
    # are indistinguishable from outside, so the probe cascades its sentinels over
    # an option that does not exist and records the honest `rejected` -- slower
    # than PrusaSlicer, and not a claim Orca never made.
    unknown_option="",
    candidates=_options_from_settings_keys,
    read_config=_read_settings_json,
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
    # Measured 2026-09-10 on 2.4.2: rc=0, a 616-key dump, and the requested key
    # is the only one that moved.
    readback_flag="--export-settings",
    option_probe=PROBE,
)
