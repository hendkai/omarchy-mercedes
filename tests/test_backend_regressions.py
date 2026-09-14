"""Offline backend regressions; storage and HTTP are isolated."""
import unittest
import sys
import os
import tempfile
from pathlib import Path
from unittest import mock
from omarchy_mercedes import daemon, telemetry
from types import SimpleNamespace
from test_all import FakeSession, FakeResponse
from omarchy_mercedes.oauth_client import MercedesOAuthClient, AuthError
from omarchy_mercedes.vendored import vehicle_events_pb2 as vep


class SessionSafetyTests(unittest.TestCase):
    def test_new_fallback_wins_over_readable_stale_keyring(self):
        import json
        old = {"access_token": "synthetic-old"}
        new = {"access_token": "synthetic-new"}
        keyring = mock.Mock()
        keyring.get_password.return_value = json.dumps(old)
        keyring.set_password.side_effect = RuntimeError("read-only keyring")
        with tempfile.TemporaryDirectory() as directory, \
             mock.patch.object(daemon, "DATA_DIR", Path(directory)), \
             mock.patch.object(daemon, "SESSION_FILE", Path(directory) / "session.json"), \
             mock.patch.dict(sys.modules, {"keyring": keyring}):
            daemon.save_session(new)
            self.assertEqual(daemon.load_session("eu"), new)

    def test_secret_file_is_private_before_first_write(self):
        import io
        real_open = io.open
        modes = []

        def observe_open(*args, **kwargs):
            stream = real_open(*args, **kwargs)
            if "w" in stream.mode:
                modes.append(os.fstat(stream.fileno()).st_mode & 0o777)
            return stream

        with tempfile.TemporaryDirectory() as directory, \
             mock.patch.object(daemon, "DATA_DIR", Path(directory)), \
             mock.patch.object(daemon, "SESSION_FILE", Path(directory) / "session.json"), \
             mock.patch.dict(sys.modules, {"keyring": None}), \
             mock.patch.object(io, "open", side_effect=observe_open):
            old_umask = os.umask(0)
            try:
                daemon.save_session({"access_token": "synthetic"})
            finally:
                os.umask(old_umask)
            self.assertTrue(modes)
            self.assertEqual(modes, [0o600])
            self.assertEqual(daemon.load_session("eu"), {"access_token": "synthetic"})

    def test_atomic_save_ignores_predictable_temp_symlink(self):
        with tempfile.TemporaryDirectory() as directory, \
             mock.patch.object(daemon, "DATA_DIR", Path(directory)), \
             mock.patch.object(daemon, "SESSION_FILE", Path(directory) / "session.json"), \
             mock.patch.dict(sys.modules, {"keyring": None}):
            target = Path(directory) / "unrelated"
            target.write_text("unchanged")
            (Path(directory) / "session.tmp").symlink_to(target)
            daemon.save_session({"access_token": "synthetic"})
            self.assertEqual(target.read_text(), "unchanged")
            self.assertEqual(daemon.load_session("eu"), {"access_token": "synthetic"})

    def test_failed_replace_preserves_old_session_and_removes_temp(self):
        with tempfile.TemporaryDirectory() as directory, \
             mock.patch.object(daemon, "DATA_DIR", Path(directory)), \
             mock.patch.object(daemon, "SESSION_FILE", Path(directory) / "session.json"), \
             mock.patch.dict(sys.modules, {"keyring": None}):
            daemon.save_session({"access_token": "synthetic-old"})
            with mock.patch.object(daemon.os, "replace", side_effect=OSError("disk failure")):
                with self.assertRaises(OSError):
                    daemon.save_session({"access_token": "synthetic-new"})
            self.assertEqual(daemon.load_session("eu"), {"access_token": "synthetic-old"})
            self.assertEqual(sorted(p.name for p in Path(directory).iterdir()), ["session.json", "session.lock"])

    def test_successful_fake_keyring_roundtrip_and_clear(self):
        import json
        entries = {}
        keyring = SimpleNamespace(
            set_password=lambda service, user, value: entries.__setitem__((service, user), value),
            get_password=lambda service, user: entries.get((service, user)),
            delete_password=lambda service, user: entries.pop((service, user), None))
        with tempfile.TemporaryDirectory() as directory, \
             mock.patch.object(daemon, "DATA_DIR", Path(directory)), \
             mock.patch.object(daemon, "SESSION_FILE", Path(directory) / "session.json"), \
             mock.patch.dict(sys.modules, {"keyring": keyring}):
            session = {"access_token": "synthetic", "refresh_token": "synthetic-refresh"}
            daemon.save_session(session)
            self.assertFalse(daemon.SESSION_FILE.exists())
            self.assertEqual(daemon.load_session("eu"), session)
            self.assertEqual(json.loads(next(iter(entries.values()))), session)
            daemon.clear_session()
            self.assertFalse(entries)
            self.assertIsNone(daemon.load_session("eu"))

    def test_original_session_test_cannot_touch_host_keyring(self):
        from test_all import TestSessionStore
        host = mock.Mock()
        host.set_password.side_effect = RuntimeError("host keyring must not be called")
        host.get_password.return_value = None
        with mock.patch.dict(sys.modules, {"keyring": host}):
            TestSessionStore("test_save_load_and_redaction").test_save_load_and_redaction()
        self.assertEqual(host.mock_calls, [])


class TimestampTests(unittest.TestCase):
    def test_fresh_range_does_not_hide_old_soc(self):
        data = {"attributes": {"soc": {"value": 42, "ts_ms": 1000},
                               "rangeelectric": {"value": 100, "ts_ms": 9000},
                               "vtime": {"value": 10}}}
        self.assertEqual(daemon.extract_status(data, 20000)["vehicle_ts_ms"], 1000)
        del data["attributes"]["soc"]["ts_ms"]
        self.assertEqual(daemon.extract_status(data, 20000)["vehicle_ts_ms"], 10000)
        del data["attributes"]["vtime"]
        self.assertIsNone(daemon.extract_status(data, 20000)["vehicle_ts_ms"])

    def test_typed_metadata_preserves_timestamp_and_status(self):
        msg = vep.VehicleStatusUpdate()
        msg.soc.value = 42
        msg.soc.metadata.timestamp.seconds = 123
        msg.soc.metadata.timestamp.nanos = 456000000
        msg.soc.metadata.status = 1
        attr = telemetry.decode_vehicle_attributes(msg.SerializeToString())["attributes"]["soc"]
        self.assertEqual(attr["ts_ms"], 123456)
        self.assertEqual(attr["status"], 1)


class ApiAuthTests(unittest.TestCase):
    def test_only_invalid_grant_confirms_invalid_session(self):
        for code, body, expected in ((400, {"error": "invalid_grant"}, "InvalidSessionError"),
                                     (401, {"error": "invalid_grant"}, "InvalidSessionError"),
                                     (400, {"error": "invalid_request"}, "AuthError"),
                                     (401, {"error": "invalid_client"}, "AuthError"),
                                     (403, {}, "AuthError"), (503, {}, "AuthError")):
            with self.subTest(code=code, body=body):
                oauth = MercedesOAuthClient(session=FakeSession([FakeResponse(code, body)]))
                with self.assertRaises(AuthError) as caught:
                    oauth.refresh("synthetic-refresh")
                self.assertEqual(type(caught.exception).__name__, expected)

    def test_401_is_typed_on_both_endpoints(self):
        for method, args in (("list_vehicles", ("synthetic-token",)),
                             ("get_vehicle_attributes", ("SYNTHETIC", "synthetic-token"))):
            with self.subTest(method=method):
                api = telemetry.VehicleApi(session=FakeSession([FakeResponse(401)]))
                with self.assertRaises(telemetry.ApiError) as caught:
                    getattr(api, method)(*args)
                self.assertEqual(type(caught.exception).__name__, "UnauthorizedError")


class DaemonTests(unittest.TestCase):
    def setUp(self):
        self.args = SimpleNamespace(debug=False, region="eu", timeout=1, poll_interval=60,
                                    backoff_max=3600, once=True, vin=None)
        self.session = {"access_token": "synthetic-old", "refresh_token": "synthetic-refresh",
                        "expires_at": 9999999999}
        self.new_session = dict(self.session, access_token="synthetic-new")
        self.load = self.patch("load_session", return_value=self.session)
        self.save = self.patch("save_session")
        self.clear = self.patch("clear_session")
        self.write = self.patch("write_status")
        p = mock.patch("omarchy_mercedes.state.read_status", return_value={"state": "ok"})
        self.addCleanup(p.stop)
        p.start()
        p = mock.patch.object(daemon.time, "sleep", side_effect=AssertionError("unexpected sleep"))
        self.addCleanup(p.stop)
        self.sleep = p.start()
        self.patch("log")
        self.api = self.patch("VehicleApi").return_value
        self.api.list_vehicles.return_value = [{"vin": "SYNTHETIC"}]
        self.api.get_vehicle_attributes.return_value = {"attributes": {"soc": {"value": 42, "ts_ms": 1000}}}
        self.oauth = self.patch("MercedesOAuthClient").return_value
        self.oauth.refresh.return_value = self.new_session

    def test_unauthorized_refreshes_and_retries_once(self):
        self.api.list_vehicles.side_effect = [telemetry.UnauthorizedError("401"), [{"vin": "SYNTHETIC"}]]
        self.assertEqual(daemon.run_loop(self.args), 0)
        self.oauth.refresh.assert_called_once_with(self.session["refresh_token"])
        self.save.assert_called_once_with(self.new_session, expected=self.session)
        self.assertEqual(self.api.list_vehicles.call_args_list,
                         [mock.call("synthetic-old"), mock.call("synthetic-new")])
        self.clear.assert_not_called()
        self.assertEqual(self.write.call_args.args[0]["state"], "ok")

    def test_ambiguous_auth_failure_never_clears_session(self):
        self.session["expires_at"] = 0
        self.oauth.refresh.side_effect = AuthError("token endpoint rejected request: HTTP 401")
        daemon.run_loop(self.args)
        self.clear.assert_not_called()
        self.assertEqual(self.write.call_args.args[0]["state"], "error")

    def test_confirmed_invalid_grant_clears_session(self):
        from omarchy_mercedes.oauth_client import InvalidSessionError
        self.session["expires_at"] = 0
        self.oauth.refresh.side_effect = InvalidSessionError("invalid grant")
        daemon.run_loop(self.args)
        self.clear.assert_called_once_with(expected=self.session)
        self.assertEqual(self.write.call_args.args[0]["state"], "no-session")

    def test_once_reports_failures(self):
        for error in (telemetry.ApiError("HTTP 503"), AuthError("network"), RuntimeError("unexpected")):
            with self.subTest(error=type(error).__name__):
                self.api.list_vehicles.side_effect = error
                self.assertEqual(daemon.run_loop(self.args), 1)
        self.api.list_vehicles.side_effect = None
        self.api.get_vehicle_attributes.return_value = {"attributes": {}}
        self.assertEqual(daemon.run_loop(self.args), 1)
        self.load.return_value = None
        self.assertEqual(daemon.run_loop(self.args), 2)
        self.load.return_value = self.session
        self.session["expires_at"] = 0
        from omarchy_mercedes.oauth_client import InvalidSessionError
        self.oauth.refresh.side_effect = InvalidSessionError("invalid grant")
        self.assertEqual(daemon.run_loop(self.args), 2)

    def test_login_is_picked_up_between_polls(self):
        self.args.once = False
        self.load.side_effect = [None, None, self.session]
        self.sleep.side_effect = [None, None, KeyboardInterrupt]
        with self.assertRaises(KeyboardInterrupt):
            daemon.run_loop(self.args)
        self.assertEqual([c.args[0]["state"] for c in self.write.call_args_list],
                         ["no-session", "no-session", "ok"])
        self.api.list_vehicles.assert_called_once_with("synthetic-old")
        self.clear.assert_not_called()

    def test_replaced_valid_session_is_picked_up(self):
        self.args.once = False
        self.load.side_effect = [self.session, self.new_session]
        self.sleep.side_effect = [None, KeyboardInterrupt]
        with self.assertRaises(KeyboardInterrupt):
            daemon.run_loop(self.args)
        self.assertEqual(self.api.list_vehicles.call_args_list,
                         [mock.call("synthetic-old"), mock.call("synthetic-new")])

    def test_expiry_refresh_is_not_repeated_on_401(self):
        self.session["expires_at"] = 0
        self.api.list_vehicles.side_effect = telemetry.UnauthorizedError("401")
        self.assertEqual(daemon.run_loop(self.args), 1)
        self.oauth.refresh.assert_called_once()
        self.clear.assert_not_called()

    def test_repeated_401_stops_after_one_refresh_without_deleting_grant(self):
        self.api.list_vehicles.side_effect = telemetry.UnauthorizedError("401")
        self.assertEqual(daemon.run_loop(self.args), 1)
        self.assertEqual(self.api.list_vehicles.call_count, 2)
        self.oauth.refresh.assert_called_once()
        self.clear.assert_not_called()

    def test_widget_401_retries_with_refreshed_token(self):
        good = self.api.get_vehicle_attributes.return_value
        self.api.get_vehicle_attributes.side_effect = [telemetry.UnauthorizedError("401"), good]
        self.assertEqual(daemon.run_loop(self.args), 0)
        self.oauth.refresh.assert_called_once()
        self.assertEqual(self.api.get_vehicle_attributes.call_args_list,
                         [mock.call("SYNTHETIC", "synthetic-old"), mock.call("SYNTHETIC", "synthetic-new")])

    def test_valid_session_does_not_refresh(self):
        self.assertEqual(daemon.run_loop(self.args), 0)
        self.oauth.refresh.assert_not_called()
        self.save.assert_not_called()
        self.clear.assert_not_called()

    def patch(self, name, **kwargs):
        p = mock.patch.object(daemon, name, **kwargs)
        self.addCleanup(p.stop)
        return p.start()

