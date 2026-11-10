"""Govee H5055 6-probe BBQ thermometer."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, Platform
from homeassistant.core import HomeAssistant

from .coordinator import H5055Coordinator

PLATFORMS = [Platform.BINARY_SENSOR, Platform.NUMBER, Platform.SENSOR]

type H5055ConfigEntry = ConfigEntry[H5055Coordinator]


async def async_setup_entry(hass: HomeAssistant, entry: H5055ConfigEntry) -> bool:
    coordinator = H5055Coordinator(hass, entry.data[CONF_ADDRESS])
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Start listening once the entities exist, so the first reading reaches them.
    coordinator.async_start()
    entry.async_on_unload(coordinator.async_stop)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: H5055ConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
