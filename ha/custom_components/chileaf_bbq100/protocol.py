"""Chileaf BBQ100 wire protocol. No Home Assistant imports, so it can be tested alone.

Decoded from the vendor's Android app (Chi-BBQ 1.0.6, package com.qili.bbq).

GATT (a Nordic-UART-like service):
  service 6e40fd00-b5a3-f393-e0a9-e50e24dcca9e
  write   6e408d03-...  commands to the thermometer
  notify  6e408d02-...  replies and pushed readings

Every frame in both directions is

    0x6A, total_length, command, payload..., checksum

where total_length counts the whole frame and checksum is the low byte of the
sum of all bytes before it.

Temperatures are signed 16-bit big-endian hundredths of a degree Celsius.
30200 (302.00 C) means "no probe plugged in". Probes are numbered 0-3 on the
wire; this module uses 1-4.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

SERVICE_UUID = "6e40fd00-b5a3-f393-e0a9-e50e24dcca9e"
WRITE_UUID = "6e408d03-b5a3-f393-e0a9-e50e24dcca9e"
NOTIFY_UUID = "6e408d02-b5a3-f393-e0a9-e50e24dcca9e"

HEADER = 0x6A
PROBE_COUNT = 4
NO_PROBE = 30200

# Range the app accepts: -20 to 300 C, in hundredths.
TEMP_MIN_C = -20
TEMP_MAX_C = 300
# The app's timer wheels go to 99:59.
TIMER_MAX_MINUTES = 99


class Cmd(IntEnum):
    VERSION = 0x01
    CHANNEL = 0x02       # query / report one probe's full state
    GET_UNIT = 0x03
    SET_MEAT = 0x04      # meat mode: meat type + doneness
    SET_CUSTOM = 0x05    # custom doneness table (not used here)
    GET_CUSTOM = 0x06    # doneness temperatures for one meat type
    SET_TEMP = 0x07      # temperature mode: target temperature
    SET_TIMER = 0x08     # timer mode: minutes + seconds
    RUN = 0x09           # start / stop
    STOP_ALARM = 0x0A
    SET_UNIT = 0x0B
    SET_MODE = 0x0C
    ALL_TEMPS = 0x0F     # pushed by the thermometer: all four probe readings


class Mode(IntEnum):
    MEAT = 0
    TEMPERATURE = 1
    TIMER = 2


class Unit(IntEnum):
    """Unit on the thermometer's own display."""

    FAHRENHEIT = 0
    CELSIUS = 1


MEATS = ["Beef", "Veal", "Lamb", "Burger", "Pork", "Chicken", "Turkey", "Fish"]
DONENESS = ["Rare", "Medium rare", "Medium", "Medium well", "Well done"]

# Doneness levels the app offers for each meat (indexes into DONENESS).
MEAT_DONENESS: dict[int, tuple[int, ...]] = {
    0: (0, 1, 2, 3, 4),  # beef
    1: (0, 1, 2, 3, 4),  # veal
    2: (0, 1, 2, 3, 4),  # lamb
    3: (4,),             # burger
    4: (1, 2, 3, 4),     # pork
    5: (4,),             # chicken
    6: (4,),             # turkey
    7: (4,),             # fish
}


def meat_presets() -> list[tuple[int, int, str]]:
    """Every (meat, doneness, label) the app offers, e.g. (0, 1, "Beef medium rare")."""
    out = []
    for meat, levels in MEAT_DONENESS.items():
        for level in levels:
            label = MEATS[meat] if len(levels) == 1 else f"{MEATS[meat]} {DONENESS[level].lower()}"
            out.append((meat, level, label))
    return out


class FrameError(ValueError):
    """A notification that is not a usable frame."""


# --------------------------------------------------------------- building


def checksum(data: bytes) -> int:
    return sum(data) & 0xFF


def build_frame(cmd: int, payload: bytes = b"") -> bytes:
    body = bytes([HEADER, len(payload) + 4, cmd]) + payload
    return body + bytes([checksum(body)])


def _wire_probe(probe: int) -> int:
    if not 1 <= probe <= PROBE_COUNT:
        raise ValueError(f"probe must be 1-{PROBE_COUNT}, got {probe}")
    return probe - 1


def query_channel(probe: int) -> bytes:
    return build_frame(Cmd.CHANNEL, bytes([_wire_probe(probe)]))


def query_unit() -> bytes:
    return build_frame(Cmd.GET_UNIT)


def query_version() -> bytes:
    return build_frame(Cmd.VERSION)


def set_target_temperature(probe: int, celsius: float) -> bytes:
    """Put a probe in temperature mode with this target."""
    if not TEMP_MIN_C <= celsius <= TEMP_MAX_C:
        raise ValueError(f"target must be {TEMP_MIN_C}-{TEMP_MAX_C} C, got {celsius}")
    raw = round(celsius * 100) & 0xFFFF
    return build_frame(Cmd.SET_TEMP, bytes([_wire_probe(probe)]) + raw.to_bytes(2, "big"))


def set_timer(probe: int, minutes: int, seconds: int = 0) -> bytes:
    """Put a probe in timer mode, counting down from minutes:seconds."""
    if not (0 <= minutes <= TIMER_MAX_MINUTES and 0 <= seconds <= 59) or minutes == seconds == 0:
        raise ValueError(f"timer must be 00:01-{TIMER_MAX_MINUTES}:59, got {minutes}:{seconds}")
    return build_frame(Cmd.SET_TIMER, bytes([_wire_probe(probe), minutes, seconds]))


def set_meat(probe: int, meat: int, doneness: int) -> bytes:
    """Put a probe in meat mode; the thermometer picks the target."""
    if doneness not in MEAT_DONENESS.get(meat, ()):
        raise ValueError(f"no doneness {doneness} for meat {meat}")
    return build_frame(Cmd.SET_MEAT, bytes([_wire_probe(probe), meat, doneness]))


def set_running(probe: int, running: bool) -> bytes:
    return build_frame(Cmd.RUN, bytes([_wire_probe(probe), 1 if running else 0]))


def stop_alarm(probe: int) -> bytes:
    return build_frame(Cmd.STOP_ALARM, bytes([_wire_probe(probe)]))


def set_unit(unit: Unit) -> bytes:
    return build_frame(Cmd.SET_UNIT, bytes([int(unit)]))


# ---------------------------------------------------------------- parsing


def decode_temperature(raw: int) -> float | None:
    """Big-endian u16 from the wire -> degrees C, or None if unplugged / out of range."""
    if raw == NO_PROBE:
        return None
    value = (raw - 0x10000 if raw & 0x8000 else raw) / 100
    if not TEMP_MIN_C - 20 <= value <= TEMP_MAX_C + 10:
        return None
    return value


@dataclass(frozen=True)
class AllTemps:
    """Pushed reading of all four probes (None = unplugged)."""

    temperatures: tuple[float | None, ...]


@dataclass(frozen=True)
class ChannelState:
    """Full state of one probe, the reply to query_channel()."""

    probe: int                # 1-4
    display_slot: int         # where the thermometer shows it ("showIndex")
    mode: Mode | int
    alarm: bool               # alarm is sounding
    running: bool
    target_temperature: float | None  # C, meat and temperature modes
    timer_target: int | None          # seconds, timer mode
    temperature: float | None
    time: int                 # seconds: remaining in timer mode, else elapsed
    meat: int
    doneness: int


@dataclass(frozen=True)
class UnitReport:
    unit: Unit | int


@dataclass(frozen=True)
class Ack:
    """Reply to a write, or a frame this integration does not decode."""

    cmd: int
    payload: bytes


Frame = AllTemps | ChannelState | UnitReport | Ack


def parse_frame(data: bytes) -> Frame:
    """Decode one notification. The app does not check the checksum, nor do we."""
    if len(data) < 4 or data[0] != HEADER:
        raise FrameError("not a BBQ100 frame")
    cmd = data[2]

    if cmd == Cmd.ALL_TEMPS:
        if len(data) < 11:
            raise FrameError("short temperature frame")
        return AllTemps(
            tuple(decode_temperature(int.from_bytes(data[3 + 2 * i:5 + 2 * i], "big"))
                  for i in range(PROBE_COUNT))
        )

    if cmd == Cmd.CHANNEL:
        if len(data) < 16:
            raise FrameError("short channel frame")
        if data[3] >= PROBE_COUNT:
            raise FrameError(f"bad probe {data[3]}")
        mode = data[5]
        try:
            mode = Mode(mode)
        except ValueError:
            pass
        target_temperature = timer_target = None
        if mode == Mode.TIMER:
            timer_target = data[8] * 60 + data[9]
        else:
            target_temperature = decode_temperature(int.from_bytes(data[8:10], "big"))
        return ChannelState(
            probe=data[3] + 1,
            display_slot=data[4],
            mode=mode,
            alarm=data[6] == 1,
            running=data[7] == 1,
            target_temperature=target_temperature,
            timer_target=timer_target,
            temperature=decode_temperature(int.from_bytes(data[10:12], "big")),
            time=data[12] * 60 + data[13],
            meat=data[14],
            doneness=data[15],
        )

    if cmd == Cmd.GET_UNIT:
        if len(data) < 6:
            raise FrameError("short unit frame")
        try:
            return UnitReport(Unit(data[5]))
        except ValueError:
            return UnitReport(data[5])

    return Ack(cmd, bytes(data[3:-1]))
