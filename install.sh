#!/usr/bin/env bash
# omarchy-mercedes installer (user-space, no root required).
#
# Language: interactive picker first (Deutsch / English); Enter defaults to
# German. Non-interactive: ./install.sh --lang de|en. Without a TTY the
# installer never blocks: English default + hint about --lang.
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

# ---------------------------------------------------------------------------
# i18n: LANG_CODE is "de" or "en"; resolved before any user-facing output.
# All strings are ASCII-safe German (works in C locales, like the original).
# ---------------------------------------------------------------------------

LANG_CODE=""

lang_text() { # lang_text <key> [lang] -> print the string for the given language
    local key="$1" l="${2:-$LANG_CODE}" de en
    case "$key" in
        usage)              de="Verwendung: ./install.sh [OPTIONEN]";                                     en="Usage: ./install.sh [OPTIONS]" ;;
        usage_lang)         de="  --lang de|en   Installersprache: Deutsch oder Englisch";               en="  --lang de|en   installer language: German or English" ;;
        usage_default)      de="                  (ohne Angabe: interaktive Auswahl, Enter = Deutsch)";   en="                  (default: interactive picker, Enter = German)" ;;
        usage_non_tty)      de="  Ohne Terminal: Englisch (kein Warten auf Eingabe); --lang ueberschreibt."; en="  Without a terminal: English (no input wait); override with --lang." ;;
        err_install)        de="Installation fehlgeschlagen (Exit-Code %s); technische Diagnose siehe oben."; en="Installation failed (exit code %s); see technical diagnostics above." ;;
        usage_help)         de="  -h, --help     diese Hilfe anzeigen und beenden";                       en="  -h, --help     show this help and exit" ;;
        err_prefix)         de="[Fehler]";                                                              en="[error]" ;;
        err_unknown_arg)    de="Unbekanntes Argument: %s";                                               en="Unknown argument: %s" ;;
        err_lang_value)     de="--lang erwartet einen Wert: de|en";                                      en="--lang requires a value: de|en" ;;
        err_unknown_lang)   de="Unbekannte Sprache: %s (erlaubt: de, en)";                               en="Unknown language: %s (allowed: de, en)" ;;
        err_help_hint)      de="Optionen anzeigen mit: ./install.sh --help";                             en="Show options with: ./install.sh --help" ;;
        err_lang_eof)       de="Keine Eingabe moeglich (EOF) - Installation abgebrochen.";               en="no input possible (EOF) - installation aborted." ;;
        err_not_repo)       de="Bitte aus dem Repository-Stammverzeichnis starten (pyproject.toml nicht gefunden)"; en="run from the repository root (pyproject.toml not found)" ;;
        err_no_python)      de="python3 nicht gefunden";                                                 en="python3 not found" ;;
        warn_prefix)        de="[Warnung]";                                                                en="[warn]" ;;
        install_prefix)     de="[Installation]";                                                             en="[install]" ;;
        non_tty_hint)       de="kein Terminal erkannt - Englisch wird verwendet; Sprache waehlbar mit: ./install.sh --lang de"; en="no terminal detected - using English; choose a language with: ./install.sh --lang de" ;;
        step_python)        de="installiere python-paket (benutzer) ...";                                en="installing python package (user) ..." ;;
        step_python_fb)     de="PEP-668-Distribution erkannt - nutze --break-system-packages";          en="PEP 668 distro detected - using --break-system-packages" ;;
        step_wrappers)      de="installiere wrapper in %s ...";                                          en="installing wrappers to %s ..." ;;
        step_unit)          de="installiere systemd --user unit ...";                                    en="installing systemd --user unit ..." ;;
        warn_unit_enable)   de="unit konnte nicht aktiviert werden";                                     en="could not enable unit" ;;
        warn_no_systemd)    de="systemd --user nicht verfuegbar; daemon manuell starten (siehe README)"; en="systemd --user unavailable; start the daemon manually (see README)" ;;
        step_cfgd)          de="installiere waybar-config-snippet (config.d) ...";                       en="installing waybar config snippet (config.d) ..." ;;
        step_cfg_manual)    de="waybar-config gefunden in %s - modul manuell einbinden";                 en="waybar config found at %s - manual module inclusion required" ;;
        warn_cfg_manual1)   de="automatisches Einbinden nicht moeglich: bitte 'custom/mercedes' aus";    en="automatic include not possible: please add 'custom/mercedes' from" ;;
        warn_cfg_manual2)   de="waybar/config.d/mercedes.jsonc manuell in %s ergaenzen.";                en="waybar/config.d/mercedes.jsonc manually to %s." ;;
        step_styles_append) de="styles an style.css angehaengt (backup erstellt)";                        en="styles appended to style.css (backup created)" ;;
        warn_no_waybar_cfg) de="keine waybar-config gefunden; snippets liegen im repo unter waybar/";    en="no waybar config found; snippets are in the repo under waybar/" ;;
        warn_no_waybar)     de="waybar nicht gefunden (ok auf anderen hosts); snippets liegen unter waybar/"; en="waybar not found (ok on other hosts); snippets are under waybar/" ;;
        msg_backed_up)      de="%s gesichert nach %s";                                                   en="backed up %s -> %s" ;;
        msg_done)           de="fertig.";                                                                en="done." ;;
        msg_next_title)     de="Naechste Schritte:";                                                     en="Next steps:" ;;
        msg_next1)          de="  1. omarchy-mercedes doctor";                                           en="  1. omarchy-mercedes doctor" ;;
        msg_next2)          de="  2. omarchy-mercedes login          # interaktiv, einmalig";           en="  2. omarchy-mercedes login          # interactive, one-time" ;;
        msg_next3)          de="  3. systemctl --user start omarchy-mercedes";                          en="  3. systemctl --user start omarchy-mercedes" ;;
        msg_next4)          de="  4. waybar neu starten (modul 'custom/mercedes')";                     en="  4. restart waybar (module 'custom/mercedes')" ;;
        msg_uninstall)      de="Deinstallation/Rollback: %s";                                            en="Uninstall/rollback: %s" ;;
        *)                  de="(fehler: unbekannte meldung %s)";                                        en="(error: unknown message %s)" ;;
    esac
    case "$l" in
        de) printf '%s' "$de" ;;
        *)  printf '%s' "$en" ;;
    esac
}

lang_fmt() { # lang_fmt <key> <args...> -> translated message, printf-formatted
    local key="$1"; shift
    # shellcheck disable=SC2059
    printf -- "$(lang_text "$key")\n" "$@"
}

die() { # die <message>
    printf '\033[1;31m%s\033[0m %s\n' "$(lang_text err_prefix)" "$*" >&2
    exit 1
}

warn() { # warn <message>
    printf '\033[1;33m%s\033[0m %s\n' "$(lang_text warn_prefix)" "$*" >&2
}

log() { # log <message>
    printf '\033[1;32m%s\033[0m %s\n' "$(lang_text install_prefix)" "$*"
}

# --- option parsing (errors use the language chosen so far, else English) ---

die_arg() { # die_arg <key> <args...>: translated error + --help hint, exit 1
    local key="$1"; shift
    LANG_CODE="${LANG_CODE:-en}"
    # shellcheck disable=SC2059
    printf -- '\033[1;31m%s\033[0m %s\n' "$(lang_text err_prefix)" "$(lang_fmt "$key" "$@")" >&2
    printf '%s\n' "$(lang_text err_help_hint)" >&2
    exit 1
}

SHOW_HELP="no"
INTERACTIVE="yes"
while [ $# -gt 0 ]; do
    case "$1" in
        --lang)
            [ $# -ge 2 ] || die_arg err_lang_value
            case "$2" in de|en) LANG_CODE="$2" ;; *) die_arg err_unknown_lang "$2" ;; esac
            shift 2 ;;
        --lang=*)
            case "${1#--lang=}" in de|en) LANG_CODE="${1#--lang=}" ;; *) die_arg err_unknown_lang "${1#--lang=}" ;; esac
            shift ;;
        -h|--help)
            SHOW_HELP="yes"; shift ;;
        *)
            die_arg err_unknown_arg "$1" ;;
    esac
done

# validate an explicitly chosen language before anything else
if [ -n "$LANG_CODE" ]; then
    case "$LANG_CODE" in
        de|en) INTERACTIVE="no" ;;
        *) die_arg err_unknown_lang "$LANG_CODE" ;;
    esac
fi

# --- help (after parsing so --lang is honored; never triggers the picker) ---

if [ "$SHOW_HELP" = "yes" ]; then
    if [ -z "$LANG_CODE" ]; then
        SHOW_HELP_LANGS="de en"   # plain --help: show both languages
    else
        SHOW_HELP_LANGS="$LANG_CODE"
    fi
    for l in $SHOW_HELP_LANGS; do
        printf '%s\n' "$(lang_text usage "$l")"
        printf '%s\n' "$(lang_text usage_lang "$l")"
        printf '%s\n' "$(lang_text usage_default "$l")"
        printf '%s\n' "$(lang_text usage_help "$l")"
        printf '%s\n' "$(lang_text usage_non_tty "$l")"
        if [ "$l" = "de" ]; then printf '\n'; fi
    done
    exit 0
fi

# --- interactive language picker (bilingual prompt, runs before LANG_CODE exists) ---

choose_language() {
    local raw lower
    while :; do
        printf '\033[1mSprache waehlen / Select language\033[0m\n'
        printf '  1) Deutsch    2) English  [1]: '
        if ! IFS= read -r raw; then
            # EOF (Ctrl-D): abort cleanly before anything was installed
            LANG_CODE="de"
            die "$(lang_text err_lang_eof) / $(LANG_CODE=en lang_text err_lang_eof)"
        fi
        lower="$(printf '%s' "$raw" | tr '[:upper:]' '[:lower:]')"
        case "$lower" in
            ""|1|de|deutsch)     LANG_CODE="de"; return 0 ;;
            2|en|english)        LANG_CODE="en"; return 0 ;;
            *)
                printf 'Ungueltige Auswahl "%s" - bitte 1 oder 2 eingeben / invalid choice, enter 1 or 2.\n' "$raw" >&2 ;;
        esac
    done
}

PICKER_USED="no"
if [ "$INTERACTIVE" = "yes" ]; then
    if [ -t 0 ] && [ -t 1 ]; then
        choose_language
        PICKER_USED="yes"
    else
        # no TTY and no --lang: never block, default to English
        LANG_CODE="en"
    fi
fi

# non-TTY without --lang: hint (in the effective language, English) about --lang
if [ "$INTERACTIVE" = "yes" ] && [ "$PICKER_USED" = "no" ]; then
    warn "$(lang_text non_tty_hint)"
fi

trap 'rc=$?; die "$(lang_fmt err_install "$rc")"' ERR
set -E

backup_file() {
    local f="$1"
    if [ -f "$f" ]; then
        mkdir -p "$BACKUP_DIR"
        cp -a "$f" "$BACKUP_DIR/"
        log "$(lang_fmt msg_backed_up "$f" "$BACKUP_DIR/")"
    fi
}

[ -f "$REPO_DIR/pyproject.toml" ] || die "$(lang_text err_not_repo)"
command -v python3 >/dev/null || die "$(lang_text err_no_python)"

mkdir -p "$BIN_DIR" "$DATA_DIR" "$STATE_DIR"
chmod 700 "$DATA_DIR"

# 1. Python package (user space). --break-system-packages for PEP 668 distros.
log "$(lang_text step_python)"
if ! python3 -m pip install --user "$REPO_DIR" 2>/dev/null; then
    warn "$(lang_text step_python_fb)"
    python3 -m pip install --user --break-system-packages "$REPO_DIR"
fi

# 2. Wrappers
log "$(lang_fmt step_wrappers "$BIN_DIR")"
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
    log "$(lang_text step_unit)"
    UDIR="$HOME/.config/systemd/user"
    mkdir -p "$UDIR"
    backup_file "$UDIR/omarchy-mercedes.service"
    sed "s|%h|$HOME|g" "$REPO_DIR/systemd/omarchy-mercedes.service" > "$UDIR/omarchy-mercedes.service"
    systemctl --user daemon-reload
    systemctl --user enable omarchy-mercedes.service >/dev/null 2>&1 || warn "$(lang_text warn_unit_enable)"
else
    warn "$(lang_text warn_no_systemd)"
fi

# 4. Waybar config (backup + targeted include)
WAYBAR_CFG="$HOME/.config/waybar/config"
WAYBAR_CFG_JSONC="$HOME/.config/waybar/config.jsonc"
if command -v waybar >/dev/null; then
    if [ -f "$WAYBAR_CFG" ] || [ -f "$WAYBAR_CFG_JSONC" ]; then
        CFG="${WAYBAR_CFG_JSONC:-$WAYBAR_CFG}"
        # Omarchy standard layout: ~/.config/waybar/config.d/ includes
        if [ -d "$HOME/.config/waybar/config.d" ]; then
            log "$(lang_text step_cfgd)"
            cp "$REPO_DIR/waybar/config.d/mercedes.jsonc" "$HOME/.config/waybar/config.d/mercedes.jsonc"
        else
            log "$(lang_fmt step_cfg_manual "$CFG")"
            warn "$(lang_text warn_cfg_manual1)"
            warn "$(lang_fmt warn_cfg_manual2 "$CFG")"
            backup_file "$CFG"
            cp "$REPO_DIR/waybar/config.d/mercedes.jsonc" "$HOME/.config/waybar/mercedes.jsonc"
        fi
        # styles
        if [ -d "$HOME/.config/waybar/style.d" ]; then
            cp "$REPO_DIR/waybar/style.d/mercedes.css" "$HOME/.config/waybar/style.d/mercedes.css"
        elif [ -f "$HOME/.config/waybar/style.css" ]; then
            backup_file "$HOME/.config/waybar/style.css"
            { echo ""; echo "/* omarchy-mercedes (appended by installer) */"; cat "$REPO_DIR/waybar/style.d/mercedes.css"; } \
                >> "$HOME/.config/waybar/style.css"
            log "$(lang_text step_styles_append)"
        fi
    else
        warn "$(lang_text warn_no_waybar_cfg)"
    fi
else
    warn "$(lang_text warn_no_waybar)"
fi

log "$(lang_text msg_done)"
echo
echo "$(lang_text msg_next_title)"
echo "$(lang_text msg_next1)"
echo "$(lang_text msg_next2)"
echo "$(lang_text msg_next3)"
echo "$(lang_text msg_next4)"
echo
echo "$(lang_fmt msg_uninstall "$REPO_DIR/uninstall.sh")"
