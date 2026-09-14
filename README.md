# omarchy-mercedes

> **EXPERIMENTELL / TESTVERSION — kein verifizierter Mercedes-Live-Login oder
> 2FA-/Omarchy-GUI-Test.** Die automatisierten Auth-/Fahrzeugtests sind
> ausschließlich synthetisch. Eine grüne CI bestätigt keine funktionierende
> Anmeldung bei Mercedes. Liveprüfung übernimmt der Nutzer; keine stabile
> Freigabe behauptet.

Mercedes-Ladestand in der Omarchy/Waybar-Leiste, ohne Home Assistant als
Laufzeitabhängigkeit. Der Connector liest nur Account-Fahrzeugliste und
Widget-Telemetrie; keine Fahrzeugbefehle, kein Wakeup, keine Klima-/Schlosssteuerung.
Waybar liest ausschließlich den lokalen Cache, niemals Tokens oder Netzwerk.

Dieses inoffizielle Projekt verwendet die Mobile-SDK-Endpunkte, die auch
[mbapi2020](https://github.com/ReneNulschDE/mbapi2020) nutzt. Es ist nicht von
Mercedes-Benz unterstützt oder mit Mercedes-Benz Group AG verbunden. Endpunkte,
Anmeldebedingungen und Kontozugriff können sich ändern; Nutzung auf eigenes Risiko.
Wir machen keine Aussage über aktuelle Verfügbarkeit offizieller Developer-APIs.

## Installation

Voraussetzungen: Linux, Python ≥ 3.9 mit `venv` und pip, Internet für PyPI;
Waybar für die Anzeige und optional ein laufender systemd-Benutzermanager.
Auf Debian ist eventuell `python3-venv` nachzuinstallieren, auf Arch `python`
und `python-pip`. Der Installer arbeitet ohne root.

```bash
git clone https://github.com/hendkai/omarchy-mercedes.git
cd omarchy-mercedes
./install.sh
export PATH="$HOME/.local/bin:$PATH"
omarchy-mercedes doctor
```

Das Paket inklusive optionalem `keyring` wird in einer isolierten venv unter
`~/.local/share/omarchy-mercedes/venv` installiert. Keine System-/User-pip-
Installation und kein `--break-system-packages`-Fallback. Bei pip-/venv-Fehlern
stoppt der Installer mit Fehlerstatus. PATH dauerhaft in der Shell ergänzen.

Der Installer:

- installiert Wrapper unter `~/.local/bin` und eine systemd-`--user`-Unit;
- aktiviert/startet den Dienst **nicht** automatisch; ein eigener aktiver Dienst
  wird vor einer Neuinstallation gestoppt und muss danach neu gestartet werden;
- integriert `custom/mercedes` direkt in `modules-right` und als Moduldefinition
  der vorhandenen monolithischen `~/.config/waybar/config.jsonc` (sonst `config`);
- erhält Kommentare/unbeteiligte JSONC-Abschnitte, ergänzt CSS und kopiert Snippets;
- verändert ohne vorhandene Hauptkonfiguration keine Waybar-Dateien;
- sichert Originalinhalt/Modus und eigene Ziel-Hashes vor dem Schreiben im privaten
  `~/.local/state/omarchy-mercedes/install-manifest.json`.

Neuinstallation ist idempotent. Vorhandene gleichnamige Wrapper/Unit/Snippets
werden gesichert und beim Uninstall wiederhergestellt. Wurde eine verwaltete
Datei zwischenzeitlich vom Nutzer geändert, bricht Reinstall/Uninstall ab,
**ohne sie zu überschreiben oder zu löschen**. Der Manifest-Backup bleibt zur
bewussten manuellen Zusammenführung erhalten. Ein alter Pre-Manifest-Installer
wird nicht blind migriert. Symlinks und unklare JSONC-Formen (mehrere Bars als
Array, doppelte Schlüssel, fehlendes `modules-right`) werden sicher abgelehnt.
Installer unterstützen nur Standard-HOME-Pfade; benutzerdefinierte
`OMARCHY_MERCEDES_DATA_DIR`/`OMARCHY_MERCEDES_STATE_DIR` dafür vorher entfernen.

## Anmeldung (experimentell)

```bash
omarchy-mercedes login                 # Browser + verdeckter manueller Callback
# oder URL selbst öffnen:
omarchy-mercedes login --no-open
```

Es existiert **kein Callback-Listener und kein registrierter xdg-Protokollhandler**.
Ein Desktop-Browser zeigt die `rismycar://`-Adresse oft NICHT in der Adressleiste.
Deshalb ist „Adresse einfach kopieren“ kein verlässlicher Weg.

Manueller Fallback für erfahrene Nutzer:

1. Auf der geöffneten Mercedes-Seite die Browser-Entwicklertools öffnen, Tab
   Netzwerk wählen, „Log beibehalten / Preserve log“ einschalten.
2. Die Anmeldung inklusive eventueller MFA ausschließlich bei Mercedes abschließen.
3. Die finale Redirect-Antwort auswählen, ihren `Location`-Header kopieren:
   `rismycar://login-callback?code=…&state=…`. Falls dieser Redirect nicht sichtbar
   ist oder Mercedes den Flow ablehnt: abbrechen. Es wird nichts umgangen.
4. Die vollständige Callback-URL innerhalb von 5 Minuten am **verdeckten
   Terminal-Prompt** einfügen. Kein Code auf der Befehlszeile, in Chat, Screenshot,
   HAR-Export oder Shell-History. Anschließend Clipboard und Netzwerkprotokoll löschen.

Die URL muss zum OAuth-`state` dieses Versuchs passen; PKCE bindet den Austausch.
Fehler beim Browserstart geben eine manuell zu öffnende Login-URL aus.
Timeout, EOF und Strg+C brechen ab. Ohne interaktives TTY wird nicht auf sichtbare
stdin-Eingabe zurückgefallen. Der Capture-/Austauschpfad wurde mit synthetischen
Callbacks/echtem PTY getestet, **nicht mit einem echten Mercedes-Konto**. Browser-
Version und Backend können diesen manuellen Fallback verhindern.

`omarchy-mercedes login --password` ist ein ebenfalls experimenteller CIAM-
Passwortflow. OTP-Pflicht/Legal-Consent werden als Fehler gemeldet; keine
MFA-/CAPTCHA-Umgehung und keine behauptete 2FA-Unterstützung.

```bash
systemctl --user enable --now omarchy-mercedes
omarchy-mercedes status
omarchy-mercedes daemon --once          # optional, echter Smoke nach Login
# Waybar danach über die Desktop-Umgebung neu laden.
```

Ohne systemd-Benutzermanager: `omarchy-mercedes daemon` im Terminal starten.
Diesen manuellen Prozess vor Deinstallation selbst beenden. Die User-Unit nutzt
`NoNewPrivileges` und private Umask; sie beansprucht keine ungetestete
Filesystem-Namespace-Isolation oder zusätzlichen Gruppenrechte.

## Zustände und Frische

| Anzeige | class | Bedeutung |
|---|---|---|
| 🚗 82% | `ok` | gültiger, frischer SoC |
| 🔌 82% | `charging` | SoC UND tatsächlicher Ladezustand frisch |
| 🚗 82% (?) | `stale` | SoC älter als 30 Minuten |
| 🚗 offline | `offline` | Cache fehlt, ist beschädigt oder lange nicht geschrieben |
| 🚗 Anmeldung erforderlich | `no-session` | keine Session für Region / widerrufene Session |
| 🚗 ! | `error` | API-/Netzfehler oder ungültige Messwerte |

Das Alter des **SoC-eigenen** Zeitstempels bestimmt die Prozent-Anzeige — frische
Reichweite macht alten SoC nicht frisch. Reichweite, Ladestatus, Ladeleistung und
Ladeende haben eigene Zeitstempel/Alter im Tooltip. Unbekannte/ungültige Werte
werden nicht als Messungen ausgegeben; alte Ladezustände färben die Leiste nicht
als aktiven Ladevorgang. Alte Cacheformate ohne SoC-Zeitstempel erfordern einen
neuen Poll. Alle Prozent-/Telemetriebeispiele hier sind synthetisch.

## Session und Optionen

- `login`, `vehicles` und `daemon` unterstützen `--region eu|na|apac|cn` (Default EU).
  Die Region der gespeicherten Session muss zum Dienst passen; Unit ggf. bewusst anpassen.
- `daemon --vin ...` wählt ein Fahrzeug, sonst das erste im Account. `vehicles`
  zeigt echte VINs nur lokal im Terminal; diese Ausgabe nicht veröffentlichen.
- `daemon --poll-interval 300` (Minimum 60 Sekunden), exponentieller begrenzter
  Backoff bei transienten Fehlern. Kein sofortiger Retry-Sturm.
- Access-/Refresh-Tokens bevorzugt im Keyring, ohne vorherige Klartextdatei.
  Fallback `~/.local/share/omarchy-mercedes/session.json`: atomar von Beginn an
  0600, private Verzeichnisse 0700. Ein neuer Fallback verdrängt einen alten
  Keyring-Eintrag unabhängig von dessen Ablaufdatum.
- Automatische Refresh-Rotation; höchstens ein Refresh je Poll, bei erneutem 401
  Anmeldung erforderlich. Netzwerk-/5xx-Fehler löschen keine Session.
- Laufender Daemon liest den Store vor jedem Poll neu. Login/Logout/Refresh
  werden über Prozesslock serialisiert; Logout wartet gegebenenfalls den laufenden
  HTTP-Poll ab. Nach Rückkehr kann kein alter In-Memory-Refresh die Session erneuern.
- `omarchy-mercedes logout` löscht beide Tokenstores und setzt sofort no-session.
  Ein secretfreier lokaler Logout-Marker verhindert alte Keyring-Sessions auch
  bei gesperrtem Keyring; fehlgeschlagene Keyring-Löschung wird **als Fehler** gemeldet.
  Keyring entsperren und Logout wiederholen, bevor das Paket entfernt wird.
- `daemon --once`: Exit 0 = auswertbare Messung (kann weiterhin `stale` sein!),
  1 = Daten-/API-/Netzfehler, 2 = keine gültige Session. Zusätzlich Tooltip/Alter prüfen.
- Waybar `--stale-after 1800`, `--timezone Europe/Berlin`, `--compact`.
  Wrapper-Zeitzone über `OMARCHY_MERCEDES_TZ`, ungültige Zeitzone fällt auf Systemzone zurück.

## Deinstallation

```bash
./uninstall.sh
```

Prompt „Session (Tokens) und Statuscache belassen? [J/n]“:
`J`/Enter behält **beide** Stores, `n` löscht Keyring- und Dateitokens, solange
CLI/Abhängigkeiten noch existieren und der User-Dienst gestoppt ist. Bei einem
Keyring-Fehler bleibt das Paket für einen Wiederholungsversuch erhalten. Keine
pauschale Löschung unbekannter Benutzerverzeichnisse. Originaldateien werden aus
dem Manifest wiederhergestellt; Nutzeränderungen erzwingen manuelle Klärung.

## Entwicklung und Testnachweise

```bash
python3 -m venv .venv
.venv/bin/pip install '.[keyring]'
.venv/bin/python -m unittest discover -s tests -v
bash -n install.sh uninstall.sh
# Linux, wegwerfbarer Testbenutzer empfohlen:
bash tools/verify_linux.sh
```

Alle Unit-/Session-/Auth-Fixtures sind synthetisch und verwenden keinen echten
Keyring. Der Linux-Runner installiert das echte Wheel in eine isolierte venv,
führt die öffentliche CLI außerhalb des Quellverzeichnisses aus und prüft
Kollisionen/Reinstall/Uninstall. Kein echter Mercedes-Aufruf. Details und Grenzen:
[docs/VERIFICATION.md](docs/VERIFICATION.md).

## Lizenz und KI-Mitwirkung

MIT, mit vollständigen upstream MIT- und gogoproto BSD-Notices in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) und im Wheel.
Entwicklungsprovenienz: [AI_CONTRIBUTION.md](AI_CONTRIBUTION.md).
Keine Runtime-KI, keine behauptete menschliche Codeprüfung oder rechtliche
Konformitätszertifizierung. Kein offizielles Mercedes-Benz-Produkt.
