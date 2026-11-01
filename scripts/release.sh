#!/usr/bin/env bash
# Publishes a GitHub release with the wheel and usb-monitor.json (version, wheel name,
# SHA-256) for the in-app updater and scripts/install.sh.
#
# Usage: scripts/release.sh NOTES.md
# Bump the version in pyproject.toml and __init__.py and commit first.
set -euo pipefail
cd "$(dirname "$0")/.."
notes="${1:?usage: scripts/release.sh NOTES.md}"
[[ -f "$notes" ]] || { echo "no notes file: $notes" >&2; exit 2; }
version=$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml)
code_version=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' src/usb_monitor/__init__.py)
if [[ "$version" != "$code_version" ]]; then
  echo "version mismatch: pyproject.toml $version, __init__.py $code_version" >&2; exit 1
fi
if git rev-parse -q --verify "refs/tags/v$version" >/dev/null; then
  echo "tag v$version already exists" >&2; exit 1
fi
if [[ -n "$(git status --porcelain)" ]]; then
  echo "commit your changes first" >&2; exit 1
fi
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
uv build -q --wheel --out-dir "$tmp"
wheel=$(cd "$tmp" && ls usb_monitor-"$version"-*.whl)
sha=$(sha256sum "$tmp/$wheel" | cut -d' ' -f1)
printf '{"version": "%s", "wheel": "%s", "sha256": "%s"}\n' "$version" "$wheel" "$sha" > "$tmp/usb-monitor.json"
git tag -a "v$version" -m "USB Monitor $version"
git push origin HEAD "v$version"
gh release create "v$version" "$tmp/$wheel" "$tmp/usb-monitor.json" \
  --title "USB Monitor $version" --notes-file "$notes" --verify-tag
echo "released USB Monitor $version ($wheel, sha256 $sha)"
