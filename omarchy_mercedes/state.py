"""Status cache shared between connector daemon and Waybar module.

The connector writes ~/.local/state/omarchy-mercedes/status.json (redacted,
no secrets, no VIN). The Waybar module only ever reads this file - it never
performs network I/O, so a broken connector can never block the bar.

Vehicle-data freshness (age of the telemetrics timestamp) and connection
freshness (age of our last successful fetch) are tracked SEPARATELY, so a
fresh connection can still show stale car data honestly.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path

DEFAULT_STATE_DIR = Path(os.environ.get("OMARCHY_MERCEDES_STATE_DIR", "~/.local/state/omarchy-mercedes")).expanduser()
STATUS_FILE = DEFAULT_STATE_DIR / "status.json"

STATE_OK = "ok"
STATE_STALE = "stale"            # connection fresh, vehicle data old
STATE_OFFLINE = "offline"        # connector produced nothing recently
STATE_NO_SESSION = "no-session"  # login required
STATE_ERROR = "error"            # connector hit an error (auth, api, ...)


def now_ms() -> int:
    return int(time.time() * 1000)


def write_status(data: dict, path: Path = STATUS_FILE) -> None:
    data = dict(data)
    data.setdefault("written_at_ms", now_ms())
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    os.replace(tmp, path)


def read_status(path: Path = STATUS_FILE) -> dict | None:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def fmt_age(age_s: float) -> str:
    """Human age in German (matches the module's UI language)."""
    age_s = max(0, int(age_s))
    if age_s < 60:
        return f"{age_s} s"
    if age_s < 3600:
        return f"{age_s // 60} min"
    if age_s < 86400:
        h, m = divmod(age_s, 3600)
        return f"{h} h {m // 60:02d} min" if m % 60 else f"{h} h"
    d, h = divmod(age_s, 86400)
    return f"{d} d {h // 3600} h"


def fmt_local(ms: int | float | None, tz_name: str | None = None) -> str:
    """Format an epoch-ms timestamp as local time.

    tz_name: explicit IANA zone from config (documented, never guessed from
    naive strings). Falls back to system-local when unset/unavailable.
    """
    if not ms:
        return "keine Angabe"
    dt = datetime.fromtimestamp(ms / 1000.0)
    if tz_name:
        try:
            from zoneinfo import ZoneInfo

            dt = dt.astimezone(ZoneInfo(tz_name))
        except Exception:
            pass  # documented fallback: system zone
    return dt.strftime("%d.%m. %H:%M")


def vehicle_age_s(status: dict) -> float | None:
    """Age of the newest vehicle telemetrics timestamp we displayed."""
    ts = status.get("vehicle_ts_ms")
    return (time.time() - ts / 1000.0) if ts else None


def connection_age_s(status: dict) -> float | None:
    """Age of the connector's last successful data write."""
    ts = status.get("fetched_at_ms")
    return (time.time() - ts / 1000.0) if ts else None


def classify(status: dict | None, stale_after_s: int, offline_after_s: int | None = None) -> str:
    """Derive display state from a status dict (None/missing file => offline).

    offline_after_s defaults to 3x the freshness bound; the status file's own
    write time bounds how long we trust a cached view.
    """
    if not isinstance(status, dict):
        return STATE_NO_SESSION if status is None and False else STATE_OFFLINE
    if status.get("state") == STATE_NO_SESSION:
        return STATE_NO_SESSION
    written = status.get("written_at_ms")
    if not written:
        return STATE_OFFLINE
    if offline_after_s is None:
        offline_after_s = 3 * stale_after_s
    if time.time() * 1000 - written > offline_after_s * 1000:
        return STATE_OFFLINE
    if status.get("state") == STATE_ERROR:
        return STATE_ERROR
    age = vehicle_age_s(status)
    if age is None:
        return STATE_ERROR
    if age > stale_after_s:
        return STATE_STALE
    return STATE_OK
