# Mercedes SoC for Omarchy

A read-only Mercedes-Benz battery, electric range and charging-status widget for
Omarchy's **Quickshell bar**, with a separate local Python connector. No Home
Assistant is required. A legacy Waybar module is also included.

- Silver vector vehicle mark, percentage or charge-bar display, optional range.
- Left-click settings for placement and display; hover for freshness and charging
  details; right-click for CLI status in a terminal.
- Vehicle-data age and connection freshness are separate: a successful poll does
  not make old vehicle data fresh. Stale, offline and sign-in states are visible.
- Widget and settings follow the OS locale, with 20 bundled language catalogs and
  an English fallback. [Widget controls and language coverage](omarchy-plugin/README.md).
- No vehicle commands: no unlocking, climate control, charging control or wakeups.

> **Unofficial integration.** Not affiliated with, endorsed by, or supported by
> Mercedes-Benz Group AG or its subsidiaries. This uses an undocumented mobile
> API, informed by [mbapi2020](https://github.com/ReneNulschDE/mbapi2020), not an
> official developer API. API changes, session revocation and account restrictions
> are possible. Use only with an account and vehicle you are authorized to access,
> subject to Mercedes-Benz's terms. A marketplace listing is not a security review;
> Omarchy plugins run unsandboxed as your user.

## Prerequisites

- An Omarchy release with Quickshell shell plugins and `omarchy plugin` commands.
  The native widget does not require Waybar.
- Python **3.9+**, pip and venv support; `requests>=2.28` and `protobuf>=4.25`
  are installed into a dedicated virtual environment below. Optional
  `keyring>=24` needs a working, unlocked desktop Secret Service backend.
- A Mercedes account with a compatible connected vehicle and working connected
  services; internet access to Mercedes authentication/telemetry endpoints.
  Available fields vary by vehicle, account and region; compatibility is not
  guaranteed. Default region is `eu`; `na`, `apac` and `cn` are CLI options.
- A browser for **your own interactive login**, and systemd user services for
  background operation. Without systemd, run the daemon in a foreground terminal.

## Install (marketplace / native Omarchy)

**Adding the plugin installs only the widget repository. It does not install
Python dependencies, run `install.sh`, authenticate, or start the connector.**
Without a running, authenticated connector the widget has no live vehicle data.
Review the code before enabling it.

### 1. Add the widget

```sh
omarchy plugin add https://github.com/hendkai/omarchy-mercedes.git --enable
```

Omarchy asks for consent and placement. The repository root manifest loads
`omarchy-plugin/BarWidget.qml`; the adjacent panel, translations and assets remain
in that directory. Plugin ID: `hendkai.omarchy-mercedes`.

If you previously used `./install.sh`, first stop the connector and remove the
old **copied** widget with `omarchy plugin remove hendkai.omarchy-mercedes`.
Omarchy backs up non-git plugin folders. Then add the repository above. Do not run
`install.sh` inside a marketplace-managed checkout: its legacy copy layout is
different. Keep your account data; no new login is needed if the session is valid.

### 2. Explicitly install the connector

These commands install outside the managed checkout, so plugin removal cannot
silently delete the Python runtime. No root or `--break-system-packages` is used.
If any target below already exists, inspect it first: **do not overwrite an
existing executable, service unit or virtual environment without a backup and
your consent**. For an existing installation, follow [Update](#update) instead.

```sh
PLUGIN="$HOME/.config/omarchy/plugins/hendkai.omarchy-mercedes"
VENV="$HOME/.local/share/omarchy-mercedes-venv"
python3 -m venv "$VENV"
# Hash-verified, transitively pinned installs only (requirements.lock /
# build.lock committed in the plugin repo; see "Reproducible install").
"$VENV/bin/python" -m pip install --require-hashes -r "$PLUGIN/requirements.lock"
"$VENV/bin/python" -m pip install --no-deps --require-hashes -r "$PLUGIN/build.lock"
"$VENV/bin/python" -m pip install --no-build-isolation --no-deps "$PLUGIN"
mkdir -p "$HOME/.local/bin"
# Refuses to replace an existing CLI (no -f).
ln -s "$VENV/bin/omarchy-mercedes" "$HOME/.local/bin/omarchy-mercedes"
mkdir -p "$HOME/.local/share/omarchy-mercedes" "$HOME/.local/state/omarchy-mercedes"
chmod 700 "$HOME/.local/share/omarchy-mercedes" "$HOME/.local/state/omarchy-mercedes"
```

Ensure `~/.local/bin` is on your desktop session's `PATH` for right-click status.
A desktop keyring backend (`keyring==25.7.0`) is already part of the
hash-verified `requirements.lock` — no extra floating install is needed.

### 3. Log in yourself, then start the daemon

```sh
"$HOME/.local/bin/omarchy-mercedes" doctor
"$HOME/.local/bin/omarchy-mercedes" login
```

Complete the Mercedes browser login yourself, including any second factor. If
the browser cannot open the `rismycar://login-callback` redirect, follow the
local CLI prompt to paste the callback there. That URL contains a short-lived
credential: **never put it, passwords, codes or tokens in an issue or chat**.

For systemd, the following command refuses to overwrite an existing unit:

```sh
mkdir -p "$HOME/.config/systemd/user"
( set -C; cat "$HOME/.config/omarchy/plugins/hendkai.omarchy-mercedes/systemd/omarchy-mercedes.service" > "$HOME/.config/systemd/user/omarchy-mercedes.service" )
systemctl --user daemon-reload
systemctl --user enable --now omarchy-mercedes.service
"$HOME/.local/bin/omarchy-mercedes" status
```

The unit invokes `~/.local/bin/omarchy-mercedes`. For other regions or a selected
vehicle, use `systemctl --user edit omarchy-mercedes.service`, setting an empty
`ExecStart=` followed by your replacement under `[Service]`, for example
`ExecStart=%h/.local/bin/omarchy-mercedes daemon --region na`. Restart after edits.
`omarchy-mercedes vehicles` lists vehicles; `--vin` selects one (treat VINs as
private). Without an override the first account vehicle is selected.

Without systemd, run `~/.local/bin/omarchy-mercedes daemon --region eu` in a
terminal instead. Default polling interval is 300 seconds, minimum 60, with
backoff on errors. Consult `omarchy-mercedes daemon --help` for options.

## Update

The widget checkout and installed Python package are **separate**:

```sh
omarchy plugin update hendkai.omarchy-mercedes
# Review the changed code/release notes before updating the connector.
systemctl --user stop omarchy-mercedes.service
# Re-run the same locked, hash-verified steps as the initial install
"$HOME/.local/share/omarchy-mercedes-venv/bin/python" -m pip install --require-hashes -r "$HOME/.config/omarchy/plugins/hendkai.omarchy-mercedes/requirements.lock"
"$HOME/.local/share/omarchy-mercedes-venv/bin/python" -m pip install --no-deps --require-hashes -r "$HOME/.config/omarchy/plugins/hendkai.omarchy-mercedes/build.lock"
"$HOME/.local/share/omarchy-mercedes-venv/bin/python" -m pip install --no-build-isolation --no-deps --upgrade "$HOME/.config/omarchy/plugins/hendkai.omarchy-mercedes"
systemctl --user start omarchy-mercedes.service
"$HOME/.local/bin/omarchy-mercedes" status
```

An Omarchy plugin update does not run pip or migrate your service unit. If the
shipped service changes, review the diff and back up your installed unit before
explicitly replacing it and running `systemctl --user daemon-reload`. Existing
sessions are retained; log in again only when required. For a manually run daemon,
stop/restart that process instead of using systemctl. Keep the managed checkout
unmodified so Omarchy can update it safely.

## Remove

For the recommended installation above:

```sh
systemctl --user disable --now omarchy-mercedes.service
rm -- "$HOME/.config/systemd/user/omarchy-mercedes.service"
systemctl --user daemon-reload
omarchy plugin remove hendkai.omarchy-mercedes
# Remove only the CLI symlink and venv you created in the install steps.
rm -- "$HOME/.local/bin/omarchy-mercedes"
rm -r -- "$HOME/.local/share/omarchy-mercedes-venv"
```

If you added systemd overrides, review and remove the corresponding
`~/.config/systemd/user/omarchy-mercedes.service.d/` files too. If you did not
install the service, stop the foreground daemon and skip the systemctl/unit
steps. Omarchy handles widget disable/removal; other bar settings are not reset.
**Removing the widget alone does not stop or uninstall the daemon.**

Account data is retained by default. To erase it, first stop the daemon, then
explicitly delete `~/.local/share/omarchy-mercedes/` (file-backed session) and
`~/.local/state/omarchy-mercedes/` (status and installer backups). If a Secret
Service keyring was used, also remove the `omarchy-mercedes` / `session` credential
with your desktop password/keyring manager. Deleting files does not erase keyring
entries or revoke server-side sessions; use Mercedes account session controls
where available. Do not publish backups or status files.

## Privacy and security

```text
Your browser + Mercedes login -> local connector -> Mercedes telemetry API
                                      |
                                      v
                 ~/.local/state/omarchy-mercedes/status.json
                                      |
                                      v
                              Quickshell widget
```

The widget reads a local status cache; authentication and network requests live
in the separate connector. The project does not provide an intermediary cloud
service or analytics endpoint. Mercedes receives authentication and telemetry
requests. Local status includes vehicle information and timestamps; even without
tokens, it is private. CLI vehicle listings and diagnostics can reveal identifying
data: inspect and redact before sharing.

Sessions use the desktop keyring when available, otherwise
`~/.local/share/omarchy-mercedes/session.json` with restricted file permissions
(`0600`). This fallback is a plaintext credential file, **not encryption**.
Protect your home directory and backups. Redaction is defense in depth, not a
reason to share raw logs. Mercedes can expire or revoke sessions at any time;
there is no guarantee of a permanent login.

## Legacy installer and Waybar

`./install.sh` is an alternative user-space installer, **not an Omarchy marketplace
hook**. Review it before running: it uses pip `--user` (retrying with
`--break-system-packages`), replaces CLI wrappers and the service unit, copies the
standalone `omarchy-plugin/` bundle, registers it in `shell.json`, and may modify
Waybar snippets/styles. It enables but does not immediately start the daemon.
It makes backups, but is not a general configuration transaction/rollback tool.
Prefer the isolated virtual-environment instructions above on modern Arch.

Do not mix the legacy installer and marketplace layout. For a legacy installation,
remove the widget with `omarchy plugin remove hendkai.omarchy-mercedes`, then run
`./uninstall.sh` from your source checkout. That script handles the old pip/user
wrappers/service and Waybar files, **not the native plugin**; its Waybar rollback
can restore older configuration, so back up current changes first. Its session
prompt only deletes file-backed data, not keyring credentials.

Waybar users can use the snippets under `waybar/` and the packaged
`omarchy-mercedes-waybar` entry point. Add `custom/mercedes` to the desired module
list and include its styles manually. The Waybar formatter defaults to
`Europe/Berlin`; `OMARCHY_MERCEDES_TZ` is honored by the legacy wrapper, or pass
`--timezone` directly to the formatter. The native widget uses the OS locale.

## Reproducible install

Every runtime and build dependency is transitively pinned and SHA-256
hash-verified: `requirements.lock` (incl. the keyring extra) and `build.lock`
(`setuptools==80.9.0`, `wheel==0.45.1`). `pyproject.toml` pins the build
system exactly (no `>=` ranges). All install paths — `install.sh`, README,
CI — use `--require-hashes` with `--no-build-isolation` and `--no-deps` from
the reviewed tree; nothing resolves at install time. Pin updates happen via a
new lockfile commit (uv pip compile), never on the user's machine.

## Development and verification

```sh
# In a development venv, not your account/session environment:
python -m pip install --require-hashes -r requirements.lock
python -m pip install --no-deps --require-hashes -r build.lock
python -m pip install --no-build-isolation --no-deps -e .
PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring python -m unittest discover -s tests -v
bash -n install.sh uninstall.sh tests/check_marketplace_setup.sh
bash tests/check_marketplace_setup.sh  # temporary HOME; downloads/builds dependencies
omarchy plugin validate .
```

Tests use synthetic fixtures and offline mocks; no real login or Mercedes API
smoke test runs in CI. Keep the null keyring override when testing locally.
Packaging checks enforce exactly one root manifest and real relative entry
points; legacy installer tests verify its generated flattened manifest. The installed Omarchy validator and Qt/Omarchy-dependent tests skip
explicitly when their runtime is unavailable; a generic Linux CI pass is not
proof of a live desktop rendering test. [Widget test details](omarchy-plugin/README.md).

## License, assets and affiliation

Project code is MIT licensed: [LICENSE](LICENSE). Vendored protobuf modules have
separate upstream notices in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md), which
also documents dependencies and the bundled neutral vehicle icon.

The silver [electric-vehicle.svg](omarchy-plugin/assets/electric-vehicle.svg) is
original neutral car-and-battery artwork created for this project and released
under the same MIT license. It contains no manufacturer logo or emblem and uses
no downloaded brand assets. Mercedes-Benz names and trademarks remain the
property of their respective owners; the MIT license grants **no trademark
rights**. This unofficial integration has no claimed affiliation or endorsement.
No private desktop screenshot is included as a marketplace preview.
