"""R1-R7 regression tests. ALL data synthetic; no network or real keyring."""
import contextlib
import io
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, Mock

from omarchy_mercedes import cli, daemon, state, login_helper
from omarchy_mercedes.telemetry import ApiError
from omarchy_mercedes.oauth_client import AuthError
from omarchy_mercedes.waybar_module import render


class MemoryKeyring:
    def __init__(self):
        self.blob = None
        self.fail = False

    def get_password(self, *args):
        return self.blob

    def set_password(self, service, user, blob):
        if self.fail:
            raise RuntimeError('synthetic unavailable')
        self.blob = blob

    def delete_password(self, *args):
        if self.fail:
            raise RuntimeError('synthetic unavailable')
        self.blob = None


def sample():
    now = state.now_ms()
    return {'attributes': {name: {'value': value, 'ts_ms': now, 'status': 0}
            for name, value in [('stateofcharge', 48), ('rangeelectric', 250),
                                ('chargingactive', True), ('chargingpower', 11.0)]}}


def token(value='SYNTHETIC'):
    return {'access_token': value, 'refresh_token': 'SYNTHETIC_REFRESH',
            'expires_at': time.time() + 3600, 'region': 'eu'}


class Freshness(unittest.TestCase):
    def test_mixed_timestamps(self):
        data = sample()
        data['attributes']['stateofcharge']['ts_ms'] -= 86400000
        status = daemon.extract_status(data, state.now_ms())
        status['written_at_ms'] = state.now_ms()
        self.assertEqual(render(status)['class'], 'stale')
        self.assertIn('1 d', render(status)['tooltip'])

    def test_invalid_fields(self):
        for value in [-1, 101, True, '48', float('nan')]:
            data = sample()
            data['attributes']['stateofcharge']['value'] = value
            self.assertEqual(daemon.extract_status(data, state.now_ms())['state'], 'error')
        for status in [1, 2, 3, 4, None, '0']:
            data = sample()
            data['attributes']['stateofcharge']['status'] = status
            self.assertEqual(daemon.extract_status(data, state.now_ms())['state'], 'error')
        for ts in [None, True, -1, 'today', state.now_ms() + 86400000]:
            data = sample()
            data['attributes']['stateofcharge']['ts_ms'] = ts
            self.assertEqual(daemon.extract_status(data, state.now_ms())['state'], 'error')

    def test_unknown_charging_not_false_or_truthy_string(self):
        for value in ['unknown', 'false', 2, None]:
            data = sample()
            data['attributes']['chargingactive']['value'] = value
            self.assertIsNone(daemon.extract_status(data, state.now_ms())['charging'])

    def test_each_field_age_and_stale_charging(self):
        data = sample()
        data['attributes']['chargingactive']['ts_ms'] -= 86400000
        data['attributes']['chargingpower']['ts_ms'] -= 7200000
        status = daemon.extract_status(data, state.now_ms())
        status['written_at_ms'] = state.now_ms()
        output = render(status)
        self.assertEqual(output['class'], 'ok')
        self.assertIn('veraltet', output['tooltip'])
        self.assertIn('Ladeleistung', output['tooltip'])
        self.assertIsNotNone(status['charging_ts_ms'])


class StoreFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.data = self.root / 'private'
        self.kr = MemoryKeyring()
        status_patch = patch.object(daemon, 'write_status', side_effect=lambda data: state.write_status(data, self.root/'state'/'status.json'))
        status_patch.start()
        self.addCleanup(status_patch.stop)
        for name, value in [('DATA_DIR', self.data), ('SESSION_FILE', self.data/'session.json')]:
            patcher = patch.object(daemon, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(daemon, '_keyring', return_value=self.kr)
        patcher.start()
        self.addCleanup(patcher.stop)


class Stores(StoreFixture):
    def test_keyring_first_never_plaintext(self):
        daemon.save_session(token())
        self.assertFalse(daemon.SESSION_FILE.exists())
        self.assertEqual(daemon.load_session('eu')['access_token'], 'SYNTHETIC')

    def test_creation_modes_before_writes_and_temp_symlink(self):
        self.kr.fail = True
        seen = []
        real_write = os.fdopen
        def observe(fd, *a, **kw):
            seen.append(os.fstat(fd).st_mode & 0o777)
            self.assertEqual(self.data.stat().st_mode & 0o777, 0o700)
            return real_write(fd, *a, **kw)
        old = os.umask(0o022)
        try:
            with patch('os.fdopen', side_effect=observe):
                daemon.save_session(token())
        finally:
            os.umask(old)
        self.assertIn(0o600, seen)
        self.assertEqual(self.data.stat().st_mode & 0o777, 0o700)
        target = self.root/'untouched'
        target.write_text('SYNTHETIC ORIGINAL')
        (self.data/'session.tmp').symlink_to(target)
        daemon.save_session(token('SYNTHETIC_NEW'))
        self.assertEqual(target.read_text(), 'SYNTHETIC ORIGINAL')

    def test_parent_and_read_symlinks_rejected(self):
        self.data.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(OSError):
            daemon.save_session(token())
        self.data.unlink()
        self.data.mkdir(mode=0o700)
        target = self.root/'untouched'
        target.write_text(json.dumps(token()))
        target.chmod(0o644)
        daemon.SESSION_FILE.symlink_to(target)
        self.assertIsNone(daemon.load_session('eu'))
        self.assertEqual(target.stat().st_mode & 0o777, 0o644)

    def test_fallback_newer_than_long_lived_keyring(self):
        first = token('SYNTHETIC_OLD')
        first['expires_at'] = time.time() + 1000000
        daemon.save_session(first)
        self.kr.fail = True
        daemon.save_session(token('SYNTHETIC_NEW'))
        self.assertEqual(daemon.load_session('eu')['access_token'], 'SYNTHETIC_NEW')
        self.assertIsNone(daemon.load_session('na'))

    def test_clear_both_and_failed_delete_no_resurrection(self):
        daemon.save_session(token())
        self.kr.fail = True
        daemon.save_session(token('SYNTHETIC_NEW'))
        with self.assertRaises(RuntimeError):
            daemon.clear_session()
        self.kr.fail = False
        self.assertIsNone(daemon.load_session('eu'))
        daemon.clear_session()
        self.assertIsNone(self.kr.blob)
        self.assertIsNone(daemon.load_session('eu'))

    def test_process_lock_blocks_concurrent_session_write(self):
        import subprocess
        import sys
        env = dict(os.environ, OMARCHY_MERCEDES_DATA_DIR=str(self.data),
                   OMARCHY_MERCEDES_STATE_DIR=str(self.root/'state'),
                   PYTHON_KEYRING_BACKEND='keyring.backends.null.Keyring')
        code = ("from omarchy_mercedes.daemon import save_session; "
                "print('READY', flush=True); "
                "save_session({'access_token':'SYNTHETIC_PROCESS', 'expires_at':1}); "
                "print('DONE', flush=True)")
        process = None
        try:
            with daemon.session_lock():
                process = subprocess.Popen([sys.executable, '-c', code], env=env,
                                           cwd=Path(__file__).resolve().parents[1],
                                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                self.assertEqual(process.stdout.readline().strip(), 'READY')
                with self.assertRaises(subprocess.TimeoutExpired):
                    process.wait(timeout=0.1)
            output, errors = process.communicate(timeout=10)
            self.assertEqual(process.returncode, 0, errors)
            self.assertIn('DONE', output)
            self.assertEqual(daemon.load_session('eu')['access_token'], 'SYNTHETIC_PROCESS')
        finally:
            if process is not None and process.poll() is None:
                process.kill()
                process.communicate(timeout=5)

    def test_noop_keyring_falls_back(self):
        self.kr.set_password = lambda *args: None
        daemon.save_session(token())
        self.assertTrue(daemon.SESSION_FILE.exists())
        self.assertEqual(daemon.load_session("eu")["access_token"], "SYNTHETIC")

    def test_malformed_session_is_ignored(self):
        self.kr.blob = json.dumps({'access_token': [], 'saved_at': 'bad'})
        self.assertIsNone(daemon.load_session('eu'))


class Lifecycle(StoreFixture):
    def args(self, once=True):
        return SimpleNamespace(debug=False, poll_interval=60, region='eu', timeout=1,
                               once=once, vin=None, backoff_max=3600)

    def api(self):
        api = Mock()
        api.list_vehicles.return_value = [{'vin': 'SYNTHETIC'}]
        api.get_vehicle_attributes.return_value = sample()
        return api

    def test_logout_serializes_with_inflight_refresh(self):
        import threading
        saved = token()
        saved['expires_at'] = 1
        daemon.save_session(saved)
        entered, release, logout_done = threading.Event(), threading.Event(), threading.Event()
        errors = []
        def refresh(_):
            entered.set()
            if not release.wait(5):
                raise RuntimeError('synthetic timeout')
            return token('SYNTHETIC_ROTATED')
        def logout():
            try:
                daemon.clear_session()
                logout_done.set()
            except BaseException as e:
                errors.append(e)
        oauth = Mock()
        oauth.refresh.side_effect = refresh
        with patch.object(daemon, 'VehicleApi', return_value=self.api()), patch.object(daemon, 'MercedesOAuthClient', return_value=oauth):
            poller = threading.Thread(target=lambda: daemon.run_loop(self.args()))
            poller.start()
            self.assertTrue(entered.wait(5))
            clearer = threading.Thread(target=logout)
            clearer.start()
            self.assertFalse(logout_done.wait(0.05))
            release.set()
            poller.join(5)
            clearer.join(5)
            self.assertFalse(poller.is_alive() or clearer.is_alive())
        self.assertFalse(errors)
        self.assertTrue(logout_done.is_set())
        self.assertIsNone(daemon.load_session('eu'))
        self.assertEqual(state.read_status(self.root/'state'/'status.json')['state'], 'no-session')

    def test_no_session_once(self):
        with patch.object(daemon, 'write_status') as publish:
            self.assertEqual(daemon.run_loop(self.args()), 2)
            self.assertEqual(publish.call_args[0][0]['state'], 'no-session')

    def test_login_logout_relogin_running_daemon(self):
        api = self.api()
        outputs = []
        class Stop(Exception):
            pass
        steps = iter([lambda: daemon.save_session(token()), daemon.clear_session,
                      lambda: daemon.save_session(token('SYNTHETIC_NEW')), lambda: (_ for _ in ()).throw(Stop())])
        with patch.object(daemon, 'VehicleApi', return_value=api), \
             patch.object(daemon, 'write_status', side_effect=lambda s: outputs.append(s['state'])), \
             patch.object(daemon.time, 'sleep', side_effect=lambda _: next(steps)()):
            with self.assertRaises(Stop):
                daemon.run_loop(self.args(False))
        self.assertEqual(outputs, ['no-session', 'ok', 'no-session', 'no-session', 'ok'])
        self.assertEqual(api.list_vehicles.call_count, 2)
        self.assertEqual(api.list_vehicles.call_args[0][0], 'SYNTHETIC_NEW')

    def test_401_refresh_once_then_success(self):
        daemon.save_session(token())
        api = self.api()
        api.list_vehicles.side_effect = [ApiError('unauthorized (401)'), [{'vin': 'SYNTHETIC'}]]
        oauth = Mock()
        oauth.refresh.return_value = token('SYNTHETIC_REFRESHED')
        with patch.object(daemon, 'VehicleApi', return_value=api), patch.object(daemon, 'MercedesOAuthClient', return_value=oauth), patch.object(daemon, 'write_status'):
            self.assertEqual(daemon.run_loop(self.args()), 0)
        oauth.refresh.assert_called_once()
        self.assertEqual(daemon.load_session('eu')['access_token'], 'SYNTHETIC_REFRESHED')

    def test_401_twice_revokes_but_transient_preserves(self):
        for error, expected, retained in [(ApiError('unauthorized (401)'), 2, False),
                                          (ApiError('HTTP 503'), 1, True)]:
            daemon.save_session(token())
            api = self.api()
            api.list_vehicles.side_effect = error
            oauth = Mock()
            oauth.refresh.return_value = token()
            with patch.object(daemon, 'VehicleApi', return_value=api), patch.object(daemon, 'MercedesOAuthClient', return_value=oauth), patch.object(daemon, 'write_status'):
                self.assertEqual(daemon.run_loop(self.args()), expected)
            self.assertEqual(daemon.load_session('eu') is not None, retained)
            self.assertLessEqual(oauth.refresh.call_count, 1)

    def test_refresh_network_failure_keeps_store_and_backoff(self):
        saved = token()
        saved['expires_at'] = 1
        daemon.save_session(saved)
        oauth = Mock()
        oauth.refresh.side_effect = AuthError('network error during POST: Timeout')
        class Stop(Exception):
            pass
        with patch.object(daemon, 'MercedesOAuthClient', return_value=oauth), patch.object(daemon, 'write_status'), patch.object(daemon.time, 'sleep', side_effect=Stop) as sleep:
            with self.assertRaises(Stop):
                daemon.run_loop(self.args(False))
        self.assertGreaterEqual(sleep.call_args[0][0], 60)
        self.assertIsNotNone(daemon.load_session('eu'))


class PublicCLI(unittest.TestCase):
    def test_malformed_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'status.json'
            for value in [[], 1, 'x', {'state':'ok','written_at_ms':[]}, {'state':'ok','written_at_ms':state.now_ms(),'vehicle_ts_ms':'bad'}]:
                path.write_text(json.dumps(value))
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    self.assertEqual(cli.main(['waybar','--status-file',str(path)]), 0)
                self.assertIn(json.loads(out.getvalue())['class'], ['offline','error'])

    def test_doctor_without_version_attribute(self):
        with patch.dict('sys.modules', {'keyring': MemoryKeyring()}), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(['doctor']), 0)

    def test_login_region_propagated(self):
        with patch.object(login_helper, 'login_browser', return_value=token()), patch.object(daemon, 'save_session') as save, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(['login','--region','na']), 0)
        self.assertEqual(save.call_args[0][1], 'na')


if __name__ == '__main__':
    unittest.main()
