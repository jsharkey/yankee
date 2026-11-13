"""Tests for the Dazzle Bright command builders. Run: python -m pytest ha/tests"""

import importlib
import sys
import types
from pathlib import Path

import pytest

# Load the integration's modules without its __init__ (which needs Home Assistant).
_DIR = Path(__file__).parents[1] / "custom_components/dazzle_bright"
_pkg = types.ModuleType("dazzle_bright_under_test")
_pkg.__path__ = [str(_DIR)]
sys.modules["dazzle_bright_under_test"] = _pkg
dm = importlib.import_module("dazzle_bright_under_test.dazzle_multicolor")
templates = importlib.import_module("dazzle_bright_under_test.templates")


def frames(argv, seq=1, max_len=255):
    payload, cmd_id, _ = dm.build_command(argv)
    return [f.hex(" ") for f in dm.frame_v0(payload, seq, cmd_id, max_len)]


# --- bytes confirmed on a real IOTBTCC3 (product 197) -----------------------


def test_power():
    assert frames("off") == ["00 01 80 00 00 02 03 0a 71 24"]
    assert frames("on") == ["00 01 80 00 00 02 03 0a 71 23"]


def test_color_matches_capture_from_vendor_app():
    payload, cmd_id, _ = dm.build_command("color yellow")
    assert payload.hex(" ") == "e0 01 00 a1 1e 64 64 00 00 00 00 14 00 00"
    assert cmd_id == 0x0A


def test_static_tiles_palette_per_led():
    payload, cmd_id, _ = dm.build_command("-b 40 static --points 6 red 00ff00")
    assert cmd_id == 0x0B
    assert payload[:4] == bytes([0xEC, 0x01, 0x00, 40])
    red, green = "00 64 64 00 00", "3c 64 64 00 00"
    entries = [payload[4 + i * 5 : 9 + i * 5].hex(" ") for i in range(6)]
    assert entries == [red, green] * 3


def test_static_repeat_blocks():
    payload, _, _ = dm.build_command("static --points 6 --repeat 3 red white")
    values = [payload[4 + i * 5 + 1] for i in range(6)]  # sat byte: 100 red, 0 white
    assert values == [0x64] * 3 + [0x00] * 3


def test_random_palette():
    payload, _, _ = dm.build_command("-b 25 random red green")
    assert payload.hex(" ") == "ec 07 00 19 02 00 64 64 00 00 3c 64 64 00 00"


# --- transport ----------------------------------------------------------------


def test_long_command_is_fragmented_and_reassembles():
    payload, cmd_id, _ = dm.build_command("static --points 100 red green")
    assert len(payload) == 504
    out = dm.frame_v0(payload, 7, cmd_id, 255)
    assert len(out) == 3
    first, *rest = out
    assert first[:8] == bytes([0x40, 7, 0, 0, 0x01, 0xF8, 248, 0x0B])
    assert [f[0:2] for f in rest] == [bytes([0x40, 7])] * 2
    assert [int.from_bytes(f[2:4], "big") for f in rest] == [1, 0x8002]
    body = first[8:] + b"".join(f[5 : 5 + f[4]] for f in rest)
    assert body == payload


def test_short_command_is_single_packet():
    payload, cmd_id, _ = dm.build_command("random red")
    (pkt,) = dm.frame_v0(payload, 1, cmd_id, 255)
    assert pkt[:8] == bytes([0, 1, 0x80, 0, 0, len(payload), len(payload) + 1, 0x0B])


# --- animations and parsing ---------------------------------------------------


def test_anim_header():
    payload, _, _ = dm.build_command("-b 60 anim meteor --speed 70 red white")
    #                  E1 21 prev bri model other dir dens speed rotate
    assert payload[:10] == bytes([0xE1, 0x21, 0, 60, 13, 0, 1, 100, 70, 1])
    assert payload[15] == 2  # two palette colours after the 5-byte background
    assert len(payload) == 10 + 5 + 1 + 2 * 5


@pytest.mark.parametrize(
    "argv",
    [
        "anim meteor --speed 70 red white",
        "anim --speed 70 meteor red white",
        "anim meteor red white --speed 70",
    ],
)
def test_colours_may_follow_options(argv):
    # plain argparse only allowed this ordering on Python 3.13+
    payload, _, args = dm.build_command(argv)
    assert args.colors == ["red", "white"] and payload[8] == 70


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        ("anim bogus", "unknown animation"),
        ("static red", "--points"),
        ("color purpl", "bad colour"),
        ("scene meteor", "must be a number"),
        ("list-anims", "not a device command"),
    ],
)
def test_bad_commands_raise(argv, message):
    with pytest.raises(dm.CommandError, match=message):
        dm.build_command(argv)


# --- templates ------------------------------------------------------------------


def test_parse_templates():
    text = "# comment\nchristmas: random red green blue purple\n\nCandy Cane: static red white\n"
    parsed = templates.parse_templates(text)
    assert parsed == {
        "christmas": "random red green blue purple",
        "Candy Cane": "static red white",
    }
    assert templates.find_template(parsed, "candy cane") == "static red white"


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("no colon here", "line 1"),
        ("a: random red\nA: random blue", "duplicate"),
        ("name:", "line 1"),
    ],
)
def test_bad_templates(text, message):
    with pytest.raises(templates.TemplateError, match=message):
        templates.parse_templates(text)


def test_validate_rejects_bad_command():
    with pytest.raises(templates.TemplateError, match="'x'.*unknown animation"):
        templates.validate_templates("x: anim nope red", 100)


def test_default_templates_are_valid():
    from dazzle_bright_under_test import const  # noqa: PLC0415

    assert len(templates.validate_templates(const.DEFAULT_TEMPLATES, 100)) >= 8


def test_build_argv_adds_brightness_and_points():
    assert templates.build_argv("static red", 40, 150) == [
        "-b", "40", "static", "red", "--points", "150",
    ]
    assert templates.build_argv("static --points 7 red", None, 150) == [
        "static", "--points", "7", "red",
    ]


def test_blank_turns_every_led_off():
    # "off" in the integration: every LED value 0 (unlike "color off", which
    # the colour command clamps to a dim glow).
    payload, _ = templates.build_payload("static off", None, 100)
    assert payload[:2] == bytes([0xEC, 0x01]) and not any(payload[4:])
    color_off, _, _ = dm.build_command("color off")
    assert color_off[6] == 1
