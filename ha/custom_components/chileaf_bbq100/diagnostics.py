"""Diagnostics download: state plus recent raw notifications, to help decode them."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.core import HomeAssistant

from . import BBQ100ConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: BBQ100ConfigEntry
) -> dict[str, Any]:
    d = entry.runtime_data
    return {
        "address": d.address,
        "enabled": d.enabled,
        "connected": d.connected,
        "unit": d.unit,
        "version": d.version,
        "probes": {
            n: {
                "temperature": s.temperature,
                "time_now": s.time_now(),
                "channel": asdict(s.channel) if s.channel else None,
            }
            for n, s in d.probes.items()
        },
        "recent_frames": list(d.recent_frames),
    }
