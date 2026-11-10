"""Temperature, battery and device-reported alarm limit sensors."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfTemperature,
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
    entities: list[SensorEntity] = [BatterySensor(coordinator), RssiSensor(coordinator)]
    for probe in range(1, PROBE_COUNT + 1):
        entities.append(ProbeTemperatureSensor(coordinator, probe))
        entities.append(DeviceLimitSensor(coordinator, probe, "low"))
        entities.append(DeviceLimitSensor(coordinator, probe, "high"))
    async_add_entities(entities)


class _TemperatureBase(H5055Entity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_suggested_display_precision = 0


class ProbeTemperatureSensor(_TemperatureBase):
    """Current temperature of one probe; unknown while it is unplugged."""

    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: H5055Coordinator, probe: int) -> None:
        super().__init__(coordinator, f"probe_{probe}_temperature")
        self.probe = probe
        self._attr_translation_key = "probe_temperature"
        self._attr_translation_placeholders = {"probe": str(probe)}

    @property
    def available(self) -> bool:
        return self.coordinator.available

    @property
    def native_value(self) -> int | None:
        reading = self.coordinator.probes.get(self.probe)
        return reading.temperature if reading else None


class DeviceLimitSensor(_TemperatureBase):
    """Alarm limit the thermometer itself reports (set in the Govee app)."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: H5055Coordinator, probe: int, side: str) -> None:
        super().__init__(coordinator, f"probe_{probe}_device_{side}_alarm")
        self.probe = probe
        self.side = side
        self._attr_translation_key = f"device_{side}_alarm"
        self._attr_translation_placeholders = {"probe": str(probe)}

    @property
    def available(self) -> bool:
        return self.coordinator.available

    @property
    def native_value(self) -> int | None:
        reading = self.coordinator.probes.get(self.probe)
        if reading is None:
            return None
        return reading.low_alarm if self.side == "low" else reading.high_alarm


class BatterySensor(H5055Entity, SensorEntity):
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: H5055Coordinator) -> None:
        super().__init__(coordinator, "battery")

    @property
    def available(self) -> bool:
        return self.coordinator.available

    @property
    def native_value(self) -> int | None:
        return self.coordinator.battery


class RssiSensor(H5055Entity, SensorEntity):
    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: H5055Coordinator) -> None:
        super().__init__(coordinator, "rssi")

    @property
    def available(self) -> bool:
        return self.coordinator.available

    @property
    def native_value(self) -> int | None:
        return self.coordinator.rssi
