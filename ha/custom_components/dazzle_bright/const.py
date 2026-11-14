"""Constants for the Dazzle Bright string lights integration."""
from __future__ import annotations

from typing import Final

DOMAIN: Final = "dazzle_bright"

CONF_TEMPLATES: Final = "templates"
CONF_POINT_COUNT: Final = "point_count"
CONF_INPUT_SELECT: Final = "input_select"
CONF_DISCONNECT_DELAY: Final = "disconnect_delay"
CONF_POWER_ON_FIRST: Final = "power_on_first"
CONF_BLANK_OFF: Final = "blank_off"
CONF_MODE: Final = "mode"
CONF_LAYOUT: Final = "layout"
CONF_NIGHT_COLOR: Final = "night_color"
CONF_SIGNAL_COLORS: Final = "signal_colors"

MODE_PATTERNS: Final = "patterns"   # string lights: templates (IOTBTCC3, product 197)
MODE_SEGMENTS: Final = "segments"   # segment bar: night + signal (IOTBT4E8, product 170)

DEFAULT_LAYOUT: Final = "night*8 black*9 signal"
DEFAULT_NIGHT_COLOR: Final = "ff8811"
DEFAULT_SIGNAL_COLORS: Final = "black, red, yellow=ff4400, green, blue, purple"
# 0.3.0's default; entries still carrying it get the new default.
OLD_DEFAULT_SIGNAL_COLORS: Final = "black, red, yellow, green, blue, purple"

DEFAULT_POINT_COUNT: Final = 100
DEFAULT_DISCONNECT_DELAY: Final = 60  # seconds an idle BLE link is kept open

# One template per line: "<name>: <dazzle_multicolor.py arguments>".
# Brightness (-b) is added from the light entity, and "static" gets
# --points from the options when it is omitted.
DEFAULT_TEMPLATES: Final = """\
christmas: random red green blue purple
candy cane: static --repeat 3 red white
classic multicolor: static red green blue orange purple
warm white: color warm
meteor: anim meteor --speed 70 red white
falling snow: anim fallingSnow --speed 40 white 0080ff
twinkle: anim starFlicker --speed 50 red green white gold
halloween: random orange purple
"""

GATT_WRITE_UUID: Final = "0000ff01-0000-1000-8000-00805f9b34fb"

SERVICE_SEND_COMMAND: Final = "send_command"
ATTR_COMMAND: Final = "command"
ATTR_TEMPLATE: Final = "template"
