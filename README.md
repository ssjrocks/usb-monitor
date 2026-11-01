# USB Monitor

A small Linux desktop app that shows your connected USB devices live. It recognises
RTL-SDR sticks and other SDRs, Arduino, ESP32 and Pico boards, USB-serial chips (CH340,
CP210x, FTDI, PL2303) and debug probes, and sorts them to the top.

- **Live table:** name, type, serial port or disk, speed, power, driver and physical USB port.
- **Activity:** USB requests per second, so you can see whether a device is actually working.
- **Events:** connects, disconnects and drivers attaching, as they happen. A board that drops
  off and comes back is shown even if it's gone for only a moment.
- **Kernel errors:** a device with a bad cable never finishes connecting, so it wouldn't appear
  in any list. Those failures are shown in the event log (read from `journalctl`; your user
  needs to be in the `adm` or `systemd-journal` group).
- **Details:** interfaces, the stable `/dev/serial/by-id` path, and which of your programs has
  the device open.
- **Hints:** for example, the kernel's TV driver holding an RTL-SDR stick, a serial chip with
  no port, or a port you don't have permission to open.

It only reads what the kernel already knows, from sysfs. It never opens a device or a serial
port, so watching can't reset a board or disturb a running program. Activity comes from the
kernel's `urbnum` counter, so it counts requests, not bytes.

## Install

Needs [uv](https://docs.astral.sh/uv/). This installs the latest release and adds it to your
app menu:

```bash
curl -fsSL https://raw.githubusercontent.com/ssjrocks/usb-monitor/main/scripts/install.sh | bash
```

The app checks GitHub for a new release at most twice a day and shows an update button when
there is one. That check is its only network use. Nothing is sent about you or your devices.

## From source

```bash
uv venv --seed --python 3.12 .venv
uv pip install --python .venv/bin/python -e . pytest
.venv/bin/usb-monitor
.venv/bin/python -m pytest
```

`usb-monitor list` prints the devices once, and `usb-monitor update --install` updates from
the command line.

## Releasing

Bump the version in `pyproject.toml` and `src/usb_monitor/__init__.py`, commit, and run
`scripts/release.sh NOTES.md`.

## License

GPL-3.0-only
