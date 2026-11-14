"""BLE device wrapper: connection handling and state for one string of lights."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant, callback

from . import dazzle_multicolor as dm
from .const import GATT_WRITE_UUID
from .segments import rainbow_args, render, segment_args
from .templates import TemplateError, build_payload, find_template

_LOGGER = logging.getLogger(__name__)

# Every LED value 0. Not "color off": the colour command clamps its value to >= 1.
BLANK_ARGS = "static off"

FRAGMENT_GAP = 0.03  # seconds between fragments of one message (as the script)

# After a failed connect, how long to wait for the lights' next advertisement
# before giving up. The local adapter's scan cache is emptied whenever its
# scanner restarts, and connections fail ("no scanner currently has it in its
# discovered devices") until the lights are heard again.
ADVERT_WAIT = 30
CONNECT_ATTEMPTS = 3


@dataclass
class SegmentBar:
    """Segment-bar mode: layout slots plus the night/signal state they resolve to."""

    slots: list[str]
    night_color: str
    signal_colors: dict[str, str]  # select option -> colour sent
    night_on: bool = False
    rainbow_on: bool = False  # overrides night + signal
    signal: str = field(default="")

    def __post_init__(self) -> None:
        if self.signal not in self.signal_colors:
            self.signal = next(iter(self.signal_colors))

    def args(self) -> str:
        if self.rainbow_on:
            return rainbow_args(len(self.slots))
        return segment_args(render(self.slots, self.night_on, self.night_color,
                                   self.signal_colors[self.signal]))

    def blank_args(self) -> str:
        return segment_args(["black"] * len(self.slots))


def ha_to_pct(brightness: int) -> int:
    """HA brightness 0-255 -> device 1-100."""
    return max(1, min(100, round(brightness * 100 / 255)))


class DazzleDevice:
    """One Dazzle Bright (IOTBT) string. State is assumed, not read back."""

    def __init__(
        self,
        hass: HomeAssistant,
        address: str,
        name: str,
        templates: dict[str, str],
        point_count: int,
        disconnect_delay: int,
        power_on_first: bool = False,
        blank_off: bool = True,
        bar: SegmentBar | None = None,
    ) -> None:
        self.hass = hass
        self.address = address
        self.name = name
        self.templates = templates
        self.point_count = point_count
        self._disconnect_delay = disconnect_delay
        # The vendor app never sends a power-on before a pattern: the pattern
        # command itself switches the string on. Sending 0x71 0x23 first makes the
        # lights wake in their default/last state (a white flash) until the
        # pattern arrives. Kept as an option for firmware that needs it.
        self._power_on_first = power_on_first
        # The lights show a stored white state whenever they really power on,
        # whatever command wakes them. With blank_off, "off" sets every LED to
        # value 0 (EC 01, all black) instead of cutting power, so "on" is just
        # the next pattern and the white power-on state is never shown.
        self._blank_off = blank_off
        # Segment-bar mode: the pattern is always built from the layout and the
        # night switch / signal select, never from templates.
        self.bar = bar

        self._client: BleakClientWithServiceCache | None = None
        self._ble_device: BLEDevice | None = None
        self._connect_lock = asyncio.Lock()
        self._send_lock = asyncio.Lock()
        self._disconnect_timer: asyncio.TimerHandle | None = None
        self._seq = 0
        self._callbacks: list[Callable[[], None]] = []

        # assumed state
        self.is_on: bool | None = None
        self.brightness: int = 255           # HA scale 0-255
        self.active_template: str | None = None
        self.active_args: str | None = None  # last pattern command (template or service)

    # ------------------------------------------------------------- callbacks
    @callback
    def register_callback(self, cb: Callable[[], None]) -> Callable[[], None]:
        self._callbacks.append(cb)

        def _remove() -> None:
            if cb in self._callbacks:
                self._callbacks.remove(cb)
        return _remove

    @callback
    def _notify(self) -> None:
        for cb in list(self._callbacks):
            cb()

    # ----------------------------------------------------------- high level
    async def async_turn_on(self, brightness: int | None = None) -> None:
        """Turn on by sending the active pattern directly (no white flash).

        Only falls back to a bare power-on when there is no pattern to send.
        """
        if brightness is not None:
            self.brightness = brightness
        args = self.bar.args() if self.bar else (self.active_args or self._fallback_args())
        if args is None:
            await self._send(*_power(True))
        elif brightness is not None or self.is_on is not True:
            payload = build_payload(args, ha_to_pct(self.brightness), self.point_count)
            if self._power_on_first and self.is_on is not True:
                await self._send(*_power(True))
            await self._send(*payload)
            if self.active_args is None and not self.bar:
                self.active_args = args
        self.is_on = True
        self._notify()

    async def async_turn_off(self) -> None:
        if self._blank_off:
            blank = self.bar.blank_args() if self.bar else BLANK_ARGS
            await self._send(*build_payload(blank, None, self.point_count))
        else:
            await self._send(*_power(False))
        self.is_on = False
        self._notify()

    async def async_set_night(self, on: bool) -> None:
        """Night switch (segment bar). Shown at once if the light is on, else at next turn-on."""
        assert self.bar is not None
        self.bar.night_on = on
        await self._refresh_bar()

    async def async_set_rainbow(self, on: bool) -> None:
        """Rainbow switch (segment bar): overrides night + signal while on."""
        assert self.bar is not None
        self.bar.rainbow_on = on
        await self._refresh_bar()

    async def async_set_signal(self, color: str) -> None:
        """Signal select (segment bar). Shown at once if the light is on, else at next turn-on."""
        assert self.bar is not None
        if color not in self.bar.signal_colors:
            raise TemplateError(f"unknown signal colour {color!r}")
        self.bar.signal = color
        await self._refresh_bar()

    async def _refresh_bar(self) -> None:
        assert self.bar is not None
        if self.is_on:
            await self._send(*build_payload(self.bar.args(), ha_to_pct(self.brightness),
                                            self.point_count))
        self._notify()

    async def async_apply_template(self, name: str) -> None:
        """Run a named template (from the select entity or the input_select)."""
        args = find_template(self.templates, name)
        if args is None:
            raise TemplateError(f"unknown template {name!r}")
        await self.async_send_command(args, template=_canonical(self.templates, name))

    async def async_send_command(self, args: str, template: str | None = None) -> None:
        """Send any dazzle_multicolor command line, e.g. "anim meteor red white".

        Pattern commands are remembered so brightness changes can re-send them;
        on/off/query are passed through without changing the active pattern.
        """
        first = args.split()[0] if args.split() else ""
        if first in ("on", "off", "query"):
            await self._send(*build_payload(args, None, self.point_count))
            if first in ("on", "off"):
                self.is_on = first == "on"
                self._notify()
            return
        payload, cmd_id = build_payload(args, ha_to_pct(self.brightness), self.point_count)
        if self._power_on_first and self.is_on is not True:
            await self._send(*_power(True))
        await self._send(payload, cmd_id)
        self.active_args = args
        self.active_template = template
        self.is_on = True
        self._notify()

    def restore(self, is_on: bool | None, brightness: int | None,
                template: str | None, args: str | None) -> None:
        """Restore assumed state after a Home Assistant restart (nothing is sent)."""
        self.is_on = is_on
        if brightness:
            self.brightness = brightness
        if template and find_template(self.templates, template) is not None:
            self.active_template = _canonical(self.templates, template)
            self.active_args = find_template(self.templates, template)
        elif args:
            self.active_args = args

    def _fallback_args(self) -> str | None:
        """Pattern to use for a brightness change before any pattern was chosen."""
        return next(iter(self.templates.values()), None)

    # ------------------------------------------------------------ transport
    async def _send(self, payload: bytes, cmd_id: int) -> None:
        async with self._send_lock:
            client = await self._ensure_connected()
            mtu = getattr(client, "mtu_size", None) or 23
            max_len = max(20, min(mtu - 4, 255))
            self._seq = (self._seq + 1) & 0xFF
            frags = dm.frame_v0(payload, self._seq, cmd_id, max_len)
            try:
                for i, frag in enumerate(frags):
                    _LOGGER.debug("%s write: %s", self.name, frag.hex(" "))
                    await client.write_gatt_char(GATT_WRITE_UUID, frag, response=False)
                    if i < len(frags) - 1:
                        await asyncio.sleep(FRAGMENT_GAP)
            except BleakError as err:
                _LOGGER.warning("%s: write failed (%s), dropping connection", self.name, err)
                await self._disconnect()
                raise

    async def _ensure_connected(self) -> BleakClientWithServiceCache:
        self._cancel_disconnect_timer()
        if self._client and self._client.is_connected:
            self._schedule_disconnect()
            return self._client
        async with self._connect_lock:
            if not (self._client and self._client.is_connected):
                ble_device = bluetooth.async_ble_device_from_address(
                    self.hass, self.address, connectable=True
                ) or self._ble_device
                if ble_device is None:
                    ble_device = await self._wait_for_advertisement(None)
                self._ble_device = ble_device
                try:
                    self._client = await self._connect()
                except BleakError as err:
                    # Usually the adapter has not re-heard the lights since
                    # its scanner restarted. Wait for a fresh advert, retry once.
                    _LOGGER.debug("%s: connect failed (%s); waiting for an "
                                  "advertisement", self.name, err)
                    self._ble_device = await self._wait_for_advertisement(err)
                    self._client = await self._connect()
        self._schedule_disconnect()
        return self._client

    async def _connect(self) -> BleakClientWithServiceCache:
        _LOGGER.debug("Connecting to %s", self.name)
        return await establish_connection(
            BleakClientWithServiceCache,
            self._ble_device,
            self.name,
            disconnected_callback=self._on_disconnected,
            max_attempts=CONNECT_ATTEMPTS,
            use_services_cache=True,
            ble_device_callback=lambda: self._ble_device,
        )

    async def _wait_for_advertisement(self, err: Exception | None) -> BLEDevice:
        """Wait until the lights advertise again (newer than any we know of).

        Registering a callback replays the last cached advert straight away,
        so only adverts with a later timestamp count.
        """
        last = bluetooth.async_last_service_info(self.hass, self.address, connectable=True)
        stale = last.time if last else float("-inf")
        try:
            info = await bluetooth.async_process_advertisements(
                self.hass,
                lambda i: i.time > stale,
                {"address": self.address, "connectable": True},
                bluetooth.BluetoothScanningMode.ACTIVE,
                ADVERT_WAIT,
            )
        except TimeoutError:
            raise BleakError(
                f"the lights have not advertised for {ADVERT_WAIT} s. They may be "
                "connected to another device (close the phone app, and don't "
                "add it to lednetwf_ble as well), or out of range of your "
                "Bluetooth adapter"
            ) from err
        _LOGGER.debug("%s advertised again (RSSI %s)", self.name, info.rssi)
        return info.device

    @callback
    def async_start(self) -> Callable[[], None]:
        """Track the lights' advertisements so connects use the freshest path."""

        @callback
        def _seen(info, _change) -> None:
            self._ble_device = info.device

        return bluetooth.async_register_callback(
            self.hass, _seen,
            {"address": self.address, "connectable": True},
            bluetooth.BluetoothScanningMode.ACTIVE,
        )

    def _cancel_disconnect_timer(self) -> None:
        if self._disconnect_timer:
            self._disconnect_timer.cancel()
            self._disconnect_timer = None

    def _schedule_disconnect(self) -> None:
        self._cancel_disconnect_timer()
        self._disconnect_timer = self.hass.loop.call_later(
            self._disconnect_delay,
            lambda: self.hass.async_create_task(self._disconnect()),
        )

    async def _disconnect(self) -> None:
        self._cancel_disconnect_timer()
        client, self._client = self._client, None
        if client and client.is_connected:
            try:
                await client.disconnect()
            except BleakError:
                pass

    @callback
    def _on_disconnected(self, _client) -> None:
        _LOGGER.debug("%s disconnected", self.name)
        self._client = None

    async def async_shutdown(self) -> None:
        await self._disconnect()


def _power(on: bool) -> tuple[bytes, int]:
    return dm.build_power(on), 0x0A


def _canonical(templates: dict[str, str], name: str) -> str:
    for key in templates:
        if key.lower() == name.strip().lower():
            return key
    return name
