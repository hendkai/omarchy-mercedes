"""Offline marketplace packaging checks; never access account credentials."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest

REPO = Path(__file__).resolve().parents[1]


class MarketplacePackagingTest(unittest.TestCase):
    def test_root_manifest_loads_existing_bundle(self):
        self.assertTrue((REPO / 'manifest.json').is_file(), 'Marketplace requires a root manifest')
        root = json.loads((REPO / 'manifest.json').read_text())
        self.assertEqual(root['entryPoints'], {'barWidget': 'omarchy-plugin/BarWidget.qml'})
        candidates = sorted(str(p.relative_to(REPO)) for pattern in ('manifest.json', '*/manifest.json') for p in REPO.glob(pattern))
        self.assertEqual(candidates, ['manifest.json'], 'Marketplace submissions allow exactly one root manifest')
        for field in ('schemaVersion', 'id', 'name', 'version', 'author', 'description', 'kinds', 'entryPoints'):
            self.assertTrue(root[field], field)
        for entry in root['entryPoints'].values():
            self.assertTrue((REPO / entry).is_file())
        for name in ('SettingsPanel.qml', 'I18n.js', 'assets/electric-vehicle.svg'):
            self.assertTrue((REPO / 'omarchy-plugin' / name).is_file())
        for name in ('README.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md'):
            self.assertTrue((REPO / name).is_file())

    @unittest.skipUnless(shutil.which('omarchy-plugin-validate'), 'Installed Omarchy validator unavailable')
    def test_real_omarchy_validator(self):
        result = subprocess.run(['omarchy-plugin-validate', str(REPO)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
