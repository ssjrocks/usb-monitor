import argparse
import logging
import signal
import sys
import traceback
from pathlib import Path

from usb_monitor import APP_ID, APP_NAME, __version__, devices, known, updater


def list_devices() -> int:
    found = devices.scan()
    order = sorted(found.values(), key=lambda d: (known.CATEGORIES.index(d.category), d.port))
    for device in order:
        nodes = ", ".join(device.nodes)
        print(f"{device.category:15} {device.usb_id}  {device.port:12} {devices.title(device)}  {nodes}")
    return 0


def check_update(install: bool) -> int:
    update = updater.check()
    updater.mark_checked()
    if update is None:
        print(f"{APP_NAME} {__version__}: no update found")
        return 0
    print(f"Update available: {update.version}")
    if install:
        updater.install(update)
        print(f"Installed {update.version}")
    return 0


def run_gui() -> int:
    from PyQt6.QtGui import QIcon
    from PyQt6.QtWidgets import QApplication

    from usb_monitor.window import MainWindow

    # PyQt aborts on an exception in a slot unless a hook takes it.
    sys.excepthook = lambda *error: traceback.print_exception(*error)
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setDesktopFileName(APP_ID)
    app.setWindowIcon(QIcon(str(Path(__file__).with_name("icon.svg"))))
    window = MainWindow()
    window.show()
    return app.exec()


def main() -> int:
    parser = argparse.ArgumentParser(prog="usb-monitor", description=APP_NAME)
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("list", help="print connected devices and exit")
    update = commands.add_parser("update", help="check GitHub for a newer release")
    update.add_argument("--install", action="store_true", help="install a newer release")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    if args.command == "list":
        return list_devices()
    if args.command == "update":
        return check_update(args.install)
    return run_gui()
