"""Tests for the BBQ100 protocol module. Run: python -m pytest ha/tests

The expected bytes follow the vendor app's GattFactory / view models
(Chi-BBQ 1.0.6); no capture from a real thermometer yet.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

_PATH = Path(__file__).parents[1] / "custom_components/chileaf_bbq100/protocol.py"
_spec = importlib.util.spec_from_file_location("bbq100_protocol", _PATH)
p = importlib.util.module_from_spec(_spec)
sys.modules["bbq100_protocol"] = p
_spec.loader.exec_module(p)


def frame(hexstr: str) -> bytes:
    """Hex body without checksum -> full frame with the checksum appended."""
    body = bytes.fromhex(hexstr)
    return body + bytes([sum(body) & 0xFF])


# --- commands ----------------------------------------------------------------


def test_get_unit_matches_app_constant():
    # GattFactory.obtainTempUnit() builds exactly 6A 04 03 71.
    assert p.query_unit().hex(" ") == "6a 04 03 71"
    assert p.query_version().hex(" ") == "6a 04 01 6f"


def test_query_channel_uses_zero_based_probe():
    assert p.query_channel(1).hex(" ") == "6a 05 02 00 71"
    assert p.query_channel(4).hex(" ") == "6a 05 02 03 74"


def test_set_target_temperature_in_hundredths():
    # 74 C on probe 2 -> 7400 = 0x1CE8.
    assert p.set_target_temperature(2, 74) == frame("6a 07 07 01 1c e8")
    assert p.set_target_temperature(1, 63.5) == frame("6a 07 07 00 18 ce")


def test_set_timer():
    assert p.set_timer(3, 12, 30) == frame("6a 07 08 02 0c 1e")
    with pytest.raises(ValueError):
        p.set_timer(1, 0, 0)
    with pytest.raises(ValueError):
        p.set_timer(1, 100, 0)


def test_set_meat_checks_doneness_per_meat():
    assert p.set_meat(1, 0, 1) == frame("6a 07 04 00 00 01")  # beef medium rare
    with pytest.raises(ValueError):
        p.set_meat(1, 5, 0)  # rare chicken is not offered


def test_run_alarm_unit():
    assert p.set_running(4, True) == frame("6a 06 09 03 01")
    assert p.set_running(4, False) == frame("6a 06 09 03 00")
    assert p.stop_alarm(2) == frame("6a 05 0a 01")
    assert p.set_unit(p.Unit.CELSIUS) == frame("6a 05 0b 01")
    assert p.set_unit(p.Unit.FAHRENHEIT) == frame("6a 05 0b 00")


def test_bad_probe_rejected():
    with pytest.raises(ValueError):
        p.query_channel(0)
    with pytest.raises(ValueError):
        p.query_channel(5)


def test_meat_presets():
    labels = [label for _, _, label in p.meat_presets()]
    assert labels[:2] == ["Beef rare", "Beef medium rare"]
    assert "Chicken" in labels and "Pork medium" in labels
    assert "Pork rare" not in labels
    assert len(labels) == 5 * 3 + 4 + 4  # beef/veal/lamb, pork, four single-level meats


# --- notifications ---------------------------------------------------------------


def test_all_temps():
    # Probe 1 at 23.45 C, 2 unplugged (30200), 3 at -5.00 C, 4 at 250 C.
    data = frame("6a 0c 0f 09 29 75 f8 fe 0c 61 a8")
    assert p.parse_frame(data) == p.AllTemps((23.45, None, -5.0, 250.0))


def test_channel_temperature_mode():
    # probe 2, slot 1, temperature mode, no alarm, running, target 74 C,
    # current 61.2 C, 3:05 elapsed, meat 0 / doneness 2.
    data = frame("6a 11 02 01 01 01 00 01 1c e8 17 e8 03 05 00 02")
    state = p.parse_frame(data)
    assert state == p.ChannelState(
        probe=2, display_slot=1, mode=p.Mode.TEMPERATURE, alarm=False, running=True,
        target_temperature=74.0, timer_target=None, temperature=61.2,
        time=185, meat=0, doneness=2,
    )


def test_channel_timer_mode_target_is_minutes_seconds():
    data = frame("6a 11 02 03 03 02 01 01 0a 1e 75 f8 01 02 00 00")
    state = p.parse_frame(data)
    assert state.probe == 4 and state.mode == p.Mode.TIMER and state.alarm
    assert state.timer_target == 10 * 60 + 30
    assert state.target_temperature is None
    assert state.temperature is None  # unplugged
    assert state.time == 62


def test_channel_bad_probe():
    with pytest.raises(p.FrameError):
        p.parse_frame(frame("6a 11 02 07 00 00 00 00 00 00 00 00 00 00 00 00"))


def test_unit_report():
    assert p.parse_frame(frame("6a 07 03 00 00 01")) == p.UnitReport(p.Unit.CELSIUS)
    assert p.parse_frame(frame("6a 07 03 00 00 00")) == p.UnitReport(p.Unit.FAHRENHEIT)


def test_ack_and_garbage():
    assert p.parse_frame(frame("6a 05 09 01")) == p.Ack(0x09, b"\x01")
    with pytest.raises(p.FrameError):
        p.parse_frame(b"\x00\x01\x02\x03")
    with pytest.raises(p.FrameError):
        p.parse_frame(frame("6a 08 0f 00"))  # short temperature frame


def test_decode_temperature():
    assert p.decode_temperature(30200) is None
    assert p.decode_temperature(0xFFFF) == -0.01
    assert p.decode_temperature(0x7FFF) is None  # 327.67 C: implausible
