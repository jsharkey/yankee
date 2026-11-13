#!/usr/bin/env python3
"""
dazzle_multicolor.py - multi-colour control for Zengge "IOTBT" string lights
(Dazzle Bright / Surplife app, product id 197 = 0xC5, "hc3" category).

Reverse engineered from com.dazzle.bright APK (Flutter, Dart 3.11 AOT, decompiled
with blutter). See PROTOCOL_NOTES.md next to this file for the derivation.

Requires:  pip install bleak

Examples
--------
  # see the bytes without touching the lights
  python dazzle_multicolor.py --dry-run static --points 100 red green

  # red/green alternating along a 100-LED string (the app's "multi colour" tab)
  python dazzle_multicolor.py -a AA:BB:CC:DD:EE:FF static --points 100 red green

  # candy cane in blocks of 3: rrrwwwrrrwww...
  python dazzle_multicolor.py -a ... static --points 100 --repeat 3 red white

  # let the controller scatter a palette randomly along the string
  python dazzle_multicolor.py -a ... random red green blue gold

  # paint individual LEDs (experimental, E1 23 single frame)
  python dazzle_multicolor.py -a ... frame red red off off blue blue

  # any command at 40% brightness (global option, before the sub-command)
  python dazzle_multicolor.py -a ... -b 40 static --points 100 red green

  # single solid colour (v3 E0 01 - the integration's working colour command)
  python dazzle_multicolor.py -a ... -b 60 color warm

  # animations (app "control modes", E1 21): list them, then run one
  python dazzle_multicolor.py list-anims
  python dazzle_multicolor.py -a ... anim meteor --speed 70 red white
  python dazzle_multicolor.py -a ... anim fallingSnow --direction 2 white blue

  # symphony scene command (E1 01) - alternative animation engine
  python dazzle_multicolor.py -a ... scene 11 --speed 60 red green

  # power
  python dazzle_multicolor.py -a ... off
  python dazzle_multicolor.py -a ... on

  # dump the device's state frame (to find the LED count)
  python dazzle_multicolor.py -a ... query
"""
from __future__ import annotations

import argparse
import asyncio
import colorsys
import os
import sys
import time

WRITE_UUID = "0000ff01-0000-1000-8000-00805f9b34fb"
NOTIFY_UUID = "0000ff02-0000-1000-8000-00805f9b34fb"

NAMED = {
    "red": (255, 0, 0), "green": (0, 255, 0), "blue": (0, 0, 255),
    "white": (255, 255, 255), "warm": (255, 170, 80), "gold": (255, 180, 0),
    "yellow": (255, 255, 0), "orange": (255, 100, 0), "purple": (160, 0, 255),
    "pink": (255, 60, 150), "cyan": (0, 255, 255), "magenta": (255, 0, 255),
    "off": (0, 0, 0), "black": (0, 0, 0),
}


# --------------------------------------------------------------------------
# colour encoding (identical in every command family below)
# --------------------------------------------------------------------------
def parse_color(s: str) -> tuple[int, int, int]:
    s = s.strip().lower()
    if s in NAMED:
        return NAMED[s]
    s = s.lstrip("#")
    if len(s) == 6:
        return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
    raise ValueError(f"bad colour {s!r} (use a name or RRGGBB)")


def rgb_to_hsv(r: int, g: int, b: int) -> tuple[int, int, int]:
    """-> (hue 0-359, sat 0-100, val 0-100)"""
    h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    return round(h * 360) % 360, round(s * 100), round(v * 100)


def pack_hs(h: int, s: int) -> tuple[int, int]:
    """App: ((h & 0x1FF) << 7) | (s & 0x7F), sent big-endian."""
    p = ((h & 0x1FF) << 7) | (s & 0x7F)
    return (p >> 8) & 0xFF, p & 0xFF


def color5(rgb, cct: int = 0, cctv: int = 0) -> bytes:
    """5-byte ColorType: hs_hi hs_lo v cct cctv (cct/cctv = 0 for RGB colours)."""
    h, s, v = rgb_to_hsv(*rgb)
    hi, lo = pack_hs(h, s)
    return bytes([hi, lo, v, cct, cctv])


# --------------------------------------------------------------------------
# payload builders
# --------------------------------------------------------------------------
def build_ec01_static_colorful(colors, points: int, brightness: int = 100, repeat: int = 1) -> bytes:
    """
    P3 "static colourful" - what the app's VoiceControlII colour tab sends.
    ColorCommandHandlerMixin.sendP3IIStaticColorful -> buildP3StaticColorfulCmd:
        EC 01 00 <brightness> + points x [hs_hi hs_lo v cct cctv]
    The app tiles the palette cyclically across all `points` LEDs.
    `repeat` is a convenience (not in the app): each colour covers N LEDs.
    """
    if not colors:
        raise ValueError("colors is empty")
    out = bytearray([0xEC, 0x01, 0x00, brightness & 0xFF])
    for i in range(points):
        out += color5(colors[(i // repeat) % len(colors)])
    return bytes(out)


def build_ec07_random_colorful(colors, brightness: int = 100) -> bytes:
    """P3 random colourful: EC 07 00 <brightness> <n> + n x colour5."""
    out = bytearray([0xEC, 0x07, 0x00, brightness & 0xFF, len(colors) & 0xFF])
    for c in colors:
        out += color5(c)
    return bytes(out)


def build_e123_frame(leds, mode: int = 0, param: int = 0, speed: int = 0) -> bytes:
    """
    VoiceControl single-frame smear (buildSmearDataHEXV2Command) - EXPERIMENTAL.
        E1 23 01 <mode> 00 00 <param> <n_hi> <n_lo> + n x [00 hs_hi hs_lo v cct cctv speed]
    The firmware runs this format from on-device timers, but the meaning of
    <mode>/<param> was not fully resolved.
    """
    n = len(leds)
    out = bytearray([0xE1, 0x23, 0x01, mode & 0xFF, 0x00, 0x00, param & 0xFF, (n >> 8) & 0xFF, n & 0xFF])
    for c in leds:
        out += b"\x00" + color5(c) + bytes([speed & 0xFF])
    return bytes(out)


def build_e130_multicolor(colors, brightness: int = 100, preview: bool = False) -> bytes:
    """Symphony-2.0 buildMultiColorStaticHEXCmd: E1 30 <preview> <bri> <n<=8> + n x colour5."""
    colors = list(colors)[:8]
    out = bytearray([0xE1, 0x30, 1 if preview else 0, brightness & 0xFF, len(colors)])
    for c in colors:
        out += color5(c)
    return bytes(out)


def build_e104_smear(leds, effect: int = 0, p3: int = 1, speed: int = 80,
                     brightness: int = 100, preview: bool = False, item_speed: int = 0) -> bytes:
    """Symphony-2.0 buildSmearHEXCommand (RGB strings):
        E1 04 <preview> <effect> <p3> <speed> <bri> <n_hi> <n_lo> + n x [flags hs_hi hs_lo v speed]
    flags = (point_type << 3) | is_cct ; point_type 0 = static."""
    n = len(leds)
    out = bytearray([0xE1, 0x04, 1 if preview else 0, effect, p3, speed, brightness, (n >> 8) & 0xFF, n & 0xFF])
    for c in leds:
        h, s, v = rgb_to_hsv(*c)
        hi, lo = pack_hs(h, s)
        out += bytes([0x00, hi, lo, v, item_speed & 0xFF])
    return bytes(out)


def build_e001_color(rgb, brightness: int = 100) -> bytes:
    """v3 solid colour, as captured from the vendor app (= integration's
    build_iotbt_v3_color_command): E0 01 00 A1 hs_hi hs_lo v 00 00 00 00 14 00 00
    v = colour value scaled by brightness."""
    h, s, v = rgb_to_hsv(*rgb)
    hi, lo = pack_hs(h, s)
    v = max(1, min(100, round(v * brightness / 100)))
    return bytes([0xE0, 0x01, 0x00, 0xA1, hi, lo, v, 0, 0, 0, 0, 0x14, 0, 0])


# VoiceControlII "control mode" animations: SymphonyControlType enum in the app
# (name -> model id sent in byte 4 of E1 21). The lora* entries exist in the
# enum but are presumably for LoRa products.
ANIMATIONS = {
    "syncBreathe": 1, "asyncBreathe": 2, "syncJump": 3, "asyncJump": 4,
    "syncGradient": 5, "asyncGradient": 6, "syncStrobe": 7, "asyncStrobe": 8,
    "starFlicker": 9, "blossom": 10, "marquee": 11, "fireworks": 12, "meteor": 13,
    "runningWater": 14, "cover": 15, "buildingBlocks": 16, "fillingGradient": 17,
    "fillingJump": 18, "fillingBreathe": 19, "colorfulAlwaysOn": 20,
    "colorfulFlicker": 21, "colorfulBreathe": 22, "fallingSnow": 23,
    "sublimation": 24, "collision": 25, "interval": 26, "gorgeous": 27,
    "segmentationAsyncBreathe": 28, "segmentationAsyncJump": 29,
    "segmentationAsyncStrobe": 30, "colorfulMarquee": 31, "flickerTransform": 32,
    "squirm": 33, "colorAsyncFlicker": 34, "accumulation": 35, "shuttle": 36,
    "shuttle2": 37, "staticRed": 38, "staticOrange": 39, "staticYellow": 40,
    "staticGreen": 41, "staticCyan": 42, "staticBlue": 43, "staticPurple": 44,
    "staticWhite": 45, "streamer": 46, "chase": 47, "marquee2": 48, "cycle": 49,
    "blink": 50, "volcano": 51, "collision2": 52, "fireworks2": 53,
    "fallingSnow2": 54, "fireworks3": 55, "upDown": 56, "loraRainbowBridge": 57,
    "loraMeteor": 58, "loraComet": 59, "loraNewYear": 60, "loraWinterSolstice": 61,
}


def resolve_animation(name: str) -> int:
    if name.isdigit():
        return int(name)
    for k, v in ANIMATIONS.items():
        if k.lower() == name.lower():
            return v
    raise ValueError(f"unknown animation {name!r} (see list-anims)")


def build_e121_control_mode(model: int, colors, brightness: int = 100, speed: int = 100,
                            direction: int = 1, density: int = 100, other_mode: int = 0,
                            rotate: int = 1, bg=(0, 0, 0), preview: bool = False) -> bytes:
    """
    VoiceControlII control-mode animation (buildCustomModeHEXCommand, reached via
    VoiceControlIICommandHandlerMixin.sendControlCommand / sendCustomModeCommand):
      E1 21 <preview> <brightness> <model> <otherMode> <direction> <density> <speed> <rotate>
            <bg colour5> <n<=8> n x colour5
    App defaults when the UI hides a control: direction 1, density 100, speed 100.
    """
    colors = list(colors)[:8]
    out = bytearray([0xE1, 0x21, 1 if preview else 0, brightness & 0xFF, model & 0xFF,
                     other_mode & 0xFF, direction & 0xFF, density & 0xFF, speed & 0xFF,
                     rotate & 0xFF])
    out += color5(bg)
    out.append(len(colors))
    for c in colors:
        out += color5(c)
    return bytes(out)


def _color4(rgb) -> bytes:
    """4-byte colour used by E1 01/E1 03: A1 hs_hi hs_lo v (0xB1 marks CCT entries)."""
    h, s, v = rgb_to_hsv(*rgb)
    hi, lo = pack_hs(h, s)
    return bytes([0xA1, hi, lo, v])


def build_e101_scene(model: int, colors, brightness: int = 100, speed: int = 50,
                     model_expand: int = 0, direction: int = 1, density: int = 100,
                     bg=(0, 0, 0), preview: bool = False) -> bytes:
    """
    Symphony-2.0 scene (buildSymphonyCustomHEXCommand; same bytes as the
    integration's build_iotbt_segment_effect_command):
      E1 01 <preview> <brightness> <model> <modelExpand> <direction> <density> <speed> 00
            <bg colour4> <n> n x colour4
    """
    out = bytearray([0xE1, 0x01, 1 if preview else 0, brightness & 0xFF, model & 0xFF,
                     model_expand & 0xFF, direction & 0xFF, density & 0xFF, speed & 0xFF, 0x00])
    out += _color4(bg)
    out.append(len(colors))
    for c in colors:
        out += _color4(c)
    return bytes(out)


def scale_brightness(colors, brightness: int):
    """For commands without a brightness byte: scale each colour's value."""
    f = max(0, min(100, brightness)) / 100
    return [tuple(round(x * f) for x in c) for c in colors]


def build_power(on: bool) -> bytes:
    """0x71 power (0x23 on / 0x24 off), no checksum, cmdId 0x0A - the integration's
    build_iotbt_power_command, which works on this device."""
    return bytes([0x71, 0x23 if on else 0x24])


STATE_QUERY = bytes([0xEA, 0x81, 0x8A, 0x8B])  # same query the integration uses (0x0A family)


# --------------------------------------------------------------------------
# transport (com.zengge.hagallbjarkan LowerTransportLayerEncoder.generator, v0)
# --------------------------------------------------------------------------
def frame_v0(payload: bytes, seq: int, cmd_id: int, max_len: int) -> list[bytes]:
    """
    ble_version < 8 framing. max_len = min(MTU-4, 255) in the app.
      single : 00 seq 80 00 len_hi len_lo (len+1)&FF cmd  | payload
      first  : 40 seq 00 00 len_hi len_lo (max_len-7) cmd | payload[:max_len-8]
      next   : 40 seq idx_hi idx_lo n                     | chunk (n <= max_len-5)
               (idx | 0x8000 on the last fragment)
    """
    L = len(payload)
    if L <= max_len - 8:
        return [bytes([0x00, seq, 0x80, 0x00, (L >> 8) & 0xFF, L & 0xFF, (L + 1) & 0xFF, cmd_id]) + payload]
    frags = []
    first = max_len - 8
    frags.append(bytes([0x40, seq, 0x00, 0x00, (L >> 8) & 0xFF, L & 0xFF, (max_len - 7) & 0xFF, cmd_id]) + payload[:first])
    pos, idx = first, 1
    while pos < L:
        n = min(L - pos, max_len - 5)
        last = pos + n >= L
        seg = (idx | 0x8000) if last else idx
        frags.append(bytes([0x40, seq, (seg >> 8) & 0xFF, seg & 0xFF, n]) + payload[pos:pos + n])
        pos += n
        idx += 1
    return frags


def frame_v1(payload: bytes, seq: int, cmd_id: int, max_len: int) -> list[bytes]:
    """ble_version >= 8 framing (generatorV1), max_len = min(MTU-4, 512)."""
    L = len(payload)
    if L <= max_len - 9:
        return [bytes([0x01, seq, 0x80, 0x00, (L >> 8) & 0xFF, L & 0xFF, ((L + 1) >> 8) & 0xFF, (L + 1) & 0xFF, cmd_id]) + payload]
    frags = []
    first = max_len - 9
    f8 = max_len - 8
    frags.append(bytes([0x41, seq, 0x00, 0x00, (L >> 8) & 0xFF, L & 0xFF, (f8 >> 8) & 0xFF, f8 & 0xFF, cmd_id]) + payload[:first])
    pos, idx = first, 1
    while pos < L:
        n = min(L - pos, max_len - 6)
        seg = (idx | 0x8000) if pos + n >= L else idx
        frags.append(bytes([0x41, seq, (seg >> 8) & 0xFF, seg & 0xFF, (n >> 8) & 0xFF, n & 0xFF]) + payload[pos:pos + n])
        pos += n
        idx += 1
    return frags


# --------------------------------------------------------------------------
def default_cmd_id(args) -> int:
    if args.cmd_id is not None:
        return args.cmd_id
    return 0x0A if args.cmd in ("query", "color", "on", "off") else 0x0B


async def run(args, payload: bytes | None):
    seq = args.seq & 0xFF
    framer = frame_v1 if args.ble_version >= 8 else frame_v0
    cap = 512 if args.ble_version >= 8 else 255

    if args.dry_run:
        max_len = min(args.mtu - 4, cap) if args.mtu else cap
        cmd_id = default_cmd_id(args)
        print(f"payload ({len(payload)} bytes): {payload.hex(' ')}")
        for i, f in enumerate(framer(payload, seq, cmd_id, max_len)):
            print(f"pkt{i} ({len(f)}): {f.hex(' ')}")
        return

    from bleak import BleakClient

    t0 = time.monotonic()

    def mark(what: str):
        if args.timing:
            print(f"[{time.monotonic() - t0:6.2f}s] {what}", file=sys.stderr)

    client = BleakClient(args.address, timeout=20)
    mark("connecting")
    await client.connect()
    mark("connected")
    try:
        await _send(args, client, payload, seq, framer, cap, mark)
    finally:
        # A graceful disconnect can take 1-2 s on BlueZ/CoreBluetooth/WinRT while
        # the link is torn down. Cap it; the OS drops the link either way once
        # this process exits.
        mark("disconnecting")
        try:
            await asyncio.wait_for(client.disconnect(), timeout=args.disconnect_timeout)
            mark("disconnected")
        except (asyncio.TimeoutError, Exception):
            mark("disconnect skipped (timeout)")


async def _send(args, client, payload, seq, framer, cap, mark):
    mtu = args.mtu or getattr(client, "mtu_size", 23) or 23
    max_len = max(min(mtu - 4, cap), 20)
    print(f"connected, mtu={mtu} -> fragment size {max_len}")

    got_reply = asyncio.Event()

    def on_notify(_h, data: bytearray):
        print("notify:", bytes(data).hex(" "))
        try:
            txt = bytes(data[8:]).decode()
            if txt.startswith("{"):
                print("   json:", txt)
        except Exception:
            pass
        got_reply.set()

    if args.cmd == "query":
        payload = STATE_QUERY
        await client.start_notify(NOTIFY_UUID, on_notify)
    cmd_id = default_cmd_id(args)
    frags = framer(payload, seq, cmd_id, max_len)
    for i, f in enumerate(frags):
        print("write:", f.hex(" "))
        await client.write_gatt_char(WRITE_UUID, f, response=args.with_response)
        if i < len(frags) - 1:
            await asyncio.sleep(args.gap)
    mark(f"sent {len(frags)} packet(s)")
    if args.cmd == "query":
        # wait for the reply, then briefly for any further fragments
        try:
            await asyncio.wait_for(got_reply.wait(), timeout=3.0)
            await asyncio.sleep(0.3)
        except asyncio.TimeoutError:
            print("no reply within 3 s")
    else:
        # let a write-without-response leave the adapter before disconnecting
        await asyncio.sleep(args.linger)


class CommandError(ValueError):
    """Bad command line / template (raised instead of exiting when used as a library)."""


def _parser_class(raise_errors: bool):
    class _Parser(argparse.ArgumentParser):
        def error(self, message):
            if raise_errors:
                raise CommandError(message)
            super().error(message)
    return _Parser


def build_parser(raise_errors: bool = False) -> argparse.ArgumentParser:
    ap = _parser_class(raise_errors)(description=__doc__,
                                    formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-a", "--address", help="BLE MAC / UUID of IOTBTxxx")
    ap.add_argument("--dry-run", action="store_true", help="print packets, don't connect")
    ap.add_argument("--cmd-id", type=lambda x: int(x, 0), default=None,
                    help="transport cmdId byte (default 0x0B; 0x0A for color/query, as the app sends them)")
    ap.add_argument("--ble-version", type=int, default=7, help="advert byte 1 (yours is 7)")
    ap.add_argument("--mtu", type=int, default=0, help="override negotiated MTU")
    ap.add_argument("--seq", type=int, default=1)
    ap.add_argument("--gap", type=float, default=0.03, help="seconds between fragments")
    ap.add_argument("--with-response", action="store_true")
    ap.add_argument("--timing", action="store_true", help="print connect/send/disconnect timings")
    ap.add_argument("--linger", type=float, default=0.1,
                    help="seconds to wait after the last write before disconnecting (default 0.1)")
    ap.add_argument("--disconnect-timeout", type=float, default=0.3,
                    help="max seconds to wait for a clean disconnect (default 0.3)")
    ap.add_argument("-b", "--brightness", type=int, default=None,
                    help="brightness 0-100 for any command (default 100)")
    sub = ap.add_subparsers(dest="cmd", required=True, parser_class=type(ap))

    def bri(p):  # per-command --brightness still accepted (overrides -b)
        p.add_argument("--brightness", dest="sub_brightness", type=int, default=None,
                       help=argparse.SUPPRESS)

    p = sub.add_parser("color", help="E0 01: one solid colour (v3 colour command)")
    bri(p)
    p.add_argument("colors", nargs=1, metavar="color")

    p = sub.add_parser("static", help="EC 01: palette tiled along the string (app's multi-colour)")
    p.add_argument("--points", type=int, required=True, help="number of LEDs/points on the string")
    bri(p)
    p.add_argument("--repeat", type=int, default=1, help="LEDs per colour block")
    p.add_argument("colors", nargs="+")

    p = sub.add_parser("random", help="EC 07: device scatters palette randomly")
    bri(p)
    p.add_argument("colors", nargs="+")

    anim_help = ("speed 0-100; direction (app default 1, try 2 to reverse); density 0-100; "
                 "colours = palette (max 8)")
    p = sub.add_parser("anim", help="E1 21: animated control mode (see list-anims)",
                       description=anim_help)
    p.add_argument("items", nargs="+", metavar="ANIMATION [COLOR ...]",
                   help="animation name from list-anims (or model number), then palette colours")
    bri(p)
    p.add_argument("--speed", type=int, default=50)
    p.add_argument("--direction", type=int, default=1)
    p.add_argument("--density", type=int, default=100)
    p.add_argument("--other-mode", type=int, default=0)
    p.add_argument("--rotate", type=int, default=1)
    p.add_argument("--bg", default="off", help="background colour (default off)")

    p = sub.add_parser("scene", help="E1 01: symphony scene engine (alternative animations)")
    p.add_argument("items", nargs="+", metavar="MODEL [COLOR ...]",
                   help="scene/model number (1-255), then palette colours")
    bri(p)
    p.add_argument("--speed", type=int, default=50)
    p.add_argument("--model-expand", type=int, default=0)
    p.add_argument("--direction", type=int, default=1)
    p.add_argument("--density", type=int, default=100)
    p.add_argument("--bg", default="off")

    sub.add_parser("list-anims", help="list animation names for the anim command")

    p = sub.add_parser("frame", help="E1 23: explicit per-LED list (experimental)")
    bri(p)
    p.add_argument("--mode", type=int, default=0)
    p.add_argument("--param", type=int, default=0)
    p.add_argument("--speed", type=int, default=0)
    p.add_argument("colors", nargs="+")

    p = sub.add_parser("multi8", help="E1 30: up to 8 static colours (symphony-2.0 family)")
    bri(p)
    p.add_argument("colors", nargs="+")

    p = sub.add_parser("smear", help="E1 04: per-LED paint (symphony-2.0 RGB family)")
    p.add_argument("--speed", type=int, default=80)
    bri(p)
    p.add_argument("colors", nargs="+")

    sub.add_parser("on", help="turn the lights on (0x71 0x23)")
    sub.add_parser("off", help="turn the lights off (0x71 0x24)")
    sub.add_parser("query", help="send 0xEA 0x81 state query and print notifications")

    return ap


def parse_command(argv, ap: argparse.ArgumentParser) -> argparse.Namespace:
    """Parse argv (list or string) into a Namespace with .cmd, .colors, .b etc."""
    if isinstance(argv, str):
        argv = argv.split()
    # parse_known_args + fold-back lets colours come after options
    # ("anim meteor --speed 70 red white") on every Python version; plain
    # parse_args() only accepts that ordering on Python 3.13+.
    args, extra = ap.parse_known_args(argv)
    if extra:
        if args.cmd in ("anim", "scene") and not any(x.startswith("-") for x in extra):
            args.items += extra
        else:
            ap.error("unrecognized arguments: " + " ".join(extra))

    b = getattr(args, "sub_brightness", None)
    b = b if b is not None else (args.brightness if args.brightness is not None else 100)
    args.b = max(0, min(100, b))

    if args.cmd in ("anim", "scene"):
        # first positional is the animation/model, the rest are colours
        args.target = args.items[0]
        args.colors = args.items[1:] or ["red", "green", "blue"]
    return args


def payload_from_args(args: argparse.Namespace) -> bytes | None:
    """Build the raw (unframed) payload for a parsed command. Raises CommandError."""
    b = args.b
    if args.cmd in ("on", "off"):
        return build_power(args.cmd == "on")
    if args.cmd == "query":
        return STATE_QUERY
    if args.cmd == "list-anims":
        return None
    try:
        cols = [parse_color(c) for c in args.colors]
    except ValueError as e:
        raise CommandError(str(e)) from None
    if args.cmd == "color":
        return build_e001_color(cols[0], b)
    if args.cmd == "static":
        return build_ec01_static_colorful(cols, args.points, b, max(1, args.repeat))
    if args.cmd == "random":
        return build_ec07_random_colorful(cols, b)
    if args.cmd == "anim":
        try:
            model = resolve_animation(args.target)
        except ValueError as e:
            raise CommandError(str(e)) from None
        return build_e121_control_mode(
            model, cols, b, args.speed, args.direction,
            args.density, args.other_mode, args.rotate, parse_color(args.bg))
    if args.cmd == "scene":
        if not args.target.isdigit():
            raise CommandError(f"scene model must be a number, got {args.target!r}")
        return build_e101_scene(int(args.target), cols, b, args.speed, args.model_expand,
                                args.direction, args.density, parse_color(args.bg))
    if args.cmd == "frame":
        # no brightness byte in E1 23: scale the colours instead
        return build_e123_frame(scale_brightness(cols, b), args.mode, args.param, args.speed)
    if args.cmd == "multi8":
        return build_e130_multicolor(cols, b)
    if args.cmd == "smear":
        return build_e104_smear(cols, speed=args.speed, brightness=b)
    raise CommandError(f"unsupported command {args.cmd!r}")


def build_command(argv) -> tuple[bytes, int, argparse.Namespace]:
    """
    Library entry point: command line (string or list, without -a/--dry-run)
    -> (payload, cmd_id, parsed_args). Frame the payload with frame_v0().
    Example: build_command("-b 40 random red green blue")
    """
    args = parse_command(argv, build_parser(raise_errors=True))
    if args.cmd == "list-anims":
        raise CommandError("list-anims is not a device command")
    return payload_from_args(args), default_cmd_id(args), args


def main():
    ap = build_parser()
    args = parse_command(sys.argv[1:], ap)
    if args.cmd == "list-anims":
        for name, model in ANIMATIONS.items():
            print(f"{model:3d}  {name}")
        return 0
    if not args.dry_run and not args.address:
        ap.error("--address is required unless --dry-run")
    try:
        payload = payload_from_args(args)
    except CommandError as e:
        ap.error(str(e))
    asyncio.run(run(args, payload))
    if not args.dry_run:
        # Skip interpreter shutdown: bleak backends can leave threads/D-Bus
        # handlers that delay process exit for a second or more.
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(0)


if __name__ == "__main__":
    sys.exit(main())
