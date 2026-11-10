"""Alarm binary sensors driven by the limits set in Home Assistant."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import H5055ConfigEntry
from .coordinator import H5055Coordinator
from .entity import H5055Entity
from .parser import PROBE_COUNT


async def async_setup_entry(
    hass: HomeAssistant,
    entry: H5055ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    entities: list[BinarySensorEntity] = [
        ProbeAlarm(coordinator, probe) for probe in range(1, PROBE_COUNT + 1)
    ]
    entities.append(AnyProbeAlarm(coordinator))
    async_add_entities(entities)


class ProbeAlarm(H5055Entity, BinarySensorEntity):
    """On while the probe reads below its low limit or above its high limit."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator: H5055Coordinator, probe: int) -> None:
        super().__init__(coordinator, f"probe_{probe}_alarm")
        self.probe = probe
        self._attr_translation_key = "probe_alarm"
        self._attr_translation_placeholders = {"probe": str(probe)}

    @property
    def available(self) -> bool:
        return self.coordinator.available

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.alarm_active(self.probe)

    @property
    def extra_state_attributes(self) -> dict[str, float | None]:
        limits = self.coordinator.limits
        return {
            "low_limit": limits.get((self.probe, "low")),
            "high_limit": limits.get((self.probe, "high")),
        }


class AnyProbeAlarm(H5055Entity, BinarySensorEntity):
    """On while any probe is in alarm; handy as a single automation trigger."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_translation_key = "any_alarm"

    def __init__(self, coordinator: H5055Coordinator) -> None:
        super().__init__(coordinator, "any_alarm")

    @property
    def available(self) -> bool:
        return self.coordinator.available

    @property
    def is_on(self) -> bool:
        return any(
            self.coordinator.alarm_active(probe)
            for probe in range(1, PROBE_COUNT + 1)
        )
