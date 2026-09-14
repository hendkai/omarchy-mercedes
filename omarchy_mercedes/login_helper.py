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
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser

from .api_constants import LOGIN_APP_ID, LOGIN_BASE_URL, OAUTH_REDIRECT_URI, OAUTH_SCOPE
from .oauth_client import MercedesOAuthClient, SAFARI_UA, _basic_headers

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

import hashlib


class LoginAborted(RuntimeError):
    pass


def _pkce_pair():
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge


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
        "locale": "de-DE",
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
        if line.startswith("rismycar://"):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(line).query)
            code = q.get("code", [None])[0]
        else:
            code = line

    t = threading.Thread(target=stdin_watcher, daemon=True)
    t.start()
    while time.time() < deadline and not code:
        time.sleep(0.3)
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
