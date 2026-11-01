"""Live signals from the kernel: device events, and USB errors from its log."""

import logging
import re
import socket

from PyQt6.QtCore import QObject, QProcess, QSocketNotifier, pyqtSignal

LOG = logging.getLogger(__name__)

NETLINK_KOBJECT_UEVENT = 15
KERNEL_EVENTS = 1
WATCHED_SUBSYSTEMS = {"usb", "tty", "block", "net", "hidraw", "sound", "video4linux"}

# A device that fails to enumerate never reaches sysfs, so these lines are the only sign of a
# bad cable or a board that isn't answering.
USB_PROBLEM = re.compile(
    r"^usb \S+: .*(error -\d+|not accepting address|not responding|cable is bad"
    r"|unable to enumerate|over-?current|disabled by hub|attempt power cycle)",
    re.IGNORECASE,
)


def parse_uevent(data: bytes) -> dict[str, str]:
    """Fields of a kernel uevent: "add@/devices/..." then KEY=VALUE, separated by NULs."""
    fields = {}
    for part in data.split(b"\0")[1:]:
        key, _, value = part.decode(errors="replace").partition("=")
        if key:
            fields[key] = value
    return fields


def is_usb_problem(line: str) -> bool:
    return bool(USB_PROBLEM.search(line))


class UeventWatcher(QObject):
    """Emits changed when the kernel reports something a USB device could have caused."""

    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.sock = socket.socket(
            socket.AF_NETLINK, socket.SOCK_DGRAM | socket.SOCK_NONBLOCK, NETLINK_KOBJECT_UEVENT
        )
        self.sock.bind((0, KERNEL_EVENTS))
        self.notifier = QSocketNotifier(self.sock.fileno(), QSocketNotifier.Type.Read, self)
        self.notifier.activated.connect(self._read)

    def _read(self) -> None:
        relevant = False
        while True:
            try:
                data = self.sock.recv(65536)
            except BlockingIOError:
                break
            except OSError as error:
                # ENOBUFS: a burst overflowed the socket. The next scan catches up.
                LOG.warning("uevent socket: %s", error)
                relevant = True
                break
            if parse_uevent(data).get("SUBSYSTEM") in WATCHED_SUBSYSTEMS:
                relevant = True
        if relevant:
            self.changed.emit()


class KernelLog(QObject):
    """Follows the kernel log and emits USB errors as they're written."""

    problem = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self._read)
        self.process.start("journalctl", ["-k", "-f", "-n", "0", "-o", "cat", "--no-pager"])

    def _read(self) -> None:
        while self.process.canReadLine():
            line = bytes(self.process.readLine()).decode(errors="replace").strip()
            if is_usb_problem(line):
                self.problem.emit(line)

    def stop(self) -> None:
        self.process.terminate()
        self.process.waitForFinished(1000)
