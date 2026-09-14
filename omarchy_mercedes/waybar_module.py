"""Waybar custom module: reads the local status cache and prints Waybar JSON.

Design rules from the task:
- NO network I/O here, NO login triggers. Reads status.json only.
- Stale/offline is shown honestly (car icon + '?' / label), never as fresh.
- Output: single JSON line {"text","tooltip","class","percentage"} (Waybar
  custom module protocol; "alt" and "percentage" included when meaningful).
- Escaping: Waybar needs Pango-escaped text; we escape &, <, > and quotes in
  both text and tooltip.
"""

from __future__ import annotations

import json
import sys

from .state import (
    STATE_ERROR,
    STATE_NO_SESSION,
    STATE_OFFLINE,
    STATE_OK,
    STATE_STALE,
    STATUS_FILE,
    classify,
    connection_age_s,
    fmt_age,
    fmt_local,
    read_status,
    vehicle_age_s,
    age_s,
)

ICON_CAR = "\N{AUTOMOBILE}"
ICON_PLUG = "\N{ELECTRIC PLUG}"  # U+1F50C


def pango_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def render(status: dict | None, stale_after_s: int = 1800, tz: str | None = None) -> dict:
    """Build the Waybar JSON dict from a status cache dict (or None)."""
    st = classify(status, stale_after_s)

    if st in (STATE_OK, STATE_STALE) and isinstance(status, dict):
        soc = status.get("soc_percent")
        rng = status.get("range_km")
        charging_age = age_s(status.get("charging_ts_ms"))
        charging = status.get("charging") is True and charging_age is not None and charging_age <= stale_after_s
        unit = status.get("range_unit", "km")
        v_age = vehicle_age_s(status)
        c_age = connection_age_s(status)

        if st == STATE_OK:
            icon = ICON_PLUG if charging else ICON_CAR
            text = f"{icon} {soc}%"
        else:
            text = f"{ICON_CAR} {soc}% (?)" if soc is not None else f"{ICON_CAR} ?"

        tip = []
        def measurement(label, value, ts):
            age = age_s(ts)
            if value is None or age is None:
                tip.append(f"{label}: unbekannt")
            else:
                stale = "; veraltet" if age > stale_after_s else ""
                tip.append(f"{label}: {value} (Stand: {fmt_local(ts, tz)}, vor {fmt_age(age)}{stale})")

        measurement("Reichweite", f"{rng} {unit}" if rng is not None else None, status.get("range_ts_ms"))
        active = status.get("charging")
        measurement("Ladestatus", "Ladevorgang aktiv" if active is True else ("nicht aktiv" if active is False else None), status.get("charging_ts_ms"))
        power = status.get("charging_power_kw")
        measurement("Ladeleistung", f"{power} kW" if power is not None else None, status.get("charging_power_ts_ms"))
        measurement("Ladeende", status.get("end_of_charge_time"), status.get("end_of_charge_ts_ms"))
        measurement("Ladestand", f"{soc}%", status.get("soc_ts_ms"))
        tip.append(f"Letzter Abgleich: {fmt_local(status.get('fetched_at_ms'), tz)}" + (f" (vor {fmt_age(c_age)})" if c_age is not None else ""))
        if status.get("error_hint"):
            tip.append(f"Hinweis: {status['error_hint']}")
        return {
            "text": pango_escape(text),
            "tooltip": pango_escape("\n".join(tip)),
            "class": "charging" if (charging and st == STATE_OK) else st,
            "percentage": soc if isinstance(soc, int) else None,
        }

    if st == STATE_NO_SESSION:
        return {
            "text": pango_escape(f"{ICON_CAR} Anmeldung erforderlich"),
            "tooltip": pango_escape(
                "Noch nicht eingeloggt.\nStarte: omarchy-mercedes login"
            ),
            "class": STATE_NO_SESSION,
            "percentage": None,
        }

    if st == STATE_ERROR:
        hint = (status or {}).get("error_hint", "Unbekannter Fehler")
        c_age = connection_age_s(status or {})
        tip = f"Fehler: {hint}"
        if c_age is not None:
            tip += f"\nLetzter Abgleich vor {fmt_age(c_age)}"
        return {
            "text": pango_escape(f"{ICON_CAR} !"),
            "tooltip": pango_escape(tip),
            "class": STATE_ERROR,
            "percentage": None,
        }

    # offline / no file
    return {
        "text": pango_escape(f"{ICON_CAR} offline"),
        "text_alt_plug": None,
        "tooltip": pango_escape("Keine aktuellen Daten (Connector offline).\nomarchy-mercedes status für Details."),
        "class": STATE_OFFLINE,
        "percentage": None,
    }


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="omarchy-mercedes-waybar")
    ap.add_argument("--status-file", default=str(STATUS_FILE))
    ap.add_argument("--stale-after", type=int, default=1800,
                    help="vehicle data older than this many seconds shows as stale (default 1800)")
    ap.add_argument("--timezone", default=None, help="IANA tz for tooltip times, e.g. Europe/Berlin")
    ap.add_argument("--compact", action="store_true", help="icon + percent only")
    args = ap.parse_args(argv)

    from pathlib import Path

    try:
        status = read_status(Path(args.status_file))
        out = render(status, stale_after_s=args.stale_after, tz=args.timezone)
    except Exception:
        # a broken cache must never crash the bar: emit valid offline JSON
        out = render(None, stale_after_s=args.stale_after, tz=args.timezone)
    if args.compact:
        out["tooltip"] = ""
    out = {k: v for k, v in out.items() if v is not None}
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
