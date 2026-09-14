import json
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]

class I18nTest(unittest.TestCase):
    def test_catalog_parity_fallback_and_regional_resolution(self):
        if not shutil.which('node'):
            self.skipTest('Node required for catalog checks')
        code=(ROOT/'omarchy-plugin/I18n.js').read_text().replace('.pragma library','',1)
        code+='\nconsole.log(JSON.stringify({keys:keys,catalogs:catalogs,resolved:[language("de_DE.UTF-8"),language("pt-BR"),language("zh_TW"),language("no_NO"),language("xx_YY"),language("C")],fallback:text("xx","charging"),substitution:text("de","stale",[30])}));'
        r=subprocess.run(['node','-e',code],capture_output=True,text=True,check=True)
        data=json.loads(r.stdout)
        supported='de en fr es it pt nl pl cs da sv nb fi tr uk ru ja ko zh ar'.split()
        self.assertEqual(set(data['catalogs']),set(supported))
        for language,values in data['catalogs'].items():
            self.assertEqual(len(values),len(data['keys']),language)
            self.assertTrue(all(isinstance(v,str) and v for v in values),language)
            for value,base in zip(values,data['catalogs']['en']):
                self.assertEqual('{0}' in value,'{0}' in base,language)
        self.assertEqual(data['resolved'],['de','pt','zh','nb','en','en'])
        self.assertEqual(data['fallback'],'Charging')
        self.assertIn('30',data['substitution'])
        source=(ROOT/'omarchy-plugin/BarWidget.qml').read_text()
        self.assertNotIn('de_DE',source)
        self.assertIn('Qt.locale()',source)
