"""Interactive login helper.

Two flows, both real Mercedes flows (no invented endpoints):

A) BROWSER (preferred, supports 2FA/MFA): we start a PKCE authorization
   request, open the Mercedes login page in the user's browser, run a tiny
   localhost HTTP listener; the page redirects to rismycar://login-callback
   which the desktop normally cannot catch - so we also register a temporary
   xdg-mime handler (Linux) or instruct manual code paste (any OS).

B) PASSWORD (headless): CIAM password grant flow as implemented by
   mbapi2020; fails with TwoFactorRequiredError when OTP is enforced.

Neither flow puts passwords or codes on the command line; input uses
getpass-style prompts. Tokens go to the session store (keyring/0600 file),
never to the repo, logs or chat.
"""

from __future__ import annotations

import base64
import json
import secrets
import shlex
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser
from pathlib import Path

from .api_constants import LOGIN_APP_ID, LOGIN_BASE_URL, OAUTH_REDIRECT_URI, OAUTH_SCOPE
from .oauth_client import MercedesOAuthClient, SAFARI_UA, _basic_headers

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

import hashlib


class LoginAborted(RuntimeError):
    pass


class _RismycarHandler:
    """Temporarily register an xdg handler that captures rismycar:// URLs.

    GNOME/KDE have no app for the rismycar:// scheme, so the OAuth redirect
    dies in a useless "No Apps available" dialog and the code is lost. We
    register a tiny desktop entry for the duration of the login that writes
    the full callback URL to a capture file; removed again afterwards.
    """

    def __init__(self) -> None:
        import tempfile

        self.tmpdir = Path(tempfile.mkdtemp(prefix="omarchy-mercedes-login-"))
        self.capture_file = self.tmpdir / "callback.url"
        self.desktop_name = "omarchy-mercedes-capture.desktop"
        self.desktop_path = Path.home() / ".local/share/applications" / self.desktop_name
        self._prev_default: str | None = None

    def install(self) -> bool:
        try:
            import shutil
            import subprocess

            if not shutil.which("xdg-mime"):
                return False
            apps_dir = self.desktop_path.parent
            apps_dir.mkdir(parents=True, exist_ok=True)
            script = self.tmpdir / "capture.sh"
            script.write_text(
                "#!/bin/sh\n"
                "printf '%s' \"$1\" > " + shlex.quote(str(self.capture_file)) + "\n"
            )
            script.chmod(0o755)
            self.desktop_path.write_text(
                "[Desktop Entry]\n"
                "Type=Application\n"
                "Name=omarchy-mercedes login capture\n"
                f"Exec={script} %u\n"
                "NoDisplay=true\n"
                "X-GNOME-UsesPortal=true\n"
                "MimeType=x-scheme-handler/rismycar;\n"
            )
            prev = subprocess.run(
                ["xdg-mime", "query", "default", "x-scheme-handler/rismycar"],
                capture_output=True, text=True,
            ).stdout.strip()
            self._prev_default = prev or None
            subprocess.run(
                ["xdg-mime", "default", self.desktop_name, "x-scheme-handler/rismycar"],
                check=True, capture_output=True,
            )
            # The portal daemon caches scheme handlers; without a refresh
            # Chromium's OpenURI still shows the "No apps available" dialog.
            subprocess.run(
                ["update-desktop-database", str(apps_dir)], capture_output=True
            )
            subprocess.run(
                ["systemctl", "--user", "try-restart", "xdg-desktop-portal-gtk.service"],
                capture_output=True,
            )
            time.sleep(4)  # let the portal come back up before the browser redirects
            return True
        except Exception:
            return False

    def read(self) -> str | None:
        try:
            url = self.capture_file.read_text().strip()
            return url or None
        except OSError:
            return None

    def remove(self) -> None:
        import shutil
        import subprocess

        try:
            if self._prev_default:
                subprocess.run(
                    ["xdg-mime", "default", self._prev_default,
                     "x-scheme-handler/rismycar"],
                    capture_output=True,
                )
        except Exception:
            pass
        try:
            self.desktop_path.unlink(missing_ok=True)
        except OSError:
            pass
        shutil.rmtree(self.tmpdir, ignore_errors=True)


def _pkce_pair():
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge


def _system_locale(default: str = "de-DE") -> str:
    """OS-Locale als IANA-Tag (de_DE -> de-DE); Fallback default."""
    import locale as _locale

    try:
        loc = _locale.getlocale()[0] or _locale.getdefaultlocale()[0]
    except Exception:
        loc = None
    if not loc:
        return default
    return loc.split(".")[0].replace("_", "-")


def login_browser(region: str = "eu", timeout_s: int = 300, open_browser: bool = True) -> dict:
    """Browser login: user authenticates at Mercedes, we catch the code.

    We listen on 127.0.0.1:<free port> and use redirect_uri
    http://localhost:<port>/cb ONLY as a local helper - Mercedes requires the
    rismycar:// scheme for this client_id, so after authentication the IdP
    shows/redirects to rismycar://login-callback?code=... . Desktop browsers
    cannot hand that to us automatically, so we ALSO watch for the manual
    fallback: the user pastes the code (or the full rismycar:// URL) into the
    terminal prompt when the browser cannot complete the handoff.

    Returns the token dict (stored by caller).
    """
    if requests is None:
        raise LoginAborted("'requests' required for login (pip install requests)")

    verifier, challenge = _pkce_pair()
    base = LOGIN_BASE_URL[region]
    client_id = LOGIN_APP_ID[region]

    params = {
        "client_id": client_id,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "redirect_uri": OAUTH_REDIRECT_URI,
        "response_type": "code",
        "scope": OAUTH_SCOPE,
        "locale": _system_locale(),
    }
    auth_url = f"{base}/as/authorization.oauth2?{urllib.parse.urlencode(params)}"

    print("Mercedes-Benz Login (Browser)")
    print("=============================")
    print("1. Es öffnet sich die Mercedes-Anmeldeseite im Browser.")
    print("2. Nach erfolgreicher Anmeldung versucht der Browser, zu")
    print("   rismycar://login-callback?code=... umzuleiten.")
    print("3. Desktop-Browser brechen dort oft ab - KEIN PROBLEM:")
    print("   kopiere in dem Fall die komplette Adresse aus der Adressleiste")
    print("   (oder den Code darin) und füge sie hier ein.")

    if open_browser:
        webbrowser.open(auth_url)
    else:
        print(f"\nLogin-URL:\n{auth_url}\n")

    print("\nWarte auf Autorisierungs-Code (Strg+C zum Abbrechen)...")
    handler = _RismycarHandler()
    handler_installed = handler.install()
    if handler_installed:
        print("rismycar://-Handler aktiv: der Code wird automatisch übernommen.")
    else:
        print("Kein automatischer Handler möglich - Code bitte manuell einfügen.")
    deadline = time.time() + timeout_s
    code = None

    # stdin watcher: user pastes rismycar://... or raw code
    def stdin_watcher():
        nonlocal code
        try:
            line = sys.stdin.readline()
        except Exception:
            return
        line = line.strip()
        if not line:
            return
        if "authorization.oauth2" in line or line.startswith("https://"):
            print(
                "Das war die Login-Start-URL, nicht der Code.\n"
                "Richtig: die Adresse nach dem Login (beginnt mit rismycar://)\n"
                "oder nur den Code selbst (code=...). Nochmal einfügen:"
            )
            line2 = sys.stdin.readline().strip()
            line = line2 or line
        if line.startswith("rismycar://"):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(line).query)
            code = q.get("code", [None])[0]
        elif "code=" in line:
            q = urllib.parse.parse_qs(urllib.parse.urlparse(line).query)
            code = q.get("code", [None])[0]
        else:
            code = line

    t = threading.Thread(target=stdin_watcher, daemon=True)
    t.start()
    captured_url = None
    while time.time() < deadline and not code:
        if handler_installed:
            captured_url = handler.read()
            if captured_url:
                q = urllib.parse.parse_qs(urllib.parse.urlparse(captured_url).query)
                code = q.get("code", [None])[0]
                if code:
                    print("Code automatisch empfangen (rismycar://-Handler).")
                    break
                if "error" in (q or {}):
                    print(f"Login-Fehler von Mercedes: {q.get('error')}")
                    handler.remove()
                    raise LoginAborted(f"authorization error: {q.get('error')}")
        time.sleep(0.3)
    handler.remove()
    if not code:
        raise LoginAborted("timeout waiting for authorization code")
    print("Code erhalten, tausche gegen Token ...")

    oauth = MercedesOAuthClient(region=region)
    return oauth.exchange_code(code, verifier)


def login_password(region: str = "eu") -> dict:
    """Headless password login (no 2FA accounts; browser flow handles OTP)."""
    import getpass

    email = input("Mercedes Account E-Mail: ").strip()
    if not email:
        raise LoginAborted("no email given")
    password = getpass.getpass("Passwort (Eingabe verdeckt): ")
    if not password:
        raise LoginAborted("no password given")
    oauth = MercedesOAuthClient(region=region)
    return oauth.login_with_password(email, password)
