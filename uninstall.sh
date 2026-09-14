#!/usr/bin/env bash
# omarchy-mercedes uninstaller with rollback of installer backups.
set -euo pipefail

STATE_DIR="$HOME/.local/state/omarchy-mercedes"
BIN_DIR="$HOME/.local/bin"

log() { printf '\033[1;32m[uninstall]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n' "$*" >&2; }

# 0. stop service
if command -v systemctl >/dev/null && systemctl --user >/dev/null 2>&1; then
    systemctl --user disable --now omarchy-mercedes.service >/dev/null 2>&1 || true
    rm -f "$HOME/.config/systemd/user/omarchy-mercedes.service"
    systemctl --user daemon-reload || true
    log "systemd unit entfernt"
fi

# 1. binaries
rm -f "$BIN_DIR/omarchy-mercedes" "$BIN_DIR/omarchy-mercedes-waybar"
log "wrapper entfernt"

# 2. python package
python3 -m pip uninstall -y omarchy-mercedes >/dev/null 2>&1 \
  || python3 -m pip uninstall -y --break-system-packages omarchy-mercedes >/dev/null 2>&1 \
  || warn "pip uninstall fehlgeschlagen (manuell entfernen)"
log "python package entfernt"

# 3. waybar snippets + style.css rollback
rm -f "$HOME/.config/waybar/config.d/mercedes.jsonc" "$HOME/.config/waybar/mercedes.jsonc" \
      "$HOME/.config/waybar/style.d/mercedes.css"
LATEST_BACKUP="$(ls -1dt "$STATE_DIR"/backup/* 2>/dev/null | head -1 || true)"
if [[ -n "$LATEST_BACKUP" ]]; then
    for f in "$LATEST_BACKUP"/*; do
        name="$(basename "$f")"
        case "$name" in
            style.css|config|config.jsonc)
                cp -a "$f" "$HOME/.config/waybar/$name"
                log "rollback: $name wiederhergestellt"
                ;;
        esac
    done
fi

# 4. ask before deleting session/status (keep by default)
echo "Session (Tokens) und Statuscache belassen? [J/n]"
read -r ans
if [[ "${ans:-J}" == "n" ]]; then
    rm -rf "$HOME/.local/share/omarchy-mercedes" "$STATE_DIR"
    log "session + status geloescht"
else
    log "session + status behalten (~/.local/share/omarchy-mercedes)"
fi

log "fertig. waybar ggf. neu starten."
