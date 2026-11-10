"""Shared entity base for the Govee H5055."""

from __future__ import annotations

from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, MANUFACTURER, MODEL
from .coordinator import H5055Coordinator


class H5055Entity(Entity):
    """Base entity that refreshes whenever a good frame arrives."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, coordinator: H5055Coordinator, key: str) -> None:
        self.coordinator = coordinator
        address = coordinator.address
        self._attr_unique_id = f"{address}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, address)},
            connections={(CONNECTION_BLUETOOTH, address)},
            manufacturer=MANUFACTURER,
            model=MODEL,
            name=f"{MODEL} {address.replace(':', '')[-4:]}",
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            self.coordinator.async_add_listener(self.async_write_ha_state)
        )
