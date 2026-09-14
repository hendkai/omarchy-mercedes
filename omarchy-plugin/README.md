# Omarchy plugin: Mercedes SoC

Bar widget for [omarchy-mercedes](../README.md) on Omarchy's Quickshell bar
(no Waybar needed). Reads the connector daemon's redacted status cache at
`~/.local/state/omarchy-mercedes/status.json` — no network, no tokens in the
bar process.

## Install

The repo's `install.sh` copies this directory to
`~/.config/omarchy/plugins/hendkai.omarchy-mercedes/` and registers the
widget in `~/.config/omarchy/shell.json` (center, before the clock).

## Settings (right-click the bar → plugin settings)

- **Display mode** — percent (`🚗 55% · 233 km`) or battery bar
  (`🚗 ▮▮▮▮▮▮▯▯▯▯`)
- **Show range** — electric range next to the SoC
- **Stale after** — seconds before vehicle data is marked stale

Colors: green while charging (plug icon), amber `(?)` for stale data,
red for offline/error/no-session.
