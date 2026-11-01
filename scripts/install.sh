#!/usr/bin/env bash
# Installs the latest release into its own venv and adds it to the app menu. The in-app
# updater recognises this venv by its usb-monitor-venv marker file.
set -euo pipefail
repo=ssjrocks/usb-monitor
data="${XDG_DATA_HOME:-$HOME/.local/share}"
venv="$data/usb-monitor/venv"
command -v uv >/dev/null || { echo "uv not found: https://docs.astral.sh/uv/" >&2; exit 1; }

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
base="https://github.com/$repo/releases/latest/download"
curl -fsSL "$base/usb-monitor.json" -o "$tmp/info.json"
field() { python3 -c "import json,sys; print(json.load(open(sys.argv[1]))[sys.argv[2]])" "$tmp/info.json" "$1"; }
wheel=$(field wheel)
curl -fsSL "$base/$wheel" -o "$tmp/$wheel"
echo "$(field sha256)  $tmp/$wheel" | sha256sum --check --quiet

[[ -x "$venv/bin/python" ]] || uv venv -q --seed --python 3.12 "$venv"
touch "$venv/usb-monitor-venv"
"$venv/bin/python" -m pip install -q "$tmp/$wheel"

icon=$("$venv/bin/python" -c 'import pathlib, usb_monitor; print(pathlib.Path(usb_monitor.__file__).with_name("icon.svg"))')
mkdir -p "$data/icons/hicolor/scalable/apps" "$data/applications"
cp "$icon" "$data/icons/hicolor/scalable/apps/io.github.ssjrocks.UsbMonitor.svg"
cat > "$data/applications/io.github.ssjrocks.UsbMonitor.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=USB Monitor
Comment=Live monitor for connected USB devices
Exec=$venv/bin/usb-monitor
Icon=io.github.ssjrocks.UsbMonitor
Terminal=false
Categories=Development;Utility;
DESKTOP
update-desktop-database -q "$data/applications" 2>/dev/null || true
echo "Installed USB Monitor $(field version). Start it from the app menu or run $venv/bin/usb-monitor"
