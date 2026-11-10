"""Listens for H5055 advertisements and keeps the latest good reading."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
import logging
import time

from homeassistant.components import bluetooth
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback

from .parser import FrameRejected, ProbeReading, parse_frame, select_payload

_LOGGER = logging.getLogger(__name__)

# How many raw frames to keep for the diagnostics download.
_HISTORY = 50


class H5055Coordinator:
    """State for one thermometer, fed by passive Bluetooth advertisements."""

    def __init__(self, hass: HomeAssistant, address: str) -> None:
        self.hass = hass
        self.address = address
        self.battery: int | None = None
        self.rssi: int | None = None
        self.probes: dict[int, ProbeReading] = {}
        self.available = False
        self.recent_frames: deque[dict] = deque(maxlen=_HISTORY)
        self.rejected_count = 0
        self._seen_rejects: set[bytes] = set()
        # Alarm thresholds set from Home Assistant: {(probe, "low"|"high"): C}.
        self.limits: dict[tuple[int, str], float] = {}
        self._last_payload: bytes | None = None
        self._listeners: list[Callable[[], None]] = []
        self._unsubs: list[CALLBACK_TYPE] = []

    @callback
    def async_start(self) -> None:
        self._unsubs.append(
            bluetooth.async_register_callback(
                self.hass,
                self._async_handle_advertisement,
                bluetooth.BluetoothCallbackMatcher(
                    address=self.address, connectable=False
                ),
                bluetooth.BluetoothScanningMode.PASSIVE,
            )
        )
        self._unsubs.append(
            bluetooth.async_track_unavailable(
                self.hass, self._async_handle_unavailable, self.address, connectable=False
            )
        )
        if last := bluetooth.async_last_service_info(
            self.hass, self.address, connectable=False
        ):
            self._async_handle_advertisement(last, bluetooth.BluetoothChange.ADVERTISEMENT)

    @callback
    def async_stop(self) -> None:
        while self._unsubs:
            self._unsubs.pop()()

    @callback
    def async_add_listener(self, update: Callable[[], None]) -> CALLBACK_TYPE:
        self._listeners.append(update)

        @callback
        def _remove() -> None:
            self._listeners.remove(update)

        return _remove

    def alarm_active(self, probe: int) -> bool | None:
        """Whether a probe is outside the limits set in Home Assistant."""
        reading = self.probes.get(probe)
        if reading is None or reading.temperature is None:
            return None
        low = self.limits.get((probe, "low"))
        high = self.limits.get((probe, "high"))
        return (low is not None and reading.temperature < low) or (
            high is not None and reading.temperature > high
        )

    @callback
    def async_notify(self) -> None:
        for update in list(self._listeners):
            update()

    @callback
    def _async_handle_unavailable(
        self, _info: bluetooth.BluetoothServiceInfoBleak
    ) -> None:
        self.available = False
        self._last_payload = None
        self.async_notify()

    @callback
    def _async_handle_advertisement(
        self,
        info: bluetooth.BluetoothServiceInfoBleak,
        _change: bluetooth.BluetoothChange,
    ) -> None:
        self.rssi = info.rssi
        payload = select_payload(info.address, info.manufacturer_data)
        if payload is None or payload == self._last_payload:
            # BlueZ keeps re-reporting the last payload for every company id,
            # so an unchanged payload carries no new information.
            return
        self._last_payload = payload
        try:
            frame = parse_frame(payload, info.address)
        except FrameRejected as err:
            self.rejected_count += 1
            self.recent_frames.append(
                {"time": time.time(), "data": payload.hex(), "rejected": str(err)}
            )
            if payload not in self._seen_rejects and len(self._seen_rejects) < 200:
                self._seen_rejects.add(payload)
                _LOGGER.debug(
                    "%s: ignoring non-temperature frame %s (%s)",
                    self.address,
                    payload.hex(),
                    err,
                )
            return

        self.recent_frames.append({"time": time.time(), "data": payload.hex()})
        self.battery = frame.battery
        for reading in frame.probes:
            self.probes[reading.probe] = reading
        self.available = True
        self.async_notify()
