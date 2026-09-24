"""Synthetic regression tests for real desktop pairing failure modes."""
import contextlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from omarchy_mercedes import callback as cb
from omarchy_mercedes import login_helper as lh

GOOD = 'rismycar://login-callback?code=SYNTHETIC123&state=synthetic'

class PairingRegressions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {
            'XDG_CONFIG_HOME': str(self.root/'config'),
            'XDG_DATA_HOME': str(self.root/'data'),
            'OMARCHY_MERCEDES_RUNTIME_DIR': str(self.root/'runtime'),
        })
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_legacy_or_dead_marker_does_not_accept_callback(self):
        token=cb.session_token()
        cb.marker_path(token).write_text('')
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cb.main(['--session',token,GOOD]),1)
        self.assertFalse(cb.spool_path(token).exists())

    def test_only_one_login_can_own_desktop_handler(self):
        with cb.login_lock():
            with self.assertRaises(RuntimeError):
                with cb.login_lock():
                    self.fail('second login acquired handler')

    def test_url_code_rejects_control_characters(self):
        with self.assertRaises(cb.InvalidCallback):
            cb.parse_pasted_callback('rismycar://login-callback?code=%00%0A&state=synthetic', 'synthetic')

    def test_cleanup_removes_pending_callback(self):
        token = cb.session_token()
        cb.marker_create(token)
        cb.write_spool(token, GOOD)
        cb.marker_remove(token)
        self.assertFalse(cb.spool_path(token).exists())

    def test_real_xdg_registration_refreshes_application_cache(self):
        import shutil
        if not all(shutil.which(x) for x in ('xdg-mime','gio','update-desktop-database')):
            self.skipTest('XDG tools required')
        token=cb.session_token()
        cb.marker_create(token)
        installed, previous=cb.install_desktop_handler(token,input_fn=lambda _: 'n')
        self.addCleanup(cb.restore_desktop_handler,token,previous)
        self.addCleanup(cb.marker_remove,token)
        self.assertTrue(installed)
        cache=cb.applications_dir()/'mimeinfo.cache'
        self.assertTrue(cache.exists(), 'Desktop registration must update MIME cache')
        self.assertIn(cb.desktop_file_path(token).name,cache.read_text())
        cb.restore_desktop_handler(token,previous)
        self.assertNotIn(cb.desktop_file_path(token).name,cache.read_text())

    def test_error_message_never_echoes_untrusted_query(self):
        with self.assertRaises(cb.InvalidCallback) as caught:
            cb.parse_pasted_callback('rismycar://login-callback?error=SYNTHETIC_SECRET')
        self.assertNotIn('SYNTHETIC_SECRET',str(caught.exception))

    def test_real_desktop_exec_delivers_callback_without_logging_code(self):
        import shutil
        if not shutil.which('gio'):
            self.skipTest('gio required')
        token=cb.session_token()
        cb.marker_create(token)
        self.addCleanup(cb.marker_remove,token)
        desktop=cb.desktop_file_path(token)
        desktop.parent.mkdir(parents=True,exist_ok=True)
        desktop.write_text(cb._desktop_content(token,sys.executable))
        env={**os.environ,'PYTHONPATH':str(Path(__file__).resolve().parents[1])}
        result=subprocess.run(['gio','launch',str(desktop),GOOD],env=env,capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,0,result.stderr)
        import time
        deadline=time.monotonic()+3
        received=None
        while time.monotonic()<deadline and received is None:
            received=cb.read_spool(token)
            if received is None: time.sleep(.02)
        self.assertIsNotNone(received)
        # GIO canonicalizes the empty path to '/' when expanding %u.
        self.assertEqual(cb.parse_pasted_callback(received, 'synthetic'),'SYNTHETIC123')
        self.assertNotIn('SYNTHETIC123',result.stdout+result.stderr)

    def _assert_pending_input_discarded(self, outcome):
        import json
        import pty
        import select
        import termios
        import time

        master, slave = pty.openpty()
        gate_read, gate_write = os.pipe()
        before = termios.tcgetattr(slave)
        script = '''
import json
import os
from unittest.mock import patch
from omarchy_mercedes import login_helper as lh
from omarchy_mercedes import callback as cb
first = True
def callback(_token):
    global first
    if first:
        first = False
        os.read(GATE, 1)
        if OUTCOME == 'interrupt':
            raise KeyboardInterrupt
    return CALLBACK if OUTCOME == 'automatic' else None
with patch.object(cb, 'read_spool', side_effect=callback):
    try:
        code = lh._wait_for_code('synthetic', 'synthetic', .3, True)
        assert OUTCOME == 'automatic' and code == 'SYNTHETIC123'
    except lh.LoginAborted:
        assert OUTCOME == 'timeout'
    except KeyboardInterrupt:
        assert OUTCOME == 'interrupt'
print('FOLLOWUP', flush=True)
print('INPUT=' + json.dumps(input()), flush=True)
'''.replace('GATE', str(gate_read)).replace('OUTCOME', repr(outcome)).replace('CALLBACK', repr(GOOD))
        p = None
        try:
            env = {**os.environ, 'HOME': str(self.root/'home')}
            p = subprocess.Popen(
                [sys.executable, '-u', '-c', script], stdin=slave,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                pass_fds=(gate_read,), env=env, bufsize=0,
            )

            assert p.stdout is not None
            output_fd = p.stdout.fileno()

            def read_line():
                line = b''
                deadline = time.monotonic() + 5
                while not line.endswith(b'\n'):
                    remaining = deadline - time.monotonic()
                    self.assertGreater(remaining, 0, 'Child output timed out')
                    self.assertTrue(select.select([output_fd], [], [], remaining)[0])
                    chunk = os.read(output_fd, 1)
                    self.assertTrue(chunk, 'Child exited before follow-up input')
                    line += chunk
                return line

            self.assertIn(b'(verdeckt)', read_line())
            self.assertFalse(termios.tcgetattr(slave)[3] & termios.ECHO)
            # No newline: the real canonical terminal queue retains this input.
            os.write(master, GOOD.encode())
            time.sleep(.05)
            os.write(gate_write, b'1')
            while read_line().strip() != b'FOLLOWUP':
                pass
            self.assertEqual(termios.tcgetattr(slave), before)
            os.write(master, b'\n')
            out, err = p.communicate(timeout=5)
            self.assertEqual(p.returncode, 0, err.decode())
            self.assertEqual(json.loads(out.decode().removeprefix('INPUT=')), '',
                             'Follow-up input must not receive the hidden callback')
            self.assertEqual(termios.tcgetattr(slave), before)
        finally:
            if p is not None:
                if p.poll() is None:
                    p.kill()
                p.communicate()
            for fd in (master, slave, gate_read, gate_write):
                os.close(fd)

    def test_pending_hidden_input_discarded_after_timeout(self):
        self._assert_pending_input_discarded('timeout')

    def test_pending_hidden_input_discarded_after_automatic_callback(self):
        self._assert_pending_input_discarded('automatic')

    def test_pending_hidden_input_discarded_after_cancellation(self):
        self._assert_pending_input_discarded('interrupt')

    def test_terminal_echo_restored_after_timeout_and_success(self):
        import pty, termios
        for success in (False,True,"interrupt"):
            with self.subTest(success=success):
                master,slave=pty.openpty()
                before=termios.tcgetattr(slave)
                script='''
from unittest.mock import patch
from omarchy_mercedes import login_helper as lh
from omarchy_mercedes import callback as cb
with patch.object(cb, 'install_desktop_handler', return_value=(True,None)), patch.object(cb, 'restore_desktop_handler'), patch.object(cb, 'read_spool', return_value=CALLBACK), patch.object(lh.webbrowser,'open', return_value=True), patch.object(lh.secrets,'token_urlsafe',return_value='synthetic'), patch.object(lh.MercedesOAuthClient,'exchange_code',return_value={'synthetic':True}):
    try:
        lh.login_browser(timeout_s=.3)
    except (lh.LoginAborted, KeyboardInterrupt):
        pass
'''.replace('CALLBACK',repr(GOOD if success is True else None))
                if success == 'interrupt': script=script.replace('timeout_s=.3','timeout_s=5')
                p=subprocess.Popen([sys.executable,'-c',script],stdin=slave,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,env=os.environ.copy())
                try:
                    if success == 'interrupt':
                        import time, signal
                        deadline=time.monotonic()+3
                        while time.monotonic()<deadline and termios.tcgetattr(slave)[3] & termios.ECHO:
                            time.sleep(.01)
                        self.assertFalse(termios.tcgetattr(slave)[3] & termios.ECHO)
                        p.send_signal(signal.SIGINT)
                    _,err=p.communicate(timeout=5)
                    self.assertEqual(p.returncode,0,err.decode())
                    self.assertEqual(termios.tcgetattr(slave),before,'Terminal attributes must be restored')
                    self.assertEqual(list((self.root/'runtime').glob('*.active')),[])
                    self.assertEqual(list((self.root/'runtime').glob('*.url')),[])
                finally:
                    if p.poll() is None: p.kill(); p.wait()
                    termios.tcsetattr(slave,termios.TCSANOW,before)
                    os.close(master); os.close(slave)
