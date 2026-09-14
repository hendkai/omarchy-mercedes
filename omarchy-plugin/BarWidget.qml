// omarchy-mercedes bar widget — renders the connector daemon's status cache
// (~/.local/state/omarchy-mercedes/status.json). Pixels only: no network,
// no login, no tokens. The daemon (systemd --user) does all the talking to
// Mercedes; this widget just reads the redacted cache file.

import QtQuick
import Quickshell
import Quickshell.Io
import qs.Ui

BarWidget {
  id: root
  moduleName: "hendkai.omarchy-mercedes"

  readonly property color fg: bar ? bar.foreground : "#ffffff"
  readonly property color urgentColor: bar ? bar.urgent : "#f38ba8"
  readonly property color accent: bar && bar.accent !== undefined
    ? bar.accent : "#a6e3a1"

  property var status: null
  property bool resolved: false
  property real nowMs: Date.now()

  readonly property string statusPath:
    (Quickshell.env("HOME") || "")
    + "/.local/state/omarchy-mercedes/status.json"

  // --- settings -----------------------------------------------------------
  function setting(name, fallback) {
    var value = settings ? settings[name] : undefined
    return value === undefined || value === null ? fallback : value
  }
  readonly property real staleAfterSec: root.setting("staleAfterSec", 1800)
  readonly property bool showRange: root.setting("showRange", true)
  readonly property string displayMode: root.setting("displayMode", "percent")

  // --- soc helpers --------------------------------------------------------
  readonly property real socValue: {
    var soc = status && status.soc_percent
    return (typeof soc === "number") ? soc : -1
  }

  // --- state derivation (mirrors the python state.classify) --------------
  readonly property string connectionState: {
    if (!resolved) return "checking"
    if (!status) return "offline"
    var written = status.written_at_ms || 0
    if (!written) return "offline"
    if (nowMs - written > 3 * staleAfterSec * 1000) return "offline"
    return status.state || "error"
  }
  readonly property string displayState: {
    if (connectionState === "checking") return "checking"
    if (connectionState === "offline") return "offline"
    if (connectionState === "no-session") return "no-session"
    var ts = (status && status.vehicle_ts_ms) || 0
    if (connectionState === "ok") {
      if (!ts) return "error"
      if (nowMs - ts > staleAfterSec * 1000) return "stale"
      return "ok"
    }
    return "error"
  }
  readonly property bool charging:
    status && status.charging === true && displayState === "ok"

  // --- pixels -------------------------------------------------------------
  readonly property string icon: charging ? "🔌" : "🚗"
  readonly property string socText: {
    if (displayState === "checking") return "…"
    if (displayState === "no-session") return "Anmeldung …"
    if (displayState === "error") return "!"
    if (displayState === "offline") return "offline"
    if (socValue < 0) return "?"
    return Math.round(socValue) + "%"
  }
  readonly property string rangeText: {
    if (!showRange || displayState !== "ok") return ""
    var r = status && status.range_km
    if (r === null || r === undefined) return ""
    return " · " + Math.round(r) + " km"
  }
  readonly property bool showBar: displayMode === "bar"
    && (displayState === "ok" || displayState === "stale" || displayState === "error")
    && socValue >= 0
  readonly property color stateColor: {
    if (displayState === "checking") return Qt.alpha(fg, 0.5)
    if (displayState === "offline" || displayState === "error"
        || displayState === "no-session") return urgentColor
    if (displayState === "stale") return "#f9e2af"
    if (charging) return accent
    return fg
  }

  function fmtAge(ms) {
    if (!ms) return "keine Angabe"
    var s = Math.max(0, Math.floor((nowMs - ms) / 1000))
    if (s < 60) return s + " s"
    if (s < 3600) return Math.floor(s / 60) + " min"
    if (s < 86400) return Math.floor(s / 3600) + " h "
      + ("0" + Math.floor((s % 3600) / 60)).slice(-2) + " min"
    return Math.floor(s / 86400) + " d " + Math.floor((s % 86400) / 3600) + " h"
  }
  function fmtLocal(ms) {
    if (!ms) return "keine Angabe"
    return new Date(ms).toLocaleString(Qt.locale("de_DE"), "dd.MM. hh:mm")
  }

  function tooltip() {
    if (displayState === "checking") return "Mercedes — status wird gelesen"
    if (displayState === "no-session")
      return "Noch nicht eingeloggt.\nomarchy-mercedes login"
    if (displayState === "offline")
      return "Keine aktuellen Daten (Connector offline).\nomarchy-mercedes status für Details."
    var lines = []
    if (status.soc_percent !== null && status.soc_percent !== undefined)
      lines.push("Ladestand: " + Math.round(status.soc_percent) + "%")
    if (status.range_km !== null && status.range_km !== undefined)
      lines.push("Reichweite: " + Math.round(status.range_km) + " km")
    if (charging) {
      var line = "Ladevorgang aktiv"
      if (status.charging_power_kw)
        line += " (" + status.charging_power_kw + " kW)"
      lines.push(line)
      if (status.end_of_charge_time)
        lines.push("Ladeende: " + status.end_of_charge_time)
    }
    lines.push("Fahrzeugdaten: " + fmtLocal(status.vehicle_ts_ms)
      + " (vor " + fmtAge(status.vehicle_ts_ms) + ")")
    lines.push("Letzter Abgleich: " + fmtLocal(status.fetched_at_ms)
      + " (vor " + fmtAge(status.fetched_at_ms) + ")")
    if (displayState === "stale") lines.push("Fahrzeugdaten sind älter als "
      + Math.round(staleAfterSec / 60) + " min")
    if (status.error_hint) lines.push("Hinweis: " + status.error_hint)
    return lines.join("\n")
  }

  // --- cache file ---------------------------------------------------------
  function applyStatus(text) {
    try {
      root.status = JSON.parse(text)
    } catch (e) {
      /* mid-replace read; keep last-known-good pixels */
    }
  }

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  FileView {
    id: statusFile
    path: root.statusPath
    watchChanges: true
    printErrors: false
    onLoaded: {
      root.applyStatus(text())
      root.resolved = true
    }
    onLoadFailed: {
      root.status = null
      root.resolved = true
    }
    onFileChanged: statusApply.restart()
  }
  Timer { id: statusApply; interval: 150; repeat: false
          onTriggered: statusFile.reload() }
  // periodic refresh so staleness ages even when the file does not change
  Timer {
    interval: 30000
    repeat: true
    running: true
    onTriggered: {
      root.nowMs = Date.now()
      statusFile.reload()
    }
  }

  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    labelVisible: false
    hasVisualContent: true
    horizontalMargin: 8
    verticalPadding: 8
    // WidgetButton only measures its internal label; our custom Row needs
    // to drive the width itself or the content overlaps neighbouring widgets
    fixedWidth: content.implicitWidth + button.scaledHorizontalMargin * 2
    tooltipText: root.tooltip()
    onPressed: function(b) {
      if (b === Qt.RightButton)
        Quickshell.execDetached(["sh", "-c",
          "xdg-terminal-exec omarchy-mercedes status"])
    }

    Row {
      id: content
      anchors.centerIn: parent
      spacing: 7

      Text {
        text: root.icon
        color: root.stateColor
        font.pixelSize: button.fontSize
        anchors.verticalCenter: parent.verticalCenter
      }

      Text {
        visible: !root.showBar
        text: root.socText + root.rangeText
          + (root.displayState === "stale" ? " (?)" : "")
        color: root.stateColor
        font.pixelSize: button.fontSize
        font.family: button.fontFamily
        anchors.verticalCenter: parent.verticalCenter
      }

      // battery bar: 10 real rectangles, filled per 10% step
      Row {
        visible: root.showBar
        spacing: 2
        anchors.verticalCenter: parent.verticalCenter

        Repeater {
          model: 10

          Rectangle {
            required property int index
            readonly property bool filled: root.socValue >= 0
              && index < Math.round(root.socValue / 10)
            width: 6
            height: button.fontSize * 0.9
            radius: 1
            color: filled ? root.stateColor : Qt.alpha(root.fg, 0.22)
          }
        }
      }

      Text {
        visible: root.showBar && root.showRange
          && root.displayState === "ok"
        text: root.rangeText
        color: root.fg
        font.pixelSize: button.fontSize
        font.family: button.fontFamily
        anchors.verticalCenter: parent.verticalCenter
      }
    }
  }
}
