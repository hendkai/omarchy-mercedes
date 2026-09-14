# Omarchy plugin: Mercedes SoC

Read-only Quickshell widget for [omarchy-mercedes](../README.md). Reads
`~/.local/state/omarchy-mercedes/status.json`; no network, login or tokens
in the bar process. The silver car-and-battery icon is original neutral vector
artwork released under the project's MIT license, not a manufacturer logo,
an emoji or a font dependency. This is an unofficial integration.

## Install / update

For marketplace installation, daemon setup, updates and removal, follow the
[repository README](../README.md#install-marketplace--native-omarchy). The root
manifest references this directory; Omarchy clones the whole repository but runs
**no installer hooks**. Do not run the legacy installer in that managed checkout.

For legacy standalone installations, `install.sh` ships the **entire directory**, including `SettingsPanel.qml`
and `assets/`, and generates a flattened manifest from the canonical root
manifest. A second checked-in manifest is intentionally absent: the marketplace
requires exactly one root manifest for new submissions. Existing plugin files are backed up. Reinstallation preserves
the first existing layout entry, all its settings and its position; accidental
duplicates are removed. Only a new registration is placed before the clock.
The installer does not start the connector or perform a login.

## Controls and appearance

- **Left click:** settings popup: position, percent/bar emphasis and range.
- **Right click:** `omarchy-mercedes status` in a terminal.
- **Hover:** data age, last sync, range, charging information and errors.
- **Percent:** numeric percentage only; no battery/progress bar.
- **Bar:** charge-level bar instead of the numeric percentage (exact value in tooltip).
- **Show range:** secondary range text; disabling it compacts the slot.
- **Stale after:** inline `staleAfterSec` setting (default 1800 seconds), also
  exposed in Omarchy's plugin schema.

Fresh: neutral foreground. Charging: accent color and `+`. Stale: amber and
`~`; old range is not presented as fresh. Error: `!`. No session: `!` with a localized sign-in hint in the tooltip. Offline: dimmed vehicle icon and `—`. Full explanations remain in the tooltip.

## Layout contract and verification

Omarchy allocates a ModuleSlot using the widget's `implicitWidth`; the
WidgetButton base normally measures only its own hidden/empty label, not
custom children. The widget explicitly reserves font-scaled content slots
plus horizontal padding, bounds/elides text and clips painting to its slot.
Widths do not change as connection state or charge level changes. A vertical
bar uses a compact stack; range remains available in its tooltip.

## Language

The widget, popup and tooltip follow `Qt.locale()` (operating-system locale),
including numeric/date formatting. Bundled catalogs: de, en, fr, es, it, pt,
nl, pl, cs, da, sv, nb, fi, tr, uk, ru, ja, ko, zh, ar. Regional locales fall
back to their base language, then English; `no` maps to `nb`. Arabic uses
Qt layout mirroring. These are 20 catalogs, **not every world language**;
regional wording variants and native-speaker review remain future work.
Add a complete row to `I18n.js` to extend coverage. CLI/backend diagnostics
and Omarchy-owned manifest metadata are not translated by this widget; no
vehicle data is sent to a translation service. Units `km` and `kW` are SI.

Plugin hot reload can retain an old QML component even when disk files have
changed. Do not infer success from file copies or a "reloading" log line.
Read actual layout geometry:

```sh
quickshell ipc -p /usr/share/omarchy/shell call shell debugBarGeometry
```

If geometry still shows the old slot, restart the shell (briefly hides bar
and popups; does not restart the vehicle connector):

```sh
quickshell kill -p /usr/share/omarchy/shell
quickshell -d -n -p /usr/share/omarchy/shell
```

Check the **new instance's** log path printed on launch for plugin errors.

## Tests (no real keyring writes)

From the repo root:

```sh
PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring python -m unittest discover -s tests -v
```

Qt regression tests use the installed Omarchy `WidgetButton`, `BarWidget`,
`Panel` and `PanelController` with stubbed file IO/theme/Wayland surfaces.
They cover content bounds next to a Monday clock, state-stable widths,
font sizes, range modes, charging/stale state and popup settings wiring.
A width-removal mutation must fail, proving the overlap test is red-capable.
Requires `/usr/lib/qt6/bin/qmltestrunner` (or one on PATH) and Omarchy;
otherwise that test is explicitly skipped. Installer tests run only the
actual plugin block in temporary HOME directories, twice, never pip/systemd.
