"""Advertisement parser for the Govee H5055 6-probe BBQ thermometer.

Kept free of Home Assistant imports so it can be unit tested on its own.

The H5055 advertises a 22 byte manufacturer-specific data block. Govee stuffs
bytes 4..6 of the device MAC address into the start of it, so the
"company id" Home Assistant reports changes per device (for
A4:C1:38:40:07:6C it is 0x0740 == 1856) and ``data[0]`` is the last MAC byte.
Offsets below index the 20 bytes Home Assistant hands us *after* the company
id has been stripped off::

    [0]      last byte of the MAC address
    [1]      frame type -- 0x00 for a temperature frame
    [2]      battery percent (bit 7 is a flag, masked off)
    [3]      probe selector: bits 6-7 pick the probe pair (00 -> 1&2,
             01 -> 3&4, 10 -> 5&6); bits 0-5 are "probe N is plugged in"
    [4]      status byte for the first probe of the pair
    [5:7]    first probe temperature, int16 little endian, whole degrees C
    [7:9]    first probe low alarm limit  (0xFFFF = not set)
    [9:11]   first probe high alarm limit (0xFFFF = not set)
    [11]     status byte for the second probe of the pair
    [12:14]  second probe temperature
    [14:16]  second probe low alarm limit
    [16:18]  second probe high alarm limit
    [18:20]  always 0x0000 in a temperature frame

The device also sends other kinds of 20 byte frames on the same advertisement
(for example ``6c 41 00 01 01 e4 81 00 ff ff ...``). Home Assistant's built-in
``govee_ble`` parser does not tell these apart from temperature frames and
decodes them as temperatures (that one comes out as -32284 C, with the battery
at 0 %), which is where the erratic readings come from. This parser only
accepts frames that pass every structural check below, and range-checks the
values as well.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import struct

SERVICE_UUID = "00005550-0000-1000-8000-00805f9b34fb"

FRAME_LENGTH = 20
FRAME_TYPE_TEMPERATURE = 0x00
NO_VALUE = 0xFFFF

# The probes are rated to roughly 300 C; anything outside this window is
# treated as a corrupt reading rather than reported.
MIN_VALID_TEMP = -40
MAX_VALID_TEMP = 400

PROBE_COUNT = 6

# Bits 6-7 of the selector byte -> (first probe, second probe) numbers.
_PAIR_FOR_SELECTOR = {
    0x00: (1, 2),
    0x40: (3, 4),
    0x80: (5, 6),
}

_PROBE_BLOCK = struct.Struct("<BHHH")  # status, temp, low, high


@dataclass(frozen=True)
class ProbeReading:
    """One probe's state from a single advertisement."""

    probe: int
    connected: bool
    temperature: int | None
    low_alarm: int | None
    high_alarm: int | None
    status: int


@dataclass(frozen=True)
class H5055Frame:
    """A decoded temperature frame. It carries two of the six probes."""

    battery: int
    probes: tuple[ProbeReading, ...] = field(default_factory=tuple)


class FrameRejected(ValueError):
    """The bytes are not a temperature frame we trust."""


def company_id_for_address(address: str) -> int | None:
    """Return the manufacturer id this device's MAC address produces."""
    parts = address.split(":")
    if len(parts) != 6:
        return None
    try:
        return int(parts[4], 16) << 8 | int(parts[3], 16)
    except ValueError:
        return None


def last_mac_byte(address: str) -> int | None:
    """Return the last byte of a MAC address, or None if it isn't one."""
    parts = address.split(":")
    if len(parts) != 6:
        return None
    try:
        return int(parts[5], 16)
    except ValueError:
        return None


def select_payload(address: str, manufacturer_data: dict[int, bytes]) -> bytes | None:
    """Pick the H5055 payload out of an advertisement's manufacturer data.

    A device may also advertise other blocks (such as an Apple iBeacon under
    id 76), so prefer the id derived from the MAC address and fall back to any
    20 byte block whose first byte matches the end of the MAC.
    """
    expected_id = company_id_for_address(address)
    if expected_id is not None and expected_id in manufacturer_data:
        return manufacturer_data[expected_id]
    tail = last_mac_byte(address)
    for payload in manufacturer_data.values():
        if len(payload) == FRAME_LENGTH and (tail is None or payload[0] == tail):
            return payload
    return None


def _value(raw: int) -> int | None:
    if raw == NO_VALUE:
        return None
    signed = raw - 0x10000 if raw & 0x8000 else raw
    if not MIN_VALID_TEMP <= signed <= MAX_VALID_TEMP:
        raise FrameRejected(f"value {raw:#06x} out of range")
    return signed


def parse_frame(data: bytes, address: str | None = None) -> H5055Frame:
    """Decode a temperature frame or raise FrameRejected."""
    if len(data) != FRAME_LENGTH:
        raise FrameRejected(f"length {len(data)} != {FRAME_LENGTH}")
    if address is not None:
        tail = last_mac_byte(address)
        if tail is not None and data[0] != tail:
            raise FrameRejected("first byte does not match MAC address")
    if data[1] != FRAME_TYPE_TEMPERATURE:
        raise FrameRejected(f"frame type {data[1]:#04x}")
    if data[18:20] != b"\x00\x00":
        raise FrameRejected("trailer is not 0x0000")
    selector = data[3]
    pair = _PAIR_FOR_SELECTOR.get(selector & 0xC0)
    if pair is None:
        raise FrameRejected(f"unknown probe selector {selector:#04x}")
    battery = data[2] & 0x7F
    if battery > 100:
        raise FrameRejected(f"battery {battery}")

    probes: list[ProbeReading] = []
    for probe, offset in zip(pair, (4, 11)):
        status, temp, low, high = _PROBE_BLOCK.unpack_from(data, offset)
        connected = bool(selector & (1 << (probe - 1)))
        temperature = _value(temp)
        probes.append(
            ProbeReading(
                probe=probe,
                connected=connected,
                temperature=temperature if connected else None,
                low_alarm=_value(low),
                high_alarm=_value(high),
                status=status,
            )
        )
    return H5055Frame(battery=battery, probes=tuple(probes))
