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

# 2. Wrappers
log "installing wrappers to $BIN_DIR ..."
cat > "$BIN_DIR/omarchy-mercedes" <<'EOF'
#!/usr/bin/env bash
exec python3 -m omarchy_mercedes.cli "$@"
EOF
cat > "$BIN_DIR/omarchy-mercedes-waybar" <<'EOF'
#!/usr/bin/env bash
# Waybar custom module entrypoint: reads the local status cache only.
exec python3 -m omarchy_mercedes.waybar_module --timezone "${OMARCHY_MERCEDES_TZ:-Europe/Berlin}" "$@"
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

log "fertig."
echo
echo "Naechste Schritte:"
echo "  1. omarchy-mercedes doctor"
echo "  2. omarchy-mercedes login          # interaktiv, einmalig"
echo "  3. systemctl --user start omarchy-mercedes"
echo "  4. waybar neu starten (Modul 'custom/mercedes')"
echo
echo "Deinstallation/Rollback: $REPO_DIR/uninstall.sh"
