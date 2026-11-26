"""Target temperature and timer per probe, written to the thermometer."""

from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.const import UnitOfTemperature, UnitOfTime
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
    entities: list[NumberEntity] = []
    for probe in range(1, p.PROBE_COUNT + 1):
        entities += [TargetTemperatureNumber(device, probe), TimerNumber(device, probe)]
    async_add_entities(entities)


class TargetTemperatureNumber(ProbeEntity, NumberEntity):
    """The probe's target. Setting it switches the probe to temperature mode.

    In meat mode this shows the target the thermometer chose for the meat.
    """

    _attr_device_class = NumberDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_native_min_value = 0
    _attr_native_max_value = p.TEMP_MAX_C
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX

    def __init__(self, device: BBQ100Device, probe: int) -> None:
        super().__init__(device, probe, "target_temperature", "target_temperature")

    @property
    def native_value(self) -> float | None:
        ch = self.probe_state.channel
        return ch.target_temperature if ch else None

    async def async_set_native_value(self, value: float) -> None:
        await self.device.async_set_target_temperature(self.probe, value)


class TimerNumber(ProbeEntity, NumberEntity):
    """Countdown length. Setting it switches the probe to timer mode."""

    _attr_device_class = NumberDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_native_min_value = 1
    _attr_native_max_value = p.TIMER_MAX_MINUTES
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX

    def __init__(self, device: BBQ100Device, probe: int) -> None:
        super().__init__(device, probe, "timer", "timer")

    @property
    def native_value(self) -> float | None:
        ch = self.probe_state.channel
        if ch is None or ch.timer_target is None:
            return None
        return round(ch.timer_target / 60, 2)

    async def async_set_native_value(self, value: float) -> None:
        total = round(value * 60)
        await self.device.async_set_timer(self.probe, total // 60, total % 60)
