"""Reported numbers, each carrying where it came from.

A number in `slice.lock` that nobody can trace is the section 2.3 failure in its
smallest form: a plausible substitute for a measured value. So a stat is not a
number here. It is a number **and** its source, and the two cannot be separated --
:class:`Stat` refuses to exist without both, which is why there is a class at all
rather than a `dict[str, float]`.

The other half is absence. TOML has no null, so a stat that could not be measured
cannot be written as one; and omitting the key makes "slicelab looked and the
engine would not say" indistinguishable from "slicelab never looked". Both of those
are reported, differently: a measured stat carries `value`, an unmeasurable one
carries `reason` and no `value`, and exactly one of the two is always set.

The case that forces it, measured on PrusaSlicer 2.9.6 (Flatpak, Debian 13) on
2026-10-05 with a 20 mm cube and the MK3S triple:

    stock                      --filament-density=0
    ; filament used [mm] = 1251.87    ; filament used [mm] = 1251.87
    ; filament used [g]  = 3.73       (the line is absent)
    ; total filament used [g] = 3.73  ; total filament used [g] = 0.00
    ; filament_density = 1.24         ; filament_density = 0

The extrusion is identical and real. The mass is `0.00` because the profile says
the filament weighs nothing per cm3, and anything that reads that number learns
the print is weightless. The issue recorded this for OrcaSlicer; it is PrusaSlicer
too, with a twist -- the per-object line vanishes while the *total* keeps printing
a zero. So the detector is the declared density, not the suspicious zero.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

__all__ = ["Stat", "StatError"]


class StatError(ValueError):
    """A stat was constructed with no source, or with both a value and a reason."""


@dataclass(frozen=True)
class Stat:
    """One reported number, or one recorded reason there is none.

    `source` says what kind of place the number came from and `key` is that place's
    own name for it, verbatim -- `; filament used [mm]`, `;LAYER_CHANGE`. Keeping
    the engine's spelling is what lets a reader check the claim against the
    artifact without knowing how slicelab is built.
    """

    source: str
    key: str
    value: float | int | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if not self.source or not self.key:
            raise StatError("a stat carries its source and that source's own key, always")
        if (self.value is None) == (self.reason is None):
            raise StatError(
                f"{self.key!r}: a stat is a value or a reason there is none, never both "
                f"and never neither (value={self.value!r}, reason={self.reason!r})"
            )

    @property
    def measured(self) -> bool:
        return self.value is not None

    def as_table(self) -> dict[str, float | int | str]:
        """The TOML table for this stat.

        `value` is omitted rather than nulled when there is none, because TOML has
        no null and a `0` would be read as a measurement.
        """
        table: dict[str, float | int | str] = {"source": self.source, "key": self.key}
        if self.value is not None:
            table["value"] = self.value
        if self.reason is not None:
            table["reason"] = self.reason
        return table


#: Why a mass is not recorded even though the engine printed one.
DENSITY_ZERO: Final = "filament_density_zero"

#: Why a per-filament figure is not recorded as the print's.
#:
#: This engine writes `; filament used [mm] = 1251.87, 300.00` on a multi-material
#: print and states no `total filament used [mm]` to go with it -- unlike the mass,
#: which has one. So there is no measured total for that field, and summing the parts
#: would be slicelab's arithmetic carrying the engine's key.
PER_FILAMENT_LIST: Final = "per_filament_list_with_no_stated_total"

#: Why a figure the engine printed is not recorded as a number.
NOT_A_NUMBER: Final = "engine_printed_a_value_that_is_not_a_number"

#: Why no artifact-derived stat is recorded at all.
CONTAINER_NOT_TEXT: Final = "container_carries_no_text_footer"
