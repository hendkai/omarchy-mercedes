#!/usr/bin/env bash
# Exercise the README's venv setup outside the source tree. No desktop IPC,
# login, credential lookup, daemon, systemctl, or live configuration writes.
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEST_ROOT="$(mktemp -d)"
trap 'rm -rf -- "$TEST_ROOT"' EXIT
export HOME="$TEST_ROOT/home"
export XDG_DATA_HOME="$HOME/.local/share"
export XDG_STATE_HOME="$HOME/.local/state"
export XDG_CONFIG_HOME="$HOME/.config"
export PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring
unset DBUS_SESSION_BUS_ADDRESS
PLUGIN="$HOME/.config/omarchy/plugins/hendkai.omarchy-mercedes"
VENV="$HOME/.local/share/omarchy-mercedes-venv"
mkdir -p "$PLUGIN"
# Model the files in the marketplace checkout, including the root manifest.
for entry in manifest.json README.md LICENSE THIRD_PARTY_NOTICES.md pyproject.toml omarchy_mercedes omarchy-plugin systemd; do
    cp -a "$REPO/$entry" "$PLUGIN/"
done
python3 -m venv "$VENV"
"$VENV/bin/python" -m pip install "$PLUGIN"
mkdir -p "$HOME/.local/bin"
ln -s "$VENV/bin/omarchy-mercedes" "$HOME/.local/bin/omarchy-mercedes"
mkdir -p "$HOME/.local/share/omarchy-mercedes" "$HOME/.local/state/omarchy-mercedes"
chmod 700 "$HOME/.local/share/omarchy-mercedes" "$HOME/.local/state/omarchy-mercedes"
mkdir -p "$HOME/.config/systemd/user"
( set -C; cat "$PLUGIN/systemd/omarchy-mercedes.service" > "$HOME/.config/systemd/user/omarchy-mercedes.service" )
# Both installation operations must refuse to replace existing user files.
if ln -s "$VENV/bin/omarchy-mercedes" "$HOME/.local/bin/omarchy-mercedes" 2>/dev/null; then
    printf 'ERROR: CLI overwrite was not refused\n' >&2; exit 1
fi
if ( set -C; cat "$PLUGIN/systemd/omarchy-mercedes.service" > "$HOME/.config/systemd/user/omarchy-mercedes.service" ) 2>/dev/null; then
    printf 'ERROR: service overwrite was not refused\n' >&2; exit 1
fi
# Change directory so imports cannot accidentally come from the original repo.
cd "$TEST_ROOT"
"$HOME/.local/bin/omarchy-mercedes" --version
"$VENV/bin/python" -c 'import omarchy_mercedes, os; assert omarchy_mercedes.__file__.startswith(os.environ["HOME"] + "/.local/share/omarchy-mercedes-venv/")'
"$VENV/bin/omarchy-mercedes-waybar" | "$VENV/bin/python" -c 'import json,sys; d=json.load(sys.stdin); assert "text" in d and "class" in d; print("Installed Waybar JSON: valid")'
# Updating the same version is still a real wheel build/install operation.
"$VENV/bin/python" -m pip install --upgrade "$PLUGIN"
# Preserve a synthetic session sentinel while removing code/runtime.
printf 'synthetic retained data\n' > "$HOME/.local/share/omarchy-mercedes/retention-test"
rm -- "$HOME/.config/systemd/user/omarchy-mercedes.service"
rm -r -- "$PLUGIN"
rm -- "$HOME/.local/bin/omarchy-mercedes"
rm -r -- "$VENV"
test ! -e "$HOME/.local/bin/omarchy-mercedes"
test ! -e "$VENV"
test -f "$HOME/.local/share/omarchy-mercedes/retention-test"
printf 'Marketplace venv setup/update/removal: PASS (temporary HOME, no services/login)\n'
