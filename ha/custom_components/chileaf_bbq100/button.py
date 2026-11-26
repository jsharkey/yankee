"""Silence a probe's alarm on the thermometer."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import BBQ100ConfigEntry
from . import protocol as p
from .device import BBQ100Device
from .entity import ProbeEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BBQ100ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    device = entry.runtime_data
    async_add_entities(StopAlarmButton(device, probe) for probe in range(1, p.PROBE_COUNT + 1))


class StopAlarmButton(ProbeEntity, ButtonEntity):
    def __init__(self, device: BBQ100Device, probe: int) -> None:
        super().__init__(device, probe, "stop_alarm", "stop_alarm")

    async def async_press(self) -> None:
        await self.device.async_stop_alarm(self.probe)
