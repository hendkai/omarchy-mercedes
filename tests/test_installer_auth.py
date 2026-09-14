"""Installer/auth regressions with SYNTHETIC files, fake keyring, real PTY.

Package install is exercised separately by tools/verify_linux.sh, NOT mocked
results advertised as actual installation. These tests never call user systemd.
"""
import contextlib
import io
import json
import os
from pathlib import Path
import select
import signal
import sys
import tempfile
import time
import unittest
from unittest.mock import patch, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from installer import Installer
from waybar_integrate import integrate, strip_jsonc
from omarchy_mercedes import login_helper as login


class JSONC(unittest.TestCase):
    def test_targeted_comments_strings_trailing_commas(self):
        text = '''{ // SYNTHETIC comment
  "custom/x": {"format": "literal ,} and // and \\\"escape\\\"",},
  "modules-right": [/* retain me */ "clock",],
}'''
        result = integrate(text, {'exec': 'synthetic'})
        self.assertIn('/* retain me */', result)
        self.assertIn('"custom/x": {"format": "literal ,} and // and \\\"escape\\\"",}', result)
        self.assertEqual(json.loads(strip_jsonc(result))['modules-right'], ['custom/mercedes','clock'])
        self.assertEqual(integrate(result, {'exec': 'synthetic'}), result)

    def test_empty_array_and_no_trailing_comma(self):
        for text in ['{"modules-right": []}', '{"modules-right": ["clock"] // ending\n}']:
            result = integrate(text, {'exec':'synthetic'})
            self.assertIn('custom/mercedes', json.loads(strip_jsonc(result)))

    def test_reject_ambiguous(self):
        for text in ['[]', '{}', '{"modules-right": [], "modules-right": []}', '{"modules-right": "no"}']:
            with self.assertRaises(ValueError):
                integrate(text, {})


class Ownership(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name).resolve()
        self.installer = Installer(self.home)
        p = patch.object(Installer, 'systemctl', return_value=False)
        p.start()
        self.addCleanup(p.stop)
        self.runner = patch('installer.subprocess.run', return_value=Mock(returncode=0)).start()
        self.addCleanup(patch.stopall)

    def test_collision_reinstall_restore_all_originals(self):
        wb = self.home/'.config/waybar'
        targets = {self.installer.bin/'omarchy-mercedes': b'SYNTHETIC ORIGINAL WRAPPER',
                   self.installer.bin/'omarchy-mercedes-waybar': b'SYNTHETIC ORIGINAL BAR',
                   self.installer.unit: b'SYNTHETIC ORIGINAL UNIT',
                   wb/'config': b'{ // SYNTHETIC original\n"modules-right":["clock"], "custom/mercedes":{"exec":"old"}}',
                   wb/'style.css': b'/* SYNTHETIC ORIGINAL STYLE */',
                   wb/'config.d/mercedes.jsonc': b'SYNTHETIC ORIGINAL SNIPPET',
                   wb/'style.d/mercedes.css': b'SYNTHETIC ORIGINAL CSS'}
        for path, content in targets.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        self.installer.install()
        installed = {p: p.read_bytes() for p in targets}
        self.installer = Installer(self.home)
        self.installer.install()
        self.assertEqual(installed, {p:p.read_bytes() for p in targets})
        self.assertFalse((wb/'config.jsonc').exists())
        self.installer.uninstall(keep=True)
        self.assertEqual(targets, {p:p.read_bytes() for p in targets})
        # Retain must never invoke logout (and never touch a real keyring).
        self.assertFalse(any('logout' in call.args[0] for call in self.runner.call_args_list))

    def test_user_edit_aborts_without_overwrite_or_delete(self):
        path = self.installer.bin/'omarchy-mercedes'
        self.installer.put(path, b'SYNTHETIC installed')
        path.write_bytes(b'SYNTHETIC user edit')
        with self.assertRaisesRegex(RuntimeError, 'User change'):
            Installer(self.home).uninstall(keep=False)
        with self.assertRaisesRegex(RuntimeError, 'User change'):
            Installer(self.home).install()
        self.assertEqual(path.read_bytes(), b'SYNTHETIC user edit')
        self.runner.assert_not_called()

    def test_delete_before_package_removal_and_failed_logout_retains(self):
        self.installer.install()
        self.runner.side_effect = RuntimeError('SYNTHETIC locked keyring')
        with self.assertRaises(RuntimeError):
            self.installer.uninstall(keep=False)
        self.assertTrue((self.installer.bin/'omarchy-mercedes').exists())
        self.assertTrue(self.installer.manifest.exists())
        self.runner.side_effect = None
        self.installer.uninstall(keep=False)
        self.assertIn('logout', self.runner.call_args.args[0])
        self.assertFalse((self.installer.bin/'omarchy-mercedes').exists())

    def test_symlink_and_unowned_venv_rejected(self):
        self.installer.venv.mkdir(parents=True)
        with self.assertRaisesRegex(RuntimeError, 'unowned'):
            self.installer.preflight()
        self.installer.venv.rmdir()
        other = self.home/'other'
        other.write_text('SYNTHETIC original')
        target = self.installer.bin/'omarchy-mercedes'
        target.parent.mkdir(parents=True)
        target.symlink_to(other)
        with self.assertRaises(RuntimeError):
            self.installer.install()
        self.assertEqual(other.read_text(), 'SYNTHETIC original')


class BrowserAuth(unittest.TestCase):
    def test_callback_state_and_url_validation(self):
        self.assertEqual(login._parse_callback('rismycar://login-callback?code=SYNTHETIC&state=expected', 'expected'), 'SYNTHETIC')
        for url in ['SYNTHETIC', 'https://example.com/?code=SYNTHETIC&state=expected',
                    'rismycar://login-callback?code=SYNTHETIC&state=wrong',
                    'rismycar://login-callback?code=SYNTHETIC',
                    'rismycar://login-callback?code=a&code=b&state=expected']:
            with self.assertRaises(login.LoginAborted):
                login._parse_callback(url, 'expected')

    def test_no_open_and_browser_failure_have_manual_url(self):
        for opened in [False, True]:
            for browser in [False, OSError('SYNTHETIC')]:
                out = io.StringIO()
                with patch.object(login.secrets, 'token_urlsafe', return_value='SYNTHETIC_STATE'), \
                     patch.object(login, '_hidden_input', return_value='rismycar://login-callback?code=SYNTHETIC_CODE&state=SYNTHETIC_STATE'), \
                     patch.object(login.webbrowser, 'open', side_effect=browser if isinstance(browser, Exception) else None, return_value=False), \
                     patch.object(login, 'MercedesOAuthClient') as oauth, contextlib.redirect_stdout(out):
                    oauth._pkce.return_value = ('SYNTHETIC_VERIFIER','SYNTHETIC_CHALLENGE')
                    oauth.return_value.exchange_code.return_value = {'access_token':'SYNTHETIC_TOKEN'}
                    login.login_browser(open_browser=opened)
                self.assertIn('https://', out.getvalue())
                for secret in ['SYNTHETIC_CODE','SYNTHETIC_VERIFIER','SYNTHETIC_TOKEN']:
                    self.assertNotIn(secret, out.getvalue())

    @unittest.skipUnless(hasattr(os, 'fork'), 'PTY regression requires Unix')
    def test_real_tty_hidden_input_timeout_and_abort(self):
        import pty
        for action in ['input', 'timeout', 'abort']:
            pid, fd = pty.fork()
            if pid == 0:
                try:
                    value = login._hidden_input('SYNTHETIC_PROMPT: ', 0.3 if action == 'timeout' else 3)
                    os._exit(0 if value == 'SYNTHETIC_SECRET' else 7)
                except login.LoginAborted:
                    os._exit(0 if action == 'timeout' else 8)
                except KeyboardInterrupt:
                    os._exit(0 if action == 'abort' else 9)
                except BaseException:
                    os._exit(10)
            output = b''
            sent = False
            deadline = time.monotonic() + 5
            try:
                while time.monotonic() < deadline:
                    if select.select([fd], [], [], 0.1)[0]:
                        try:
                            chunk = os.read(fd, 4096)
                        except OSError:
                            break
                        if not chunk:
                            break
                        output += chunk
                        if b'SYNTHETIC_PROMPT:' in output and not sent:
                            if action == 'input':
                                os.write(fd, b'SYNTHETIC_SECRET\n')
                            elif action == 'abort':
                                os.kill(pid, signal.SIGINT)
                            sent = True
                else:
                    os.kill(pid, signal.SIGKILL)
                _, status = os.waitpid(pid, 0)
                self.assertEqual(os.waitstatus_to_exitcode(status), 0, output)
                self.assertNotIn(b'SYNTHETIC_SECRET', output)
            finally:
                os.close(fd)


if __name__ == '__main__':
    unittest.main()
