"""Select entities: pattern template (string lights) or signal colour (segment bar)."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DazzleConfigEntry
from .device import DazzleDevice
from .light import device_info
from .templates import TemplateError


async def async_setup_entry(
    hass: HomeAssistant, entry: DazzleConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    device = entry.runtime_data
    if device.bar:
        async_add_entities([DazzleSignalSelect(device)])
    else:
        async_add_entities([DazzlePatternSelect(device)])


class DazzlePatternSelect(SelectEntity):
    """Pattern picker; options are the template names from the integration options."""

    _attr_has_entity_name = True
    _attr_translation_key = "pattern"
    _attr_assumed_state = True

    def __init__(self, device: DazzleDevice) -> None:
        self._device = device
        self._attr_unique_id = f"{device.address}_pattern"
        self._attr_device_info = device_info(device)
        self._attr_options = list(device.templates)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._device.register_callback(self._update))

    @callback
    def _update(self) -> None:
        self.async_write_ha_state()

    @property
    def current_option(self) -> str | None:
        t = self._device.active_template
        return t if t in self._attr_options else None

    async def async_select_option(self, option: str) -> None:
        try:
            await self._device.async_apply_template(option)
        except TemplateError as err:
            raise HomeAssistantError(str(err)) from err
        except Exception as err:  # BLE errors
            raise HomeAssistantError(f"{self._device.name}: {err}") from err


class DazzleSignalSelect(SelectEntity, RestoreEntity):
    """Segment bar: colour of the "signal" slot(s) in the layout."""

    _attr_has_entity_name = True
    _attr_translation_key = "signal"
    _attr_assumed_state = True

    def __init__(self, device: DazzleDevice) -> None:
        self._device = device
        self._attr_unique_id = f"{device.address}_signal"
        self._attr_device_info = device_info(device)
        self._attr_options = list(device.bar.signal_colors)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in self._attr_options:
            self._device.bar.signal = last.state  # restore only; nothing is sent
        self.async_on_remove(self._device.register_callback(self._update))

    @callback
    def _update(self) -> None:
        self.async_write_ha_state()

    @property
    def current_option(self) -> str | None:
        return self._device.bar.signal

    async def async_select_option(self, option: str) -> None:
        try:
            await self._device.async_set_signal(option)
        except TemplateError as err:
            raise HomeAssistantError(str(err)) from err
        except Exception as err:  # BLE errors
            raise HomeAssistantError(f"{self._device.name}: {err}") from err
