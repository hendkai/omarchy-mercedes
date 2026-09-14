"""Exercise the actual plugin installer block, never pip/systemd/keyring."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
ID = 'hendkai.omarchy-mercedes'

class PluginInstallTest(unittest.TestCase):
    def install(self, home):
        source = (REPO / 'install.sh').read_text()
        block = source.split('# 5. Omarchy shell plugin', 1)[1].split('\nlog "fertig."', 1)[0]
        script = 'set -euo pipefail\nlog() { :; }; warn() { printf "%s\\n" "$*" >&2; };\n# 5. Omarchy shell plugin' + block
        env = {**os.environ, 'HOME':str(home), 'REPO_DIR':str(REPO), 'BACKUP_DIR':str(home / 'backup')}
        r = subprocess.run(['bash', '-c', script], env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout+r.stderr)

    def test_repeat_preserves_position_settings_and_ships_panel(self):
        with tempfile.TemporaryDirectory() as td:
            home=Path(td); config=home/'.config/omarchy/shell.json'; config.parent.mkdir(parents=True)
            data={'bar':{'layout':{'left':[], 'center':[{'id':'omarchy.clock'}], 'right':[{'id':'before'}, {'id':ID,'showRange':False,'displayMode':'bar','staleAfterSec':3600}, {'id':'after'}]}}}
            config.write_text(json.dumps(data))
            for _ in range(2):
                self.install(home)
                self.assertEqual(json.loads(config.read_text()), data)
                plugin=config.parent/'plugins'/ID
                for name in ['SettingsPanel.qml','assets/mercedes-star.svg','BarWidget.qml']:
                    self.assertEqual((plugin/name).read_bytes(), (REPO/'omarchy-plugin'/name).read_bytes())

    def test_first_registration_and_duplicate_cleanup(self):
        with tempfile.TemporaryDirectory() as td:
            home=Path(td); config=home/'.config/omarchy/shell.json'; config.parent.mkdir(parents=True)
            config.write_text('{"bar":{"layout":{"center":[{"id":"omarchy.clock"}]}}}')
            self.install(home)
            d=json.loads(config.read_text()); self.assertEqual(d['bar']['layout']['center'][0], {'id':ID})
            d['bar']['layout']['right']=[{'id':ID}]; config.write_text(json.dumps(d))
            self.install(home)
            result=json.loads(config.read_text())['bar']['layout']
            self.assertEqual(sum(x['id']==ID for s in result.values() for x in s),1)
