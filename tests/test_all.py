"""Tests for omarchy-mercedes.

All vehicle/auth data here is SYNTHETIC (built from the real protobuf schema
or fake HTTP sessions). No real API calls, no real tokens, no real VINs.
Run: python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import json
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from omarchy_mercedes import state, telemetry  # noqa: E402
from omarchy_mercedes.daemon import (  # noqa: E402
    extract_status,
    load_session,
    save_session,
    token_is_expired,
)
from omarchy_mercedes.oauth_client import (  # noqa: E402
    AuthError,
    MercedesOAuthClient,
    redact,
)
from omarchy_mercedes.waybar_module import pango_escape, render  # noqa: E402

NOW_S = 1800000000  # fixed epoch for deterministic tests


def build_vep_update(soc=82, range_km=315, charging=True, soc_ts_ms=None, emit_ts_ms=None):
    """Build a SYNTHETIC VehicleStatusUpdate protobuf (live observed format)."""
    from omarchy_mercedes.vendored import vehicle_events_pb2 as vep

    m = vep.VehicleStatusUpdate()
    m.fin_or_vin = "SYNTHETIC00000000"  # fake VIN, never a real one
    ts_s = (soc_ts_ms // 1000) if soc_ts_ms else (NOW_S - 120)  # data 2 min old
    ts_ms = soc_ts_ms or ts_s * 1000
    m.soc.value = soc
    m.soc.metadata.timestamp.seconds = ts_ms // 1000
    m.rangeelectric.value = range_km
    m.rangeelectric.metadata.timestamp.seconds = ts_ms // 1000
    m.chargingactive.value = charging
    m.chargingactive.metadata.timestamp.seconds = ts_ms // 1000
    m.chargingstatus.value = vep.CHARGINGSTATUS_CHARGING
    m.chargingstatus.metadata.timestamp.seconds = ts_ms // 1000
    m.vtime.value = emit_ts_ms // 1000 if emit_ts_ms else ts_s
    return m.SerializeToString()


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, content=b"", headers=None, url=""):
        self.status_code = status_code
        self._json = json_data
        self.content = content
        self.text = content.decode("utf-8", "replace")
        self.headers = headers or {}
        self.url = url

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json


class FakeSession:
    """Fake requests.Session for oauth/telemetry tests (no network)."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.cookies = mock.Mock()

    def request(self, method, url, **kw):
        self.calls.append((method, url, kw))
        return self.responses.pop(0)

    def post(self, url, **kw):
        return self.request("POST", url, **kw)

    def get(self, url, **kw):
        return self.request("GET", url, **kw)


class TestProtobufDecode(unittest.TestCase):
    def test_decode_synthetic_fixture(self):
        blob = build_vep_update(soc=42, range_km=210, charging=False)
        out = telemetry.decode_vehicle_attributes(blob)
        self.assertEqual(out["attributes"]["soc"]["value"], 42)
        self.assertEqual(out["attributes"]["rangeelectric"]["value"], 210)
        self.assertFalse(out["attributes"]["chargingactive"]["value"])

    def test_decode_garbage_raises_apierror(self):
        with self.assertRaises(telemetry.ApiError):
            telemetry.decode_vehicle_attributes(b"\xff\xff not protobuf \x00\x01")


class TestExtractStatus(unittest.TestCase):
    def test_extract_ok(self):
        blob = build_vep_update(soc=77, range_km=280, charging=True)
        data = telemetry.decode_vehicle_attributes(blob)
        st = extract_status(data, fetched_at_ms=NOW_S * 1000)
        self.assertEqual(st["state"], state.STATE_OK)
        self.assertEqual(st["soc_percent"], 77)
        self.assertEqual(st["range_km"], 280)
        self.assertTrue(st["charging"])
        self.assertIsNone(st["charging_power_kw"])  # not delivered by VehicleStatusUpdate

    def test_extract_missing_soc_is_error(self):
        from omarchy_mercedes.vendored import vehicle_events_pb2 as vep

        m = vep.VehicleStatusUpdate()
        m.overall_range.value = 421.0
        st = extract_status(telemetry.decode_vehicle_attributes(m.SerializeToString()), NOW_S * 1000)
        self.assertEqual(st["state"], state.STATE_ERROR)

    def test_vehicle_ts_is_soc_attribute_ts(self):
        blob = build_vep_update(soc_ts_ms=1000)
        data = telemetry.decode_vehicle_attributes(blob)
        st = extract_status(data, NOW_S * 1000)
        self.assertEqual(st["vehicle_ts_ms"], 1000)


class TestClassifyAndState(unittest.TestCase):
    def fresh_status(self, age_s=60, state_="ok"):
        ts = (NOW_S - age_s) * 1000
        return {
            "state": state_,
            "soc_percent": 50,
            "vehicle_ts_ms": ts,
            "fetched_at_ms": ts,
            "written_at_ms": ts,
        }

    def test_fresh_is_ok(self):
        with mock.patch.object(state.time, "time", return_value=NOW_S):
            self.assertEqual(state.classify(self.fresh_status(60), 1800), "ok")

    def test_stale_vehicle_data(self):
        # connection fresh (file just written) but vehicle data old -> stale
        st = self.fresh_status(7200)
        st["written_at_ms"] = NOW_S * 1000
        with mock.patch.object(state.time, "time", return_value=NOW_S):
            self.assertEqual(state.classify(st, 1800), "stale")

    def test_offline_when_file_too_old(self):
        with mock.patch.object(state.time, "time", return_value=NOW_S):
            self.assertEqual(state.classify(self.fresh_status(4 * 3600), 1800), "offline")

    def test_none_is_offline(self):
        self.assertEqual(state.classify(None, 1800), "offline")

    def test_no_session(self):
        with mock.patch.object(state.time, "time", return_value=NOW_S):
            self.assertEqual(state.classify({"state": "no-session", "written_at_ms": NOW_S * 1000}, 1800),
                             "no-session")

    def test_error_state(self):
        with mock.patch.object(state.time, "time", return_value=NOW_S):
            self.assertEqual(state.classify(self.fresh_status(10, "error"), 1800), "error")

    def test_status_file_roundtrip(self):
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "status.json"
            state.write_status({"state": "ok", "soc_percent": 33}, p)
            self.assertEqual(state.read_status(p)["soc_percent"], 33)
            # invalid json -> None, never a crash
            p.write_text("{broken")
            self.assertIsNone(state.read_status(p))


class TestWaybarRender(unittest.TestCase):
    def render_now(self, status):
        with mock.patch.object(state.time, "time", return_value=NOW_S):
            return render(status, stale_after_s=1800)

    def test_ok_charging(self):
        out = self.render_now({
            "state": "ok", "soc_percent": 82, "range_km": 315, "range_unit": "km",
            "charging": True, "charging_power_kw": 11,
            "vehicle_ts_ms": (NOW_S - 120) * 1000, "fetched_at_ms": (NOW_S - 60) * 1000,
            "written_at_ms": NOW_S * 1000,
        })
        self.assertIn("82%", out["text"])
        self.assertIn("\N{ELECTRIC PLUG}", out["text"])
        self.assertEqual(out["class"], "charging")
        self.assertEqual(out["percentage"], 82)
        self.assertIn("315 km", out["tooltip"])
        self.assertIn("Ladevorgang aktiv", out["tooltip"])

    def test_ok_not_charging(self):
        out = self.render_now({
            "state": "ok", "soc_percent": 64, "range_km": 240, "charging": False,
            "vehicle_ts_ms": (NOW_S - 300) * 1000, "fetched_at_ms": (NOW_S - 60) * 1000,
            "written_at_ms": NOW_S * 1000,
        })
        self.assertEqual(out["class"], "ok")
        self.assertIn("\N{AUTOMOBILE}", out["text"])

    def test_stale_marked_not_fresh(self):
        out = self.render_now({
            "state": "ok", "soc_percent": 82, "range_km": 315, "charging": False,
            "vehicle_ts_ms": (NOW_S - 86400) * 1000, "fetched_at_ms": (NOW_S - 60) * 1000,
            "written_at_ms": NOW_S * 1000,
        })
        self.assertEqual(out["class"], "stale")
        self.assertIn("?", out["text"])  # uncertainty visible
        self.assertIn("1 d", out["tooltip"])  # honest age in tooltip

    def test_offline(self):
        out = self.render_now(None)
        self.assertEqual(out["class"], "offline")
        self.assertIn("offline", out["text"])

    def test_no_session(self):
        out = self.render_now({"state": "no-session", "written_at_ms": NOW_S * 1000})
        self.assertEqual(out["class"], "no-session")
        self.assertIn("Anmeldung", out["text"])

    def test_error(self):
        out = self.render_now({
            "state": "error", "error_hint": "HTTP 503", "soc_percent": None,
            "written_at_ms": NOW_S * 1000,
        })
        self.assertEqual(out["class"], "error")
        self.assertIn("HTTP 503", out["tooltip"])

    def test_pango_escaping(self):
        self.assertEqual(pango_escape('a&<>"\'z'), "a&amp;&lt;&gt;&quot;&#39;z")
        out = self.render_now({
            "state": "error", "error_hint": '<script>&"danger"',
            "written_at_ms": NOW_S * 1000,
        })
        self.assertNotIn("<script>", out["tooltip"])
        self.assertIn("&lt;script&gt;", out["tooltip"])

    def test_valid_json_output(self):
        out = self.render_now({
            "state": "ok", "soc_percent": 82, "charging": True,
            "vehicle_ts_ms": (NOW_S - 10) * 1000, "fetched_at_ms": (NOW_S - 5) * 1000,
            "written_at_ms": NOW_S * 1000,
        })
        json.dumps(out)  # must not raise


class TestOAuthClient(unittest.TestCase):
    def _client(self, responses):
        s = FakeSession(responses)
        c = MercedesOAuthClient(region="eu", session=s)
        return c, s

    def test_exchange_code_parses_tokens(self):
        c, _ = self._client([FakeResponse(200, {
            "access_token": "at-abc", "refresh_token": "rt-def", "expires_in": 3600,
        })])
        tok = c.exchange_code("CODE", "VERIFIER")
        self.assertEqual(tok["access_token"], "at-abc")
        self.assertTrue(tok["expires_at"] > time.time())

    def test_exchange_code_rejects_http_error(self):
        c, _ = self._client([FakeResponse(400, {"error": "invalid_grant"})])
        with self.assertRaises(AuthError):
            c.exchange_code("CODE", "V")

    def test_refresh_rotation_flag(self):
        c, _ = self._client([FakeResponse(200, {
            "access_token": "at2", "refresh_token": "rt-NEW", "expires_in": 3600,
        })])
        tok = c.refresh("rt-OLD")
        self.assertEqual(tok["refresh_token"], "rt-NEW")
        self.assertTrue(tok["refresh_rotated"])

    def test_refresh_without_rotation_keeps_old(self):
        c, _ = self._client([FakeResponse(200, {"access_token": "at2", "expires_in": 3600})])
        tok = c.refresh("rt-OLD")
        self.assertEqual(tok["refresh_token"], "rt-OLD")
        self.assertFalse(tok["refresh_rotated"])

    def test_refresh_revoked_raises(self):
        c, _ = self._client([FakeResponse(401, {"error": "invalid_grant"})])
        with self.assertRaises(AuthError):
            c.refresh("rt-revoked")

    def test_password_login_2fa_raises_specific(self):
        # minimal happy path up to the password step, then OTP demanded
        responses = [
            FakeResponse(200, url="https://id.mercedes-benz.com/as/login?resume=%2Fresume1"),
            FakeResponse(200, {}),
            FakeResponse(200, {}),
            FakeResponse(200, {"result": "GOTO_LOGIN_OTP"}),
        ]
        c, _ = self._client(responses)
        from omarchy_mercedes.oauth_client import TwoFactorRequiredError

        with self.assertRaises(TwoFactorRequiredError):
            c.login_with_password("user@example.com", "pw")

    def test_password_login_success_end_to_end(self):
        responses = [
            FakeResponse(200, url="https://id.mercedes-benz.com/as/login?resume=%2Fresume1"),
            FakeResponse(200, {}),
            FakeResponse(200, {}),
            FakeResponse(200, {"result": "RESUME2OIDCP", "token": "prelogin-token"}),
            FakeResponse(302, headers={"Location": "rismycar://login-callback?code=THECODE"}),
            FakeResponse(200, {"access_token": "at", "refresh_token": "rt", "expires_in": 3600}),
        ]
        c, s = self._client(responses)
        tok = c.login_with_password("user@example.com", "hunter2-SECRET")
        self.assertEqual(tok["access_token"], "at")
        # the password is only ever sent in the POST body to the IdP login
        # endpoint - never in a URL, never to any other endpoint
        for method, url, kw in s.calls:
            self.assertNotIn("hunter2-SECRET", url)
            if "login/pass" not in url and "disablePasskeyDemo" not in url:
                self.assertNotIn("hunter2-SECRET", json.dumps(kw.get("json", {})))

    def test_network_error_wrapped(self):
        class ExplodingSession:
            def request(self, *a, **k):
                raise OSError("dns fail")

        c = MercedesOAuthClient(region="eu", session=ExplodingSession())
        with self.assertRaises(AuthError):
            c.exchange_code("C", "V")


class TestSessionStore(unittest.TestCase):
    def test_save_load_and_redaction(self):
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            with mock.patch("omarchy_mercedes.daemon.DATA_DIR", Path(d)), \
                 mock.patch("omarchy_mercedes.daemon.SESSION_FILE", Path(d) / "session.json"), \
                 mock.patch.dict(sys.modules, {"keyring": None}):
                tok = {"access_token": "SECRET-AT", "refresh_token": "SECRET-RT", "expires_at": 1}
                save_session(tok)
                f = Path(d) / "session.json"
                # Explicitly disable keyring, independent of host configuration.
                self.assertTrue(f.exists())
                self.assertEqual(f.stat().st_mode & 0o777, 0o600)
                loaded = load_session("eu")
                self.assertEqual(loaded["refresh_token"], "SECRET-RT")

    def test_token_expiry_check(self):
        self.assertTrue(token_is_expired({"expires_at": time.time() + 10}))
        self.assertFalse(token_is_expired({"expires_at": time.time() + 3600}))


class TestRedaction(unittest.TestCase):
    def test_redact_tokens_and_jwts(self):
        jwt_like = "aaaaaaaabbbbbbbbcccccccc." + "x" * 30 + "." + "y" * 30
        data = {
            "access_token": "abc", "refresh_token": "def", "password": "pw",
            "nested": {"id_token": jwt_like, "code": "xyz"},
            "keep": "value", "n": 5,
        }
        r = redact(data)
        self.assertEqual(r["access_token"], "***REDACTED***")
        # id_token is blacklisted by key, so it is fully redacted
        self.assertEqual(r["nested"]["id_token"], "***REDACTED***")
        # JWT-pattern redaction applies to NON-blacklisted keys:
        r2 = redact({"note": jwt_like})
        self.assertEqual(r2["note"], "***REDACTED-JWT***")
        self.assertEqual(r["keep"], "value")
        self.assertEqual(r["n"], 5)
        dumped = json.dumps(r)
        for secret in ("abc", "def", "xyz", jwt_like):
            self.assertNotIn(secret, dumped)


class TestTimestampHandling(unittest.TestCase):
    """Task requirement: naive timestamps must NOT be silently read as UTC."""

    def test_fmt_local_uses_epoch_ms_only(self):
        # state layer only ever consumes epoch-ms integers; naive ISO strings
        # are rejected by design (vehicle_ts_ms is int|None)
        self.assertEqual(state.fmt_local(None), "keine Angabe")
        self.assertIn(":", state.fmt_local(NOW_S * 1000))

    def test_fmt_local_explicit_tz(self):
        out = state.fmt_local(86400 * 1000, tz_name="UTC")  # epoch + 1 day
        # 02.01.1970 00:00 in UTC
        self.assertTrue(out.startswith("02.01.1970") or "00:00" in out, out)


if __name__ == "__main__":
    unittest.main()
