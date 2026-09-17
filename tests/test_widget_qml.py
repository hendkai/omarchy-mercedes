"""Real Qt layout regression, using the installed Omarchy base components.
Run: python -m unittest discover -s tests -p test_widget_qml.py -v
Only IO, theme and popup surfaces are stubbed; WidgetButton/BarWidget are real.
"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]

class WidgetLayoutTest(unittest.TestCase):
    def test_content_fits_host_slot(self):
        runner = shutil.which('qmltestrunner') or '/usr/lib/qt6/bin/qmltestrunner'
        ui = Path('/usr/share/omarchy/shell/Ui')
        if not Path(runner).exists() or not ui.exists():
            self.skipTest('Requires Qt Quick Test and installed Omarchy shell')
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            def put(name, text):
                p = d / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(text)
            for name in ('WidgetButton', 'BarWidget', 'Panel', 'PanelController'):
                put('qs/Ui/' + name + '.qml', (ui / (name + '.qml')).read_text())
            put('qs/Ui/qmldir', 'module qs.Ui\nWidgetButton 1.0 WidgetButton.qml\nBarWidget 1.0 BarWidget.qml\nPanel 1.0 Panel.qml\nPanelController 1.0 PanelController.qml\nKeyboardPanel 1.0 KeyboardPanel.qml\n')
            put('qs/Commons/qmldir', 'module qs.Commons\nsingleton Style 1.0 Style.qml\nsingleton Color 1.0 Color.qml\n')
            put('qs/Commons/Style.qml', 'pragma Singleton\nimport QtQuick\nQtObject { property var font: ({family:"sans-serif",body:13}); property var bar: ({sizeHorizontal:26}); function spaceReal(v) { return v } }')
            put('qs/Commons/Color.qml', 'pragma Singleton\nimport QtQuick\nQtObject { property color foreground:"white"; property color urgent:"red" }')
            put('Quickshell/qmldir', 'module Quickshell\nsingleton Quickshell 1.0 Quickshell.qml\n')
            put('Quickshell/Quickshell.qml', 'pragma Singleton\nimport QtQuick\nQtObject { function env(k) {return ""} function execDetached(v) {} }')
            put('Quickshell/Io/qmldir', 'module Quickshell.Io\nFileView 1.0 FileView.qml\n')
            put('Quickshell/Io/FileView.qml', 'import QtQuick\nQtObject { property string path; property bool watchChanges; property bool printErrors; signal loaded(); signal loadFailed(); signal fileChanged(); function text(){return "{}"} function reload(){} }')
            shutil.copytree(REPO / 'omarchy-plugin', d / 'plugin')
            put('qs/Ui/KeyboardPanel.qml', 'import QtQuick\nItem { property var anchorItem; property var owner; property var bar; property bool open; property var focusTarget; property int contentWidth; property int contentHeight; function fittedContentWidth(v){return v} function fittedContentHeight(v){return v} }')
            put('Quickshell/Io/IpcHandler.qml', 'import QtQuick\nQtObject { property bool enabled; property string target }')
            with (d/'Quickshell/Io/qmldir').open('a') as f: f.write('IpcHandler 1.0 IpcHandler.qml\n')
            put('tst_layout.qml', '''import QtQuick
import QtTest
import "plugin" as Mercedes
TestCase {
 name: "MercedesLayout"; when: windowShown; visible: true
 width: 800; height: 100
 QtObject {
  id: fakeBar
  property bool vertical:false
  property int barSize:26
  property string fontFamily:"sans-serif"
  property color foreground:"white"
  property color barForeground:"white"
  property color urgent:"red"
  property color accent:"green"
  property bool foregroundAnimationEnabled:false
  property var layout: ({center:[{id:"hendkai.omarchy-mercedes"}]})
  property QtObject shell: QtObject {
   property var lastEntry: null
   function updateEntryInline(id,entry) {lastEntry=entry}
  }
  function hideTooltip(t) {}
 }

 Row {
  id: host
  Item {
   id: slot
   width: widget.implicitWidth; height: widget.implicitHeight
   Mercedes.BarWidget { id: widget; anchors.fill: parent }
  }
  Text { id: clock; text: "Monday 20:45" }
 }
 function descendants(item) {
  var out=[]
  for(var i=0;i<item.children.length;i++) { var c=item.children[i]; out.push(c); out=out.concat(descendants(c)) }
  return out
 }
 function test_geometry() {
  widget.resolved=true
  var now=Date.now(); widget.nowMs=now
  widget.status={state:"ok",soc_percent:100,range_km:999,written_at_ms:now,vehicle_ts_ms:now}
  for (var mode of ["percent","bar"]) {
   widget.settings={displayMode:mode,showRange:true}; wait(100)
   verify(slot.width>65, "host reserves composed content width: " + slot.width)
   for(var c of descendants(widget)) {
    if(c.visible && c.width>0 && c.height>0 && c.text !== undefined && c.text!=="") {
     var p=c.mapToItem(slot,0,0)
     verify(p.x>=0 && p.x+c.width<=slot.width+0.5, "painted text fits slot: " + c.text + " at " + p.x + " width " + c.width + " / " + slot.width)
    }
   }
   compare(clock.x,slot.width)
  }
  var fullWidth=slot.width
  widget.status={state:"no-session",written_at_ms:now}; wait(100)
  compare(slot.width,fullWidth,"state changes must not move the adjacent clock")
  var icon=findChild(widget,"electricVehicleIcon")
  verify(icon!==null,"original neutral EV vector replaces brand imagery")
  verify(icon.source.toString().endsWith("/assets/electric-vehicle.svg"))
  tryCompare(icon,"status",Image.Ready)
  verify(icon.sourceSize.width>0 && icon.sourceSize.height>0)
  widget.open(); wait(10); verify(widget.opened,"settings panel opens")
  widget.close(); verify(!widget.opened)
  widget.bar=fakeBar
  var panel=findChild(widget,"mercedesSettings")
  verify(panel!==null); compare(panel.hostWidget,widget)
  widget.settings={displayMode:"percent",showRange:true,staleAfterSec:3600}
  panel.applySetting("displayMode","bar")
  compare(widget.settings.staleAfterSec,3600); compare(widget.displayMode,"bar")
  compare(panel.bar,fakeBar); compare(fakeBar.shell.lastEntry.displayMode,"bar")
  compare(fakeBar.shell.lastEntry.staleAfterSec,3600)
  var button=findChild(widget,"mercedesButton")
  widget.status={state:"ok",soc_percent:55,range_km:123,written_at_ms:now,vehicle_ts_ms:now}
  var chargeBar=findChild(widget,"mercedesChargeBar")
  verify(chargeBar!==null)
  findChild(panel,"percentModeButton").clicked(); wait(10); verify(!chargeBar.visible,"percent means NO bar"); compare(fakeBar.shell.lastEntry.displayMode,"percent")
  findChild(panel,"barModeButton").clicked(); wait(10); verify(chargeBar.visible,"bar selection shows bar: " + widget.displayMode + "/" + widget.displayState + "/" + widget.socValue + "/" + widget.showBar)
  widget.uiLocale=Qt.locale("fr_FR"); compare(widget.tr("position"),"Position")
  compare(widget.tr("showRange"),"Afficher l’autonomie")
  widget.uiLocale=Qt.locale("ar_EG"); compare(widget.language,"ar")
  widget.uiLocale=Qt.locale("en_US")
  for(var fontSize of [11,13,18]) {
   button.fontSize=fontSize
   for(var range of [false,true]) {
    widget.settings={showRange:range}
    wait(50); var reserved=slot.width
    for(var state of ["ok","error","no-session","offline"]) {
     widget.status={state:state,soc_percent:100,range_km:9999,written_at_ms:now,vehicle_ts_ms:now}
     wait(10); compare(slot.width,reserved)
     compare(clock.x,slot.width)
    }
    widget.status={state:"ok",soc_percent:55,range_km:123,written_at_ms:now,vehicle_ts_ms:now-1900000}
    wait(10); compare(widget.displayState,"stale"); compare(slot.width,reserved)
    widget.status={state:"ok",charging:true,soc_percent:55,written_at_ms:now,vehicle_ts_ms:now}
    wait(10); verify(widget.charging)
   }
  }
 }
}
''')
            result = subprocess.run([runner, '-input', str(d / 'tst_layout.qml'), '-import', str(d)], env={**os.environ, 'QT_QPA_PLATFORM':'offscreen'}, text=True, capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            # Prove this harness catches the original label-only slot bug.
            widget_path = d / 'plugin/BarWidget.qml'
            original = widget_path.read_text()
            mutant = '\n'.join(line for line in original.splitlines() if 'fixedWidth:' not in line)
            widget_path.write_text(mutant)
            broken = subprocess.run([runner, '-input', str(d / 'tst_layout.qml'), '-import', str(d)], env={**os.environ, 'QT_QPA_PLATFORM':'offscreen'}, text=True, capture_output=True, timeout=30)
            self.assertNotEqual(broken.returncode, 0, 'Width mutation was not detected')
            self.assertIn('host reserves composed content width', broken.stdout)

if __name__ == '__main__':
    unittest.main()
