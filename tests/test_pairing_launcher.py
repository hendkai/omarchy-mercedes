import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]

class PairingLauncherTests(unittest.TestCase):
    def run_launcher(self, cli_code=None):
        with tempfile.TemporaryDirectory(prefix='mercedes-user with spaces-') as td:
            home=Path(td)
            if cli_code is not None:
                binary=home/'.local/bin/omarchy-mercedes'
                binary.parent.mkdir(parents=True)
                binary.write_text('#!/bin/sh\nprintf "%s\\n" "$*" > "$HOME/called"\nexit '+str(cli_code)+'\n')
                binary.chmod(0o700)
            env={**os.environ,'HOME':td,'PATH':'/usr/bin:/bin','LC_ALL':'C','DBUS_SESSION_BUS_ADDRESS':''}
            result=subprocess.run(['/bin/sh',str(ROOT/'omarchy-plugin/PairAccount.sh')],input='\n',text=True,capture_output=True,env=env,timeout=5)
            called=(home/'called').read_text() if (home/'called').exists() else None
            return result,called

    def test_fresh_user_gets_setup_guidance_not_disappearing_window(self):
        result,called=self.run_launcher()
        self.assertEqual(result.returncode,127)
        self.assertIn('connector',result.stdout.lower())
        self.assertIn('README',result.stdout)
        self.assertIn('Enter',result.stdout)
        self.assertIsNone(called)

    def test_user_local_cli_works_when_desktop_path_omits_local_bin(self):
        result,called=self.run_launcher(0)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(called,'login --browser\n')
        self.assertIn('successful',result.stdout)

    def test_failure_remains_visible_and_returns_exit_status(self):
        result,called=self.run_launcher(1)
        self.assertEqual(result.returncode,1)
        self.assertIn('failed',result.stdout)
        self.assertIn('Enter',result.stdout)
