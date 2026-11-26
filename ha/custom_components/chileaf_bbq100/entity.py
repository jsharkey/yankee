"""Shared entity base for the BBQ100."""

from __future__ import annotations

from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, MANUFACTURER, MODEL
from .device import BBQ100Device, ProbeState


class BBQ100Entity(Entity):
    """Base entity, refreshed whenever the thermometer reports something."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, device: BBQ100Device, key: str) -> None:
        self.device = device
        self._attr_unique_id = f"{device.address}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device.address)},
            connections={(CONNECTION_BLUETOOTH, device.address)},
            manufacturer=MANUFACTURER,
            model=MODEL,
            name=device.name,
        )

    @property
    def available(self) -> bool:
        return self.device.connected

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self.device.async_add_listener(self.async_write_ha_state))


class ProbeEntity(BBQ100Entity):
    """An entity for one of the four probes."""

    def __init__(self, device: BBQ100Device, probe: int, key: str, translation_key: str) -> None:
        super().__init__(device, f"probe_{probe}_{key}")
        self.probe = probe
        self._attr_translation_key = translation_key
        self._attr_translation_placeholders = {"probe": str(probe)}

    @property
    def probe_state(self) -> ProbeState:
        return self.device.probes[self.probe]
