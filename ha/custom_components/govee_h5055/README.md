# Govee H5055 for Home Assistant

A custom integration for the Govee H5055 6-probe Bluetooth BBQ thermometer.
It only listens to the thermometer's Bluetooth advertisements and never
connects to it.

## Why not the built-in Govee Bluetooth integration?

Newer H5055 firmware sends frame type `0x41`, which has a different layout
(big-endian hundredths of a degree, fields shifted by three bytes). The
built-in `govee_ble` parser only knows the older type `0x00` layout and decodes
`0x41` frames with it anyway. A real device holding steady at 25 °C reads as
484 °C, -32284 °C or 16868 °C depending on which probe pair the frame carries,
with the battery at 0 %. That is why its readings jump around.

This parser picks the layout from the frame type and accepts a frame only when:

* the first byte matches the end of the MAC address;
* the frame type is `0x00` or `0x41`;
* the probe selector is valid;
* every value is between -40 and 400 °C.

It ignores everything else. The diagnostics download lists the last 50 raw
frames, including the ignored ones, to help decode the other frame types later.

## Entities (per thermometer)

| Entity | What it is |
|-|-|
| `sensor.…_probe_N` (×6) | Probe temperature. Unknown while that probe is unplugged. |
| `sensor.…_probe_N_device_low_alarm` / `…_high_alarm` | The alarm limits the thermometer reports, as set in the Govee app (diagnostic). |
| `number.…_probe_N_low_limit` / `…_high_limit` | Alarm limits that you set in Home Assistant. They survive restarts. Leave the low limit at its minimum or the high limit at its maximum to turn that side off. |
| `binary_sensor.…_probe_N_alarm` | On while that probe reads outside its Home Assistant limits. |
| `binary_sensor.…_alarm` | On while any probe is in alarm. |
| `sensor.…_battery`, `sensor.…_signal_strength` | Diagnostics (signal strength is disabled by default). |

Home Assistant shows temperatures in your unit system (°F is fine). They are
stored in °C because the device reports °C.

The limits are kept in Home Assistant and are not written to the thermometer.
The limits that the thermometer itself reports are shown read-only.

## Install

1. Copy `custom_components/govee_h5055` into your Home Assistant
   `config/custom_components/` directory and restart.
2. The thermometer is discovered automatically (Settings → Devices &
   services). You can also add it by hand with **Add integration → Govee H5055
   BBQ Thermometer**.
3. Ignore or delete the H5055 device that the built-in **Govee Bluetooth**
   integration created, so that you don't have two sets of sensors.

## Tests

The parser has no Home Assistant dependencies:

    python -m pytest ha/tests
