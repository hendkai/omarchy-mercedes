// omarchy-mercedes settings panel — opened by clicking the bar widget.
// Position (left/center/right) goes through the bar's own layout mutator,
// display settings through the widget entry's inline settings.

import QtQuick
import QtQuick.Controls as Controls
import QtQuick.Layouts
import Quickshell
import qs.Commons
import qs.Ui
import "I18n.js" as I18n

Panel {
  id: panelRoot
  objectName: "mercedesSettings"
  readonly property var uiLocale: hostWidget ? hostWidget.uiLocale : Qt.locale()
  readonly property string language: I18n.language(uiLocale.name)
  function tr(key) { return I18n.text(uiLocale.name, key) }
  moduleName: "hendkai.omarchy-mercedes"

  manageIpc: false
  property var anchorItem: null
  bar: hostWidget ? hostWidget.bar : null
  property var hostWidget: null
  property string widgetId: "hendkai.omarchy-mercedes"
  readonly property color contentForeground: bar ? bar.foreground : Color.foreground
  readonly property var anchorsList: ["left", "center", "right"]
  readonly property string activeSection: currentSection()

  function currentSection() {
    if (!bar) return "center"
    var layout = bar.layout || {}
    for (var s = 0; s < anchorsList.length; s++) {
      var arr = layout[anchorsList[s]] || []
      for (var i = 0; i < arr.length; i++)
        if (arr[i] && arr[i].id === widgetId) return anchorsList[s]
    }
    return "center"
  }

  function hostSettings() {
    return hostWidget && hostWidget.settings ? hostWidget.settings : {}
  }

  function setting(name, fallback) {
    var value = hostSettings()[name]
    return value === undefined || value === null ? fallback : value
  }

  function applySetting(name, value) {
    var entry = { id: widgetId }
    var hs = hostSettings()
    for (var k in hs) if (k !== "id") entry[k] = hs[k]
    entry[name] = value
    if (hostWidget) hostWidget.settings = entry
    if (bar && bar.shell
        && typeof bar.shell.updateEntryInline === "function")
      bar.shell.updateEntryInline(widgetId, entry)
  }

  function moveTo(section) {
    if (bar && bar.shell
        && typeof bar.shell.mutateShellConfig === "function") {
      bar.shell.mutateShellConfig(function(config) {
        if (!config.bar) config.bar = { layout: {} }
        if (!config.bar.layout) config.bar.layout = {}
        var sections = ["left", "center", "right"]
        var entry = null
        for (var s = 0; s < sections.length; s++) {
          var arr = config.bar.layout[sections[s]] || []
          for (var i = 0; i < arr.length; i++) {
            if (arr[i] && arr[i].id === widgetId) {
              entry = arr[i]
              arr.splice(i, 1)
              break
            }
          }
        }
        if (!entry) entry = { id: widgetId }
        if (!config.bar.layout[section]) config.bar.layout[section] = []
        config.bar.layout[section].push(entry)
      })
    }
    close()
  }

  KeyboardPanel {
    id: popup
    anchorItem: panelRoot.anchorItem
    owner: panelRoot.hostWidget || panelRoot
    bar: panelRoot.bar
    open: panelRoot.opened
    focusTarget: content
    contentWidth: popup.fittedContentWidth(300)
    contentHeight: popup.fittedContentHeight(content.implicitHeight)

  ColumnLayout {
    id: content
    LayoutMirroring.enabled: panelRoot.language === "ar"
    LayoutMirroring.childrenInherit: true
    width: parent.width
    Keys.onEscapePressed: panelRoot.close()
    spacing: 10

    Text {
      text: "Mercedes-Benz"
      color: panelRoot.contentForeground
      font.bold: true
      font.pixelSize: 15
      Layout.bottomMargin: 6
    }

    Text {
      text: panelRoot.tr("position")
      color: panelRoot.contentForeground
      font.pixelSize: 12
      opacity: 0.7
    }
    RowLayout {
      spacing: 8
      Repeater {
        model: panelRoot.anchorsList
        delegate: Controls.Button {
          required property string modelData
          text: panelRoot.tr(modelData)
          checked: panelRoot.activeSection === modelData
          onClicked: panelRoot.moveTo(modelData)
        }
      }
    }

    Text {
      text: panelRoot.tr("display")
      color: panelRoot.contentForeground
      font.pixelSize: 12
      opacity: 0.7
    }
    RowLayout {
      spacing: 8
      Controls.Button {
        objectName: "percentModeButton"
        text: panelRoot.tr("percent")
        checked: panelRoot.setting("displayMode", "percent") !== "bar"
        onClicked: panelRoot.applySetting("displayMode", "percent")
      }
      Controls.Button {
        objectName: "barModeButton"
        text: panelRoot.tr("bar")
        checked: panelRoot.setting("displayMode", "percent") === "bar"
        onClicked: panelRoot.applySetting("displayMode", "bar")
      }
    }

    Controls.CheckBox {
      text: panelRoot.tr("showRange")
      checked: panelRoot.setting("showRange", true)
      onClicked: panelRoot.applySetting("showRange", checked)
    }
  }
  }
}
