"""What a USB device is, from its IDs, or failing that its interface classes."""

SDR = "SDR"
BOARD = "Dev board"
SERIAL = "Serial adapter"
DEBUG = "Debug probe"
HUB = "Hub"
STORAGE = "Storage"
INPUT = "HID"
AUDIO = "Audio"
VIDEO = "Video"
NETWORK = "Network"
WIRELESS = "Wireless"
PRINTER = "Printer"
OTHER = "Other"

# Order of the Type column and of the default sort: hardware you're working on comes first.
CATEGORIES = [
    SDR, BOARD, SERIAL, DEBUG, STORAGE, NETWORK, WIRELESS, AUDIO, VIDEO, INPUT, PRINTER, OTHER, HUB,
]
DEV_HARDWARE = {SDR, BOARD, SERIAL, DEBUG}

# From librtlsdr's udev rules: DVB-T sticks built on the RTL2832U.
RTL_SDR_IDS = """
0bda:2832 0bda:2838 0413:6680 0413:6f0f 0458:707f 0ccd:00a9 0ccd:00b3 0ccd:00b4 0ccd:00b5
0ccd:00b7 0ccd:00b8 0ccd:00b9 0ccd:00c0 0ccd:00c6 0ccd:00d3 0ccd:00d7 0ccd:00e0 1554:5020
15f4:0131 15f4:0133 185b:0620 185b:0650 185b:0680 1b80:d393 1b80:d394 1b80:d395 1b80:d397
1b80:d398 1b80:d39d 1b80:d3a4 1b80:d3a8 1b80:d3af 1b80:d3b0 1d19:1101 1d19:1102 1d19:1103
1d19:1104 1f4d:a803 1f4d:b803 1f4d:c803 1f4d:d286 1f4d:d803
""".split()

EXACT = {
    **{usb_id: (SDR, "RTL-SDR") for usb_id in RTL_SDR_IDS},
    "1d50:6089": (SDR, "HackRF One"),
    "1d50:60a1": (SDR, "Airspy"),
    "1d50:6108": (SDR, "LimeSDR"),
    "1df7:2500": (SDR, "SDRplay RSP1"),
    "1df7:3000": (SDR, "SDRplay RSP1A"),
    "1df7:3010": (SDR, "SDRplay RSP2"),
    "0456:b673": (SDR, "ADALM-Pluto"),
    "2cf0:5246": (SDR, "bladeRF"),
    "2cf0:5250": (SDR, "bladeRF 2.0 micro"),
    "2500:0020": (SDR, "USRP B210"),
    "1a86:7523": (SERIAL, "CH340 serial"),
    "1a86:5523": (SERIAL, "CH341 serial"),
    "1a86:55d3": (SERIAL, "CH343 serial"),
    "1a86:55d4": (SERIAL, "CH9102 serial"),
    "10c4:ea60": (SERIAL, "CP210x serial"),
    "10c4:ea70": (SERIAL, "CP2105 dual serial"),
    "0403:6001": (SERIAL, "FT232 serial"),
    "0403:6010": (SERIAL, "FT2232 dual serial"),
    "0403:6011": (SERIAL, "FT4232 quad serial"),
    "0403:6014": (SERIAL, "FT232H serial"),
    "0403:6015": (SERIAL, "FT-X serial"),
    "067b:2303": (SERIAL, "PL2303 serial"),
    "303a:1001": (BOARD, "ESP32 (built-in USB)"),
    "303a:0002": (BOARD, "ESP32-S2"),
    "2e8a:0003": (BOARD, "RP2040 in BOOTSEL mode"),
    "2e8a:0005": (BOARD, "Raspberry Pi Pico (MicroPython)"),
    "2e8a:000a": (BOARD, "Raspberry Pi Pico"),
    "0483:df11": (BOARD, "STM32 in DFU mode"),
    "2e8a:000c": (DEBUG, "Raspberry Pi Debug Probe"),
    "0483:3748": (DEBUG, "ST-Link V2"),
    "0483:374b": (DEBUG, "ST-Link V2.1"),
    "0483:3752": (DEBUG, "ST-Link V2.1"),
    "0483:374e": (DEBUG, "STLINK-V3"),
    "0483:374f": (DEBUG, "STLINK-V3"),
    "0d28:0204": (DEBUG, "DAPLink"),
    "1d50:6018": (DEBUG, "Black Magic Probe"),
}

# Any product from these vendors.
VENDORS = {
    "2341": (BOARD, "Arduino"),
    "2a03": (BOARD, "Arduino"),
    "303a": (BOARD, "Espressif board"),
    "239a": (BOARD, "Adafruit board"),
    "1b4f": (BOARD, "SparkFun board"),
    "2886": (BOARD, "Seeed board"),
    "2e8a": (BOARD, "Raspberry Pi board"),
    "1366": (DEBUG, "SEGGER J-Link"),
}

# USB interface class to category, for everything the tables above don't name.
CLASSES = {
    "01": AUDIO,
    "02": SERIAL,
    "03": INPUT,
    "07": PRINTER,
    "08": STORAGE,
    "09": HUB,
    "0a": SERIAL,
    "0e": VIDEO,
    "e0": WIRELESS,
}

SERIAL_NOTES = "Often an Arduino or ESP32 clone, or a programming cable."


def classify(usb_id: str, interface_classes: list[str], nodes: list[str]) -> tuple[str, str]:
    """(category, known name); the name is empty when only the class is known."""
    if usb_id in EXACT:
        return EXACT[usb_id]
    vendor = usb_id.split(":")[0]
    if vendor in VENDORS:
        return VENDORS[vendor]
    # A device's real job can sit behind a vendor-specific class, so check what it created first.
    if any(node.startswith("net:") for node in nodes):
        return NETWORK, ""
    for wanted in ("09", "08", "e0", "0e", "01", "02", "07", "03"):
        if wanted in interface_classes:
            return CLASSES[wanted], ""
    return OTHER, ""
