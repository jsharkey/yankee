"""Diagnostics download: recent raw frames, to help decode unknown ones."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.core import HomeAssistant

from . import H5055ConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: H5055ConfigEntry
) -> dict[str, Any]:
    c = entry.runtime_data
    return {
        "address": c.address,
        "available": c.available,
        "battery": c.battery,
        "rssi": c.rssi,
        "rejected_frames": c.rejected_count,
        "probes": {n: asdict(r) for n, r in sorted(c.probes.items())},
        "limits": {f"{p}_{side}": v for (p, side), v in c.limits.items()},
        "recent_frames": list(c.recent_frames),
    }
