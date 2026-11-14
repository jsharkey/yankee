"""Switch entities (segment bar only): night light and rainbow."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import STATE_ON
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import DazzleConfigEntry
from .device import DazzleDevice
from .light import device_info


async def async_setup_entry(
    hass: HomeAssistant, entry: DazzleConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    device = entry.runtime_data
    if device.bar:
        async_add_entities([DazzleNightSwitch(device), DazzleRainbowSwitch(device)])


class _BarSwitch(SwitchEntity, RestoreEntity):
    """A segment-bar flag: restored after restart (nothing sent), applied when the light is on."""

    _attr_has_entity_name = True
    _attr_assumed_state = True
    _flag: str  # SegmentBar attribute

    def __init__(self, device: DazzleDevice) -> None:
        self._device = device
        self._attr_unique_id = f"{device.address}_{self._attr_translation_key}"
        self._attr_device_info = device_info(device)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is not None:
            setattr(self._device.bar, self._flag, last.state == STATE_ON)  # restore only
        self.async_on_remove(self._device.register_callback(self._update))

    @callback
    def _update(self) -> None:
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool:
        return getattr(self._device.bar, self._flag)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)

    async def _apply(self, on: bool) -> None:
        raise NotImplementedError

    async def _set(self, on: bool) -> None:
        try:
            await self._apply(on)
        except Exception as err:  # BLE errors
            raise HomeAssistantError(f"{self._device.name}: {err}") from err


class DazzleNightSwitch(_BarSwitch):
    """On: the layout's "night" slots show the night colour. Off: black."""

    _attr_translation_key = "night"
    _flag = "night_on"

    async def _apply(self, on: bool) -> None:
        await self._device.async_set_night(on)


class DazzleRainbowSwitch(_BarSwitch):
    """On: red/orange/yellow/green/blue/purple along the whole bar, overriding night + signal."""

    _attr_translation_key = "rainbow"
    _flag = "rainbow_on"

    async def _apply(self, on: bool) -> None:
        await self._device.async_set_rainbow(on)
