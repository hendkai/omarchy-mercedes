"""rismycar:// callback handoff for the browser login (Linux/Omarchy).

Why this module exists: after a successful Mercedes login the IdP redirects
to ``rismycar://login-callback?code=...&state=...``. Desktop Linux has no app
for that custom scheme, so the browser/portal shows an "Open With" dialog
with nothing to choose ("No apps installed that can open ...") and the
authorization code is lost. During ``omarchy-mercedes login`` we therefore
register a TEMPORARY XDG handler for the scheme:

    xdg-mime default -> omarchy-mercedes-login-<session>.desktop
    Exec=<python> -m omarchy_mercedes.callback --session <hex32> %u

The handler is a separate short-lived process: it validates the URL shape,
writes it to a per-login spool file (0600, on tmpfs when XDG_RUNTIME_DIR
exists) and prints no secret. The interactive login polls the spool, checks
the OAuth ``state`` binding and performs the PKCE token exchange
(see login_helper.login_browser).

Security properties (by design):
- No shell anywhere: subprocess calls use argv lists only; the .desktop
  Exec line is static text plus a validated hex session token ([0-9a-f]{32}),
  so no shell interpolation of remote data is possible.
- An existing handler for the scheme is NEVER silently replaced: the previous
  default is queried, the user is asked for consent, and the previous default
  is restored when the login ends (any exit path).
- Session binding: the handler only accepts a callback while the login's
  marker file exists; the marker is removed on every exit path. A callback
  arriving with no active login is refused and not written anywhere.
- Codes/tokens/state never appear in stdout, stderr or logs.
- Pasted input validation (parse_pasted_callback) rejects the authorization
  START url and any other web address BEFORE anything reaches the token
  endpoint - pasting the start url was the cause of the reported HTTP 400.
"""

from __future__ import annotations

import argparse
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

SCHEME = "rismycar"
CALLBACK_HOST = "login-callback"
MIME_TYPE = "x-scheme-handler/rismycar"
DESKTOP_PREFIX = "omarchy-mercedes-login-"
_XDG_TIMEOUT = 10  # seconds per xdg-* call

_TOKEN_RE = re.compile(r"[0-9a-f]{32}")
# OAuth authorization codes: unreserved chars only, sane length
_BARE_CODE_RE = re.compile(r"[A-Za-z0-9._~+-]{8,2048}")


class InvalidCallback(ValueError):
    """Pasted input is not a usable authorization callback.

    str(e) is a user-facing German explanation. It deliberately never
    contains the pasted value itself (it may be a partial secret).
    """


# --------------------------------------------------------------------------
# session / runtime plumbing
# --------------------------------------------------------------------------

def validate_session_token(token) -> str:
    """Return the token iff it is a hex32 value (no path traversal possible)."""
    token = str(token or "")
    if not _TOKEN_RE.fullmatch(token):
        raise ValueError("invalid session token")
    return token


def session_token() -> str:
    """Random per-login session token (hex32; safe to embed in Exec lines)."""
    return secrets.token_hex(16)


def runtime_dir(env=None) -> Path:
    """Per-user 0700 runtime dir for marker/spool files (tmpfs preferred)."""
    env = os.environ if env is None else env
    override = env.get("OMARCHY_MERCEDES_RUNTIME_DIR")
    if override:
        base = Path(override)
    elif env.get("XDG_RUNTIME_DIR"):
        base = Path(env["XDG_RUNTIME_DIR"]) / "omarchy-mercedes"
    else:
        uid = os.getuid() if hasattr(os, "getuid") else "user"
        base = Path(tempfile.gettempdir()) / f"omarchy-mercedes-{uid}"
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == "posix" and hasattr(os, "geteuid"):
        if base.stat().st_uid != os.geteuid():
            raise RuntimeError(f"runtime dir not owned by current user: {base}")
    os.chmod(base, 0o700)
    return base


def marker_path(token, env=None) -> Path:
    return runtime_dir(env) / f"{validate_session_token(token)}.active"


def spool_path(token, env=None) -> Path:
    return runtime_dir(env) / f"{validate_session_token(token)}.url"


def marker_create(token, env=None) -> None:
    """Announce 'a login with this token is running' to the handler."""
    p = marker_path(token, env)
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w"):
        pass
    os.chmod(p, 0o600)


def marker_remove(token, env=None) -> None:
    try:
        marker_path(token, env).unlink()
    except FileNotFoundError:
        pass


def write_spool(token, url, env=None) -> None:
    """Atomically write the callback URL for the login (0600, no echo)."""
    p = spool_path(token, env)
    tmp = p.parent / f".{secrets.token_hex(8)}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(url)
        os.replace(tmp, p)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def read_spool(token, env=None):
    """Consume and return the spooled callback URL (or None)."""
    p = spool_path(token, env)
    tmp = p.parent / f".{secrets.token_hex(8)}.consumed"
    try:
        os.replace(p, tmp)
    except FileNotFoundError:
        return None
    try:
        return tmp.read_text(encoding="utf-8").strip() or None
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


# --------------------------------------------------------------------------
# pasted-input validation
# --------------------------------------------------------------------------

def parse_pasted_callback(raw, expected_state=None) -> str:
    """Validate pasted login input and return the authorization code.

    Accepts either the full ``rismycar://login-callback?code=...&state=...``
    URL (state must match when expected_state is given) or a bare code value.
    Rejects the authorization START url, any other web address, foreign
    schemes, wrong hosts/paths, error callbacks, empty/multiple code values
    and state mismatches - each with an actionable German explanation.
    The pasted value is never echoed back in the message.
    """
    if raw is None:
        raise InvalidCallback("Keine Eingabe erhalten.")
    text = str(raw).strip()
    for q in ('"', "'"):
        if len(text) >= 2 and text.startswith(q) and text.endswith(q):
            text = text[1:-1].strip()
    if not text:
        raise InvalidCallback("Leere Eingabe — bitte die Callback-Adresse oder den Code-Wert einfügen.")

    low = text.lower()
    if low.startswith(("http://", "https://")):
        u = urlparse(text)
        host = (u.hostname or "").lower()
        if "id.mercedes-benz.com" in host and (u.path or "").startswith("/as/authorization"):
            raise InvalidCallback(
                "Das ist die START-Adresse des Logins (die Anmeldeseite selbst), "
                "nicht der Callback nach der Anmeldung — sie gehört nicht ins Terminal. "
                "Nach der fertigen Anmeldung erscheint unter Linux eine automatische "
                "Übergabe bzw. eine Adresse, die mit rismycar://login-callback beginnt; "
                "nur diese (oder nur der Wert nach code=) ist hier richtig. Zeigt die "
                "Adressleiste weiterhin diese id.mercedes-benz.com-Adresse, wurde die "
                "Anmeldung im Browser noch nicht abgeschlossen oder die Rückleitung "
                "nicht zu Ende geführt."
            )
        raise InvalidCallback(
            "Das ist eine gewöhnliche Web-Adresse (http(s)://…), nicht der "
            "Login-Callback. Richtig ist eine Adresse, die mit "
            "rismycar://login-callback beginnt, oder nur der Code-Wert."
        )

    if "://" in text:
        u = urlparse(text)
        if (u.scheme or "").lower() != SCHEME:
            raise InvalidCallback(
                "Unerwartetes Adress-Schema — erwartet wird die Rückleitung "
                "rismycar://login-callback?code=… (oder nur der Code-Wert)."
            )
        if (u.netloc or "").lower() != CALLBACK_HOST or u.path not in ("", "/"):
            raise InvalidCallback(
                "Das ist eine rismycar-Adresse, aber nicht der erwartete Callback "
                "rismycar://login-callback?code=…."
            )
        q = parse_qs(u.query, keep_blank_values=True)
        if "error" in q:
            err = str(q["error"][0])[:120]
            raise InvalidCallback(
                f"Mercedes hat die Anmeldung abgelehnt (error={err}). "
                "Bitte den Login neu starten."
            )
        codes = q.get("code", [])
        if len(codes) != 1 or not codes[0].strip():
            raise InvalidCallback(
                "Der Callback enthält keinen eindeutigen code-Wert "
                "(leer oder mehrfach vorhanden)."
            )
        if expected_state is not None:
            states = q.get("state", [])
            if len(states) != 1 or states[0] != expected_state:
                raise InvalidCallback(
                    "Der Callback passt nicht zu diesem Login (state-Parameter "
                    "weicht ab) — bitte den Login neu starten und die neue "
                    "Rückleitung verwenden."
                )
        return codes[0].strip()

    # no scheme: allow the convenience "code=..." form and bare codes
    if "&" in text or "=" in text:
        part = text.split("=", 1)
        if len(part) == 2 and part[0].strip().lower() == "code" and "&" not in part[1]:
            text = part[1].strip()
        else:
            raise InvalidCallback(
                "Die Eingabe sieht nach einem URL-Ausschnitt aus. Bitte die "
                "komplette rismycar://login-callback-Adresse einfügen oder nur "
                "den Code-Wert (alles nach code= bis zum nächsten &)."
            )
    if any(ch.isspace() for ch in text):
        raise InvalidCallback(
            "Die Eingabe enthält Leerzeichen/Umbrüche — bitte NUR die "
            "Callback-Adresse oder NUR den Code einfügen."
        )
    if not _BARE_CODE_RE.fullmatch(text):
        raise InvalidCallback(
            "Das sieht nicht nach einem Autorisierungs-Code aus. Richtig: die "
            "komplette rismycar://login-callback-Adresse oder nur der Code-Wert "
            "(Buchstaben, Ziffern sowie - _ . ~ +)."
        )
    return text


# --------------------------------------------------------------------------
# CLI handler (invoked by the desktop with the callback URL)
# --------------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="omarchy-mercedes-callback",
        description=(
            "Nimmt einen rismycar://-Login-Callback entgegen "
            "(intern; wird vom Desktop während 'omarchy-mercedes login' aufgerufen)."
        ),
    )
    ap.add_argument("--session", required=True, help="interne Login-Session-Kennung")
    ap.add_argument("url", help="rismycar://login-callback?code=…")
    args = ap.parse_args(argv)

    try:
        token = validate_session_token(args.session)
    except ValueError:
        print("Ungültige Session-Kennung — Login bitte neu starten.", file=sys.stderr)
        return 2

    if not marker_path(token).exists():
        print(
            "Kein aktiver omarchy-mercedes-Login gefunden — bitte zuerst "
            "'omarchy-mercedes login' im Terminal starten und die Anmeldung "
            "im Browser abschließen.",
            file=sys.stderr,
        )
        return 1

    try:
        # structural check only; the state binding is verified by the login
        parse_pasted_callback(args.url)
    except InvalidCallback as e:
        print(f"Ungültiger Login-Callback: {e}", file=sys.stderr)
        return 1

    write_spool(token, args.url)
    # deliberately no secret in this output (no code, no state)
    print("Login-Callback übernommen — bitte zum Terminal mit dem laufenden Login wechseln.")
    return 0


# --------------------------------------------------------------------------
# temporary XDG handler registration (Linux)
# --------------------------------------------------------------------------

def _run(cmd, runner):
    """Run an xdg tool via argv list (never a shell) with a timeout."""
    if runner is None:
        runner = subprocess.run
    try:
        return runner(cmd, capture_output=True, text=True, timeout=_XDG_TIMEOUT)
    except FileNotFoundError:  # tool not installed
        return None
    except subprocess.TimeoutExpired:
        return None


def query_default(runner=None) -> str:
    r = _run(["xdg-mime", "query", "default", MIME_TYPE], runner)
    if r is None or r.returncode != 0:
        return ""
    return (r.stdout or "").strip()


def applications_dir() -> Path:
    data_home = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return Path(data_home) / "applications"


def desktop_file_path(token) -> Path:
    return applications_dir() / f"{DESKTOP_PREFIX}{validate_session_token(token)}.desktop"


def _desktop_content(token, python_exe) -> str:
    exe = str(python_exe)
    if any(c in exe for c in ' \t"'):
        exe = f'"{exe}"'
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Version=1.0\n"
        "Name=omarchy-mercedes Login\n"
        "Comment=Nimmt den Mercedes-Login-Callback (rismycar://login-callback) entgegen\n"
        f"Exec={exe} -m omarchy_mercedes.callback --session {validate_session_token(token)} %u\n"
        "NoDisplay=true\n"
        "Terminal=false\n"
        f"MimeType={MIME_TYPE};\n"
    )


def install_desktop_handler(token, *, python_exe=None, runner=None, input_fn=None,
                            which=None, platform_=None):
    """Register the temporary rismycar:// XDG handler for this login (Linux).

    Returns ``(installed, previous_default)``. previous_default is the desktop
    id that owned the scheme before (None if none); restore_desktop_handler()
    puts it back. An existing foreign handler is never silently replaced: the
    user is asked and registration is skipped on decline. Non-Linux or
    missing xdg-mime: no-op returning (False, None).
    """
    plat = platform_ if platform_ is not None else sys.platform
    if not plat.startswith("linux"):
        return False, None
    which = which or shutil.which
    if which("xdg-mime") is None:
        print("  Hinweis: xdg-mime nicht gefunden — Callback bitte manuell einfügen.")
        return False, None

    prev = query_default(runner)
    if prev.startswith(DESKTOP_PREFIX):
        prev = ""  # leftover from a crashed login of ours; do not restore it
    if prev:
        if input_fn is None:
            input_fn = input
        try:
            answer = input_fn(
                f"Für rismycar:// ist bereits '{prev}' registriert. "
                "Für diesen Login temporär ersetzen (danach automatisch zurückgesetzt)? [j/N] "
            )
        except (EOFError, KeyboardInterrupt):
            answer = ""
        if (answer or "").strip().lower() not in ("j", "ja", "y", "yes"):
            print("  OK — bestehende Zuordnung bleibt bestehen; Callback bitte manuell einfügen.")
            return False, None

    p = desktop_file_path(token)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_desktop_content(token, python_exe or sys.executable), encoding="utf-8")
    os.chmod(p, 0o644)
    r = _run(["xdg-mime", "default", p.name, MIME_TYPE], runner)
    if r is None or r.returncode != 0:
        try:
            p.unlink()
        except FileNotFoundError:
            pass
        print("  Hinweis: xdg-mime nicht nutzbar — Callback bitte manuell einfügen.")
        return False, None
    return True, (prev or None)


def _remove_mimeapps_default(desktop_id: str) -> None:
    """Best effort: drop OUR default line from mimeapps.list (we added it)."""
    cfg_home = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    cfg = Path(cfg_home) / "mimeapps.list"
    try:
        if not cfg.exists():
            return
        lines = cfg.read_text(encoding="utf-8").splitlines(keepends=True)
        ours = f"{MIME_TYPE}={desktop_id}"
        kept = [ln for ln in lines if ln.rstrip("\r\n") != ours]
        if len(kept) != len(lines):
            cfg.write_text("".join(kept), encoding="utf-8")
    except Exception as e:  # best effort cleanup only
        print(f"  Hinweis: mimeapps.list konnte nicht bereinigt werden ({type(e).__name__}).")


def restore_desktop_handler(token, previous_default=None, *, runner=None, which=None,
                            platform_=None) -> None:
    """Undo install_desktop_handler (any exit path): remove file, restore default."""
    if token is None:
        return
    plat = platform_ if platform_ is not None else sys.platform
    if not plat.startswith("linux"):
        return
    try:
        token = validate_session_token(token)
    except ValueError:
        return
    try:
        desktop_file_path(token).unlink()
    except FileNotFoundError:
        pass
    if previous_default:
        _run(["xdg-mime", "default", previous_default, MIME_TYPE], runner)
    else:
        _remove_mimeapps_default(f"{DESKTOP_PREFIX}{token}.desktop")


def cleanup_stale_handlers(*, runner=None, platform_=None, max_age_s=6 * 3600) -> int:
    """Remove login handler leftovers from crashed logins (not live ones)."""
    plat = platform_ if platform_ is not None else sys.platform
    if not plat.startswith("linux"):
        return 0
    removed = 0
    try:
        candidates = list(applications_dir().glob(f"{DESKTOP_PREFIX}*.desktop"))
    except OSError:
        return 0
    current_default = query_default(runner)
    for f in candidates:
        stem = f.name[len(DESKTOP_PREFIX):-len(".desktop")]
        try:
            validate_session_token(stem)
        except ValueError:
            continue  # not ours
        try:
            if marker_path(stem).exists():
                continue  # login still running
            if time.time() - f.stat().st_mtime < max_age_s:
                continue
            f.unlink()
            if current_default == f.name:
                _remove_mimeapps_default(f.name)
            removed += 1
        except OSError:
            continue
    return removed


if __name__ == "__main__":
    raise SystemExit(main())
