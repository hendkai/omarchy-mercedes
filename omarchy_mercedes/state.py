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
    from .private_io import write_private
    write_private(path, json.dumps(data, ensure_ascii=False, allow_nan=False))


def read_status(path: Path = STATUS_FILE) -> dict | None:
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else None
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
    if type(ms) not in (int, float) or not 0 < ms < 253402300800000:
        return "keine Angabe"
    try:
        dt = datetime.fromtimestamp(ms / 1000.0)
    except (ValueError, OSError, OverflowError):
        return "keine Angabe"
    if tz_name:
        try:
            from zoneinfo import ZoneInfo

            dt = dt.astimezone(ZoneInfo(tz_name))
        except Exception:
            pass  # documented fallback: system zone
    return dt.strftime("%d.%m. %H:%M")


def valid_timestamp(ts) -> bool:
    return type(ts) in (int, float) and 0 < ts <= time.time() * 1000 + 60000


def age_s(ts) -> float | None:
    return max(0, time.time() - ts / 1000.0) if valid_timestamp(ts) else None


def vehicle_age_s(status: dict) -> float | None:
    # Old caches used max(attribute timestamps); those cannot establish SoC age.
    return age_s(status.get("soc_ts_ms"))


def connection_age_s(status: dict) -> float | None:
    return age_s(status.get("fetched_at_ms"))


def classify(status: dict | None, stale_after_s: int, offline_after_s: int | None = None) -> str:
    if not isinstance(status, dict):
        return STATE_OFFLINE
    if status.get("state") == STATE_NO_SESSION:
        return STATE_NO_SESSION
    written_age = age_s(status.get("written_at_ms"))
    if written_age is None or written_age > (offline_after_s or 3 * stale_after_s):
        return STATE_OFFLINE
    if status.get("state") not in (STATE_OK, STATE_STALE):
        return STATE_ERROR
    soc = status.get("soc_percent")
    age = vehicle_age_s(status)
    if type(soc) is not int or not 0 <= soc <= 100 or age is None:
        return STATE_ERROR
    return STATE_STALE if age > stale_after_s else STATE_OK
