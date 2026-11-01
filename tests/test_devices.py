from pathlib import Path

from usb_monitor import devices, known


def write(folder: Path, **attrs) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for name, value in attrs.items():
        (folder / name).write_text(f"{value}\n")


def fake_device(root: Path, port: str, usb_id: str, number: int, **attrs) -> Path:
    vid, pid = usb_id.split(":")
    folder = root / port
    bus = port.removeprefix("usb").split("-")[0]
    write(folder, idVendor=vid, idProduct=pid, busnum=bus, devnum=number, urbnum=10, speed=12, **attrs)
    return folder


def fake_interface(device: Path, name: str, klass: str, driver: str = "") -> Path:
    folder = device / name
    write(folder, bInterfaceClass=klass, bInterfaceSubClass="00", bInterfaceProtocol="00")
    if driver:
        (folder / "driver").symlink_to(f"/sys/bus/usb/drivers/{driver}")
    return folder


def test_usb_serial_node_and_type(tmp_path):
    device = fake_device(tmp_path, "1-9.2", "1a86:7523", 29, product="USB Serial")
    interface = fake_interface(device, "1-9.2:1.0", "ff", "ch341")
    (interface / "ttyUSB0" / "tty" / "ttyUSB0").mkdir(parents=True)

    found = devices.scan(tmp_path)[(1, 29)]

    assert found.category == known.SERIAL
    assert devices.title(found) == "CH340 serial"
    assert found.nodes == ["/dev/ttyUSB0"]
    assert found.drivers == ["ch341"]


def test_cdc_acm_node(tmp_path):
    device = fake_device(tmp_path, "1-2", "2341:0043", 5, product="Arduino Uno")
    interface = fake_interface(device, "1-2:1.0", "02", "cdc_acm")
    (interface / "tty" / "ttyACM3").mkdir(parents=True)

    found = devices.scan(tmp_path)[(1, 5)]

    assert found.category == known.BOARD
    assert found.nodes == ["/dev/ttyACM3"]


def test_root_hub_uses_bus_prefix_for_interfaces(tmp_path):
    device = fake_device(tmp_path, "usb1", "1d6b:0002", 1)
    fake_interface(device, "1-0:1.0", "09", "hub")

    found = devices.scan(tmp_path)[(1, 1)]

    assert found.category == known.HUB
    assert found.drivers == ["hub"]


def test_interface_entries_and_half_gone_devices_are_skipped(tmp_path):
    write(tmp_path / "1-9.2:1.0", bInterfaceClass="ff")
    write(tmp_path / "1-3", idVendor="1234")
    assert devices.scan(tmp_path) == {}


def test_vendor_specific_network_adapter_is_network(tmp_path):
    device = fake_device(tmp_path, "2-1", "0bda:8153", 7)
    interface = fake_interface(device, "2-1:1.0", "ff", "r8152")
    (interface / "net" / "enx001122").mkdir(parents=True)

    found = devices.scan(tmp_path)[(2, 7)]

    assert found.category == known.NETWORK
    assert found.nodes == ["net:enx001122"]


def test_rtl_sdr_with_dvb_driver_gets_a_hint(tmp_path):
    device = fake_device(tmp_path, "1-1", "0bda:2838", 4)
    fake_interface(device, "1-1:1.0", "ff", "dvb_usb_rtl28xxu")

    found = devices.scan(tmp_path)[(1, 4)]

    assert found.category == known.SDR
    assert any("dvb_usb_rtl28xxu" in hint for hint in devices.hints(found))


def test_serial_chip_without_tty_gets_a_hint(tmp_path):
    device = fake_device(tmp_path, "1-1", "10c4:ea60", 4)
    fake_interface(device, "1-1:1.0", "ff")

    found = devices.scan(tmp_path)[(1, 4)]

    assert any("brltty" in hint for hint in devices.hints(found))


def test_lock_taking_attributes_are_read_once_per_connection(tmp_path):
    folder = fake_device(tmp_path, "1-1", "2341:0043", 4, product="First", bMaxPower="100mA")
    assert devices.scan(tmp_path)[(1, 4)].product == "First"

    (folder / "product").write_text("Second\n")
    assert devices.scan(tmp_path)[(1, 4)].product == "First"

    (folder / "devnum").write_text("5\n")
    assert devices.scan(tmp_path)[(1, 5)].product == "Second"


def test_diff_sees_reenumeration_on_same_port(tmp_path):
    device = fake_device(tmp_path, "1-1", "303a:1001", 4)
    fake_interface(device, "1-1:1.0", "02", "cdc_acm")
    before = devices.scan(tmp_path)
    (tmp_path / "1-1" / "devnum").write_text("5\n")

    added, removed, changed = devices.diff(before, devices.scan(tmp_path))

    assert [d.number for d in added] == [5]
    assert [d.number for d in removed] == [4]
    assert changed == []


def test_diff_reports_late_serial_port(tmp_path):
    device = fake_device(tmp_path, "1-1", "1a86:7523", 4)
    interface = fake_interface(device, "1-1:1.0", "ff")
    before = devices.scan(tmp_path)
    (interface / "ttyUSB0" / "tty" / "ttyUSB0").mkdir(parents=True)

    _, _, changed = devices.diff(before, devices.scan(tmp_path))

    assert changed[0][1] == ["/dev/ttyUSB0 appeared"]


def test_usb_ids_parser(tmp_path):
    path = tmp_path / "usb.ids"
    path.write_text(
        "# comment\n1a86  QinHeng\n\t7523  CH340 serial converter\n\t\t00  an interface\n"
        "C 00  (Defined at Interface level)\n\t01  Not a product\n"
    )
    names = devices.UsbIds([str(path)])

    assert names.vendor("1a86") == "QinHeng"
    assert names.product("1a86:7523") == "CH340 serial converter"
    assert names.product("1a86:0001") == ""
