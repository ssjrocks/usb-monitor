"""Reads USB devices from sysfs.

Everything here comes from what the kernel already holds: nothing opens a device or a
serial port, so watching can't send traffic to a device or reset a board.
"""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from usb_monitor import known

SYSFS = Path("/sys/bus/usb/devices")
USB_IDS = ("/usr/share/misc/usb.ids", "/usr/share/hwdata/usb.ids", "/var/lib/usbutils/usb.ids")

# sysfs directory names that hold device nodes, and the /dev prefix for each ("" = no node).
NODE_DIRS = {
    "tty": "/dev/",
    "block": "/dev/",
    "hidraw": "/dev/",
    "video4linux": "/dev/",
    "usbmisc": "/dev/",
    "net": "net:",
    "bluetooth": "",
    "sound": "",
}
SKIP_DIRS = {"power", "input", "subsystem", "driver", "device"}


@dataclass
class Interface:
    name: str
    klass: str
    subclass: str
    protocol: str
    description: str
    driver: str
    nodes: list[str] = field(default_factory=list)


@dataclass
class Device:
    port: str
    bus: int
    number: int
    vid: str
    pid: str
    manufacturer: str
    product: str
    serial: str
    speed: str
    usb_version: str
    max_power: str
    urbs: int
    power_state: str
    interfaces: list[Interface]
    category: str
    known_name: str

    @property
    def key(self) -> tuple[int, int]:
        # The device number changes on every enumeration, so a board that drops off and comes
        # back between two scans still shows up as a new device.
        return self.bus, self.number

    @property
    def usb_id(self) -> str:
        return f"{self.vid}:{self.pid}"

    @property
    def nodes(self) -> list[str]:
        return [node for interface in self.interfaces for node in interface.nodes]

    @property
    def drivers(self) -> list[str]:
        found = [interface.driver for interface in self.interfaces if interface.driver]
        return list(dict.fromkeys(found))

    @property
    def usb_node(self) -> str:
        return f"/dev/bus/usb/{self.bus:03}/{self.number:03}"

    @property
    def speed_mbps(self) -> float:
        try:
            return float(self.speed)
        except ValueError:
            return 0

    @property
    def speed_text(self) -> str:
        mbps = self.speed_mbps
        if not mbps:
            return ""
        return f"{mbps / 1000:g} Gb/s" if mbps >= 1000 else f"{mbps:g} Mb/s"

    @property
    def power_ma(self) -> int:
        match = re.match(r"\d+", self.max_power)
        return int(match.group()) if match else 0


class UsbIds:
    """Vendor and product names from the system's usb.ids, read on first use."""

    def __init__(self, paths=USB_IDS):
        self.paths = paths
        self.vendors: dict[str, str] | None = None
        self.products: dict[str, str] = {}

    def _load(self) -> None:
        self.vendors = {}
        path = next((p for p in self.paths if os.path.exists(p)), None)
        if path is None:
            return
        vendor = None
        with open(path, encoding="utf-8", errors="replace") as lines:
            for line in lines:
                if line.startswith("C "):  # the device class list follows the vendors
                    break
                if line.startswith("#") or len(line) < 7:
                    continue
                if line[0] == "\t":
                    if vendor and line[1] != "\t":
                        self.products[f"{vendor}:{line[1:5]}"] = line[7:].strip()
                else:
                    vendor = line[:4]
                    self.vendors[vendor] = line[6:].strip()

    def vendor(self, vid: str) -> str:
        if self.vendors is None:
            self._load()
        return self.vendors.get(vid, "")

    def product(self, usb_id: str) -> str:
        if self.vendors is None:
            self._load()
        return self.products.get(usb_id, "")


usb_ids = UsbIds()


def title(device: Device) -> str:
    """The name to show: the known name beats a chip's vague "USB Serial" string."""
    return (
        device.known_name
        or device.product
        or usb_ids.product(device.usb_id)
        or usb_ids.vendor(device.vid)
        or device.usb_id
    )


def _read(path: Path) -> str:
    try:
        return path.read_text(errors="replace").strip()
    except OSError:
        return ""


def _nodes_in(path: str) -> list[str]:
    nodes = []
    pending = [path]
    while pending:
        try:
            entries = [e for e in os.scandir(pending.pop()) if e.is_dir(follow_symlinks=False)]
        except OSError:
            continue
        for entry in entries:
            if entry.name in NODE_DIRS:
                prefix = NODE_DIRS[entry.name]
                try:
                    names = sorted(e.name for e in os.scandir(entry.path) if e.is_dir(follow_symlinks=False))
                except OSError:
                    continue
                nodes += [prefix + name for name in names if name not in SKIP_DIRS]
            elif entry.name not in SKIP_DIRS:
                pending.append(entry.path)
    return nodes


def _driver(path: Path) -> str:
    try:
        return os.path.basename(os.readlink(path / "driver"))
    except OSError:
        return ""


def _interfaces(path: Path, prefix: str) -> list[Interface]:
    interfaces = []
    try:
        names = sorted(e.name for e in os.scandir(path) if e.name.startswith(prefix))
    except OSError:
        return []
    for name in names:
        folder = path / name
        interfaces.append(
            Interface(
                name=name,
                klass=_read(folder / "bInterfaceClass"),
                subclass=_read(folder / "bInterfaceSubClass"),
                protocol=_read(folder / "bInterfaceProtocol"),
                description=_read(folder / "interface"),
                driver=_driver(folder),
                nodes=_nodes_in(str(folder)),
            )
        )
    return interfaces


def _read_device(path: Path) -> Device | None:
    port = path.name
    vid = _read(path / "idVendor")
    pid = _read(path / "idProduct")
    bus = _read(path / "busnum")
    number = _read(path / "devnum")
    if not (vid and pid and bus and number):
        return None  # it went away while being read
    # A root hub is called usb1, but its interface is 1-0:1.0.
    prefix = f"{bus}-0:" if port.startswith("usb") else f"{port}:"
    interfaces = _interfaces(path, prefix)
    nodes = [node for interface in interfaces for node in interface.nodes]
    classes = [interface.klass for interface in interfaces]
    category, known_name = known.classify(f"{vid}:{pid}", classes, nodes)
    urbs = _read(path / "urbnum")
    return Device(
        port=port,
        bus=int(bus),
        number=int(number),
        vid=vid,
        pid=pid,
        manufacturer=_read(path / "manufacturer"),
        product=_read(path / "product"),
        serial=_read(path / "serial"),
        speed=_read(path / "speed"),
        usb_version=_read(path / "version"),
        max_power=_read(path / "bMaxPower"),
        urbs=int(urbs) if urbs.isdigit() else 0,
        power_state=_read(path / "power" / "runtime_status"),
        interfaces=interfaces,
        category=category,
        known_name=known_name,
    )


def scan(root: Path = SYSFS) -> dict[tuple[int, int], Device]:
    devices = {}
    try:
        names = [e.name for e in os.scandir(root) if ":" not in e.name]
    except OSError:
        return {}
    for name in names:
        device = _read_device(root / name)
        if device:
            devices[device.key] = device
    return devices


def diff(old: dict, new: dict) -> tuple[list[Device], list[Device], list[tuple[Device, list[str]]]]:
    """(added, removed, changed); each change carries the sentences that describe it."""
    added = [new[key] for key in new if key not in old]
    removed = [old[key] for key in old if key not in new]
    changed = []
    for key in new.keys() & old.keys():
        before, after = old[key], new[key]
        notes = []
        for node in after.nodes:
            if node not in before.nodes:
                notes.append(f"{node.removeprefix('net:')} appeared")
        for node in before.nodes:
            if node not in after.nodes:
                notes.append(f"{node.removeprefix('net:')} went away")
        for driver in after.drivers:
            if driver not in before.drivers:
                notes.append(f"driver {driver} attached")
        for driver in before.drivers:
            if driver not in after.drivers:
                notes.append(f"driver {driver} released it")
        if notes:
            changed.append((after, notes))
    return added, removed, changed


def hints(device: Device) -> list[str]:
    """Things that commonly stop a device working, as far as sysfs can show them."""
    found = []
    for driver in device.drivers:
        if device.category == known.SDR and driver.startswith("dvb_usb"):
            found.append(
                f"The kernel's TV driver {driver} holds this stick. SDR software may not be able "
                f"to open it until that module is unloaded or blacklisted."
            )
    if device.category == known.SERIAL and not any("tty" in node for node in device.nodes):
        found.append(
            "No serial port was created. On Ubuntu, brltty often grabs these chips; "
            "removing it usually fixes that."
        )
    # A serial port is opened through its tty; only tools like rtl_sdr use the raw USB node.
    paths = [node for node in device.nodes if "/tty" in node]
    if not paths and device.category in known.DEV_HARDWARE:
        paths = [device.usb_node]
    for path in paths:
        if os.path.exists(path) and not os.access(path, os.R_OK | os.W_OK):
            found.append(f"You don't have read and write access to {path}.")
    return found


def serial_links() -> dict[str, str]:
    """Stable /dev/serial/by-id names, by the node they point to."""
    links = {}
    folder = "/dev/serial/by-id"
    try:
        for entry in os.scandir(folder):
            links[os.path.realpath(entry.path)] = entry.path
    except OSError:
        pass
    return links


def processes_using(paths: list[str]) -> list[tuple[int, str, str]]:
    """(pid, name, path) for each process that has one of the paths open.

    Other users' processes can't be read, so this is only as complete as our permissions.
    """
    wanted = set(paths)
    users = []
    own_pid = os.getpid()
    for entry in os.scandir("/proc"):
        if not entry.name.isdigit() or int(entry.name) == own_pid:
            continue
        try:
            for fd in os.scandir(f"/proc/{entry.name}/fd"):
                try:
                    target = os.readlink(fd.path)
                except OSError:
                    continue
                if target in wanted:
                    name = _read(Path(f"/proc/{entry.name}/comm"))
                    users.append((int(entry.name), name, target))
        except OSError:
            continue
    return sorted(set(users))
