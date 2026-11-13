"""Config and options flows."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_ADDRESS, CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers.device_registry import format_mac
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
)

from .const import (
    CONF_DISCONNECT_DELAY,
    CONF_INPUT_SELECT,
    CONF_POINT_COUNT,
    CONF_POWER_ON_FIRST,
    CONF_BLANK_OFF,
    CONF_TEMPLATES,
    DEFAULT_DISCONNECT_DELAY,
    DEFAULT_POINT_COUNT,
    DEFAULT_TEMPLATES,
    DOMAIN,
)
from .templates import TemplateError, validate_templates


def is_supported_name(name: str | None) -> bool:
    """Same name rule as lednetwf_ble (_is_valid_device_name): LEDnetWF*, IOTWF*, IOTB*."""
    n = (name or "").lower()
    return n.startswith(("lednetwf", "iotwf", "iotb"))


class DazzleConfigFlow(ConfigFlow, domain=DOMAIN):
    """Pair a string found by Bluetooth discovery or picked from a list."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovery: BluetoothServiceInfoBleak | None = None
        self._found: dict[str, str] = {}

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        if not is_supported_name(discovery_info.name):
            return self.async_abort(reason="not_supported")
        await self.async_set_unique_id(format_mac(discovery_info.address))
        self._abort_if_unique_id_configured()
        self._discovery = discovery_info
        self.context["title_placeholders"] = {"name": discovery_info.name}
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        assert self._discovery is not None
        if user_input is not None:
            return self._create(self._discovery.address, self._discovery.name)
        self._set_confirm_only()
        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders={"name": self._discovery.name},
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            await self.async_set_unique_id(format_mac(address))
            self._abort_if_unique_id_configured()
            return self._create(address, self._found.get(address, address))

        configured = {e.unique_id for e in self._async_current_entries()}
        self._found = {
            info.address: info.name
            for info in async_discovered_service_info(self.hass)
            if is_supported_name(info.name) and format_mac(info.address) not in configured
        }
        if not self._found:
            return self.async_abort(reason="no_devices_found")
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_ADDRESS): vol.In(
                    {addr: f"{name} ({addr})" for addr, name in self._found.items()}
                )
            }),
        )

    def _create(self, address: str, name: str) -> ConfigFlowResult:
        return self.async_create_entry(
            title=name,
            data={CONF_ADDRESS: address, CONF_NAME: name},
            options={
                CONF_TEMPLATES: DEFAULT_TEMPLATES,
                CONF_POINT_COUNT: DEFAULT_POINT_COUNT,
                CONF_DISCONNECT_DELAY: DEFAULT_DISCONNECT_DELAY,
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return DazzleOptionsFlow()


class DazzleOptionsFlow(OptionsFlow):
    """Templates, LED count, optional input_select to follow."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        placeholders = {"error": ""}
        opts = self.config_entry.options

        if user_input is not None:
            points = int(user_input[CONF_POINT_COUNT])
            try:
                validate_templates(user_input[CONF_TEMPLATES], points)
            except TemplateError as err:
                errors[CONF_TEMPLATES] = "invalid_template"
                placeholders["error"] = str(err)
            else:
                data = {
                    CONF_TEMPLATES: user_input[CONF_TEMPLATES],
                    CONF_POINT_COUNT: points,
                    CONF_DISCONNECT_DELAY: int(user_input[CONF_DISCONNECT_DELAY]),
                    CONF_POWER_ON_FIRST: bool(user_input.get(CONF_POWER_ON_FIRST, False)),
                    CONF_BLANK_OFF: bool(user_input.get(CONF_BLANK_OFF, True)),
                }
                if user_input.get(CONF_INPUT_SELECT):
                    data[CONF_INPUT_SELECT] = user_input[CONF_INPUT_SELECT]
                return self.async_create_entry(data=data)
            opts = {**opts, **user_input}

        schema: dict[Any, Any] = {
            vol.Required(
                CONF_TEMPLATES, default=opts.get(CONF_TEMPLATES, DEFAULT_TEMPLATES)
            ): TextSelector(TextSelectorConfig(multiline=True)),
            vol.Required(
                CONF_POINT_COUNT, default=opts.get(CONF_POINT_COUNT, DEFAULT_POINT_COUNT)
            ): NumberSelector(NumberSelectorConfig(min=1, max=2048, mode=NumberSelectorMode.BOX)),
            vol.Required(
                CONF_DISCONNECT_DELAY,
                default=opts.get(CONF_DISCONNECT_DELAY, DEFAULT_DISCONNECT_DELAY),
            ): NumberSelector(NumberSelectorConfig(min=5, max=3600, mode=NumberSelectorMode.BOX,
                                                   unit_of_measurement="s")),
        }
        schema[vol.Required(
            CONF_BLANK_OFF, default=opts.get(CONF_BLANK_OFF, True)
        )] = BooleanSelector()
        schema[vol.Required(
            CONF_POWER_ON_FIRST, default=opts.get(CONF_POWER_ON_FIRST, False)
        )] = BooleanSelector()
        current = opts.get(CONF_INPUT_SELECT)
        key = (vol.Optional(CONF_INPUT_SELECT, description={"suggested_value": current})
               if current else vol.Optional(CONF_INPUT_SELECT))
        schema[key] = EntitySelector(EntitySelectorConfig(domain="input_select"))

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(schema),
            errors=errors,
            description_placeholders=placeholders,
        )
