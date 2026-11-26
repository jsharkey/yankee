"""Start/stop per probe, and a switch to let go of the Bluetooth connection."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import STATE_OFF, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import BBQ100ConfigEntry
from . import protocol as p
from .device import BBQ100Device
from .entity import BBQ100Entity, ProbeEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BBQ100ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    device = entry.runtime_data
    entities: list[SwitchEntity] = [RunSwitch(device, n) for n in range(1, p.PROBE_COUNT + 1)]
    entities.append(ConnectionSwitch(device))
    async_add_entities(entities)


class RunSwitch(ProbeEntity, SwitchEntity):
    """Start or stop the probe's cook (the app's Start/Stop button)."""

    def __init__(self, device: BBQ100Device, probe: int) -> None:
        super().__init__(device, probe, "running", "running")

    @property
    def is_on(self) -> bool | None:
        ch = self.probe_state.channel
        return ch.running if ch else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.device.async_set_running(self.probe, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.device.async_set_running(self.probe, False)


class ConnectionSwitch(BBQ100Entity, SwitchEntity, RestoreEntity):
    """Off releases the thermometer so the phone app can connect to it."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "connection"

    def __init__(self, device: BBQ100Device) -> None:
        super().__init__(device, "connection")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state == STATE_OFF:
            await self.device.async_set_enabled(False)

    @property
    def available(self) -> bool:
        return True

    @property
    def is_on(self) -> bool:
        return self.device.enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.device.async_set_enabled(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.device.async_set_enabled(False)
