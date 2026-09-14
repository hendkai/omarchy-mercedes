"""Connector daemon: logs in once, refreshes tokens, polls read-only telemetry.

Runtime contract (from the task):
- Separate process from Waybar; writes the redacted status cache periodically.
- Session/refresh tokens NEVER in the repo, logs or chat. Stored at
  ~/.local/share/omarchy-mercedes/session.json (0600), or - preferred - in the
  user's Secret Service keyring when available (keyring package).
- Automatic refresh while the backend honors it; on revoked/expired session
  the status cache shows "Anmeldung erforderlich" (no-session).
- Polite polling: default 300 s widget poll with exponential backoff on
  errors, capped; no vehicle wakeups are triggered (read-only attributes).
- Read-only: this daemon contains NO vehicle command endpoints.
"""

from __future__ import annotations

import argparse
import fcntl
from contextlib import contextmanager
import json
import logging
import os
import sys
import tempfile
import time
from pathlib import Path

from . import __version__
from .api_constants import (
    ATTR_CHARGING_ACTIVE,
    ATTR_CHARGING_POWER,
    ATTR_CHARGING_STATUS,
    ATTR_END_OF_CHARGE_TIME,
    ATTR_RANGE_ELECTRIC,
    ATTR_STATE_OF_CHARGE,
)
from .oauth_client import AuthError, InvalidSessionError, MercedesOAuthClient, redact
from .state import STATE_ERROR, STATE_NO_SESSION, STATE_OK, now_ms, write_status
from .telemetry import ApiError, UnauthorizedError, VehicleApi

log = logging.getLogger("omarchy-mercedes")


def first_attr(data: dict, names) -> dict | None:
    """Return the first matching attribute entry (names: str or tuple)."""
    if isinstance(names, str):
        names = (names,)
    attrs = data.get("attributes") or {}
    for n in names:
        if n in attrs:
            return attrs[n]
    return None

DATA_DIR = Path(
    os.environ.get("OMARCHY_MERCEDES_DATA_DIR", "~/.local/share/omarchy-mercedes")
).expanduser()
SESSION_FILE = DATA_DIR / "session.json"
KEYRING_SERVICE = "omarchy-mercedes"
KEYRING_USER = "session"

DEFAULT_POLL_S = 300
DEFAULT_BACKOFF_MAX_S = 3600
DEFAULT_STALE_AFTER_S = 1800

MIN_POLL_S = 60  # never hammer the backend faster than this


@contextmanager
def _session_lock():
    """One stable flock inode shared by CLI login/logout and daemon writers.

    Each call opens its own descriptor, serializing threads as well as processes.
    Never unlink the lock file, and never hold this lock across network requests.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    fd = os.open(DATA_DIR / "session.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


_UNCONDITIONAL = object()


def load_session(region: str) -> dict | None:
    with _session_lock():
        return _load_session(region)


def _load_session(region: str) -> dict | None:
    """A retained fallback is newer than a keyring write that failed."""
    if SESSION_FILE.exists():
        try:
            if SESSION_FILE.stat().st_mode & 0o777 != 0o600:
                os.chmod(SESSION_FILE, 0o600)
            return json.loads(SESSION_FILE.read_text())
        except (OSError, ValueError) as e:
            log.warning("session file unreadable: %s", type(e).__name__)
    try:
        import keyring

        blob = keyring.get_password(KEYRING_SERVICE, KEYRING_USER)
        if blob:
            try:
                return json.loads(blob)
            except ValueError:
                log.warning("keyring session undecodable; ignoring")
    except Exception:
        pass  # keyring not installed / no Secret Service
    return None


def save_session(session: dict, *, expected=_UNCONDITIONAL) -> bool:
    """Atomically compare and save; login callers intentionally replace any session."""
    with _session_lock():
        if expected is not _UNCONDITIONAL and _load_session("") != expected:
            return False
        _save_session(session)
        return True


def _save_session(session: dict) -> None:
    """Persist session to keyring when possible, with an atomic 0600 fallback."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    # mkstemp creates exclusively with mode 0600, before any secret is written.
    fd, name = tempfile.mkstemp(prefix=".session-", suffix=".tmp", dir=DATA_DIR)
    tmp = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(session))
        os.replace(tmp, SESSION_FILE)
    finally:
        tmp.unlink(missing_ok=True)
    try:
        import keyring

        keyring.set_password(KEYRING_SERVICE, KEYRING_USER, json.dumps(session))
        SESSION_FILE.unlink(missing_ok=True)  # keep secrets in one place
    except Exception:
        pass  # file fallback already written


def clear_session(*, expected=_UNCONDITIONAL) -> bool:
    """Clear only the observed session when called by an in-flight refresh."""
    with _session_lock():
        if expected is not _UNCONDITIONAL and _load_session("") != expected:
            return False
        _clear_session()
        return True


def _clear_session() -> None:
    SESSION_FILE.unlink(missing_ok=True)
    try:
        import keyring

        keyring.delete_password(KEYRING_SERVICE, KEYRING_USER)
    except Exception:
        pass


def token_is_expired(session: dict, slack_s: int = 60) -> bool:
    return session.get("expires_at", 0) - time.time() < slack_s


def extract_status(data: dict, fetched_at_ms: int) -> dict:
    """Map widget attributes -> redacted status cache entry."""
    soc = first_attr(data, ATTR_STATE_OF_CHARGE)
    rng = first_attr(data, ATTR_RANGE_ELECTRIC)
    cha = first_attr(data, ATTR_CHARGING_ACTIVE)
    chs = first_attr(data, ATTR_CHARGING_STATUS)
    chp = first_attr(data, ATTR_CHARGING_POWER)
    ect = first_attr(data, ATTR_END_OF_CHARGE_TIME)

    # Freshness describes the displayed SOC, not newer unrelated attributes.
    # Use global vehicle time only when SOC has no per-attribute timestamp.
    vehicle_ts = soc.get("ts_ms") if soc else None
    if vehicle_ts is None:
        vt = first_attr(data, "vtime")
        if vt and isinstance(vt.get("value"), int):
            vehicle_ts = vt["value"] * 1000  # vtime is in seconds

    status = {
        "state": STATE_OK,
        "soc_percent": soc["value"] if soc and isinstance(soc.get("value"), int) else None,
        "range_km": rng["value"] if rng and isinstance(rng.get("value"), (int, float)) else None,
        "range_unit": "km",  # EU accounts are km; display_value holds the number, not a unit
        "charging": bool(cha["value"]) if cha and cha.get("value") is not None else False,
        "charging_power_kw": chp["value"] if chp and isinstance(chp.get("value"), (int, float)) else None,
        "end_of_charge_time": (ect or {}).get("display_value"),
        "vehicle_ts_ms": vehicle_ts,
        "fetched_at_ms": fetched_at_ms,
        "version": __version__,
    }
    if status["soc_percent"] is None:
        status["state"] = STATE_ERROR
        status["error_hint"] = "Fahrzeug liefert keinen Ladestand"
    return status


def run_loop(args) -> int:
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if args.poll_interval < MIN_POLL_S:
        log.warning("poll interval raised to minimum %ss (backend politeness)", MIN_POLL_S)
    poll_s = max(args.poll_interval, MIN_POLL_S)

    oauth = MercedesOAuthClient(region=args.region, timeout=args.timeout)
    api = VehicleApi(region=args.region, timeout=args.timeout)

    backoff_s = 0
    while True:
        fetched = now_ms()
        exit_code = 1
        try:
            # Login/logout runs in another process; reread at each poll.
            session = load_session(args.region)
            if session is None:
                log.warning("no session - run 'omarchy-mercedes login' first")
                write_status({"state": STATE_NO_SESSION, "written_at_ms": now_ms()})
                if args.once:
                    return 2
                time.sleep(poll_s)
                continue
            refreshed = False
            if token_is_expired(session):
                log.info("access token expired - refreshing")
                replacement = oauth.refresh(session["refresh_token"])
                if not save_session(replacement, expected=session):
                    raise AuthError("Session changed; retrying next poll")
                session = replacement
                refreshed = True
                log.info("token refreshed (rotated=%s)", session.get("refresh_rotated"))

            for attempt in range(2):
                try:
                    vehicles = api.list_vehicles(session["access_token"])
                    if not vehicles:
                        raise ApiError("no vehicles in account")
                    vin = args.vin or vehicles[0].get("vin")
                    if not vin:
                        raise ApiError("account vehicles lack VIN field")
                    data = api.get_vehicle_attributes(vin, session["access_token"])
                    break
                except UnauthorizedError:
                    if attempt or refreshed:
                        raise
                    replacement = oauth.refresh(session["refresh_token"])
                    if not save_session(replacement, expected=session):
                        raise AuthError("Session changed; retrying next poll")
                    session = replacement
                    refreshed = True
            status = extract_status(data, fetched)
            write_status(status)
            exit_code = 0 if status["state"] == STATE_OK else 1
            log.debug("status written: %s", json.dumps(redact(status)))
            backoff_s = 0

        except InvalidSessionError:
            exit_code = 2
            if clear_session(expected=session):
                session = None
                write_status({"state": STATE_NO_SESSION, "written_at_ms": now_ms()})
                log.warning("session revoked - login required")
            else:
                exit_code = 1
                write_status({"state": STATE_ERROR, "error_hint": "Session changed; retrying next poll",
                              "written_at_ms": now_ms()})
        except AuthError as e:
            write_status({"state": STATE_ERROR, "error_hint": f"Auth: {type(e).__name__}", "fetched_at_ms": fetched, "written_at_ms": now_ms()})
            log.warning("auth error: %s", e)
        except ApiError as e:
            write_status({"state": STATE_ERROR, "error_hint": str(e), "fetched_at_ms": fetched, "written_at_ms": now_ms()})
            log.warning("api error: %s", e)
        except Exception as e:  # never crash the daemon on unexpected errors
            write_status({"state": STATE_ERROR, "error_hint": type(e).__name__, "fetched_at_ms": fetched, "written_at_ms": now_ms()})
            log.exception("unexpected error")

        if args.once:
            return exit_code
        # exponential backoff on errors, fixed cadence otherwise
        if backoff_s:
            time.sleep(min(backoff_s, args.backoff_max))
            backoff_s = backoff_s * 2 if backoff_s > 1 else poll_s
        else:
            time.sleep(poll_s)
            # if the last cycle wrote an error, back off
            st = None
            from .state import read_status

            st = read_status()
            if isinstance(st, dict) and st.get("state") in (STATE_ERROR, STATE_NO_SESSION):
                backoff_s = poll_s * 2


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="omarchy-mercedes-daemon")
    ap.add_argument("--region", default="eu", choices=["eu", "na", "apac", "cn"])
    ap.add_argument("--vin", default=None, help="prefer this VIN (else first account vehicle)")
    arg = ap.add_argument("--poll-interval", type=int, default=DEFAULT_POLL_S)
    ap.add_argument("--timeout", type=int, default=30)
    ap.add_argument("--backoff-max", type=int, default=DEFAULT_BACKOFF_MAX_S)
    ap.add_argument("--stale-after", type=int, default=DEFAULT_STALE_AFTER_S)
    ap.add_argument("--once", action="store_true", help="single poll cycle then exit (for tests)")
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--version", action="version", version=__version__)
    args = ap.parse_args(argv)
    try:
        return run_loop(args)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
