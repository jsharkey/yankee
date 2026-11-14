"""Segment-bar layouts: a colour per segment, built from "night"/"signal" slots.

For segment lights (product 170 IOTBT4E8, 173 IOTBT6BA) that take one colour
per segment (E1 03). A layout is a space-separated list of slots, each
optionally repeated with "*N":

    night*8 black*9 signal

"night" becomes the night colour while the night switch is on (black when
off), "signal" becomes the colour picked in the signal select, and anything
else is a fixed colour name or RRGGBB.
"""
from __future__ import annotations

from . import dazzle_multicolor as dm

NIGHT = "night"
SIGNAL = "signal"

# Products whose firmware takes per-segment colours (E1 03) rather than the
# per-LED EC 01 commands of the IOTBTCC3 (197).
SEGMENT_PRODUCT_IDS = {170, 173}


class LayoutError(ValueError):
    """A layout, colour or colour list could not be parsed."""


def check_color(name: str) -> str:
    """Validate one colour (name or RRGGBB) and return it normalised."""
    try:
        dm.parse_color(name)
    except ValueError as err:
        raise LayoutError(str(err)) from None
    return name.strip().lower().lstrip("#")


def parse_layout(text: str) -> list[str]:
    """'night*8 black*9 signal' -> ['night', ..., 'black', ..., 'signal']."""
    slots: list[str] = []
    for token in (text or "").replace(",", " ").split():
        name, _, count = token.partition("*")
        name = name.strip().lower()
        try:
            n = int(count) if count else 1
        except ValueError:
            raise LayoutError(f"bad repeat count in {token!r}") from None
        if n < 1:
            raise LayoutError(f"bad repeat count in {token!r}")
        if name not in (NIGHT, SIGNAL):
            name = check_color(name)
        slots += [name] * n
    if not slots:
        raise LayoutError("the layout is empty")
    if len(slots) > 255:
        raise LayoutError(f"{len(slots)} segments; at most 255")
    return slots


def parse_color_list(text: str) -> dict[str, str]:
    """Signal options: 'black, red, yellow=ff4400' -> {label: colour}, in order.

    Each entry is a colour (name or RRGGBB), or label=colour to show a friendly
    name in the select while sending a different colour."""
    out: dict[str, str] = {}
    for part in (text or "").replace(",", " ").split():
        label, sep, color = part.partition("=")
        label = label.strip().lower()
        if sep and not label:
            raise LayoutError(f"missing label in {part!r}")
        c = check_color(color if sep else label)
        out.setdefault(label if sep else c, c)
    if not out:
        raise LayoutError("no colours given")
    return out


def render(slots: list[str], night_on: bool, night_color: str, signal: str) -> list[str]:
    """Resolve the layout slots to one concrete colour per segment."""
    night = night_color if night_on else "black"
    return [night if s == NIGHT else signal if s == SIGNAL else s for s in slots]


# Rainbow switch: these colours repeated along the whole bar.
RAINBOW = ["red", "orange", "yellow", "green", "blue", "purple"]


def rainbow_args(count: int) -> str:
    """'segments --count 18 red orange yellow green blue purple' for an 18-segment bar."""
    return f"segments --count {count} " + " ".join(RAINBOW)


def segment_args(colors: list[str]) -> str:
    """dazzle_multicolor arguments that paint exactly these segments."""
    return f"segments --count {len(colors)} " + " ".join(colors)


def product_id_from_service_data(service_data: dict[str, bytes]) -> int | None:
    """Zengge advert service data (UUID 0x5a00-0x5aff): bytes 8-9 = product id."""
    for uuid, data in (service_data or {}).items():
        if uuid.lower().startswith("00005a") and len(data) >= 10:
            return (data[8] << 8) | data[9]
    return None
