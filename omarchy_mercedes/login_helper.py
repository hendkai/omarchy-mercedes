"""Experimental interactive login; no callback listener or protocol handler.

Manual fallback: inspect the final redirect's Location in browser developer
Network tools (not the address bar), then paste it into a hidden TTY prompt.
No real Mercedes login/OTP compatibility has been verified.
"""
from __future__ import annotations

import os
import secrets
import select
import sys
import termios
import time
import urllib.parse
import webbrowser

from .api_constants import LOGIN_APP_ID, LOGIN_BASE_URL, OAUTH_REDIRECT_URI, OAUTH_SCOPE
from .oauth_client import MercedesOAuthClient


class LoginAborted(RuntimeError):
    pass


def _hidden_input(prompt: str, timeout_s: float) -> str:
    """Canonical TTY input without echo; fail closed if no private terminal.

    Unlike getpass's stdin fallback this NEVER falls back to echoed input.
    select enforces a deadline even while the user has not pressed Enter.
    """
    fd = os.open('/dev/tty', os.O_RDWR | os.O_NOCTTY)
    original = termios.tcgetattr(fd)
    try:
        hidden = termios.tcgetattr(fd)
        hidden[3] &= ~(termios.ECHO | termios.ECHONL)
        termios.tcsetattr(fd, termios.TCSAFLUSH, hidden)
        os.write(fd, prompt.encode())
        deadline = time.monotonic() + timeout_s
        parts = bytearray()
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([fd], [], [], remaining)[0]:
                raise LoginAborted('Zeitlimit für verdeckte Eingabe überschritten')
            chunk = os.read(fd, 4096)
            if not chunk:
                raise LoginAborted('Eingabe abgebrochen (EOF)')
            parts.extend(chunk)
            if len(parts) > 16384:
                raise LoginAborted('Eingabe zu lang')
            if b'\n' in parts:
                return parts.decode().strip()
    finally:
        termios.tcsetattr(fd, termios.TCSAFLUSH, original)
        os.write(fd, b'\n')
        os.close(fd)


def _parse_callback(line: str, expected_state: str) -> str:
    parsed = urllib.parse.urlparse(line.strip())
    expected = urllib.parse.urlparse(OAUTH_REDIRECT_URI)
    if (parsed.scheme, parsed.netloc, parsed.path) != (expected.scheme, expected.netloc, expected.path):
        raise LoginAborted('Vollständige rismycar-Callback-URL erforderlich; nicht die Login-URL')
    query = urllib.parse.parse_qs(parsed.query)
    if query.get('state') != [expected_state]:
        raise LoginAborted('OAuth state fehlt oder passt nicht zu diesem Login-Versuch')
    if 'error' in query or len(query.get('code', [])) != 1:
        raise LoginAborted('Autorisierung abgelehnt oder Code fehlt')
    return query['code'][0]


def login_browser(region: str = 'eu', timeout_s: int = 300, open_browser: bool = True) -> dict:
    verifier, challenge = MercedesOAuthClient._pkce()
    state = secrets.token_urlsafe(32)
    params = {
        'client_id': LOGIN_APP_ID[region], 'code_challenge': challenge,
        'code_challenge_method': 'S256', 'redirect_uri': OAUTH_REDIRECT_URI,
        'response_type': 'code', 'scope': OAUTH_SCOPE, 'locale': 'de-DE',
        'state': state,
    }
    auth_url = f"{LOGIN_BASE_URL[region]}/as/authorization.oauth2?{urllib.parse.urlencode(params)}"
    print('EXPERIMENTELL: echter Mercedes-Login/2FA nicht verifiziert.')
    print('Kein Callback-Listener/xdg-Handler. Manueller Fallback:')
    print('Browser-Entwicklertools > Netzwerk öffnen, Log beibehalten, dann Login durchführen.')
    print('Die finale Redirect-Antwort auswählen und deren Location-Header kopieren.')
    print('Die Adressleiste zeigt oft NICHT den Callback. Nicht die Login-URL kopieren.')
    print('Nur die vollständige rismycar://login-callback?code=…&state=… URL verdeckt einfügen.')
    print('Falls kein solcher Redirect sichtbar ist: abbrechen, nicht umgehen. Keine HAR-Datei teilen.')
    print('Danach Browser-Netzwerkprotokoll/Clipboard löschen. Strg+C bricht ab.')
    opened = False
    if open_browser:
        try:
            opened = webbrowser.open(auth_url)
        except Exception:
            pass
    if not opened:
        print('Login-URL manuell öffnen:')
        print(auth_url)
    try:
        callback = _hidden_input('Callback-URL (verdeckt): ', timeout_s)
    except OSError as e:
        raise LoginAborted('Privates interaktives Terminal erforderlich; kein stdin-Fallback') from e
    code = _parse_callback(callback, state)
    return MercedesOAuthClient(region=region).exchange_code(code, verifier)


def login_password(region: str = 'eu') -> dict:
    """Experimental CIAM password flow; does not bypass OTP, MFA or CAPTCHA."""
    email = input('Mercedes Account E-Mail: ').strip()
    if not email:
        raise LoginAborted('Keine E-Mail angegeben')
    password = _hidden_input('Passwort (verdeckt): ', 300)
    if not password:
        raise LoginAborted('Kein Passwort angegeben')
    return MercedesOAuthClient(region=region).login_with_password(email, password)
