// omarchy-mercedes bar widget — renders the connector daemon's status cache
// (~/.local/state/omarchy-mercedes/status.json). Pixels only: no network,
// no login, no tokens. The daemon (systemd --user) does all the talking to
// Mercedes; this widget just reads the redacted cache file.

import QtQuick
import Quickshell
import Quickshell.Io
import qs.Ui
import "I18n.js" as I18n

BarWidget {
  id: root
  moduleName: "hendkai.omarchy-mercedes"

  readonly property color fg: bar ? bar.foreground : "#ffffff"
  readonly property color urgentColor: bar ? bar.urgent : "#f38ba8"
  readonly property color accent: bar && bar.accent !== undefined
    ? bar.accent : "#a6e3a1"

  property var uiLocale: Qt.locale()
  readonly property string language: I18n.language(uiLocale.name)
  function tr(key, args) { return I18n.text(uiLocale.name, key, args) }
  function number(value) { return Number(value).toLocaleString(uiLocale, "f", 0) }
  LayoutMirroring.enabled: language === "ar"
  LayoutMirroring.childrenInherit: true
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
  readonly property string socText: {
    if (displayState === "checking") return "…"
    if (displayState === "no-session") return "!"
    if (displayState === "error") return "!"
    if (displayState === "offline") return "—"
    if (socValue < 0) return "?"
    return number(Math.round(socValue)) + "%"
  }
  readonly property string rangeText: {
    if (!showRange || displayState !== "ok") return ""
    var r = status && status.range_km
    if (r === null || r === undefined) return ""
    return number(Math.round(r)) + " km"
  }
  readonly property bool showBar: displayMode === "bar"
    && (displayState === "ok" || displayState === "stale")
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
    if (!ms) return tr("unknown")
    var s = Math.max(0, Math.floor((nowMs - ms) / 1000))
    if (s < 60) return number(s) + " " + tr("second")
    if (s < 3600) return number(Math.floor(s / 60)) + " " + tr("minute")
    if (s < 86400) return number(Math.floor(s / 3600)) + " " + tr("hour")
    return number(Math.floor(s / 86400)) + " " + tr("day")
  }
  function fmtLocal(ms) {
    if (!ms) return tr("unknown")
    return new Date(ms).toLocaleString(uiLocale, uiLocale.dateTimeFormat(Locale.ShortFormat))
  }
  function tooltip() {
    if (displayState === "checking") return "Mercedes-Benz — " + tr("checking")
    if (displayState === "no-session") return tr("login") + "\n omarchy-mercedes login"
    if (displayState === "offline") return tr("offline") + "\n omarchy-mercedes status"
    var lines = []
    if (socValue >= 0) lines.push(tr("soc") + ": " + number(socValue) + "%")
    if (status.range_km !== null && status.range_km !== undefined)
      lines.push(tr("range") + ": " + number(status.range_km) + " km")
    if (charging) {
      var line = tr("charging")
      if (status.charging_power_kw)
        line += " (" + Number(status.charging_power_kw).toLocaleString(uiLocale, "f", 1) + " kW)"
      lines.push(line)
      if (status.end_of_charge_time) lines.push(tr("chargeEnd") + ": " + status.end_of_charge_time)
    }
    lines.push(tr("vehicleData") + ": " + fmtLocal(status.vehicle_ts_ms)
      + " (" + tr("ago", [fmtAge(status.vehicle_ts_ms)]) + ")")
    lines.push(tr("sync") + ": " + fmtLocal(status.fetched_at_ms)
      + " (" + tr("ago", [fmtAge(status.fetched_at_ms)]) + ")")
    if (displayState === "stale") lines.push(tr("stale", [number(staleAfterSec / 60)]))
    // Backend-provided diagnostic strings are deliberately not translated.
    if (status.error_hint) lines.push(tr("hint") + ": " + status.error_hint)
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

  clip: true
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

  // The host allocates root.implicitWidth, NOT painted child bounds.
  // Reserve stable slots independent of status strings and Row polish timing.
  readonly property real unit: button.fontSize / 13
  readonly property real contentWidth: (showRange ? 130 : 76) * unit
  readonly property bool opened: panelLoader.item ? panelLoader.item.opened : false
  readonly property bool popoutSwitchClosing: panelLoader.item ? panelLoader.item.popoutSwitchClosing : false
  function open() { if (panelLoader.item) panelLoader.item.open() }
  function close() { if (panelLoader.item) panelLoader.item.close() }
  function closeForPopoutSwitch() { if (panelLoader.item) panelLoader.item.closeForPopoutSwitch() }
  function togglePanel() { if (panelLoader.item) panelLoader.item.toggle() }
  function injectPanel() {
    var target = panelLoader.item
    if (!target) return
    target.hostWidget = root
    target.bar = root.bar
    target.anchorItem = button
    target.settings = root.settings
  }
  onBarChanged: injectPanel()
  onSettingsChanged: injectPanel()
  Loader {
    id: panelLoader
    source: Qt.resolvedUrl("SettingsPanel.qml")
    visible: false
    onLoaded: root.injectPanel()
  }

  WidgetButton {
    id: button
    objectName: "mercedesButton"
    anchors.fill: parent
    bar: root.bar
    labelVisible: false
    hasVisualContent: true
    horizontalMargin: 10
    fixedWidth: root.vertical ? root.barSize : root.contentWidth + scaledHorizontalMargin * 2
    fixedHeight: root.vertical ? 76 * root.unit : root.barSize
    tooltipText: root.tooltip()
    onPressed: function(b) {
      if (b === Qt.RightButton)
        Quickshell.execDetached(["xdg-terminal-exec", "omarchy-mercedes", "status"])
      else if (b === Qt.LeftButton) root.togglePanel()
    }

    Grid {
      id: content
      objectName: "mercedesContent"
      anchors.centerIn: parent
      columns: root.vertical ? 1 : 4
      spacing: 6 * root.unit

      Image {
        objectName: "electricVehicleIcon"
        width: 20 * root.unit; height: 20 * root.unit
        source: Qt.resolvedUrl("assets/electric-vehicle.svg")
        sourceSize.width: width * 2; sourceSize.height: height * 2
        opacity: root.displayState === "offline" ? 0.45 : 1
      }
      Item {
        width: root.vertical ? root.barSize - 4 : 38 * root.unit; height: 20 * root.unit
        Text {
          anchors.verticalCenter: parent.verticalCenter
          visible: !root.showBar
          width: parent.width
          text: root.socText
          color: root.stateColor
          font.family: button.fontFamily
          font.pixelSize: button.fontSize
          font.weight: Font.DemiBold
          horizontalAlignment: root.vertical ? Text.AlignHCenter : Text.AlignLeft
          elide: Text.ElideRight
          textFormat: Text.PlainText
        }
        Rectangle {
          objectName: "mercedesChargeBar"
          anchors.verticalCenter: parent.verticalCenter
          width: parent.width; height: 6 * root.unit
          radius: height / 2
          visible: root.showBar && (root.displayState === "ok" || root.displayState === "stale")
          color: Qt.alpha(root.fg, 0.16)
          Rectangle {
            width: parent.width * Math.max(0, Math.min(100, root.socValue)) / 100
            height: parent.height; radius: height / 2
            color: root.stateColor
          }
        }
      }
      Text {
        visible: root.showRange && !root.vertical
        width: 48 * root.unit; height: 20 * root.unit
        text: root.rangeText || "— km"
        color: Qt.alpha(root.fg, 0.62)
        font.family: button.fontFamily
        font.pixelSize: button.fontSize * 0.85
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
        textFormat: Text.PlainText
      }
      Text {
        width: 6 * root.unit; height: 20 * root.unit
        text: root.charging ? "+" : root.displayState === "stale" ? "~"
          : root.displayState === "error" || root.displayState === "no-session" ? "!" : "·"
        color: root.stateColor
        font.pixelSize: button.fontSize
        verticalAlignment: Text.AlignVCenter
        horizontalAlignment: Text.AlignHCenter
      }
    }
  }
}
