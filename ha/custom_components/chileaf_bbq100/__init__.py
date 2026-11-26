"""Chileaf BBQ100 four-probe Bluetooth BBQ thermometer."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, Platform
from homeassistant.core import HomeAssistant

from .device import BBQ100Device

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]

type BBQ100ConfigEntry = ConfigEntry[BBQ100Device]


async def async_setup_entry(hass: HomeAssistant, entry: BBQ100ConfigEntry) -> bool:
    device = BBQ100Device(hass, entry.data[CONF_ADDRESS], entry.title)
    entry.runtime_data = device
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Connect once the entities exist (the connection switch restores its
    # state during setup), so the first readings reach them.
    device.async_start()
    return True


async def async_unload_entry(hass: HomeAssistant, entry: BBQ100ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_stop()
    return unloaded
