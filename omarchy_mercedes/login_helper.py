"""Interactive login helper.

Two flows, both real Mercedes flows (no invented endpoints):

A) BROWSER (preferred, supports 2FA/MFA): we start a PKCE authorization
   request with an OAuth ``state`` nonce and open the Mercedes login page in
   the user's browser. After login the IdP redirects to
   ``rismycar://login-callback?code=...&state=...``. Desktop Linux normally
   has no app for that scheme (the browser shows "Open With… / No apps
   installed"), so during the login we register a TEMPORARY XDG handler that
   hands the callback to this process (see omarchy_mercedes/callback.py;
   the previous handler is restored afterwards, nothing is silently
   overwritten). If the handler cannot be registered, the fallback is the
   verdeckte (non-echoing) paste prompt in the terminal: the user pastes the
   full rismycar:// callback URL or only the code value. Every input is
   validated BEFORE anything reaches the token endpoint - the login start
   URL (https://id.mercedes-benz.com/as/authorization.oauth2?...) is
   rejected with an explanation, and the OAuth state must match this login.

B) PASSWORD (headless): CIAM password grant flow as implemented by
   mbapi2020; fails with TwoFactorRequiredError when OTP is enforced.

Neither flow puts passwords or codes on the command line; all secret input
uses getpass-style (non-echoing) prompts. Tokens go to the session store
(keyring/0600 file), never to the repo, logs or chat.
"""

from __future__ import annotations

import base64
import getpass
import hashlib
import secrets
import threading
import time
import urllib.parse
import webbrowser

from . import callback as cb
from .api_constants import LOGIN_APP_ID, LOGIN_BASE_URL, OAUTH_REDIRECT_URI, OAUTH_SCOPE
from .oauth_client import MercedesOAuthClient

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None


class LoginAborted(RuntimeError):
    pass


def _pkce_pair():
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge


def _readline_hidden_quiet(prompt: str = "") -> str:
    """Read one line from stdin without echoing it (getpass-style).

    getpass turns off terminal echo and falls back to /dev/tty when stdin is
    redirected; it never echoes the typed/pasted secret back. Returns '' on
    EOF (caller decides what that means).
    """
    try:
        return getpass.getpass(prompt if prompt.endswith(" ") else prompt + " ")
    except EOFError:
        return ""


def _print_instructions(handler_installed: bool, xdg_note: bool) -> None:
    print("Mercedes-Benz Login (Browser)")
    print("=============================")
    print("1. Es öffnet sich die Mercedes-Anmeldeseite im Browser.")
    print("2. Melde dich dort an (inkl. 2FA, falls eingerichtet).")
    print("3. Nach der Anmeldung leitet Mercedes zu rismycar://login-callback?code=…")
    print("   weiter.")
    if handler_installed:
        print("   Unter Linux/Omarchy wird diese Rückleitung automatisch an dieses")
        print("   Terminal übergeben (temporärer System-Handler, wird danach wieder")
        print("   entfernt). Der Browser-Dialog 'Open With…' ist also KEIN Fehler;")
        print("   wähle dort ggf. 'omarchy-mercedes Login' als App.")
        print("   Erfolgt keine Übergabe, kannst du unten im Terminal die Adresse")
        print("   oder den Code manuell (verdeckt) einfügen.")
    else:
        print("   Desktop-Browser brechen dort oft mit 'Open With… / No apps")
        print("   installed' ab — das ist erwartbar. WICHTIG: Die Adresse aus der")
        print("   Adressleiste ist NICHT zu jedem Zeitpunkt die richtige! Richtig ist")
        print("   NUR eine Adresse, die mit rismycar://login-callback?code=… beginnt")
        print("   (oder nur der Wert nach code=). Die Anmelde-Startseite")
        print("   (https://id.mercedes-benz.com/as/authorization…) gehört NICHT hierher.")
        if xdg_note:
            print("   Hinweis: Ein automatischer System-Handler konnte nicht registriert")
            print("   werden (xdg-mime fehlt/nicht nutzbar) — manuelle Übergabe nötig.")


def _prompt_pasted_code(state: str, max_attempts: int = 3):
    """Ask for pasted callback input until valid or attempts exhausted."""
    from .callback import InvalidCallback

    for attempt in range(max_attempts):
        raw = _readline_hidden_quiet(
            "\nCallback-Adresse (rismycar://…) oder nur Code-Wert einfügen "
            f"[Versuch {attempt + 1}/{max_attempts}, Eingabe verdeckt]: "
        )
        try:
            return cb.parse_pasted_callback(raw, expected_state=state)
        except InvalidCallback as e:
            print(f"  Eingabe nicht akzeptiert: {e}")
            if raw == "":  # EOF — do not loop on a closed stdin
                raise LoginAborted(
                    "keine Eingabe möglich (stdin geschlossen) — Login abgebrochen"
                )
    raise LoginAborted("zu viele ungültige Eingaben — Login bitte neu starten")


def login_browser(region: str = "eu", timeout_s: int = 300, open_browser: bool = True,
                  input_fn=None, runner=None) -> dict:
    """Browser login: user authenticates at Mercedes, we catch the code.

    PKCE + OAuth state; the callback arrives either via the temporary XDG
    handler (spool file) or via the validated, non-echoed paste prompt.
    Returns the token dict (stored by caller). Raises LoginAborted on
    timeout/EOF/too many invalid inputs.
    """
    if requests is None:
        raise LoginAborted("'requests' required for login (pip install requests)")

    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(24)
    base = LOGIN_BASE_URL[region]
    client_id = LOGIN_APP_ID[region]

    params = {
        "client_id": client_id,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "redirect_uri": OAUTH_REDIRECT_URI,
        "response_type": "code",
        "scope": OAUTH_SCOPE,
        "state": state,
        "locale": "de-DE",
    }
    auth_url = f"{base}/as/authorization.oauth2?{urllib.parse.urlencode(params)}"

    token = cb.session_token()
    handler_installed = False
    previous_default = None
    try:
        cb.marker_create(token)
        try:
            handler_installed, previous_default = cb.install_desktop_handler(
                token, runner=runner, input_fn=input_fn
            )
        except Exception:
            handler_installed = False
        xdg_note = not handler_installed

        _print_instructions(handler_installed, xdg_note)

        if open_browser:
            webbrowser.open(auth_url)
        else:
            print(f"\nLogin-URL:\n{auth_url}\n")

        print("\nWarte auf Autorisierungs-Code (Strg+C zum Abbrechen)...")
        deadline = time.time() + timeout_s
        code = None
        aborted = None
        interrupted = False

        def stdin_watcher():
            # daemon thread: manual paste fallback, validated BEFORE use
            nonlocal code, aborted, interrupted
            try:
                code = _prompt_pasted_code(state)
            except LoginAborted as e:
                aborted = str(e)
            except KeyboardInterrupt:
                interrupted = True
            except BaseException:
                return

        t = threading.Thread(target=stdin_watcher, daemon=True)
        t.start()

        while time.time() < deadline and not code and not aborted and not interrupted:
            spooled = cb.read_spool(token)
            if spooled:
                try:
                    code = cb.parse_pasted_callback(spooled, expected_state=state)
                    print("\nCallback vom System-Handler übernommen.")
                except cb.InvalidCallback as e:
                    # never retry the same bad URL; keep waiting for valid input
                    print(f"\n  Übergebener Callback ungültig: {e}")
            time.sleep(0.3)

        if interrupted:
            raise KeyboardInterrupt
        if not code:
            raise LoginAborted(
                "timeout waiting for authorization code — Login bitte neu starten"
            )
        final_code = code  # snapshot: watcher thread must not race the exchange
        print("Code erhalten (validiert), tausche gegen Token ...")

        oauth = MercedesOAuthClient(region=region)
        return oauth.exchange_code(final_code, verifier)
    finally:
        try:
            cb.marker_remove(token)
        except Exception:
            pass
        try:
            cb.restore_desktop_handler(token, previous_default, runner=runner)
        except Exception:
            pass


def login_password(region: str = "eu") -> dict:
    """Headless password login (no 2FA accounts; browser flow handles OTP)."""
    email = input("Mercedes Account E-Mail: ").strip()
    if not email:
        raise LoginAborted("no email given")
    password = getpass.getpass("Passwort (Eingabe verdeckt): ")
    if not password:
        raise LoginAborted("no password given")
    oauth = MercedesOAuthClient(region=region)
    return oauth.login_with_password(email, password)
