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


def load_session(region: str) -> dict | None:
    """Load session from keyring (preferred) or 0600 file (fallback)."""
    try:
        import keyring

        blob = keyring.get_password(KEYRING_SERVICE, KEYRING_USER)
        if blob:
            try:
                return json.loads(blob)
            except ValueError:
                log.warning("keyring session undecodable; ignoring")
    except Exception:
        pass  # keyring not installed / no Secret Service: fall back to file
    if SESSION_FILE.exists():
        try:
            if SESSION_FILE.stat().st_mode & 0o777 != 0o600:
                os.chmod(SESSION_FILE, 0o600)
            return json.loads(SESSION_FILE.read_text())
        except (OSError, ValueError) as e:
            log.warning("session file unreadable: %s", type(e).__name__)
    return None


def save_session(session: dict) -> None:
    """Persist session to keyring when possible; always also 0600 file."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = SESSION_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(session))
    os.chmod(tmp, 0o600)
    os.replace(tmp, SESSION_FILE)
    try:
        import keyring

        keyring.set_password(KEYRING_SERVICE, KEYRING_USER, json.dumps(session))
        SESSION_FILE.unlink(missing_ok=True)  # keep secrets in one place
    except Exception:
        pass  # file fallback already written


def clear_session() -> None:
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

    # vehicle data time: newest attribute timestamp we have; the
    # VehicleStatusUpdate carries a global vtime fallback
    ts_list = [a.get("ts_ms") for a in (soc, rng, cha, chs, chp, ect) if a and a.get("ts_ms")]
    vehicle_ts = max(t for t in ts_list if t is not None) if ts_list else None
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

    session = load_session(args.region)
    if session is None:
        log.warning("no session - run 'omarchy-mercedes login' first")
        write_status({"state": STATE_NO_SESSION, "written_at_ms": now_ms()})
        if args.once:
            return 2
        time.sleep(poll_s)

    backoff_s = 0
    while True:
        fetched = now_ms()
        try:
            if session is None:
                raise AuthError("no session")
            if token_is_expired(session):
                log.info("access token expired - refreshing")
                session = oauth.refresh(session["refresh_token"])
                save_session(session)
                log.info("token refreshed (rotated=%s)", session.get("refresh_rotated"))

            vehicles = api.list_vehicles(session["access_token"])
            if not vehicles:
                raise ApiError("no vehicles in account")
            vin = args.vin
            if not vin:
                vin = vehicles[0].get("vin")
            if not vin:
                raise ApiError("account vehicles lack VIN field")

            data = api.get_vehicle_attributes(vin, session["access_token"])
            status = extract_status(data, fetched)
            write_status(status)
            log.debug("status written: %s", json.dumps(redact(status)))
            backoff_s = 0

        except AuthError as e:
            hint = "Anmeldung erforderlich" if "relogin" in str(e) or "401" in str(e) else f"Auth: {type(e).__name__}"
            if "relogin" in str(e) or "rejected" in str(e) or "401" in str(e):
                clear_session()
                session = None
                write_status({"state": STATE_NO_SESSION, "written_at_ms": now_ms()})
                log.warning("session revoked - login required")
            else:
                write_status({"state": STATE_ERROR, "error_hint": hint, "fetched_at_ms": fetched, "written_at_ms": now_ms()})
                log.warning("auth error: %s", e)
        except ApiError as e:
            write_status({"state": STATE_ERROR, "error_hint": str(e), "fetched_at_ms": fetched, "written_at_ms": now_ms()})
            log.warning("api error: %s", e)
        except Exception as e:  # never crash the daemon on unexpected errors
            write_status({"state": STATE_ERROR, "error_hint": type(e).__name__, "fetched_at_ms": fetched, "written_at_ms": now_ms()})
            log.exception("unexpected error")

        if args.once:
            return 0
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
