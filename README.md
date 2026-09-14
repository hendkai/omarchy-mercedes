# omarchy-mercedes

Ladezustand (State of Charge) deines Mercedes EQ (und anderer Mercedes-Benz
Fahrzeuge mit Mercedes me connect) direkt in der **Omarchy/Waybar-Taskleiste** —
ohne Home Assistant, ohne Cloud-Dienstleister dazwischen.

```
🚗 82%          🔌 82%          🚗 82% (?)       🚗 Anmeldung erforderlich
```

- **Read-only**: Das Modul enthält keinerlei Fahrzeug-Befehle (kein Lock,
  kein KlimaN, kein Wakeup). Nur Lesen von Ladestand, Reichweite, Lade­
  status, Ladeleistung.
- **Ehrlich bei alten Daten**: Verbindungsfrische und Fahrzeugdaten-Alter
  werden getrennt ausgewiesen. Alte Fahrzeugdaten werden nie als aktuell
  dargestellt (eigenes `stale`-Styling + Alter im Tooltip).
- **Keine Secrets in Waybar**: Der Waybar-Prozess liest nur eine lokale
  Status-Datei. Login, Tokens und Netzwerk liegen in einem getrennten
  Connector-Daemon (systemd `--user`).

> **Wichtiger Hinweis**: Dieses Projekt nutzt die inoffizielle
> Mercedes-Benz Mobile-SDK-API (dieselbe, die auch die beliebte
> Home-Assistant-Integration `mbapi2020` verwendet). Sie ist nicht
> offiziell dokumentiert und kann sich jederzeit ändern oder (selten)
> Konten blockieren. Mercedes-Logos werden nicht verwendet; dies ist keine
> offizielle Mercedes-Benz-App. Ein offizieller "Car Connect"-Zugang mit
> eigenen API-Credentials ist für Privatkonten derzeit nicht verfügbar
> (Developer-Programm für BYOCAR-Pools eingestellt).

## Wie es funktioniert

```
Mercedes CIAM (id.mercedes-benz.com)  ──OAuth2/PKCE──▶  omarchy-mercedes login
                                                            │ Tokens (0600/Keyring)
                                                            ▼
              widget/v1/vehicleattributes (protobuf) ◀── Connector-Daemon
                                                            │ redigierter Status
                                                            ▼
                                        ~/.local/state/omarchy-mercedes/status.json
                                                            │ nur Lesezugriff
                                                            ▼
                                              Waybar-Modul `custom/mercedes`
```

## Installation (Omarchy / Arch / jede Waybar-Distro)

```bash
git clone https://github.com/hendkai/omarchy-mercedes.git
cd omarchy-mercedes
./install.sh
```

Der Installer installiert als Benutzer (kein root): Python-Paket, Wrapper in
`~/.local/bin`, systemd-`--user`-Unit, Waybar-Snippets. Vorhandene Waybar-
Konfiguration wird gesichert und nur gezielt ergänzt (`config.d/`-Snippet bzw.
Backup + Hinweis). Rollback: `./uninstall.sh`.

Abhängigkeiten: `python3` (≥ 3.9), `requests`, `protobuf` (>= 4.25),
optional `keyring` (Secret Service). Der Installer installiert das Paket per
`pip --user` (auf PEP-668-Distros automatisch mit `--break-system-packages`).

## Ersteinrichtung (einmalig, interaktiv)

```bash
omarchy-mercedes doctor    # prüft python/protobuf/requests/keyring/waybar
omarchy-mercedes login     # Browser-Login bei Mercedes (unterstützt 2FA)
```

Beim Login öffnet sich die Mercedes-Anmeldeseite im Browser. Nach der Anmeldung
leitet Mercedes auf `rismycar://login-callback?code=…` um. Unter Linux/Omarchy
registriert der Login dafür temporär einen System-Handler für `rismycar://`, der
die Rückleitung automatisch an das laufende Terminal übergibt (ein vorhandener
Handler wird vorher gefragt und danach wiederhergestellt; der Browser-Dialog
„Open With…“ ist in dieser Phase also kein Fehler). Klappt die automatische
Übergabe nicht, bleibt der manuelle Fallback: die **komplette Callback-Adresse**
`rismycar://login-callback?code=…` **oder nur der Wert nach `code=`** wird im
Terminal eingefügt (verdeckt, ohne Echo). 

Wichtig und ehrlich: Die Adresse in der Adressleiste ist **nicht zu jedem
Zeitpunkt** die richtige Weiterleitung. Die Anmelde-**Startseite**
(`https://id.mercedes-benz.com/as/authorization.oauth2?…`) ist **kein** Callback
und wird vom Tool ausdrücklich abgelehnt — steht sie noch in der Adressleiste,
wurde die Anmeldung im Browser nicht (erfolgreich) abgeschlossen. Zeigt der
Browser „No apps installed that can open …“, muss **nicht** im Store nach einer
App gesucht werden: Eingabe im Terminal ist der Weg. Alternativ funktioniert der
rein headless Passwort-Flow (`omarchy-mercedes login --password`), wenn für das
Konto **keine** 2FA aktiviert ist; bei OTP-Pflicht verweist das Tool auf den
Browser-Flow.

**Status: experimentell.** Ein echter Mercedes-Login/2FA-Ablauf wurde von uns
nur teilweise verifiziert (keine Kontodaten in der CI); der automatische
Callback-Handoff ist standardmäßig aktiv, sein Zustandekommen hängt vom
Desktop/Browser ab. Rückmeldung aus realen Logins ist willkommen.

```bash
systemctl --user start --now omarchy-mercedes   # Connector-Daemon
omarchy-mercedes status                         # Kontrolle
# Waybar neu starten / neu laden — fertig.
```

Zeitzone für die Tooltip-Zeiten: standardmäßig `Europe/Berlin`
(`OMARCHY_MERCEDES_TZ` überschreiben oder `--timezone` am Waybar-Skript).

## Modul-Stati

| Anzeige              | class        | Bedeutung                                              |
|----------------------|--------------|--------------------------------------------------------|
| 🚗 82%               | `ok`         | Daten frisch                                           |
| 🔌 82% (grün)        | `charging`   | Ladevorgang aktiv                                      |
| 🚗 82% (?) (amber)   | `stale`      | Verbindung ok, Fahrzeugdaten älter als 30 min          |
| 🚗 offline (rot)     | `offline`    | Connector liefert nichts (Daemon/Netz)                 |
| 🚗 Anmeldung … (rot) | `no-session` | Login nötig (Token widerrufen/abgelaufen)              |
| 🚗 ! (rot)           | `error`      | API-/Netzfehler (Hinweis im Tooltip)                   |

Der Tooltip zeigt Reichweite, Ladeleistung, Ladeende, **Fahrzeugdaten-
Zeitpunkt mit Alter** und den letzten erfolgreichen Abgleich.

## Konfiguration

Meist ist nichts zu konfigurieren. Optionen:

- `omarchy-mercedes daemon --region eu|na|apac|cn` (Standard `eu`)
- `--vin WDD…` — bei mehreren Fahrzeugen gezielt auswählen
  (Standard: erstes Fahrzeug des Kontos; `omarchy-mercedes vehicles` zeigt alle)
- `--poll-interval` Sekunden (Standard 300, Minimum 60; + Exponential-Backoff
  bei Fehlern). Wir lösen bewusst **keine Fahrzeug-Wakeups** aus und nutzen
  nur den Widget-Attribut-Endpoint (read-only).
- Waybar: `--stale-after` Sekunden (Standard 1800)

## Token-Sicherheit

- Refresh-/Access-Tokens liegen im Secret Service (keyring), wenn verfügbar;
  Fallback: `~/.local/share/omarchy-mercedes/session.json` mit `0600`.
- Tokens erscheinen nie im Repo, in Logs (Redaction vor jedem Log) oder im Chat.
- Bei widerrufener Session zeigt das Modul `Anmeldung erforderlich` — dann
  einfach erneut `omarchy-mercedes login`.
- "Einmal einloggen, für immer" können wir nicht garantieren: Mercedes kann
  Sessions jederzeit beenden oder Refresh-Rotation erzwingen (wird
  transparent behandelt).

## Deinstallation

```bash
./uninstall.sh        # inkl. Backup-Rollback der Waybar-Konfiguration
```

## Entwicklung & Tests

```bash
python3 -m pip install --user requests "protobuf>=4.25"
python3 -m unittest discover -s tests -v   # 33 Tests (alle synthetisch)
```

Alle Test-Fixtures sind **synthetisch** (fake VINs/Tokens, reale Protobuf-
Schema-Instanzen). Es gibt keine echten API-Aufrufe in den Tests. Ein
echter Smoke-Test gegen Mercedes erfordert Login-Daten und wird bewusst
NICHT in der CI ausgeführt: `omarchy-mercedes daemon --once` nach echtem
Login prüft den kompletten Pfad.

## Lizenz & Drittanbieter

MIT — siehe [LICENSE](LICENSE) und [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)
(vendored Protobuf-Module aus `mbapi2020`, MIT).

**Disclaimer**: Kein offizielles Mercedes-Benz-Produkt. Verwendung der
inoffiziellen API auf eigenes Risiko; der Autor steht in keiner Beziehung
zu Mercedes-Benz Group AG.
