"""Login callback validation + XDG handoff tests (task t_3f9d429b).

All fixtures are SYNTHETIC (fake codes/states/URLs modeled on the public
OAuth2 flow). No real API calls, no real tokens. The regression at the core
of this task: pasting the authorization START url must be rejected and the
token exchange must NEVER be called with it.
"""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from omarchy_mercedes import callback as cb  # noqa: E402
from omarchy_mercedes import login_helper as lh  # noqa: E402
from omarchy_mercedes.login_helper import LoginAborted, login_browser  # noqa: E402

# --- synthetic fixtures (never real values) --------------------------------

STATE = "SYNTHSTATE_" + "x" * 16
OTHER_STATE = "SYNTHOTHER_" + "y" * 16
CODE = "SYNTHCODE123abc_DEF-456"
GOOD_CALLBACK = f"rismycar://login-callback?code={CODE}&state={STATE}"
START_URL = (
    "https://id.mercedes-benz.com/as/authorization.oauth2"
    "?client_id=62778dc4-1de3-44f4-af95-115f06a3a008"
    "&code_challenge=SYNTHCHALLENGE000000000000000000000000000000000000000"
    "&code_challenge_method=S256"
    "&redirect_uri=rismycar%3A%2F%2Flogin-callback"
    "&response_type=code"
    "&scope=email+profile+ciam-uid+phone+openid+offline_access"
    "&state=SYNTHSTATE0000000000000000000000"
    "&locale=de-DE"
)


def isolated_env(testcase):
    """Point all runtime/config dirs at a temp dir; return (env_dict, base)."""
    base = Path(tempfile.mkdtemp(prefix="omarchy-mercedes-test-"))
    env = {
        "OMARCHY_MERCEDES_RUNTIME_DIR": str(base / "run"),
        "XDG_DATA_HOME": str(base / "share"),
        "XDG_CONFIG_HOME": str(base / "cfg"),
    }
    patcher = mock.patch.dict(os.environ, env)
    patcher.start()
    testcase.addCleanup(patcher.stop)
    testcase.addCleanup(_rmtree, base)
    return env, base


def _rmtree(path):
    import shutil

    shutil.rmtree(path, ignore_errors=True)


class TestParsePastedCallback(unittest.TestCase):
    """Core regression: START url / web urls / foreign schemes rejected."""

    def test_start_url_rejected_with_explanation(self):
        with self.assertRaises(cb.InvalidCallback) as cm:
            cb.parse_pasted_callback(START_URL, expected_state=STATE)
        msg = str(cm.exception)
        self.assertIn("START-Adresse", msg)
        self.assertIn("rismycar://login-callback", msg)

    def test_start_url_message_contains_no_secrets(self):
        with self.assertRaises(cb.InvalidCallback) as cm:
            cb.parse_pasted_callback(START_URL)
        msg = str(cm.exception)
        self.assertNotIn("code_challenge", msg)

    def test_any_https_url_rejected(self):
        for url in ("https://example.com/", "http://id.mercedes-benz.com/other",
                    "https://login.mercedes-benz.com/as/authorization.oauth2?x=1"):
            with self.assertRaises(cb.InvalidCallback):
                cb.parse_pasted_callback(url)

    def test_valid_full_callback(self):
        self.assertEqual(cb.parse_pasted_callback(GOOD_CALLBACK, STATE), CODE)

    def test_valid_bare_code(self):
        self.assertEqual(cb.parse_pasted_callback(CODE), CODE)

    def test_code_equals_form(self):
        self.assertEqual(cb.parse_pasted_callback(f"code={CODE}"), CODE)

    def test_quoted_callback(self):
        self.assertEqual(cb.parse_pasted_callback(f'"{GOOD_CALLBACK}"'), CODE)

    def test_state_mismatch_rejected_no_secret_leak(self):
        url = f"rismycar://login-callback?code={CODE}&state={OTHER_STATE}"
        with self.assertRaises(cb.InvalidCallback) as cm:
            cb.parse_pasted_callback(url, expected_state=STATE)
        msg = str(cm.exception)
        self.assertIn("state", msg)
        self.assertNotIn(CODE, msg)
        self.assertNotIn(OTHER_STATE, msg)

    def test_missing_state_rejected_when_expected(self):
        url = f"rismycar://login-callback?code={CODE}"
        with self.assertRaises(cb.InvalidCallback):
            cb.parse_pasted_callback(url, expected_state=STATE)

    def test_error_callback_rejected(self):
        url = "rismycar://login-callback?error=access_denied&error_description=nope"
        with self.assertRaises(cb.InvalidCallback) as cm:
            cb.parse_pasted_callback(url)
        self.assertIn("access_denied", str(cm.exception))

    def test_empty_or_multiple_code_values(self):
        for q in ("", "code=", "code=a&code=b"):
            url = f"rismycar://login-callback?{q}"
            with self.assertRaises(cb.InvalidCallback):
                cb.parse_pasted_callback(url)

    def test_wrong_scheme_or_host(self):
        for url in ("mycar://login-callback?code=x",
                    "rismycar://other?code=x",
                    "rismycar://login-callback/x?code=y"):
            with self.assertRaises(cb.InvalidCallback):
                cb.parse_pasted_callback(url)

    def test_empty_none_whitespace_input(self):
        for raw in (None, "", "   ", "\n\t", "synthetic code with spaces"):
            with self.assertRaises(cb.InvalidCallback):
                cb.parse_pasted_callback(raw)

    def test_garbage_query_fragment(self):
        with self.assertRaises(cb.InvalidCallback):
            cb.parse_pasted_callback("foo=bar&baz=1")

    def test_code_charset_enforced(self):
        # characters outside the OAuth code charset must be refused
        with self.assertRaises(cb.InvalidCallback):
            cb.parse_pasted_callback("bad/code!with*meta")
        self.assertEqual(cb.parse_pasted_callback("aB-_._~+-0000"), "aB-_._~+-0000")


class TestMarkerAndSpool(unittest.TestCase):
    def setUp(self):
        isolated_env(self)

    def test_token_validation_blocks_traversal(self):
        for bad in (None, "", "../evil", "abc", "z" * 33, "ZZ" * 16, "a/b"):
            with self.assertRaises(ValueError):
                cb.validate_session_token(bad)
        good = "a" * 32
        self.assertEqual(cb.validate_session_token(good), good)

    def test_paths_stay_inside_runtime_dir(self):
        tok = cb.session_token()
        base = cb.runtime_dir().resolve()
        self.assertTrue(cb.marker_path(tok).resolve().parent == base)
        self.assertTrue(cb.spool_path(tok).resolve().parent == base)
        with self.assertRaises(ValueError):
            cb.marker_path("../evil")

    def test_runtime_dir_permissions(self):
        cb.runtime_dir()
        mode = cb.runtime_dir().stat().st_mode & 0o777
        self.assertEqual(mode, 0o700)

    def test_spool_roundtrip_and_modes(self):
        tok = cb.session_token()
        cb.marker_create(tok)
        p = cb.marker_path(tok)
        self.assertTrue(p.exists())
        self.assertEqual(p.stat().st_mode & 0o777, 0o600)
        cb.write_spool(tok, GOOD_CALLBACK)
        sp = cb.spool_path(tok)
        self.assertEqual(sp.stat().st_mode & 0o777, 0o600)
        self.assertEqual(cb.read_spool(tok), GOOD_CALLBACK)
        # consumed exactly once
        self.assertIsNone(cb.read_spool(tok))
        cb.marker_remove(tok)
        self.assertFalse(p.exists())
        cb.marker_remove(tok)  # idempotent


class TestCallbackMain(unittest.TestCase):
    """Simulated desktop handoff (the xdg-open invocation)."""

    def setUp(self):
        isolated_env(self)

    def test_no_active_session_refused(self):
        tok = cb.session_token()
        rc = cb.main(["--session", tok, GOOD_CALLBACK])
        self.assertEqual(rc, 1)
        self.assertFalse(cb.spool_path(tok).exists())

    def test_active_session_spools_url_without_echoing_secret(self):
        tok = cb.session_token()
        cb.marker_create(tok)
        with mock.patch("sys.stdout", new_callable=lambda: __import__("io").StringIO()) as out, \
             mock.patch("sys.stderr", new_callable=lambda: __import__("io").StringIO()):
            rc = cb.main(["--session", tok, GOOD_CALLBACK])
        self.assertEqual(rc, 0)
        self.assertEqual(cb.read_spool(tok), GOOD_CALLBACK)
        self.assertNotIn(CODE, out.getvalue())

    def test_invalid_url_refused_not_spooled(self):
        tok = cb.session_token()
        cb.marker_create(tok)
        rc = cb.main(["--session", tok, START_URL])
        self.assertEqual(rc, 1)
        self.assertFalse(cb.spool_path(tok).exists())

    def test_bad_session_token_rejected(self):
        self.assertEqual(cb.main(["--session", "../evil", GOOD_CALLBACK]), 2)

    def test_marker_required_even_with_valid_shape(self):
        # valid URL but login already finished -> refused, nothing written
        tok = cb.session_token()
        cb.marker_create(tok)
        cb.marker_remove(tok)
        rc = cb.main(["--session", tok, GOOD_CALLBACK])
        self.assertEqual(rc, 1)
        self.assertFalse(cb.spool_path(tok).exists())


class TestDesktopHandler(unittest.TestCase):
    def setUp(self):
        isolated_env(self)

    def _runner(self, responses):
        calls = []

        def run(cmd, **kw):
            calls.append(cmd)
            r = responses.pop(0)
            return SimpleNamespace(returncode=r.get("rc", 0),
                                   stdout=r.get("stdout", ""),
                                   stderr=r.get("stderr", ""))

        return run, calls

    def test_install_creates_handler_and_restores_none(self):
        tok = cb.session_token()
        run, calls = self._runner([
            {"rc": 0, "stdout": ""},   # query: no previous default
            {"rc": 0},                 # default set
        ])
        installed, prev = cb.install_desktop_handler(
            tok, runner=run, input_fn=self.fail, which=lambda n: "/usr/bin/xdg-mime",
            platform_="linux",
        )
        self.assertTrue(installed)
        self.assertIsNone(prev)
        f = cb.desktop_file_path(tok)
        self.assertTrue(f.exists())
        content = f.read_text()
        self.assertIn("omarchy_mercedes.callback --session ", content)
        self.assertIn("%u", content)
        self.assertIn(cb.MIME_TYPE, content)
        # clean argv: xdg-mime called with plain list, never a shell string
        self.assertEqual(calls[0], ["xdg-mime", "query", "default", cb.MIME_TYPE])
        self.assertEqual(calls[1][:3], ["xdg-mime", "default", f.name])

        # restore: file removed, no foreign default to restore
        cb.restore_desktop_handler(tok, prev, runner=run, which=lambda n: "x",
                                   platform_="linux")
        self.assertFalse(f.exists())

    def test_existing_handler_never_silently_replaced(self):
        tok = cb.session_token()
        run, calls = self._runner([{"rc": 0, "stdout": "foreign-app.desktop"}])
        installed, prev = cb.install_desktop_handler(
            tok, runner=run, input_fn=lambda prompt: "n",
            which=lambda n: "/usr/bin/xdg-mime", platform_="linux",
        )
        self.assertFalse(installed)
        self.assertEqual(len(calls), 1)  # only the query, no default overwrite
        self.assertFalse(cb.desktop_file_path(tok).exists())

    def test_existing_handler_replaced_with_consent_and_restored(self):
        tok = cb.session_token()
        run, calls = self._runner([
            {"rc": 0, "stdout": "foreign-app.desktop"},
            {"rc": 0},  # set ours
            {"rc": 0},  # restore foreign
        ])
        installed, prev = cb.install_desktop_handler(
            tok, runner=run, input_fn=lambda prompt: "j",
            which=lambda n: "/usr/bin/xdg-mime", platform_="linux",
        )
        self.assertTrue(installed)
        self.assertEqual(prev, "foreign-app.desktop")
        cb.restore_desktop_handler(tok, prev, runner=run, which=lambda n: "x",
                                   platform_="linux")
        self.assertEqual(calls[-1], ["xdg-mime", "default", "foreign-app.desktop",
                                     cb.MIME_TYPE])

    def test_consent_eof_means_no(self):
        tok = cb.session_token()

        def eof_input(prompt):
            raise EOFError

        run, _ = self._runner([{"rc": 0, "stdout": "foreign-app.desktop"}])
        installed, prev = cb.install_desktop_handler(
            tok, runner=run, input_fn=eof_input,
            which=lambda n: "/usr/bin/xdg-mime", platform_="linux",
        )
        self.assertFalse(installed)

    def test_non_linux_and_missing_xdg_mime_are_noops(self):
        tok = cb.session_token()
        run, _ = self._runner([])
        installed, prev = cb.install_desktop_handler(
            tok, runner=run, input_fn=self.fail, which=lambda n: "x",
            platform_="darwin",
        )
        self.assertFalse(installed)
        self.assertIsNone(prev)
        installed, prev = cb.install_desktop_handler(
            tok, runner=run, input_fn=self.fail, which=lambda n: None,
            platform_="linux",
        )
        self.assertFalse(installed)
        self.assertIsNone(prev)
        self.assertFalse(cb.desktop_file_path(tok).exists())

    def test_restore_cleans_mimeapps_list_line(self):
        tok = cb.session_token()
        cfg = Path(os.environ["XDG_CONFIG_HOME"]) / "mimeapps.list"
        cfg.parent.mkdir(parents=True, exist_ok=True)
        ours = f"{cb.MIME_TYPE}=omarchy-mercedes-login-{tok}.desktop"
        cfg.write_text(
            "[Default Applications]\n"
            "text/plain=other.desktop\n"
            f"{ours}\n"
            "x-scheme-handler/https=browser.desktop\n",
            encoding="utf-8",
        )
        cb.restore_desktop_handler(tok, None, runner=lambda *a, **k: SimpleNamespace(
            returncode=0, stdout="", stderr=""), which=lambda n: "x", platform_="linux")
        content = cfg.read_text()
        self.assertNotIn(ours, content)
        self.assertIn("other.desktop", content)
        self.assertIn("browser.desktop", content)

    def test_failed_registration_removes_file(self):
        tok = cb.session_token()
        run, _ = self._runner([
            {"rc": 0, "stdout": ""},
            {"rc": 1},  # xdg-mime default fails
        ])
        installed, prev = cb.install_desktop_handler(
            tok, runner=run, input_fn=self.fail, which=lambda n: "/usr/bin/xdg-mime",
            platform_="linux",
        )
        self.assertFalse(installed)
        self.assertFalse(cb.desktop_file_path(tok).exists())


class TestLoginBrowserFlow(unittest.TestCase):
    """login_browser end-to-end with mocked exchange and delivery paths."""

    def setUp(self):
        isolated_env(self)
        # deterministic state so synthetic callback fixtures match the login
        state_patcher = mock.patch.object(lh.secrets, "token_urlsafe",
                                          return_value=STATE)
        state_patcher.start()
        self.addCleanup(state_patcher.stop)
        # hermetic: never touch real xdg/mime registration from tests
        patches = [
            mock.patch.object(lh.cb, "install_desktop_handler",
                              side_effect=lambda *a, **k: (False, None)),
            mock.patch.object(lh.cb, "restore_desktop_handler"),
            mock.patch.object(lh.webbrowser, "open"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.exchange = mock.patch.object(
            lh.MercedesOAuthClient, "exchange_code",
            return_value={"access_token": "SYNTH-AT", "refresh_token": "SYNTH-RT",
                          "expires_in": 3600},
        )
        mock_x = self.exchange.start()
        self.addCleanup(self.exchange.stop)
        self.mock_exchange = mock_x

    def _deliver_via_spool(self, url, delay=0.05):
        """Simulate the OS handler writing the callback to the spool."""
        delivered = threading.Event()

        def worker():
            run_dir = Path(os.environ["OMARCHY_MERCEDES_RUNTIME_DIR"])
            deadline = time.time() + 5
            while time.time() < deadline and not delivered.is_set():
                markers = list(run_dir.glob("*.active"))
                if markers:
                    tok = markers[0].name[:-len(".active")]
                    cb.write_spool(tok, url)
                    delivered.set()
                    return
                time.sleep(0.02)

        t = threading.Thread(target=worker, daemon=True)
        t.start()
        return delivered

    def _quiet_stdin(self):
        """Watcher prompt blocks forever (no manual input in these tests)."""
        return mock.patch.object(lh, "_readline_hidden_quiet",
                                 side_effect=lambda prompt="": time.sleep(30))

    def test_valid_callback_via_spool_reaches_exchange(self):
        self._deliver_via_spool(GOOD_CALLBACK)
        with self._quiet_stdin():
            tok = login_browser("eu", timeout_s=6, open_browser=False)
        self.assertEqual(tok["access_token"], "SYNTH-AT")
        args, kwargs = self.mock_exchange.call_args
        self.assertEqual(args[0], CODE)  # the CODE, not the whole URL
        self.assertTrue(args[1])  # a PKCE verifier was passed
        # cleanup: no active marker left behind
        run_dir = Path(os.environ["OMARCHY_MERCEDES_RUNTIME_DIR"])
        self.assertEqual(list(run_dir.glob("*.active")), [])

    def test_start_url_via_spool_never_reaches_exchange(self):
        # THE regression from the user report: the whole authorization START
        # url was sent to the token endpoint (HTTP 400). It must be rejected
        # before any HTTP call.
        self._deliver_via_spool(START_URL)
        with self._quiet_stdin():
            with self.assertRaises(LoginAborted):
                login_browser("eu", timeout_s=2, open_browser=False)
        self.assertFalse(self.mock_exchange.called)

    def test_state_mismatch_via_spool_rejected(self):
        self._deliver_via_spool(
            f"rismycar://login-callback?code={CODE}&state={OTHER_STATE}")
        with self._quiet_stdin():
            with self.assertRaises(LoginAborted):
                login_browser("eu", timeout_s=2, open_browser=False)
        self.assertFalse(self.mock_exchange.called)

    def test_pasted_start_url_rejected_and_exchange_not_called(self):
        answers = iter([START_URL, START_URL, START_URL])
        with mock.patch.object(lh, "_readline_hidden_quiet",
                               side_effect=lambda prompt="": next(answers)):
            with self.assertRaises(LoginAborted):
                login_browser("eu", timeout_s=6, open_browser=False)
        self.assertFalse(self.mock_exchange.called)

    def test_pasted_valid_callback_reaches_exchange(self):
        self._deliver_via_spool  # not used; manual paste path here
        with mock.patch.object(lh, "_readline_hidden_quiet",
                               return_value=GOOD_CALLBACK):
            tok = login_browser("eu", timeout_s=6, open_browser=False)
        self.assertEqual(tok["access_token"], "SYNTH-AT")
        args, _ = self.mock_exchange.call_args
        self.assertEqual(args[0], CODE)

    def test_eof_aborts_quickly(self):
        with mock.patch.object(lh, "_readline_hidden_quiet", return_value=""):
            t0 = time.time()
            with self.assertRaises(LoginAborted):
                login_browser("eu", timeout_s=30, open_browser=False)
        self.assertLess(time.time() - t0, 5)

    def test_timeout_raises_aborted(self):
        with self._quiet_stdin():
            t0 = time.time()
            with self.assertRaises(LoginAborted) as cm:
                login_browser("eu", timeout_s=1, open_browser=False)
        self.assertIn("timeout", str(cm.exception))
        self.assertGreaterEqual(time.time() - t0, 0.9)
        self.assertFalse(self.mock_exchange.called)

    def test_keyboard_interrupt_propagates(self):
        def interrupted(prompt=""):
            raise KeyboardInterrupt

        with mock.patch.object(lh, "_readline_hidden_quiet", side_effect=interrupted):
            with self.assertRaises(KeyboardInterrupt):
                login_browser("eu", timeout_s=6, open_browser=False)
        self.assertFalse(self.mock_exchange.called)

    def test_handler_failure_still_allows_paste_login(self):
        # install_desktop_handler raised -> login must continue via paste
        with mock.patch.object(lh.cb, "install_desktop_handler",
                               side_effect=RuntimeError("boom")):
            with mock.patch.object(lh, "_readline_hidden_quiet",
                                   return_value=GOOD_CALLBACK):
                tok = login_browser("eu", timeout_s=6, open_browser=False)
        self.assertEqual(tok["access_token"], "SYNTH-AT")

    def test_authorization_url_contains_state_and_pkce(self):
        captured = {}

        def fake_open(url):
            captured["url"] = url

        with mock.patch.object(lh.webbrowser, "open", side_effect=fake_open):
            with mock.patch.object(lh, "_readline_hidden_quiet", return_value=""):
                with self.assertRaises(LoginAborted):
                    login_browser("eu", timeout_s=3, open_browser=True)
        url = captured.get("url", "")
        self.assertIn("state=", url)
        self.assertIn("code_challenge=", url)
        self.assertIn("code_challenge_method=S256", url)
        self.assertIn("response_type=code", url)


if __name__ == "__main__":
    unittest.main()
