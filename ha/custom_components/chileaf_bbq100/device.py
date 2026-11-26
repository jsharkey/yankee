"""Holds the Bluetooth connection to one BBQ100 and the latest state it reported."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
import logging
import time

from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from homeassistant.components import bluetooth
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_track_time_interval

from . import protocol as p
from .const import CHANNEL_REFRESH_INTERVAL, CONNECT_ATTEMPTS, SILENCE_TIMEOUT

_LOGGER = logging.getLogger(__name__)

# How many raw notifications to keep for the diagnostics download.
_HISTORY = 50


@dataclass
class ProbeState:
    """What we know about one probe."""

    temperature: float | None = None
    channel: p.ChannelState | None = None
    channel_at: float = field(default=0.0)  # monotonic time channel was read

    def time_now(self) -> int | None:
        """Seconds on the probe's clock now, counted on from the last report.

        Counts down in timer mode and up otherwise, as the app does, and only
        while the probe runs with no alarm sounding.
        """
        ch = self.channel
        if ch is None:
            return None
        if not ch.running:
            return ch.time if ch.mode == p.Mode.TIMER else 0
        if ch.alarm:
            return ch.time
        age = int(time.monotonic() - self.channel_at)
        if ch.mode == p.Mode.TIMER:
            return max(0, ch.time - age)
        return ch.time + age


class BBQ100Device:
    """One thermometer. Keeps a connection open while it is enabled."""

    def __init__(self, hass: HomeAssistant, address: str, name: str) -> None:
        self.hass = hass
        self.address = address
        self.name = name
        self.probes = {n: ProbeState() for n in range(1, p.PROBE_COUNT + 1)}
        self.unit: p.Unit | int | None = None
        self.version: str | None = None
        self.recent_frames: deque[dict] = deque(maxlen=_HISTORY)
        # Off lets the phone app connect: the thermometer takes one connection.
        self.enabled = True

        self._ble_device: BLEDevice | None = None
        self._client: BleakClientWithServiceCache | None = None
        self._write_response = False
        self._connect_task: asyncio.Task | None = None
        self._last_rx = 0.0
        self._listeners: list[Callable[[], None]] = []
        self._unsubs: list[CALLBACK_TYPE] = []

    # ------------------------------------------------------------ listeners
    @property
    def connected(self) -> bool:
        return self._client is not None and self._client.is_connected

    @callback
    def async_add_listener(self, update: Callable[[], None]) -> CALLBACK_TYPE:
        self._listeners.append(update)

        @callback
        def _remove() -> None:
            self._listeners.remove(update)

        return _remove

    @callback
    def _notify(self) -> None:
        for update in list(self._listeners):
            update()

    # ------------------------------------------------------------ lifecycle
    @callback
    def async_start(self) -> None:
        self._unsubs.append(
            bluetooth.async_register_callback(
                self.hass,
                self._async_advertisement,
                bluetooth.BluetoothCallbackMatcher(address=self.address, connectable=True),
                bluetooth.BluetoothScanningMode.ACTIVE,
            )
        )
        self._unsubs.append(
            async_track_time_interval(
                self.hass, self._async_tick, timedelta(seconds=CHANNEL_REFRESH_INTERVAL)
            )
        )
        if info := bluetooth.async_last_service_info(self.hass, self.address, connectable=True):
            self._ble_device = info.device
        self._async_maybe_connect()

    async def async_stop(self) -> None:
        while self._unsubs:
            self._unsubs.pop()()
        if self._connect_task:
            self._connect_task.cancel()
        await self._disconnect()

    async def async_set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        if enabled:
            self._async_maybe_connect()
        else:
            if self._connect_task:
                self._connect_task.cancel()
            await self._disconnect()
        self._notify()

    @callback
    def _async_advertisement(
        self, info: bluetooth.BluetoothServiceInfoBleak, _change: bluetooth.BluetoothChange
    ) -> None:
        # It only advertises while nothing is connected to it.
        self._ble_device = info.device
        self._async_maybe_connect()

    async def _async_tick(self, _now=None) -> None:
        if not self.connected:
            self._async_maybe_connect()
            return
        if time.monotonic() - self._last_rx > SILENCE_TIMEOUT:
            _LOGGER.debug("%s: no data for %s s, reconnecting", self.name, SILENCE_TIMEOUT)
            await self._disconnect()
            self._async_maybe_connect()
            return
        await self._refresh_channels()

    @callback
    def _async_maybe_connect(self) -> None:
        if not self.enabled or self.connected:
            return
        if self._connect_task and not self._connect_task.done():
            return
        device = (
            bluetooth.async_ble_device_from_address(self.hass, self.address, connectable=True)
            or self._ble_device
        )
        if device is None:
            return
        self._ble_device = device
        self._connect_task = self.hass.async_create_background_task(
            self._async_connect(), f"{self.name} connect"
        )

    async def _async_connect(self) -> None:
        try:
            client = await establish_connection(
                BleakClientWithServiceCache,
                self._ble_device,
                self.name,
                disconnected_callback=self._on_disconnected,
                max_attempts=CONNECT_ATTEMPTS,
                use_services_cache=True,
                ble_device_callback=lambda: self._ble_device,
            )
        except (BleakError, TimeoutError) as err:
            _LOGGER.debug("%s: connect failed: %s", self.name, err)
            return
        try:
            char = client.services.get_characteristic(p.WRITE_UUID)
            if char is None:
                raise BleakError("write characteristic not found")
            # The app writes with response whenever the characteristic allows it.
            self._write_response = "write" in char.properties
            await client.start_notify(p.NOTIFY_UUID, self._on_notification)
        except BleakError as err:
            _LOGGER.warning("%s: setup after connect failed: %s", self.name, err)
            await client.disconnect()
            return
        if not self.enabled:
            await client.disconnect()
            return
        self._client = client
        self._last_rx = time.monotonic()
        _LOGGER.debug("%s: connected", self.name)
        self._notify()
        # The app waits a second after connecting before its first requests.
        await asyncio.sleep(1)
        try:
            await self._write(p.query_unit())
            await self._write(p.query_version())
            await self._refresh_channels()
        except HomeAssistantError as err:
            _LOGGER.debug("%s: initial queries failed: %s", self.name, err)

    @callback
    def _on_disconnected(self, _client) -> None:
        _LOGGER.debug("%s: disconnected", self.name)
        self._client = None
        self._notify()

    async def _disconnect(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            try:
                await client.disconnect()
            except BleakError:
                pass
            self._notify()

    # ------------------------------------------------------------- receive
    @callback
    def _on_notification(self, _sender, data: bytearray) -> None:
        data = bytes(data)
        self._last_rx = time.monotonic()
        entry: dict = {"time": time.time(), "data": data.hex(" ")}
        self.recent_frames.append(entry)
        try:
            frame = p.parse_frame(data)
        except p.FrameError as err:
            entry["rejected"] = str(err)
            _LOGGER.debug("%s: ignoring %s (%s)", self.name, data.hex(" "), err)
            return

        if isinstance(frame, p.AllTemps):
            for n, temp in enumerate(frame.temperatures, start=1):
                self.probes[n].temperature = temp
        elif isinstance(frame, p.ChannelState):
            probe = self.probes[frame.probe]
            probe.channel = frame
            probe.channel_at = time.monotonic()
            probe.temperature = frame.temperature
        elif isinstance(frame, p.UnitReport):
            self.unit = frame.unit
        elif frame.cmd == p.Cmd.VERSION:
            self.version = frame.payload.hex(" ")
        else:
            return
        self._notify()

    # ---------------------------------------------------------------- send
    async def _write(self, frame: bytes) -> None:
        client = self._client
        if client is None or not client.is_connected:
            raise HomeAssistantError(
                f"{self.name} is not connected. Close the phone app, which "
                "holds the thermometer's only connection, and check that it is "
                "switched on and in range."
            )
        _LOGGER.debug("%s write: %s", self.name, frame.hex(" "))
        try:
            await client.write_gatt_char(p.WRITE_UUID, frame, response=self._write_response)
        except BleakError as err:
            raise HomeAssistantError(f"{self.name}: write failed: {err}") from err

    async def _refresh_channels(self) -> None:
        try:
            for n in self.probes:
                await self._write(p.query_channel(n))
        except HomeAssistantError as err:
            _LOGGER.debug("%s: channel refresh failed: %s", self.name, err)

    async def _probe_command(self, probe: int, frame: bytes) -> None:
        await self._write(frame)
        # The app re-reads the probe after each change; its reply updates us.
        await self._write(p.query_channel(probe))

    async def async_set_target_temperature(self, probe: int, celsius: float) -> None:
        await self._probe_command(probe, p.set_target_temperature(probe, celsius))

    async def async_set_timer(self, probe: int, minutes: int, seconds: int = 0) -> None:
        await self._probe_command(probe, p.set_timer(probe, minutes, seconds))

    async def async_set_meat(self, probe: int, meat: int, doneness: int) -> None:
        await self._probe_command(probe, p.set_meat(probe, meat, doneness))

    async def async_set_running(self, probe: int, running: bool) -> None:
        await self._probe_command(probe, p.set_running(probe, running))

    async def async_stop_alarm(self, probe: int) -> None:
        await self._probe_command(probe, p.stop_alarm(probe))

    async def async_set_unit(self, unit: p.Unit) -> None:
        await self._write(p.set_unit(unit))
        await self._write(p.query_unit())
