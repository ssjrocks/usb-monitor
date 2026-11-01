"""The main window: a live device table, the selected device's details, and an event log."""

import html
import logging
import sys
import threading
import time
from datetime import datetime

from PyQt6.QtCore import QProcess, QSettings, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTextBrowser,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from usb_monitor import APP_NAME, __version__, devices, known, updater
from usb_monitor.watch import KernelLog, UeventWatcher

LOG = logging.getLogger(__name__)

COLUMNS = ["Device", "Type", "ID", "Ports", "Speed", "Power", "Activity", "Driver", "USB port"]
TYPE, ACTIVITY = 1, 6

COLOURS = {
    known.SDR: "#b05cd6",
    known.BOARD: "#2e9e5b",
    known.SERIAL: "#2f86d1",
    known.DEBUG: "#d98324",
}
PLAIN_COLOUR = "#8a8f98"
NEW_ROW = QColor(46, 158, 91, 70)
GONE_ROW = QColor(217, 83, 79, 70)
LOG_CONNECT = "#2e9e5b"
LOG_REMOVE = "#d9534f"
LOG_KERNEL = "#c98a00"

ROW_FADE_MS = 8000
TICK_MS = 1000
EVENT_DELAY_MS = 150
PROCESS_CHECK_EVERY = 2.0

FILTERS = {"Hide hubs": "nohubs", "Dev hardware only": "dev", "Everything": "all"}


def dot(colour: str) -> QIcon:
    pixmap = QPixmap(16, 16)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(colour))
    painter.drawEllipse(3, 3, 10, 10)
    painter.end()
    return QIcon(pixmap)


def activity_text(device: devices.Device, rate: float | None) -> str:
    if device.power_state == "suspended":
        return "suspended"
    if rate is None:
        return ""
    return f"{rate:,.0f} URB/s" if rate >= 0.5 else "idle"


def short_nodes(device: devices.Device) -> str:
    # Every HID device has hidraw nodes; those stay in the details so the column stays readable.
    nodes = [node.removeprefix("/dev/").removeprefix("net:") for node in device.nodes]
    return ", ".join(node for node in nodes if not node.startswith(("hidraw", "hiddev")))


def row_values(device: devices.Device, rate: float | None) -> list[str]:
    return [
        devices.title(device),
        device.category,
        device.usb_id,
        short_nodes(device),
        device.speed_text,
        device.max_power,
        activity_text(device, rate),
        ", ".join(device.drivers),
        device.port,
    ]


def row_sort_keys(device: devices.Device, rate: float | None) -> list:
    keys: list = [text.lower() for text in row_values(device, rate)]
    keys[TYPE] = (known.CATEGORIES.index(device.category), keys[0])
    keys[4] = device.speed_mbps
    keys[5] = device.power_ma
    keys[ACTIVITY] = rate or 0
    return keys


class Row(QTreeWidgetItem):
    sort_keys: list = []

    def __lt__(self, other):
        tree = self.treeWidget() or other.treeWidget()
        column = tree.sortColumn()
        return self.sort_keys[column] < other.sort_keys[column]


class MainWindow(QMainWindow):
    processes_found = pyqtSignal(tuple, list)
    update_found = pyqtSignal(object)
    update_installed = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.settings = QSettings("ssjrocks", "usb-monitor")
        self.devices: dict = {}
        self.rows: dict[tuple, Row] = {}
        self.rates: dict[tuple, float] = {}
        self.last_urbs: dict[tuple, tuple[int, float]] = {}
        self.users: dict[tuple, list] = {}
        self.checking_processes = False
        self.last_process_check = 0.0
        self.pending_update = None
        self.icons = {category: dot(COLOURS.get(category, PLAIN_COLOUR)) for category in known.CATEGORIES}

        self._build()
        self.processes_found.connect(self._show_processes)
        self.update_found.connect(self._show_update)
        self.update_installed.connect(self._finish_update)

        self.devices = devices.scan()
        self._add_rows(self.devices.values(), fresh=False)
        self._apply_filter()
        self.table.sortByColumn(TYPE, Qt.SortOrder.AscendingOrder)
        self._fit_columns()
        self._log("", f"Watching {len(self.devices)} USB devices")

        self.refresh_soon = QTimer(self, singleShot=True, interval=EVENT_DELAY_MS)
        self.refresh_soon.timeout.connect(self.refresh)
        try:
            self.watcher = UeventWatcher(self)
            self.watcher.changed.connect(self.refresh_soon.start)
        except OSError as error:
            self._log(LOG_KERNEL, f"No live kernel events ({error}), checking once a second instead")
        self.kernel_log = KernelLog(self)
        self.kernel_log.problem.connect(lambda line: self._log(LOG_KERNEL, f"Kernel: {line}"))

        self.ticker = QTimer(self, interval=TICK_MS)
        self.ticker.timeout.connect(self.refresh)
        self.ticker.start()

        if updater.due():
            threading.Thread(target=self._check_update, daemon=True).start()

    def _build(self) -> None:
        self.filter = QComboBox()
        self.filter.addItems(FILTERS)
        self.filter.setCurrentText(str(self.settings.value("filter", "Hide hubs")))
        self.filter.currentTextChanged.connect(self._apply_filter)
        self.summary = QLabel()

        top = QHBoxLayout()
        top.addWidget(QLabel("Show:"))
        top.addWidget(self.filter)
        top.addStretch()
        top.addWidget(self.summary)

        self.table = QTreeWidget()
        self.table.setColumnCount(len(COLUMNS))
        self.table.setHeaderLabels(COLUMNS)
        self.table.setRootIsDecorated(False)
        self.table.setAlternatingRowColors(True)
        self.table.setUniformRowHeights(True)
        self.table.setSortingEnabled(True)
        self.table.itemSelectionChanged.connect(self._selection_changed)

        self.details = QTextBrowser()
        self.details.setOpenLinks(False)
        self.details.setPlaceholderText("Select a device to see its details")

        self.events = QPlainTextEdit(readOnly=True)
        self.events.setMaximumBlockCount(2000)
        self.events.setFont(QFont("monospace", 9))
        clear = QPushButton("Clear")
        clear.clicked.connect(self.events.clear)
        heading = QHBoxLayout()
        heading.addWidget(QLabel("Events"))
        heading.addStretch()
        heading.addWidget(clear)
        log_box = QVBoxLayout()
        log_box.setContentsMargins(0, 0, 0, 0)
        log_box.addLayout(heading)
        log_box.addWidget(self.events)
        log_panel = QWidget()
        log_panel.setLayout(log_box)

        self.lower = QSplitter(Qt.Orientation.Horizontal)
        self.lower.addWidget(self.details)
        self.lower.addWidget(log_panel)
        self.lower.setSizes([450, 650])

        self.split = QSplitter(Qt.Orientation.Vertical)
        self.split.addWidget(self.table)
        self.split.addWidget(self.lower)
        self.split.setSizes([360, 300])

        layout = QVBoxLayout()
        layout.addLayout(top)
        layout.addWidget(self.split, 1)
        root = QWidget()
        root.setLayout(layout)
        self.setCentralWidget(root)

        self.update_button = QPushButton()
        self.update_button.hide()
        self.update_button.clicked.connect(self._update_clicked)
        self.statusBar().addPermanentWidget(self.update_button)
        self.statusBar().showMessage(f"Version {__version__}")

        self.resize(1120, 720)
        geometry = self.settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)

    def _fit_columns(self) -> None:
        for column in range(len(COLUMNS)):
            self.table.resizeColumnToContents(column)
        self.table.setColumnWidth(ACTIVITY, max(self.table.columnWidth(ACTIVITY), 110))

    def refresh(self) -> None:
        new = devices.scan()
        added, removed, changed = devices.diff(self.devices, new)
        self.devices = new
        self._update_rates()

        for device in removed:
            self._log(LOG_REMOVE, f"Disconnected: {self._describe(device)}")
            self._retire_row(device)
        for device in added:
            self._log(LOG_CONNECT, f"Connected: {self._describe(device)}")
        for device, notes in changed:
            self._log("", f"{devices.title(device)}: {', '.join(notes)}")

        self._add_rows(added, fresh=True)
        for key, row in self.rows.items():
            self._set_row(row, self.devices[key])
        if added or changed:
            self._apply_filter()
            self._fit_columns()
        self._refresh_details()

    def _update_rates(self) -> None:
        now = time.monotonic()
        rates = {}
        last = {}
        for key, device in self.devices.items():
            previous = self.last_urbs.get(key)
            # Events can trigger a scan just after a tick; wait for a usable time span.
            if previous and now - previous[1] < 0.5:
                last[key] = previous
                rates[key] = self.rates.get(key)
                continue
            last[key] = (device.urbs, now)
            if previous:
                rates[key] = (device.urbs - previous[0]) / (now - previous[1])
        self.rates = rates
        self.last_urbs = last

    def _describe(self, device: devices.Device) -> str:
        parts = [devices.title(device), device.usb_id, f"port {device.port}"]
        if device.product and device.product != parts[0]:
            parts.insert(1, device.product)
        if device.nodes:
            parts.append(short_nodes(device))
        if device.drivers:
            parts.append("driver " + ", ".join(device.drivers))
        return " · ".join(parts)

    def _add_rows(self, added, fresh: bool) -> None:
        for device in added:
            row = Row()
            row.key = device.key
            row.setIcon(0, self.icons[device.category])
            self._set_row(row, device)
            self.table.addTopLevelItem(row)
            self.rows[device.key] = row
            if fresh:
                self._tint(row, NEW_ROW)
                QTimer.singleShot(ROW_FADE_MS, lambda r=row: self._tint(r, None))

    def _set_row(self, row: Row, device: devices.Device) -> None:
        rate = self.rates.get(device.key)
        row.sort_keys = row_sort_keys(device, rate)
        for column, text in enumerate(row_values(device, rate)):
            if row.text(column) != text:
                row.setText(column, text)

    def _tint(self, row: Row, colour: QColor | None) -> None:
        if row.treeWidget() is None:
            return
        brush = QBrush(colour) if colour else QBrush()
        for column in range(len(COLUMNS)):
            row.setBackground(column, brush)

    def _retire_row(self, device: devices.Device) -> None:
        """Leaves a removed device's row up for a moment, so a brief drop-out can be seen."""
        self.users.pop(device.key, None)
        row = self.rows.pop(device.key, None)
        if row is None:
            return
        self._tint(row, GONE_ROW)
        row.setText(ACTIVITY, "disconnected")
        QTimer.singleShot(ROW_FADE_MS, lambda: self._drop_row(row))

    def _drop_row(self, row: Row) -> None:
        index = self.table.indexOfTopLevelItem(row)
        if index >= 0:
            self.table.takeTopLevelItem(index)

    def _apply_filter(self) -> None:
        mode = FILTERS[self.filter.currentText()]
        shown = 0
        for key, row in self.rows.items():
            device = self.devices[key]
            hide = (mode == "nohubs" and device.category == known.HUB) or (
                mode == "dev" and device.category not in known.DEV_HARDWARE
            )
            row.setHidden(hide)
            shown += not hide
        self.summary.setText(f"{shown} shown, {len(self.devices)} connected")

    def _selected_key(self) -> tuple | None:
        selected = self.table.selectedItems()
        return selected[0].key if selected else None

    def _selection_changed(self) -> None:
        self.last_process_check = 0.0
        self._refresh_details()

    def _refresh_details(self) -> None:
        key = self._selected_key()
        if key is None:
            self.details.clear()
            return
        device = self.devices.get(key)
        if device is None:
            self.details.setHtml("<p>This device is no longer connected.</p>")
            return
        self._render_details(device)
        self._check_processes(device)

    def _render_details(self, device: devices.Device) -> None:
        esc = html.escape
        vendor = devices.usb_ids.vendor(device.vid)
        product = devices.usb_ids.product(device.usb_id)
        links = devices.serial_links()
        rows = [
            ("Maker", device.manufacturer or vendor),
            ("Product", device.product or product),
            ("Serial number", device.serial),
            ("USB ID", f"{device.usb_id}" + (f" ({vendor})" if vendor else "")),
            ("USB version", device.usb_version),
            ("Speed", device.speed_text),
            ("Max power", device.max_power),
            ("Bus / device", f"{device.bus} / {device.number}"),
            ("Power state", device.power_state),
        ]
        for node in device.nodes:
            if node in links:
                rows.append(("Stable path", links[node]))
        if device.category == known.SERIAL and device.known_name:
            rows.append(("Note", known.SERIAL_NOTES))

        parts = [f"<h3>{esc(devices.title(device))}</h3>"]
        for hint in devices.hints(device):
            parts.append(f"<p style='color:{LOG_KERNEL}'>{esc(hint)}</p>")
        parts.append("<table cellpadding='2'>")
        for label, value in rows:
            if value:
                parts.append(f"<tr><td><b>{esc(label)}</b></td><td>{esc(str(value))}</td></tr>")
        parts.append("</table><p><b>Interfaces</b></p><ul>")
        for interface in device.interfaces:
            text = f"{interface.name}: class {interface.klass}"
            if interface.description:
                text += f", {interface.description}"
            text += f", {interface.driver or 'no driver'}"
            if interface.nodes:
                text += " (" + ", ".join(interface.nodes) + ")"
            parts.append(f"<li>{esc(text)}</li>")
        parts.append("</ul><p><b>In use by</b></p>")
        users = self.users.get(device.key)
        if users is None:
            parts.append("<p>Checking…</p>")
        elif users:
            lines = [f"{name} (pid {pid}): {path}" for pid, name, path in users]
            parts.append("<ul>" + "".join(f"<li>{esc(line)}</li>" for line in lines) + "</ul>")
        else:
            parts.append("<p>Nothing of yours has it open.</p>")

        position = self.details.verticalScrollBar().value()
        self.details.setHtml("".join(parts))
        self.details.verticalScrollBar().setValue(position)

    def _check_processes(self, device: devices.Device) -> None:
        now = time.monotonic()
        if self.checking_processes or now - self.last_process_check < PROCESS_CHECK_EVERY:
            return
        self.checking_processes = True
        self.last_process_check = now
        paths = [device.usb_node] + [node for node in device.nodes if node.startswith("/dev/")]
        threading.Thread(target=self._find_processes, args=(device.key, paths), daemon=True).start()

    def _find_processes(self, key: tuple, paths: list[str]) -> None:
        try:
            users = devices.processes_using(paths)
        except OSError:
            users = []
        self.processes_found.emit(key, users)

    def _show_processes(self, key: tuple, users: list) -> None:
        self.checking_processes = False
        changed = self.users.get(key) != users
        self.users[key] = users
        if changed and key == self._selected_key() and key in self.devices:
            self._render_details(self.devices[key])

    def _log(self, colour: str, text: str) -> None:
        LOG.info(text)
        stamp = datetime.now().strftime("%H:%M:%S")
        line = html.escape(f"{stamp}  {text}")
        self.events.appendHtml(f"<span style='color:{colour}'>{line}</span>" if colour else line)

    def _check_update(self) -> None:
        try:
            found = updater.check()
            updater.mark_checked()
        except Exception as error:  # no network shouldn't trouble a local tool
            print(f"update check failed: {error}", file=sys.stderr)
            return
        if found:
            self.update_found.emit(found)

    def _show_update(self, update: updater.Update) -> None:
        self.pending_update = update
        self.update_button.setText(f"Update to {update.version}")
        self.update_button.show()

    def _update_clicked(self) -> None:
        if self.pending_update is None:
            QProcess.startDetached(sys.executable, ["-m", "usb_monitor"])
            QApplication.quit()
            return
        self.update_button.setEnabled(False)
        self.update_button.setText("Updating…")
        threading.Thread(target=self._install_update, daemon=True).start()

    def _install_update(self) -> None:
        try:
            updater.install(self.pending_update)
            self.update_installed.emit(None)
        except Exception as error:
            self.update_installed.emit(error)

    def _finish_update(self, error: Exception | None) -> None:
        self.update_button.setEnabled(True)
        if error:
            self.update_button.setText(f"Update to {self.pending_update.version}")
            QMessageBox.warning(self, APP_NAME, str(error))
            return
        self.pending_update = None
        self.update_button.setText("Restart to finish updating")

    def closeEvent(self, event) -> None:
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("filter", self.filter.currentText())
        self.kernel_log.stop()
        super().closeEvent(event)
