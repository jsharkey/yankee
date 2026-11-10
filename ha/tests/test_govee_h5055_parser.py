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

# The advertisement from the user's own device. It is not a temperature frame;
# Home Assistant's built-in parser reads it as probe 1 = -32284 C, battery 0 %.
USER_ADDRESS = "A4:C1:38:40:07:6C"
USER_FRAME = bytes.fromhex("6c41000101e48100ffffffffffffffffffffffff")

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


def test_user_frame_is_rejected():
    with pytest.raises(parser.FrameRejected):
        parser.parse_frame(USER_FRAME, USER_ADDRESS)


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
