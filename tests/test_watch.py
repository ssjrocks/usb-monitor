import pytest

from usb_monitor.watch import is_usb_problem, parse_uevent


def test_parse_uevent():
    data = b"add@/devices/pci0000:00/usb1/1-2\0ACTION=add\0SUBSYSTEM=usb\0DEVTYPE=usb_device\0"
    fields = parse_uevent(data)
    assert fields["SUBSYSTEM"] == "usb"
    assert fields["ACTION"] == "add"


# Wording taken from this machine's kernel log.
@pytest.mark.parametrize(
    "line",
    [
        "usb 1-9.4: device descriptor read/64, error -71",
        "usb 1-9.4: device descriptor read/64, error -32",
        "usb 1-9.4: device not accepting address 6, error -71",
        "usb 1-9.4: Device not responding to setup address.",
        "usb 1-9-port3: Cannot enable. Maybe the USB cable is bad?",
        "usb 1-9-port3: unable to enumerate USB device",
        "usb 1-9-port3: attempt power cycle",
        "usb usb1-port3: over-current condition",
    ],
)
def test_usb_problems_are_caught(line):
    assert is_usb_problem(line)


@pytest.mark.parametrize(
    "line",
    [
        "usb 1-9.2: ch341-uart converter now attached to ttyUSB0",
        "usb 1-9.2: New USB device found, idVendor=1a86, idProduct=7523",
        "usb 1-2: USB disconnect, device number 12",
        "nvme nvme0: error -5 on something unrelated",
    ],
)
def test_normal_lines_are_ignored(line):
    assert not is_usb_problem(line)
