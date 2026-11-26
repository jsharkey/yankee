"""Probe temperature, mode and clock sensors."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import BBQ100ConfigEntry
from . import protocol as p
from .device import BBQ100Device
from .entity import BBQ100Entity, ProbeEntity

_MODES = {p.Mode.MEAT: "meat", p.Mode.TEMPERATURE: "temperature", p.Mode.TIMER: "timer"}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BBQ100ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    device = entry.runtime_data
    entities: list[SensorEntity] = [FirmwareSensor(device)]
    for probe in range(1, p.PROBE_COUNT + 1):
        entities += [
            ProbeTemperatureSensor(device, probe),
            ProbeModeSensor(device, probe),
            ProbeTimeSensor(device, probe),
        ]
    async_add_entities(entities)


class ProbeTemperatureSensor(ProbeEntity, SensorEntity):
    """Current probe temperature; unknown while the probe is unplugged."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1

    def __init__(self, device: BBQ100Device, probe: int) -> None:
        super().__init__(device, probe, "temperature", "probe_temperature")

    @property
    def native_value(self) -> float | None:
        return self.probe_state.temperature


class ProbeModeSensor(ProbeEntity, SensorEntity):
    """Meat, temperature or timer; the attributes give the meat and doneness."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = list(_MODES.values())

    def __init__(self, device: BBQ100Device, probe: int) -> None:
        super().__init__(device, probe, "mode", "probe_mode")

    @property
    def native_value(self) -> str | None:
        ch = self.probe_state.channel
        return _MODES.get(ch.mode) if ch else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        ch = self.probe_state.channel
        if ch is None:
            return None
        attrs: dict[str, Any] = {"display_slot": ch.display_slot}
        if ch.mode == p.Mode.MEAT:
            attrs["meat"] = p.MEATS[ch.meat] if ch.meat < len(p.MEATS) else ch.meat
            attrs["doneness"] = (
                p.DONENESS[ch.doneness] if ch.doneness < len(p.DONENESS) else ch.doneness
            )
        return attrs


class ProbeTimeSensor(ProbeEntity, SensorEntity):
    """Time left in timer mode, otherwise time since the probe was started."""

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_suggested_unit_of_measurement = UnitOfTime.MINUTES
    _attr_suggested_display_precision = 0

    def __init__(self, device: BBQ100Device, probe: int) -> None:
        super().__init__(device, probe, "time", "probe_time")

    @property
    def native_value(self) -> int | None:
        return self.probe_state.time_now()


class FirmwareSensor(BBQ100Entity, SensorEntity):
    """Raw reply to the version request (its layout is not known yet)."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_translation_key = "version"

    def __init__(self, device: BBQ100Device) -> None:
        super().__init__(device, "version")

    @property
    def native_value(self) -> str | None:
        return self.device.version
