"""Dazzle Bright smart Christmas string lights (IOTBT*, BLE).

Wraps dazzle_multicolor.py: every pattern is a dazzle_multicolor command line
("random red green blue purple", "anim meteor --speed 70 red white", ...),
so anything that works with the script works here.
"""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, CONF_NAME, Platform
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event

from .const import (
    CONF_DISCONNECT_DELAY,
    CONF_INPUT_SELECT,
    CONF_POWER_ON_FIRST,
    CONF_BLANK_OFF,
    CONF_LAYOUT,
    CONF_MODE,
    CONF_NIGHT_COLOR,
    CONF_POINT_COUNT,
    CONF_SIGNAL_COLORS,
    CONF_TEMPLATES,
    DEFAULT_DISCONNECT_DELAY,
    DEFAULT_LAYOUT,
    DEFAULT_NIGHT_COLOR,
    DEFAULT_POINT_COUNT,
    DEFAULT_SIGNAL_COLORS,
    DEFAULT_TEMPLATES,
    MODE_SEGMENTS,
)
from .device import DazzleDevice, SegmentBar
from .segments import LayoutError, check_color, parse_color_list, parse_layout
from .templates import TemplateError, find_template, parse_templates

_LOGGER = logging.getLogger(__name__)

# The switch platform only adds entities in segment-bar mode.
PLATFORMS: list[Platform] = [Platform.LIGHT, Platform.SELECT, Platform.SWITCH]

type DazzleConfigEntry = ConfigEntry[DazzleDevice]


async def async_setup_entry(hass: HomeAssistant, entry: DazzleConfigEntry) -> bool:
    """Set up one string of lights from a config entry."""
    try:
        templates = parse_templates(entry.options.get(CONF_TEMPLATES, DEFAULT_TEMPLATES))
    except TemplateError as err:
        _LOGGER.error("%s: invalid templates (%s); using defaults", entry.title, err)
        templates = parse_templates(DEFAULT_TEMPLATES)

    device = DazzleDevice(
        hass,
        entry.data[CONF_ADDRESS],
        entry.data.get(CONF_NAME, entry.title),
        templates,
        int(entry.options.get(CONF_POINT_COUNT, DEFAULT_POINT_COUNT)),
        int(entry.options.get(CONF_DISCONNECT_DELAY, DEFAULT_DISCONNECT_DELAY)),
        bool(entry.options.get(CONF_POWER_ON_FIRST, False)),
        bool(entry.options.get(CONF_BLANK_OFF, True)),
        _segment_bar(entry),
    )
    entry.runtime_data = device
    entry.async_on_unload(device.async_start())

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Optional: follow an input_select helper whose options are template names.
    if not device.bar and (input_select := entry.options.get(CONF_INPUT_SELECT)):
        entry.async_on_unload(_follow_input_select(hass, device, input_select))

    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


def _segment_bar(entry: DazzleConfigEntry) -> SegmentBar | None:
    """Segment-bar settings for this entry, or None in pattern mode."""
    opts = entry.options
    if opts.get(CONF_MODE) != MODE_SEGMENTS:
        return None
    try:
        return SegmentBar(
            parse_layout(opts.get(CONF_LAYOUT, DEFAULT_LAYOUT)),
            check_color(opts.get(CONF_NIGHT_COLOR, DEFAULT_NIGHT_COLOR)),
            parse_color_list(opts.get(CONF_SIGNAL_COLORS, DEFAULT_SIGNAL_COLORS)),
        )
    except LayoutError as err:
        _LOGGER.error("%s: invalid segment settings (%s); using defaults", entry.title, err)
        return SegmentBar(parse_layout(DEFAULT_LAYOUT), DEFAULT_NIGHT_COLOR,
                          parse_color_list(DEFAULT_SIGNAL_COLORS))


def _follow_input_select(hass: HomeAssistant, device: DazzleDevice, entity_id: str):
    """Apply the matching template whenever the input_select changes.

    An option can be a template name ("christmas"), or carry its own command
    after a colon ("christmas: random red green blue purple").
    """

    @callback
    def _changed(event: Event[EventStateChangedData]) -> None:
        new = event.data["new_state"]
        old = event.data["old_state"]
        if new is None or new.state in ("unknown", "unavailable"):
            return
        if old is not None and old.state == new.state:
            return  # attribute-only change (e.g. options edited)
        option = new.state
        hass.async_create_task(_apply_option(device, entity_id, option))

    return async_track_state_change_event(hass, [entity_id], _changed)


async def _apply_option(device: DazzleDevice, entity_id: str, option: str) -> None:
    try:
        if find_template(device.templates, option) is not None:
            await device.async_apply_template(option)
        elif ":" in option:
            name, _, args = option.partition(":")
            await device.async_send_command(args.strip(), template=name.strip())
        else:
            _LOGGER.warning(
                "%s: option %r of %s matches no template (known: %s)",
                device.name, option, entity_id, ", ".join(device.templates),
            )
    except TemplateError as err:
        _LOGGER.error("%s: %s", device.name, err)
    except Exception as err:  # noqa: BLE001 - BLE errors must not kill the listener
        _LOGGER.warning("%s: could not apply %r: %s", device.name, option, err)


async def _async_options_updated(hass: HomeAssistant, entry: DazzleConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: DazzleConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_shutdown()
    return unloaded
