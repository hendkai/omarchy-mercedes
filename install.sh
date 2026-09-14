#!/usr/bin/env bash
# omarchy-mercedes installer (user-space, no root required).
#
# Installs:
#   - Python package -> ~/.local/lib/omarchy-mercedes (pip --user)
#   - CLI wrapper    -> ~/.local/bin/omarchy-mercedes
#   - Waybar script  -> ~/.local/bin/omarchy-mercedes-waybar
#   - systemd --user unit (daemon), enabled but NOT started (login first)
#   - Waybar config/style snippets -> backup + targeted include (if waybar cfg found)
#
# Backups: any modified file is copied to ~/.local/state/omarchy-mercedes/backup/<ts>/
# Rollback: ./uninstall.sh restores those backups.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_DIR="$HOME/.local/state/omarchy-mercedes"
BACKUP_DIR="$STATE_DIR/backup/$(date +%Y%m%d-%H%M%S)"
BIN_DIR="$HOME/.local/bin"
DATA_DIR="$HOME/.local/share/omarchy-mercedes"

log() { printf '\033[1;32m[install]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n' "$*" >&2; }
die() { printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; exit 1; }

backup_file() {
    local f="$1"
    if [[ -f "$f" ]]; then
        mkdir -p "$BACKUP_DIR"
        cp -a "$f" "$BACKUP_DIR/"
        log "backed up $f -> $BACKUP_DIR/"
    fi
}

[[ -f "$REPO_DIR/pyproject.toml" ]] || die "run from the repository root (pyproject.toml not found)"
command -v python3 >/dev/null || die "python3 not found"

mkdir -p "$BIN_DIR" "$DATA_DIR" "$STATE_DIR"
chmod 700 "$DATA_DIR"

# 1. Python package (user space). --break-system-packages for PEP 668 distros.
log "installing python package (user) ..."
if ! python3 -m pip install --user "$REPO_DIR" 2>/dev/null; then
    python3 -m pip install --user --break-system-packages "$REPO_DIR"
fi

# 2. Wrappers (pin the interpreter the package was installed for, so an
#    activated venv in the user's shell cannot shadow the system install)
log "installing wrappers to $BIN_DIR ..."
PY_BIN="$(command -v python3)"
cat > "$BIN_DIR/omarchy-mercedes" <<EOF
#!/usr/bin/env bash
exec $PY_BIN -m omarchy_mercedes.cli "\$@"
EOF
cat > "$BIN_DIR/omarchy-mercedes-waybar" <<EOF
#!/usr/bin/env bash
# Waybar custom module entrypoint: reads the local status cache only.
exec $PY_BIN -m omarchy_mercedes.waybar_module --timezone "\${OMARCHY_MERCEDES_TZ:-Europe/Berlin}" "\$@"
EOF
chmod +x "$BIN_DIR/omarchy-mercedes" "$BIN_DIR/omarchy-mercedes-waybar"

# 3. systemd --user unit
if command -v systemctl >/dev/null && systemctl --user >/dev/null 2>&1; then
    log "installing systemd --user unit ..."
    UDIR="$HOME/.config/systemd/user"
    mkdir -p "$UDIR"
    backup_file "$UDIR/omarchy-mercedes.service"
    sed "s|%h|$HOME|g" "$REPO_DIR/systemd/omarchy-mercedes.service" > "$UDIR/omarchy-mercedes.service"
    systemctl --user daemon-reload
    systemctl --user enable omarchy-mercedes.service >/dev/null 2>&1 || warn "could not enable unit"
else
    warn "systemd --user unavailable; start the daemon manually (see README)"
fi

# 4. Waybar config (backup + targeted include)
WAYBAR_CFG="$HOME/.config/waybar/config"
WAYBAR_CFG_JSONC="$HOME/.config/waybar/config.jsonc"
if command -v waybar >/dev/null; then
    if [[ -f "$WAYBAR_CFG" || -f "$WAYBAR_CFG_JSONC" ]]; then
        CFG="${WAYBAR_CFG_JSONC:-$WAYBAR_CFG}"
        # Omarchy standard layout: ~/.config/waybar/config.d/ includes
        if [[ -d "$HOME/.config/waybar/config.d" ]]; then
            log "installing waybar config snippet (config.d) ..."
            cp "$REPO_DIR/waybar/config.d/mercedes.jsonc" "$HOME/.config/waybar/config.d/mercedes.jsonc"
        else
            log "waybar config found at $CFG - adding module include manually"
            warn "automatisches Einbinden nicht moeglich: bitte 'custom/mercedes' aus"
            warn "waybar/config.d/mercedes.jsonc manuell in $CFG ergaenzen."
            backup_file "$CFG"
            cp "$REPO_DIR/waybar/config.d/mercedes.jsonc" "$HOME/.config/waybar/mercedes.jsonc"
        fi
        # styles
        if [[ -d "$HOME/.config/waybar/style.d" ]]; then
            cp "$REPO_DIR/waybar/style.d/mercedes.css" "$HOME/.config/waybar/style.d/mercedes.css"
        elif [[ -f "$HOME/.config/waybar/style.css" ]]; then
            backup_file "$HOME/.config/waybar/style.css"
            { echo ""; echo "/* omarchy-mercedes (appended by installer) */"; cat "$REPO_DIR/waybar/style.d/mercedes.css"; } \
                >> "$HOME/.config/waybar/style.css"
            log "styles appended to style.css (backup created)"
        fi
    else
        warn "keine waybar-config gefunden; snippets liegen im Repo unter waybar/"
    fi
else
    warn "waybar nicht gefunden (ok auf anderen Hosts); snippets liegen unter waybar/"
fi

# 5. Omarchy shell plugin (Quickshell bar; no Waybar required)
if [[ -d "$HOME/.config/omarchy" ]]; then
    log "installing Omarchy bar plugin ..."
    PLUG_DIR="$HOME/.config/omarchy/plugins/hendkai.omarchy-mercedes"
    if [[ -d "$PLUG_DIR" ]]; then
        mkdir -p "$BACKUP_DIR"
        cp -a "$PLUG_DIR" "$BACKUP_DIR/plugin-$(date +%s%N)"
    fi
    mkdir -p "$PLUG_DIR"
    # Ship the full bundle, including the settings popup and vector assets.
    cp -a "$REPO_DIR/omarchy-plugin/." "$PLUG_DIR/"
    # register the widget in shell.json (center, before the clock) — idempotent
    /usr/bin/python3 - "$HOME/.config/omarchy/shell.json" <<'PYEOF' || warn "konnte shell.json nicht anpassen - bitte Widget manuell ergaenzen"
import json, sys, shutil, time

import os, tempfile
path = sys.argv[1]
with open(path) as f:
    d = json.load(f)
original = json.dumps(d, sort_keys=True)
layout = d.setdefault("bar", {}).setdefault("layout", {})
plugin_id = "hendkai.omarchy-mercedes"
found = False
for section in ("left", "center", "right"):
    if section not in layout:
        continue
    kept = []
    for entry in layout[section]:
        if entry.get("id") == plugin_id:
            if found:
                continue
            found = True
        kept.append(entry)
    layout[section] = kept
if not found:
    center = layout.setdefault("center", [])
    clock_idx = next((i for i, x in enumerate(center)
                      if x.get("id") == "omarchy.clock"), len(center))
    center.insert(clock_idx, {"id": plugin_id})
if json.dumps(d, sort_keys=True) != original:
    shutil.copy2(path, path + ".omarchy-mercedes-bak-" + str(time.time_ns()))
    fd, temporary = tempfile.mkstemp(prefix=".shell-mercedes-", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(d, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.chmod(temporary, os.stat(path).st_mode & 0o777)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
print("shell.json: widget registered (existing settings and position preserved)")
PYEOF
    echo "  -> Omarchy-Shell laedt das Plugin automatisch neu (hot reload)."
else
    log "kein Omarchy; Waybar-Snippets liegen unter waybar/ (weiter aktiv)"
fi

log "fertig."
echo
echo "Naechste Schritte:"
echo "  1. omarchy-mercedes doctor"
echo "  2. omarchy-mercedes login          # interaktiv, einmalig"
echo "  3. systemctl --user start omarchy-mercedes"
echo "  4. waybar neu starten (Modul 'custom/mercedes')"
echo
echo "Deinstallation/Rollback: $REPO_DIR/uninstall.sh"
