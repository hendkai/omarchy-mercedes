"""Interactive OAuth login: PKCE/state, temporary XDG handoff, hidden input.

The single-threaded POSIX input loop restores terminal attributes on success,
timeout, cancellation and exceptions. No credential input runs in daemon threads.
"""
from __future__ import annotations

import base64
import getpass
import hashlib
import os
import secrets
import select
import sys
import time
import urllib.parse
import webbrowser

from . import callback as cb
from .api_constants import LOGIN_APP_ID, LOGIN_BASE_URL, OAUTH_REDIRECT_URI, OAUTH_SCOPE
from .oauth_client import MercedesOAuthClient

try:
    import requests
except ImportError:
    requests = None


class LoginAborted(RuntimeError):
    pass


def _pkce_pair():
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge


def _system_locale(default: str = "de-DE") -> str:
    import locale
    try:
        value = locale.getlocale()[0]
    except Exception:
        value = None
    return value.split(".")[0].replace("_", "-") if value else default


def _wait_for_code(token, state, timeout_s, handler_installed):
    """Poll callback and input together; never leave a hidden-input thread alive."""
    fd = None
    original = None
    termios = None
    try:
        try:
            fd = sys.stdin.fileno()
            if os.isatty(fd):
                import termios
                original = termios.tcgetattr(fd)
                hidden = list(original)
                hidden[3] &= ~(termios.ECHO | termios.ECHONL)
                termios.tcsetattr(fd, termios.TCSANOW, hidden)
        except (AttributeError, OSError, ValueError):
            fd = None
        print("Callback oder Code bei Bedarf hier einfügen (verdeckt). Strg+C bricht ab.", flush=True)
        deadline = time.monotonic() + timeout_s
        buffer = b""
        attempts = 0
        while time.monotonic() < deadline:
            spooled = cb.read_spool(token)
            if spooled:
                try:
                    if not spooled.lower().startswith("rismycar://"):
                        raise cb.InvalidCallback("Der System-Handler muss eine vollständige Callback-Adresse liefern.")
                    code = cb.parse_pasted_callback(spooled, expected_state=state)
                    print("\nCallback vom System-Handler übernommen.", flush=True)
                    return code
                except cb.InvalidCallback as error:
                    print(f"\nCallback nicht akzeptiert: {error}", flush=True)
            remaining = max(0, min(.1, deadline-time.monotonic()))
            if fd is None:
                if not handler_installed:
                    raise LoginAborted("Keine interaktive Eingabe und kein Callback-Handler verfügbar.")
                time.sleep(remaining)
                continue
            readable, _, _ = select.select([fd], [], [], remaining)
            if not readable:
                continue
            chunk = os.read(fd, 4096)
            if not chunk:
                fd = None
                if not handler_installed:
                    raise LoginAborted("Eingabe geschlossen — Login abgebrochen.")
                continue
            buffer += chunk
            if len(buffer) > 8192:
                buffer = b""
                attempts += 1
                print("Eingabe zu lang — bitte nur den Callback einfügen.", flush=True)
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                try:
                    return cb.parse_pasted_callback(line.decode("utf-8", errors="replace"), expected_state=state)
                except cb.InvalidCallback as error:
                    attempts += 1
                    print(f"Eingabe nicht akzeptiert: {error}", flush=True)
            if attempts >= 3:
                raise LoginAborted("Zu viele ungültige Eingaben — Login bitte neu starten.")
        raise LoginAborted("Zeitüberschreitung — Login bitte neu starten.")
    finally:
        if original is not None and termios is not None:
            # Discard unread hidden input before restoring echo on every exit.
            # Keep the original fd even when EOF disabled further input polling.
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSAFLUSH, original)


def login_browser(region: str = "eu", timeout_s: int = 300, open_browser: bool = True,
                  input_fn=None, runner=None) -> dict:
    with cb.login_lock():
        cb.cleanup_stale_handlers(runner=runner)
        return _login_browser(region, timeout_s, open_browser, input_fn, runner)


def _login_browser(region, timeout_s, open_browser, input_fn, runner):
    if requests is None:
        raise LoginAborted("'requests' required for login")
    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(24)
    params = {
        "client_id": LOGIN_APP_ID[region], "code_challenge": challenge,
        "code_challenge_method": "S256", "redirect_uri": OAUTH_REDIRECT_URI,
        "response_type": "code", "scope": OAUTH_SCOPE, "state": state,
        "locale": _system_locale(),
    }
    auth_url = f"{LOGIN_BASE_URL[region]}/as/authorization.oauth2?{urllib.parse.urlencode(params)}"
    token = cb.session_token()
    previous = None
    try:
        cb.marker_create(token)
        installed, previous = cb.install_desktop_handler(token, runner=runner, input_fn=input_fn)
        print("Mercedes-Benz koppeln", flush=True)
        print("Melde dich im Browser bei Mercedes an. Die Rückleitung wird automatisch übernommen."
              if installed else "Melde dich im Browser an und füge den rismycar://-Callback hier ein.", flush=True)
        print("Die https://-Anmeldeseite selbst ist KEIN Callback.", flush=True)
        # Register the handler before opening the browser (cached browser sessions
        # may redirect immediately). An unavailable browser gets an explicit fallback.
        opened = False
        if open_browser:
            try:
                opened = webbrowser.open(auth_url)
            except webbrowser.Error:
                pass
        if not opened:
            print("Öffne diese Anmeldeadresse im Browser (nicht als Callback einfügen):", flush=True)
            print(auth_url, flush=True)
        code = _wait_for_code(token, state, timeout_s, installed)
        print("Code validiert — Anmeldung wird abgeschlossen.", flush=True)
        return MercedesOAuthClient(region=region).exchange_code(code, verifier)
    finally:
        try:
            cb.marker_remove(token)
        finally:
            cb.restore_desktop_handler(token, previous, runner=runner)


def login_password(region: str = "eu") -> dict:
    email = input("Mercedes Account E-Mail: ").strip()
    if not email:
        raise LoginAborted("no email given")
    password = getpass.getpass("Passwort (Eingabe verdeckt): ")
    if not password:
        raise LoginAborted("no password given")
    return MercedesOAuthClient(region=region).login_with_password(email, password)
