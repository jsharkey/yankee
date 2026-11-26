"""Meat preset per probe, and the thermometer's display unit."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import BBQ100ConfigEntry
from . import protocol as p
from .device import BBQ100Device
from .entity import BBQ100Entity, ProbeEntity

_PRESETS = {label: (meat, level) for meat, level, label in p.meat_presets()}
_PRESET_LABELS = {value: label for label, value in _PRESETS.items()}
_UNITS = {"celsius": p.Unit.CELSIUS, "fahrenheit": p.Unit.FAHRENHEIT}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BBQ100ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    device = entry.runtime_data
    entities: list[SelectEntity] = [MeatSelect(device, n) for n in range(1, p.PROBE_COUNT + 1)]
    entities.append(DisplayUnitSelect(device))
    async_add_entities(entities)


class MeatSelect(ProbeEntity, SelectEntity):
    """Meat and doneness. Choosing one switches the probe to meat mode.

    Unknown while the probe is in temperature or timer mode.
    """

    _attr_options = list(_PRESETS)

    def __init__(self, device: BBQ100Device, probe: int) -> None:
        super().__init__(device, probe, "meat", "meat")

    @property
    def current_option(self) -> str | None:
        ch = self.probe_state.channel
        if ch is None or ch.mode != p.Mode.MEAT:
            return None
        return _PRESET_LABELS.get((ch.meat, ch.doneness))

    async def async_select_option(self, option: str) -> None:
        meat, level = _PRESETS[option]
        await self.device.async_set_meat(self.probe, meat, level)


class DisplayUnitSelect(BBQ100Entity, SelectEntity):
    """Unit on the thermometer's screen. Home Assistant's own unit is separate."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = list(_UNITS)
    _attr_translation_key = "display_unit"

    def __init__(self, device: BBQ100Device) -> None:
        super().__init__(device, "display_unit")

    @property
    def current_option(self) -> str | None:
        for option, unit in _UNITS.items():
            if self.device.unit == unit:
                return option
        return None

    async def async_select_option(self, option: str) -> None:
        await self.device.async_set_unit(_UNITS[option])
