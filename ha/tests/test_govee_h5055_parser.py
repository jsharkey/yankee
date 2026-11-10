"""Tests for the H5055 advertisement parser. Run: python -m pytest ha/tests"""

import importlib.util
import sys
from pathlib import Path

import pytest

_PATH = Path(__file__).parents[1] / "custom_components/govee_h5055/parser.py"
_spec = importlib.util.spec_from_file_location("h5055_parser", _PATH)
parser = importlib.util.module_from_spec(_spec)
sys.modules["h5055_parser"] = parser
_spec.loader.exec_module(parser)

# Frame type 0x41, captured from a real device with only probe 1 plugged in.
# Home Assistant's built-in parser reads these as wild temperatures.
USER_ADDRESS = "A4:C1:38:40:07:6C"
USER_FRAME = bytes.fromhex("6c41000101e48100ffffffffffffffffffffffff")  # 5 & 6
USER_P12 = bytes.fromhex("6c41000101e4010009c4ffffffffffffffffffff")
USER_P34 = bytes.fromhex("6c41000101e44100ffffffffffffffffffffffff")

# Temperature frames from the govee-ble test suite (device A4:C1:38:2F:AF:55).
GB_ADDRESS = "A4:C1:38:2F:AF:55"
GB_PROBE_1 = b"U\x00d\x01 \x1a\x00\xff\xff\xff\xff \x19\x00\xff\xff\xff\xff\x00\x00"
GB_PROBE_34 = b"U\x00d\x4c \x1a\x00\xff\xff\xff\xff \x19\x00\x14\x00\xb1\x00\x00\x00"
GB_PROBE_56 = b"U\x00d\xbf \x1a\x00\xff\xff\xb1\x00 \x19\x00\xff\xff\xff\xff\x00\x00"
GB_ERROR = b"U\x00d\xfb \x1a\x00\xff\xff\xb1\x00 \x19\x00\xff\xff\xff\xff\x00\x00"


def test_company_id_comes_from_mac():
    assert parser.company_id_for_address(USER_ADDRESS) == 1856
    assert parser.company_id_for_address(GB_ADDRESS) == 44847


def test_select_payload_prefers_mac_derived_id():
    data = {76: b"\x02\x15INTELLI_ROCKS_HWPr\xf2\xff\xc2", 1856: USER_FRAME}
    assert parser.select_payload(USER_ADDRESS, data) == USER_FRAME


def test_v41_probe_1_and_2():
    frame = parser.parse_frame(USER_P12, USER_ADDRESS)
    assert frame.battery == 100
    p1, p2 = frame.probes
    assert (p1.probe, p1.connected, p1.temperature) == (1, True, 25.0)
    assert (p1.low_alarm, p1.high_alarm) == (None, None)
    assert (p2.probe, p2.connected, p2.temperature) == (2, False, None)


def test_v41_empty_pairs():
    for data, pair in ((USER_P34, (3, 4)), (USER_FRAME, (5, 6))):
        frame = parser.parse_frame(data, USER_ADDRESS)
        assert tuple(p.probe for p in frame.probes) == pair
        assert all(p.temperature is None and not p.connected for p in frame.probes)


def test_v41_limits_and_fractions():
    data = bytearray(USER_P12)
    data[8:14] = (7350).to_bytes(2, "big") + (1000).to_bytes(2, "big") + (9000).to_bytes(2, "big")
    p1, _ = parser.parse_frame(bytes(data), USER_ADDRESS).probes
    assert (p1.temperature, p1.low_alarm, p1.high_alarm) == (73.5, 10.0, 90.0)


def test_v41_out_of_range_rejected():
    data = bytearray(USER_P12)
    data[8:10] = (50000).to_bytes(2, "big")
    with pytest.raises(parser.FrameRejected):
        parser.parse_frame(bytes(data), USER_ADDRESS)


def test_unknown_frame_type_rejected():
    data = bytearray(USER_P12)
    data[1] = 0x42
    with pytest.raises(parser.FrameRejected):
        parser.parse_frame(bytes(data), USER_ADDRESS)


def test_probe_1_only():
    frame = parser.parse_frame(GB_PROBE_1, GB_ADDRESS)
    assert frame.battery == 100
    p1, p2 = frame.probes
    assert (p1.probe, p1.connected, p1.temperature) == (1, True, 26)
    assert (p1.low_alarm, p1.high_alarm) == (None, None)
    assert (p2.probe, p2.connected, p2.temperature) == (2, False, None)


def test_probes_3_and_4_with_limits():
    p3, p4 = parser.parse_frame(GB_PROBE_34, GB_ADDRESS).probes
    assert (p3.probe, p3.temperature) == (3, 26)
    assert (p4.probe, p4.temperature, p4.low_alarm, p4.high_alarm) == (4, 25, 20, 177)


def test_probes_5_and_6():
    p5, p6 = parser.parse_frame(GB_PROBE_56, GB_ADDRESS).probes
    assert (p5.probe, p5.temperature, p5.high_alarm) == (5, 26, 177)
    assert (p6.probe, p6.temperature) == (6, 25)


def test_unknown_selector_rejected():
    with pytest.raises(parser.FrameRejected):
        parser.parse_frame(GB_ERROR, GB_ADDRESS)


def test_wrong_mac_rejected():
    with pytest.raises(parser.FrameRejected):
        parser.parse_frame(GB_PROBE_1, USER_ADDRESS)


def test_out_of_range_temperature_rejected():
    bad = bytearray(GB_PROBE_1)
    bad[5:7] = (2000).to_bytes(2, "little")
    with pytest.raises(parser.FrameRejected):
        parser.parse_frame(bytes(bad), GB_ADDRESS)


def test_nonzero_trailer_rejected():
    bad = bytearray(GB_PROBE_1)
    bad[18] = 0xFF
    with pytest.raises(parser.FrameRejected):
        parser.parse_frame(bytes(bad), GB_ADDRESS)
