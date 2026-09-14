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

Session lifecycle (QA R3):
- The session store is reconciled EVERY cycle, so a login (or logout) that
  happens while the daemon runs is picked up without a daemon restart.
- Sessions carry the region they were created for; a session for another
  region is ignored (relogin for that region required).
- A telemetry 401 triggers at most one refresh per cycle, then no-session
  on repeated rejection. Transient errors (network, 5xx) never clear tokens.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
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
from .oauth_client import AuthError, MercedesOAuthClient, redact
from .state import STATE_ERROR, STATE_NO_SESSION, STATE_OK, now_ms, write_status
from .telemetry import ApiError, VehicleApi

log = logging.getLogger("omarchy-mercedes")

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

# protobuf AttributeStatus codes (proto.AttributeStatus)
STATUS_VALUE_VALID = 0
STATUS_VALUE_NOT_RECEIVED = 1
STATUS_VALUE_INVALID = 3
STATUS_VALUE_NOT_AVAILABLE = 4


def _keyring():
    """Return the keyring module if actually usable, else None."""
    try:
        import keyring

        return keyring
    except Exception:
        return None  # keyring not installed / no Secret Service: file fallback


# Serialize polling/refresh with login/logout across processes. Logout waits
# for the bounded current HTTP cycle, then invalidates BOTH stores/cache.
import fcntl
import stat
import threading
from contextlib import contextmanager
from .private_io import private_dir, read_private, write_private as _write_private

_store_mutex = threading.RLock()
_store_local = threading.local()


@contextmanager
def session_lock():
    with _store_mutex:
        if getattr(_store_local, "depth", 0):
            yield
            return
        private_dir(DATA_DIR)
        fd = os.open(DATA_DIR / ".session.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
                raise OSError("unsafe session lock")
            fcntl.flock(fd, fcntl.LOCK_EX)
            _store_local.depth = 1
            yield
        finally:
            _store_local.depth = 0
            os.close(fd)


def load_session(region: str = "eu") -> dict | None:
    """Select by persistence generation, NEVER by token expiry.

    A logout tombstone suppresses old keyring data even while Secret Service
    is locked/unavailable. Region filtering happens AFTER store selection.
    """
    candidates = []
    kr = _keyring()
    blobs = []
    if kr is not None:
        try:
            blobs.append(kr.get_password(KEYRING_SERVICE, KEYRING_USER))
        except Exception:
            pass
    try:
        blobs.append(read_private(SESSION_FILE))
    except (OSError, ValueError):
        pass
    for blob in blobs:
        try:
            data = json.loads(blob)
            if not isinstance(data, dict):
                continue
            generation = data.get("saved_at_ns", 0)
            if type(generation) is not int or generation < 0:
                continue
            if data.get("logged_out") is not True:
                if not isinstance(data.get("access_token"), str) or not data["access_token"]:
                    continue
                if not isinstance(data.get("refresh_token"), (str, type(None))):
                    continue
                if not finite_number(data.get("expires_at", 0)):
                    continue
            candidates.append((generation, data))
        except (TypeError, ValueError):
            continue
    if not candidates:
        return None
    best = max(candidates, key=lambda pair: pair[0])[1]
    if best.get("logged_out") or best.get("region", "eu") != region:
        return None
    return best


def save_session(session: dict, region: str = "eu") -> dict:
    """Keyring first, atomic private file only if keyring persistence fails."""
    with session_lock():
        session = dict(session, region=region, saved_at_ns=time.time_ns())
        payload = json.dumps(session, allow_nan=False)
        kr = _keyring()
        if kr is not None:
            try:
                kr.set_password(KEYRING_SERVICE, KEYRING_USER, payload)
                if kr.get_password(KEYRING_SERVICE, KEYRING_USER) != payload:
                    raise RuntimeError("keyring did not persist the session")
            except Exception as e:
                log.warning("keyring write failed (%s); private file fallback", type(e).__name__)
            else:
                SESSION_FILE.unlink(missing_ok=True)
                return session
        _write_private(SESSION_FILE, payload)
        return session


def clear_session() -> None:
    """Invalidate locally even if keyring deletion fails; report that failure."""
    with session_lock():
        # Not a token: durable revocation prevents stale-store resurrection.
        _write_private(SESSION_FILE, json.dumps({"logged_out": True, "saved_at_ns": time.time_ns()}))
        write_status({"state": STATE_NO_SESSION})
        kr = _keyring()
        if kr is not None:
            try:
                if kr.get_password(KEYRING_SERVICE, KEYRING_USER) is not None:
                    kr.delete_password(KEYRING_SERVICE, KEYRING_USER)
            except Exception as e:
                raise RuntimeError("Local logout done; keyring deletion failed. Unlock keyring and retry logout.") from e


def token_is_expired(session: dict, slack_s: int = 60) -> bool:
    return session.get("expires_at", 0) - time.time() < slack_s


def finite_number(value) -> bool:
    import math
    return type(value) in (int, float) and math.isfinite(value)


def first_attr(data: dict, name: str) -> dict | None:
    return (data.get("attributes") or {}).get(name)


def attr_usable(attr) -> bool:
    return isinstance(attr, dict) and type(attr.get("status", 0)) is int and attr.get("status", 0) == 0


def valid_ts(attr, fetched_at_ms=None) -> int | None:
    ts = attr.get("ts_ms") if isinstance(attr, dict) else None
    upper = now_ms() if fetched_at_ms is None else fetched_at_ms
    return ts if type(ts) is int and 0 < ts <= upper + 60000 else None


def extract_status(data: dict, fetched_at_ms: int) -> dict:
    """Validate values/status/timestamps independently, with SoC-own freshness."""
    def field(name, validator):
        attr = first_attr(data, name)
        if not attr_usable(attr):
            return None, None
        value, ts = attr.get("value"), valid_ts(attr, fetched_at_ms)
        if ts is None or not validator(value):
            return None, None
        return value, ts

    soc, soc_ts = field(ATTR_STATE_OF_CHARGE, lambda v: type(v) is int and 0 <= v <= 100)
    rng, rng_ts = field(ATTR_RANGE_ELECTRIC, lambda v: finite_number(v) and v >= 0)
    charging, charging_ts = field(ATTR_CHARGING_ACTIVE, lambda v: type(v) is bool)
    power, power_ts = field(ATTR_CHARGING_POWER, lambda v: finite_number(v) and v >= 0)
    end, end_ts = field(ATTR_END_OF_CHARGE_TIME, lambda v: isinstance(v, str) and bool(v.strip()))
    status = {
        "state": STATE_OK if soc is not None else STATE_ERROR,
        "soc_percent": soc, "soc_ts_ms": soc_ts,
        "range_km": rng, "range_ts_ms": rng_ts, "range_unit": "km",
        "charging": charging, "charging_ts_ms": charging_ts,
        "charging_power_kw": power, "charging_power_ts_ms": power_ts,
        "end_of_charge_time": end, "end_of_charge_ts_ms": end_ts,
        # Compatibility alias is SoC-only, NOT the max of unrelated fields.
        "vehicle_ts_ms": soc_ts,
        "fetched_at_ms": fetched_at_ms, "version": __version__,
    }
    if soc is None:
        status["error_hint"] = "Kein gültiger Ladestand mit gültigem Zeitstempel verfügbar"
    return status


def _auth_revoked_message(text: str) -> bool:
    """True when the error means the session itself is gone (relogin needed).
    Transient problems (network, 5xx, timeouts) must NOT be treated as
    revocation (QA R3)."""
    t = text.lower()
    if "network error" in t:
        return False
    return (
        "relogin" in t
        or "rejected" in t
        or "unauthorized" in t
        or "(401)" in t
        or "401" in t
        or "invalid_grant" in t
    )


def run_loop(args) -> int:
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    poll_s = max(args.poll_interval, MIN_POLL_S)
    oauth = MercedesOAuthClient(region=args.region, timeout=args.timeout)
    api = VehicleApi(region=args.region, timeout=args.timeout)
    backoff_s = 0

    def refresh(session):
        if not session.get("refresh_token"):
            raise AuthError("relogin required: no refresh token")
        refreshed = oauth.refresh(session["refresh_token"])
        if not refreshed.get("refresh_token"):
            refreshed["refresh_token"] = session["refresh_token"]
        return save_session(refreshed, args.region)

    def fetch(session):
        vehicles = api.list_vehicles(session["access_token"])
        if not vehicles:
            raise ApiError("no vehicles in account")
        vin = args.vin or vehicles[0].get("vin")
        if not vin:
            raise ApiError("account vehicles lack VIN field")
        return api.get_vehicle_attributes(vin, session["access_token"])

    while True:
        fetched = now_ms()
        with session_lock():
            session = load_session(args.region)
            status = {"state": STATE_NO_SESSION}
            if session is not None:
                try:
                    refreshed = False
                    if token_is_expired(session):
                        session = refresh(session)
                        refreshed = True
                    try:
                        data = fetch(session)
                    except ApiError as e:
                        if not _auth_revoked_message(str(e)) or refreshed:
                            raise
                        # One forced refresh for a rejected non-expired bearer.
                        session = refresh(session)
                        data = fetch(session)
                    status = extract_status(data, fetched)
                except (AuthError, ApiError) as e:
                    if _auth_revoked_message(str(e)):
                        try:
                            clear_session()
                        except RuntimeError:
                            log.warning("local revocation saved; keyring cleanup still required")
                        status = {"state": STATE_NO_SESSION}
                    else:
                        # Do not copy arbitrary backend payloads/identifiers into cache.
                        status = {"state": STATE_ERROR, "error_hint": "Verbindungs-/API-Fehler; später erneut versuchen"}
                    log.warning("poll failed (%s)", type(e).__name__)
                except Exception as e:
                    status = {"state": STATE_ERROR, "error_hint": type(e).__name__}
                    log.warning("poll failed (%s)", type(e).__name__)
            write_status(status)

        if args.once:
            return 0 if status["state"] == STATE_OK else (2 if status["state"] == STATE_NO_SESSION else 1)
        if status["state"] == STATE_ERROR:
            backoff_s = min(backoff_s * 2 if backoff_s else poll_s, max(poll_s, args.backoff_max))
            time.sleep(backoff_s)
        else:
            backoff_s = 0
            time.sleep(poll_s)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="omarchy-mercedes-daemon")
    ap.add_argument("--region", default="eu", choices=["eu", "na", "apac", "cn"])
    ap.add_argument("--vin", default=None, help="prefer this VIN (else first account vehicle)")
    ap.add_argument("--poll-interval", type=int, default=DEFAULT_POLL_S)
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
