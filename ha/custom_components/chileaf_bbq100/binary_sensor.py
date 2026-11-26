"""Alarm and connection binary sensors."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

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
    entities: list[BinarySensorEntity] = [
        ProbeAlarm(device, probe) for probe in range(1, p.PROBE_COUNT + 1)
    ]
    entities += [AnyProbeAlarm(device), ConnectedSensor(device)]
    async_add_entities(entities)


class ProbeAlarm(ProbeEntity, BinarySensorEntity):
    """On while the thermometer's own alarm sounds for this probe."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, device: BBQ100Device, probe: int) -> None:
        super().__init__(device, probe, "alarm", "probe_alarm")

    @property
    def is_on(self) -> bool | None:
        ch = self.probe_state.channel
        return ch.alarm if ch else None


class AnyProbeAlarm(BBQ100Entity, BinarySensorEntity):
    """On while any probe's alarm sounds; handy as one automation trigger."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_translation_key = "any_alarm"

    def __init__(self, device: BBQ100Device) -> None:
        super().__init__(device, "any_alarm")

    @property
    def is_on(self) -> bool:
        return any(s.channel is not None and s.channel.alarm for s in self.device.probes.values())


class ConnectedSensor(BBQ100Entity, BinarySensorEntity):
    """Whether Home Assistant holds the Bluetooth connection right now."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "connected"

    def __init__(self, device: BBQ100Device) -> None:
        super().__init__(device, "connected")

    @property
    def available(self) -> bool:
        return True

    @property
    def is_on(self) -> bool:
        return self.device.connected
