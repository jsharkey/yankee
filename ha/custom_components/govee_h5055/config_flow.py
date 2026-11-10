"""Config flow: pick up H5055s from Bluetooth discovery or a list."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_ADDRESS

from .const import DOMAIN, MODEL
from .parser import SERVICE_UUID


def _title(address: str) -> str:
    return f"{MODEL} {address.replace(':', '')[-4:]}"


def _is_h5055(info: BluetoothServiceInfoBleak) -> bool:
    return SERVICE_UUID in info.service_uuids


class H5055ConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._discovery: BluetoothServiceInfoBleak | None = None

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        if not _is_h5055(discovery_info):
            return self.async_abort(reason="not_supported")
        self._discovery = discovery_info
        self.context["title_placeholders"] = {"name": _title(discovery_info.address)}
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        assert self._discovery is not None
        address = self._discovery.address
        if user_input is not None:
            return self.async_create_entry(
                title=_title(address), data={CONF_ADDRESS: address}
            )
        self._set_confirm_only()
        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders={"name": _title(address)},
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            await self.async_set_unique_id(address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=_title(address), data={CONF_ADDRESS: address}
            )

        configured = self._async_current_ids(include_ignore=False)
        found = {
            info.address: f"{_title(info.address)} ({info.address})"
            for info in async_discovered_service_info(self.hass, connectable=False)
            if _is_h5055(info) and info.address not in configured
        }
        if not found:
            return self.async_abort(reason="no_devices_found")
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_ADDRESS): vol.In(found)}),
        )
