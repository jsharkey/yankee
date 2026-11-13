"""Light entity: on/off and brightness."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.light import ATTR_BRIGHTNESS, ColorMode, LightEntity
from homeassistant.const import STATE_ON
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_platform
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import DazzleConfigEntry
from .const import ATTR_COMMAND, ATTR_TEMPLATE, DOMAIN, SERVICE_SEND_COMMAND
from .device import DazzleDevice
from .templates import TemplateError


async def async_setup_entry(
    hass: HomeAssistant, entry: DazzleConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([DazzleLight(entry.runtime_data)])
    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_SEND_COMMAND,
        {vol.Required(ATTR_COMMAND): cv.string},
        "async_send_command",
    )


def device_info(device: DazzleDevice) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, device.address)},
        connections={(CONNECTION_BLUETOOTH, device.address)},
        name=device.name,
        manufacturer="Dazzle Bright / Zengge",
        model="IOTBT string lights",
    )


class DazzleLight(LightEntity, RestoreEntity):
    """The string as a dimmable light. State is assumed (the lights don't report it)."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_assumed_state = True
    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}

    def __init__(self, device: DazzleDevice) -> None:
        self._device = device
        self._attr_unique_id = f"{device.address}_light"
        self._attr_device_info = device_info(device)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is not None:
            self._device.restore(
                last.state == STATE_ON,
                last.attributes.get(ATTR_BRIGHTNESS),
                last.attributes.get(ATTR_TEMPLATE),
                last.attributes.get(ATTR_COMMAND),
            )
        self.async_on_remove(self._device.register_callback(self._update))

    @callback
    def _update(self) -> None:
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool | None:
        return self._device.is_on

    @property
    def brightness(self) -> int | None:
        return self._device.brightness

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            ATTR_TEMPLATE: self._device.active_template,
            ATTR_COMMAND: self._device.active_args,
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._run(self._device.async_turn_on(kwargs.get(ATTR_BRIGHTNESS)))

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._run(self._device.async_turn_off())

    async def async_send_command(self, command: str) -> None:
        """Service dazzle_bright.send_command: any dazzle_multicolor command line."""
        await self._run(self._device.async_send_command(command))

    async def _run(self, coro) -> None:
        try:
            await coro
        except TemplateError as err:
            raise HomeAssistantError(str(err)) from err
        except Exception as err:  # BLE errors
            raise HomeAssistantError(f"{self._device.name}: {err}") from err
