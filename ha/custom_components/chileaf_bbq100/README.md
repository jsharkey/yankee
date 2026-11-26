# Chileaf BBQ100 for Home Assistant

A custom integration for the Chileaf BBQ100 four-probe Bluetooth BBQ
thermometer (Bluetooth name `BBQ100-xxxx` or `BBQ100P-xxxx`), the one that uses
the **Chi-BBQ** phone app.

The thermometer only advertises its name and sends no readings in its
adverts, so the integration connects to it and keeps the connection open. It
accepts **one connection at a time**: close the Chi-BBQ app before setting it
up, or switch off **Bluetooth connection** in Home Assistant when you want to
use the app.

## Entities (per thermometer)

| Entity | What it is |
|-|-|
| `sensor.…_probe_N` (×4) | Probe temperature. Unknown while that probe is unplugged. |
| `sensor.…_probe_N_mode` | `meat`, `temperature` or `timer`. In meat mode the attributes give the meat and doneness. |
| `sensor.…_probe_N_time` | Time left in timer mode, otherwise time since the probe was started. |
| `number.…_probe_N_target` | Target temperature. Setting it switches the probe to temperature mode. In meat mode it shows the target the thermometer chose. |
| `number.…_probe_N_timer` | Countdown in minutes (1–99). Setting it switches the probe to timer mode. |
| `select.…_probe_N_meat` | Meat and doneness, as offered in the app (e.g. "Beef medium rare", "Chicken"). Choosing one switches the probe to meat mode. |
| `switch.…_probe_N_running` | Start or stop that probe (the app's Start/Stop button). |
| `binary_sensor.…_probe_N_alarm` | On while the thermometer's alarm sounds for that probe. |
| `button.…_probe_N_stop_alarm` | Silences that probe's alarm. |
| `binary_sensor.…_alarm` | On while any probe's alarm sounds. |
| `select.…_display_unit` | °C or °F on the thermometer's own screen (config). |
| `switch.…_bluetooth_connection` | Off lets go of the thermometer so the phone app can connect (config; survives restarts). |
| `binary_sensor.…_connected` | Whether Home Assistant holds the connection (diagnostic). |

Home Assistant shows temperatures in your unit system. They are stored in °C
because the thermometer reports hundredths of a degree Celsius, whatever its
display shows.

## Protocol

Decoded from the Chi-BBQ Android app (1.0.6, package `com.qili.bbq`); see
`protocol.py`. The thermometer has one GATT service
`6e40fd00-b5a3-f393-e0a9-e50e24dcca9e`. Commands go to `6e408d03-…` and
replies come as notifications on `6e408d02-…`. Every frame is
`6A, length, command, payload…, sum8`. The thermometer pushes command `0x0F`
(all four temperatures) by itself. Home Assistant asks for each probe's full
state (`0x02`) on connect, after each change, and every 30 seconds.

The bytes come from the app's code, not from a capture of a real thermometer.
If something reads wrong, the diagnostics download lists the last 50 raw
notifications. The reply to the version request (`0x01`) is kept raw because
the app never decodes it.

## Install

1. Copy `custom_components/chileaf_bbq100` into your Home Assistant
   `config/custom_components/` directory and restart.
2. Close the Chi-BBQ app and switch the thermometer on. It is discovered
   automatically (Settings → Devices & services). You can also add it by hand
   with **Add integration → Chileaf BBQ100 Thermometer**.

## Tests

The protocol module has no Home Assistant dependencies:

    python -m pytest ha/tests
