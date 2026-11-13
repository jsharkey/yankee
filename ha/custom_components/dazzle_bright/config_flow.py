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
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
    TextSelectorConfig,
)

from .const import (
    CONF_DISCONNECT_DELAY,
    CONF_INPUT_SELECT,
    CONF_POINT_COUNT,
    CONF_POWER_ON_FIRST,
    CONF_BLANK_OFF,
    CONF_LAYOUT,
    CONF_MODE,
    CONF_NIGHT_COLOR,
    CONF_SIGNAL_COLORS,
    CONF_TEMPLATES,
    DEFAULT_DISCONNECT_DELAY,
    DEFAULT_LAYOUT,
    DEFAULT_NIGHT_COLOR,
    DEFAULT_POINT_COUNT,
    DEFAULT_SIGNAL_COLORS,
    DEFAULT_TEMPLATES,
    DOMAIN,
    MODE_PATTERNS,
    MODE_SEGMENTS,
)
from .segments import (
    SEGMENT_PRODUCT_IDS,
    LayoutError,
    check_color,
    parse_color_list,
    parse_layout,
    product_id_from_service_data,
)
from .templates import TemplateError, validate_templates


def mode_for(info: BluetoothServiceInfoBleak | None) -> str:
    """Segment-bar mode for segment products (170, 173), patterns otherwise."""
    pid = product_id_from_service_data(info.service_data) if info else None
    return MODE_SEGMENTS if pid in SEGMENT_PRODUCT_IDS else MODE_PATTERNS


def is_supported_name(name: str | None) -> bool:
    """Same name rule as lednetwf_ble (_is_valid_device_name): LEDnetWF*, IOTWF*, IOTB*."""
    n = (name or "").lower()
    return n.startswith(("lednetwf", "iotwf", "iotb"))


class DazzleConfigFlow(ConfigFlow, domain=DOMAIN):
    """Pair a string found by Bluetooth discovery or picked from a list."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovery: BluetoothServiceInfoBleak | None = None
        self._found: dict[str, BluetoothServiceInfoBleak] = {}

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
            return self._create(self._discovery.address, self._discovery.name,
                                mode_for(self._discovery))
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
            info = self._found.get(address)
            return self._create(address, info.name if info else address, mode_for(info))

        configured = {e.unique_id for e in self._async_current_entries()}
        self._found = {
            info.address: info
            for info in async_discovered_service_info(self.hass)
            if is_supported_name(info.name) and format_mac(info.address) not in configured
        }
        if not self._found:
            return self.async_abort(reason="no_devices_found")
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_ADDRESS): vol.In(
                    {addr: f"{i.name} ({addr})" for addr, i in self._found.items()}
                )
            }),
        )

    def _create(self, address: str, name: str, mode: str = MODE_PATTERNS) -> ConfigFlowResult:
        return self.async_create_entry(
            title=name,
            data={CONF_ADDRESS: address, CONF_NAME: name},
            options={
                CONF_MODE: mode,
                CONF_TEMPLATES: DEFAULT_TEMPLATES,
                CONF_POINT_COUNT: DEFAULT_POINT_COUNT,
                CONF_DISCONNECT_DELAY: DEFAULT_DISCONNECT_DELAY,
                CONF_LAYOUT: DEFAULT_LAYOUT,
                CONF_NIGHT_COLOR: DEFAULT_NIGHT_COLOR,
                CONF_SIGNAL_COLORS: DEFAULT_SIGNAL_COLORS,
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return DazzleOptionsFlow()


class DazzleOptionsFlow(OptionsFlow):
    """Step 1: mode + connection options. Step 2: templates or segment layout."""

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        opts = self.config_entry.options
        if user_input is not None:
            self._data = {
                CONF_MODE: user_input[CONF_MODE],
                CONF_DISCONNECT_DELAY: int(user_input[CONF_DISCONNECT_DELAY]),
                CONF_POWER_ON_FIRST: bool(user_input.get(CONF_POWER_ON_FIRST, False)),
                CONF_BLANK_OFF: bool(user_input.get(CONF_BLANK_OFF, True)),
            }
            if user_input[CONF_MODE] == MODE_SEGMENTS:
                return await self.async_step_segments()
            return await self.async_step_patterns()

        schema = vol.Schema({
            vol.Required(CONF_MODE, default=opts.get(CONF_MODE, MODE_PATTERNS)): SelectSelector(
                SelectSelectorConfig(options=[MODE_PATTERNS, MODE_SEGMENTS],
                                     translation_key="mode")
            ),
            vol.Required(
                CONF_DISCONNECT_DELAY,
                default=opts.get(CONF_DISCONNECT_DELAY, DEFAULT_DISCONNECT_DELAY),
            ): NumberSelector(NumberSelectorConfig(min=5, max=3600, mode=NumberSelectorMode.BOX,
                                                   unit_of_measurement="s")),
            vol.Required(CONF_BLANK_OFF, default=opts.get(CONF_BLANK_OFF, True)): BooleanSelector(),
            vol.Required(
                CONF_POWER_ON_FIRST, default=opts.get(CONF_POWER_ON_FIRST, False)
            ): BooleanSelector(),
        })
        return self.async_show_form(step_id="init", data_schema=schema)

    def _finish(self, data: dict[str, Any]) -> ConfigFlowResult:
        # Keep the other mode's settings so switching back doesn't lose them.
        merged = {**self.config_entry.options, **self._data, **data}
        return self.async_create_entry(data={k: v for k, v in merged.items() if v is not None})

    async def async_step_patterns(
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
                    CONF_INPUT_SELECT: user_input.get(CONF_INPUT_SELECT) or None,
                }
                return self._finish(data)
            opts = {**opts, **user_input}

        schema: dict[Any, Any] = {
            vol.Required(
                CONF_TEMPLATES, default=opts.get(CONF_TEMPLATES, DEFAULT_TEMPLATES)
            ): TextSelector(TextSelectorConfig(multiline=True)),
            vol.Required(
                CONF_POINT_COUNT, default=opts.get(CONF_POINT_COUNT, DEFAULT_POINT_COUNT)
            ): NumberSelector(NumberSelectorConfig(min=1, max=2048, mode=NumberSelectorMode.BOX)),
        }
        current = opts.get(CONF_INPUT_SELECT)
        key = (vol.Optional(CONF_INPUT_SELECT, description={"suggested_value": current})
               if current else vol.Optional(CONF_INPUT_SELECT))
        schema[key] = EntitySelector(EntitySelectorConfig(domain="input_select"))

        return self.async_show_form(
            step_id="patterns",
            data_schema=vol.Schema(schema),
            errors=errors,
            description_placeholders=placeholders,
        )

    async def async_step_segments(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        placeholders = {"error": ""}
        opts = self.config_entry.options

        if user_input is not None:
            field = CONF_LAYOUT
            try:
                parse_layout(user_input[CONF_LAYOUT])
                field = CONF_NIGHT_COLOR
                check_color(user_input[CONF_NIGHT_COLOR])
                field = CONF_SIGNAL_COLORS
                parse_color_list(user_input[CONF_SIGNAL_COLORS])
            except LayoutError as err:
                errors[field] = "invalid_segments"
                placeholders["error"] = str(err)
            else:
                return self._finish({
                    CONF_LAYOUT: user_input[CONF_LAYOUT],
                    CONF_NIGHT_COLOR: user_input[CONF_NIGHT_COLOR],
                    CONF_SIGNAL_COLORS: user_input[CONF_SIGNAL_COLORS],
                })
            opts = {**opts, **user_input}

        schema = vol.Schema({
            vol.Required(CONF_LAYOUT, default=opts.get(CONF_LAYOUT, DEFAULT_LAYOUT)): TextSelector(),
            vol.Required(
                CONF_NIGHT_COLOR, default=opts.get(CONF_NIGHT_COLOR, DEFAULT_NIGHT_COLOR)
            ): TextSelector(),
            vol.Required(
                CONF_SIGNAL_COLORS, default=opts.get(CONF_SIGNAL_COLORS, DEFAULT_SIGNAL_COLORS)
            ): TextSelector(),
        })
        return self.async_show_form(
            step_id="segments",
            data_schema=schema,
            errors=errors,
            description_placeholders=placeholders,
        )
