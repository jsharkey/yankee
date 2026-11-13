# Dazzle Bright String Lights (Home Assistant)

Home Assistant integration for Dazzle Bright smart Christmas string lights
(BLE name `IOTBTxxx`). It wraps `dazzle_multicolor.py`, so a pattern is just a
command line for that script.

## Install
Copy this folder into your Home Assistant `config/custom_components/` folder, then
restart.
The lights are discovered automatically (same name rules as lednetwf_ble:
`LEDnetWF*`, `IOTWF*`, `IOTB*`). You can also add them from
**Settings → Devices & services → Add integration → Dazzle Bright**.

Don't also configure the same lights in lednetwf_ble. Both would try to hold
the single Bluetooth connection. Close the phone app for the same reason.

## Entities
* **Light**: on/off and brightness. Off blanks every LED (all black) and leaves the controller running, so on goes straight to the pattern. A real power-down makes the lights flash white on the next power-on. You can switch back to real power-off in the options; the `send_command` service with `off` always powers down. Brightness re-sends the current pattern at the new
  level, because these lights have no separate brightness command. The state is assumed
  (the lights don't report it) and is restored after a restart.
* **Pattern** (select): one option per template.
* Service **`dazzle_bright.send_command`**: any script command line, e.g.
  `anim fallingSnow --direction 2 white blue`.

## Templates
Edit them under **Configure** on the integration. One per line, `name: arguments`:
```
christmas: random red green blue purple
candy cane: static --repeat 3 red white
meteor: anim meteor --speed 70 red white
```
Don't put `-b` in templates; brightness comes from the light. `static` gets
`--points` from the "Number of LEDs" option unless the template sets its own. The
options form checks every template and rejects a bad one with the script's error.

## Driving it from an input_select
In the options, pick an `input_select` helper. When its value changes, the template
with the same name (case-insensitive) is applied. An option can also carry its own
command, e.g. `party: anim chase --speed 80 red green`. Example helper:
```yaml
input_select:
  xmas_lights:
    name: Christmas lights
    options: [christmas, candy cane, meteor, "party: anim chase --speed 80 red green"]
```

## Segment bars (IOTBT4E8)
Some lights (product 170, e.g. `IOTBT4E8`; also 173) take one colour per
segment instead of per-LED patterns. They're detected from their Bluetooth
advert and set up in **segment bar** mode (you can change the mode under
**Configure**). In that mode the device has:
* **Light**: on/off and brightness, as above. Off blanks every segment.
* **Night light** (switch): the `night` segments show the night colour
  (default `ff8811`) when on, black when off.
* **Signal** (select): colour of the `signal` segment(s). Default options are
  black, red, yellow, green, blue and purple.

The default layout is `night*8 black*9 signal`, top to bottom: 18 segments, the
number on the IOTBT4E8. `name*N` repeats an entry, and any other entry is a fixed
colour. Use exactly as many entries as the bar has segments. With more, the lights
squeeze and blend them. The switch and select change the bar straight away while
the light is on. While it's off they only take effect at the next turn-on.

## Running the script directly
`dazzle_multicolor.py` in this folder is the same command-line
tool, e.g. `python dazzle_multicolor.py -a <MAC> -b 60 anim meteor red white`.

## Troubleshooting
**"No backend with an available connection slot… no scanner currently has it in its
discovered devices"**: your Bluetooth adapter hasn't heard the lights since its scanner
last restarted. The integration now waits up to 30 s for the next advertisement and then
retries, so this should resolve itself. If you get **"the lights have not advertised for
30 s"**, something else is probably connected to them (the phone app, or the same lights
also added to lednetwf_ble). BLE lights stop advertising while connected. Otherwise they
may be out of range, and an ESPHome Bluetooth proxy near the lights will help.

