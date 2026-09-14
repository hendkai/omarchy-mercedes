#!/usr/bin/env bash
# Run as an unprivileged user in a disposable Linux environment.
# Fixtures are SYNTHETIC; no Mercedes calls, no real credentials/keyring.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
export PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring
export HOME="$(mktemp -d)"
export PATH="$HOME/.local/bin:$PATH"
export XDG_RUNTIME_DIR="$HOME/runtime"
mkdir -m 700 "$XDG_RUNTIME_DIR"
mkdir -p "$HOME/.config/waybar/config.d" "$HOME/.config/waybar/style.d"
# Create collisions, including a monolithic JSONC config, without Waybar GUI.
python3 - "$HOME" <<'PY'
import json, sys
from pathlib import Path
home=Path(sys.argv[1]); wb=home/'.config/waybar'
(wb/'config.jsonc').write_text('{ // SYNTHETIC original\n "modules-right": ["clock",], "clock": {"format":"literal ,}"},\n}\n')
for name in ['config.d/mercedes.jsonc','style.d/mercedes.css','style.css']:
    (wb/name).write_text('/* SYNTHETIC ORIGINAL '+name+' */\n')
originals = {str(p.relative_to(home)):p.read_text() for p in wb.rglob('*') if p.is_file()}
for relative in ['.local/bin/omarchy-mercedes', '.local/bin/omarchy-mercedes-waybar', '.config/systemd/user/omarchy-mercedes.service']:
    path = home/relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('# SYNTHETIC ORIGINAL ' + relative + '\n')
    originals[relative] = path.read_text()
(home/'originals.json').write_text(json.dumps(originals))
PY
cd "$REPO"
python3 -m unittest discover -s tests -v
bash install.sh
cd /tmp  # installed CLI must not import from the source tree
omarchy-mercedes --version
omarchy-mercedes doctor
omarchy-mercedes status --json && exit 90 || test "$?" -eq 1
omarchy-mercedes vehicles && exit 91 || test "$?" -eq 2
omarchy-mercedes daemon --once && exit 92 || test "$?" -eq 2
omarchy-mercedes waybar | python3 -c 'import json,sys; assert json.load(sys.stdin)["class"] == "no-session"'
omarchy-mercedes-waybar | python3 -c 'import json,sys; assert json.load(sys.stdin)["class"] == "no-session"'
"$HOME/.local/share/omarchy-mercedes/venv/bin/python" -I -c 'import omarchy_mercedes; print("installed module:", omarchy_mercedes.__file__)'
if command -v systemd-analyze >/dev/null; then
    systemd-analyze --user verify "$HOME/.config/systemd/user/omarchy-mercedes.service"
    printf 'SYSTEMD_UNIT_VERIFY_OK\n'
fi
bash "$REPO/install.sh"  # idempotent real package reinstall
printf 'J\n' | bash "$REPO/uninstall.sh"
python3 - "$HOME" <<'PY'
import json, sys
from pathlib import Path
home=Path(sys.argv[1]); originals=json.loads((home/'originals.json').read_text())
assert all((home/p).read_text()==value for p,value in originals.items())
assert (home/'.local/bin/omarchy-mercedes').read_text().startswith('# SYNTHETIC ORIGINAL')
assert not (home/'.local/share/omarchy-mercedes/venv').exists()
assert (home/'.local/state/omarchy-mercedes/status.json').exists()
print('real reinstall + retain-uninstall: all original config/CSS restored')
PY
bash "$REPO/install.sh"
printf 'n\n' | bash "$REPO/uninstall.sh"
test ! -e "$HOME/.local/state/omarchy-mercedes/status.json"
test ! -e "$HOME/.local/share/omarchy-mercedes/session.json"
test ! -e "$HOME/.local/share/omarchy-mercedes/venv"
python3 - "$HOME" <<'PY'
import json, sys
from pathlib import Path
home=Path(sys.argv[1]); originals=json.loads((home/'originals.json').read_text())
assert all((home/p).read_text()==value for p,value in originals.items())
print('real delete-uninstall: file tokens/cache absent, original configs restored')
PY
printf 'LINUX_INSTALL_REGRESSIONS_OK\n'
