"""Deterministic offline races using the real session store."""
import fcntl
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from omarchy_mercedes import daemon
from omarchy_mercedes.oauth_client import InvalidSessionError
from omarchy_mercedes.telemetry import UnauthorizedError


class SessionRaceTests(unittest.TestCase):
    def test_all_store_operations_share_cross_process_lock(self):
        operations = (
            "daemon.save_session({'access_token': 'synthetic-child'})",
            "daemon.clear_session()",
            "daemon.load_session('eu')",
            "daemon.save_session({'access_token': 'synthetic-child'}, expected=None)",
            "daemon.clear_session(expected=None)",
        )
        for operation in operations:
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as directory:
                path = Path(directory)
                fd = os.open(path / "session.lock", os.O_CREAT | os.O_RDWR, 0o600)
                fcntl.flock(fd, fcntl.LOCK_EX)
                child = None
                try:
                    code = ("import sys; sys.modules['keyring'] = None; "
                            "from omarchy_mercedes import daemon; "
                            "print('ready', flush=True); " + operation)
                    child = subprocess.Popen(
                        [sys.executable, "-c", code], stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE, text=True,
                        env=dict(os.environ, OMARCHY_MERCEDES_DATA_DIR=directory,
                                 PYTHON_KEYRING_BACKEND="keyring.backends.null.Keyring"))
                    self.assertEqual(child.stdout.readline().strip(), "ready")
                    with self.assertRaises(subprocess.TimeoutExpired):
                        child.communicate(timeout=0.1)
                    fcntl.flock(fd, fcntl.LOCK_UN)
                    output, error = child.communicate(timeout=5)
                    self.assertEqual(child.returncode, 0, error)
                    self.assertEqual(output, "")
                finally:
                    os.close(fd)
                    if child is not None:
                        if child.poll() is None:
                            child.kill()
                        child.communicate()

    def test_login_survives_inflight_invalid_grant(self):
        self.race(invalid=True)

    def test_login_survives_inflight_successful_refresh(self):
        self.race()

    def test_login_survives_unauthorized_successful_refresh(self):
        self.race(unauthorized=True)

    def test_login_survives_unauthorized_invalid_grant(self):
        self.race(invalid=True, unauthorized=True)

    def race(self, invalid=False, unauthorized=False):
        old = dict(access_token="synthetic-old", refresh_token="synthetic-old-refresh",
                   expires_at=9999999999 if unauthorized else 0)
        login = dict(access_token="synthetic-login", refresh_token="synthetic-login-refresh",
                     expires_at=9999999999)
        rotated = dict(old, access_token="synthetic-rotated", expires_at=9999999999)
        args = SimpleNamespace(debug=False, region="eu", timeout=1, poll_interval=60,
                               backoff_max=3600, once=True, vin=None)
        with tempfile.TemporaryDirectory() as directory, \
             mock.patch.object(daemon, "DATA_DIR", Path(directory)), \
             mock.patch.object(daemon, "SESSION_FILE", Path(directory) / "session.json"), \
             mock.patch.dict(sys.modules, {"keyring": None}), \
             mock.patch.object(daemon, "MercedesOAuthClient") as oauth, \
             mock.patch.object(daemon, "VehicleApi") as api, \
             mock.patch.object(daemon, "write_status") as status, \
             mock.patch.object(daemon, "log"):
            daemon.save_session(old)

            def refresh(_token):
                # The login writer completes while the token endpoint is in flight.
                daemon.save_session(login)
                if invalid:
                    raise InvalidSessionError("synthetic invalid grant")
                return rotated

            oauth.return_value.refresh.side_effect = refresh
            api.return_value.list_vehicles.return_value = [{"vin": "SYNTHETIC"}]
            if unauthorized:
                api.return_value.list_vehicles.side_effect = [UnauthorizedError("401"), [{"vin": "SYNTHETIC"}]]
            api.return_value.get_vehicle_attributes.return_value = {"attributes": {"soc": {"value": 42}}}
            daemon.run_loop(args)
            self.assertEqual(daemon.load_session("eu"), login)
            self.assertNotEqual(status.call_args.args[0]["state"], "no-session")
