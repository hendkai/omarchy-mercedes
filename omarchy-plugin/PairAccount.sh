#!/bin/sh
# Launched in a terminal by SettingsPanel.qml, never by an install hook.
set -u
case "${LC_ALL:-${LC_MESSAGES:-${LANG:-en}}}" in de*) german=1 ;; *) german=0 ;; esac
finish() {
    if [ "$german" -eq 1 ]; then printf '\nEnter zum Schließen ... '; else printf '\nPress Enter to close ... '; fi
    IFS= read -r ignored || true
}
# Desktop PATH need not contain ~/.local/bin. Never interpolate shell commands.
cli="$HOME/.local/bin/omarchy-mercedes"
if [ ! -x "$cli" ]; then cli=$(command -v omarchy-mercedes 2>/dev/null || true); fi
if [ -z "$cli" ]; then
    if [ "$german" -eq 1 ]; then
        printf 'Der Mercedes-Connector ist noch nicht installiert.\n'
        printf 'Das Omarchy-Plugin installiert nur die Anzeige.\n'
        printf 'Bitte zuerst den Connector nach README einrichten:\n'
    else
        printf 'The Mercedes connector is not installed.\n'
        printf 'The Omarchy plugin only installs the widget.\n'
        printf 'Install the connector using the README first:\n'
    fi
    printf '%s/../README.md\n' "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
    finish
    exit 127
fi
"$cli" login --browser
result=$?
if [ "$result" -eq 0 ]; then
    if [ "$german" -eq 1 ]; then printf '\nKopplung erfolgreich.\n'; else printf '\nPairing successful.\n'; fi
    if command -v systemctl >/dev/null 2>&1 && systemctl --user is-active --quiet omarchy-mercedes.service; then
        if ! systemctl --user try-restart omarchy-mercedes.service; then
            printf 'Connector restart failed; check systemctl --user status omarchy-mercedes.\n'
        fi
    else
        printf 'Connector: systemctl --user start omarchy-mercedes.service\n'
    fi
else
    if [ "$german" -eq 1 ]; then printf '\nKopplung fehlgeschlagen oder abgebrochen (Status %s).\n' "$result";
    else printf '\nPairing failed or cancelled (status %s).\n' "$result"; fi
fi
finish
exit "$result"
