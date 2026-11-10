"""Low/high alarm limits per probe, kept in Home Assistant."""

from __future__ import annotations

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberMode,
    RestoreNumber,
)
from homeassistant.const import EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import H5055ConfigEntry
from .const import DEFAULT_HIGH_LIMIT, DEFAULT_LOW_LIMIT, LIMIT_MAX, LIMIT_MIN
from .coordinator import H5055Coordinator
from .entity import H5055Entity
from .parser import PROBE_COUNT


async def async_setup_entry(
    hass: HomeAssistant,
    entry: H5055ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        AlarmLimitNumber(coordinator, probe, side)
        for probe in range(1, PROBE_COUNT + 1)
        for side in ("low", "high")
    )


class AlarmLimitNumber(H5055Entity, RestoreNumber):
    """A threshold the matching alarm binary sensor compares against.

    Leaving the low limit at its minimum or the high limit at its maximum
    turns that side of the alarm off.
    """

    _attr_device_class = NumberDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_native_min_value = LIMIT_MIN
    _attr_native_max_value = LIMIT_MAX
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: H5055Coordinator, probe: int, side: str) -> None:
        super().__init__(coordinator, f"probe_{probe}_{side}_limit")
        self.probe = probe
        self.side = side
        self._attr_translation_key = f"{side}_limit"
        self._attr_translation_placeholders = {"probe": str(probe)}
        self._attr_native_value = (
            DEFAULT_LOW_LIMIT if side == "low" else DEFAULT_HIGH_LIMIT
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_number_data()) is not None:
            if last.native_value is not None:
                self._attr_native_value = last.native_value
        self._publish()

    async def async_set_native_value(self, value: float) -> None:
        self._attr_native_value = value
        self._publish()
        self.async_write_ha_state()
        self.coordinator.async_notify()

    def _publish(self) -> None:
        value = self._attr_native_value
        key = (self.probe, self.side)
        # Allow for float noise after a round trip through Fahrenheit.
        if value is None or (
            value <= LIMIT_MIN + 0.5 if self.side == "low" else value >= LIMIT_MAX - 0.5
        ):
            self.coordinator.limits.pop(key, None)
        else:
            self.coordinator.limits[key] = value
