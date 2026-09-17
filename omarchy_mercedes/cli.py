"""omarchy-mercedes command line interface."""

from __future__ import annotations

import argparse
import json
import sys

from . import __version__


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="omarchy-mercedes",
        description="Mercedes-Benz SoC in der Waybar (Omarchy) - read-only",
    )
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_login = sub.add_parser("login", help="interaktiver Mercedes-Login (Browser oder Passwort)")
    p_login.add_argument("--region", default="eu", choices=["eu", "na", "apac", "cn"])
    p_login.add_argument("--browser", action="store_true", default=True)
    p_login.add_argument("--password", action="store_true", help="headless password flow statt Browser")
    p_login.add_argument("--no-open", action="store_true", help="URL ausgeben statt Browser zu öffnen")

    p_status = sub.add_parser("status", help="zeige aktuellen Statuscache (redigiert)")
    p_status.add_argument("--json", action="store_true")

    p_veh = sub.add_parser("vehicles", help="Fahrzeuge im Konto anzeigen (benötigt Login)")
    p_veh.add_argument("--region", default="eu", choices=["eu", "na", "apac", "cn"])

    p_daemon = sub.add_parser("daemon", help="Connector-Daemon starten (systemd --user nutzt dies)")
    p_daemon.add_argument("--region", default="eu", choices=["eu", "na", "apac", "cn"])
    p_daemon.add_argument("--vin", default=None)
    p_daemon.add_argument("--poll-interval", type=int, default=300)
    p_daemon.add_argument("--timeout", type=int, default=30)
    p_daemon.add_argument("--once", action="store_true")
    p_daemon.add_argument("--debug", action="store_true")

    p_wb = sub.add_parser("waybar", help="Waybar-JSON ausgeben (Modul-Skript)")
    p_wb.add_argument("--status-file", default=None)
    p_wb.add_argument("--stale-after", type=int, default=1800)
    p_wb.add_argument("--timezone", default=None)
    p_wb.add_argument("--compact", action="store_true")

    sub.add_parser("logout", help="Session löschen (Token entfernen)")
    sub.add_parser("doctor", help="Umgebung prüfen (python, protobuf, keyring, waybar)")

    args = ap.parse_args(argv)

    if args.cmd == "login":
        from .daemon import save_session
        from .login_helper import login_browser, login_password
        from .oauth_client import redact

        try:
            if args.password:
                tok = login_password(args.region)
            else:
                tok = login_browser(args.region, open_browser=not args.no_open)
        except KeyboardInterrupt:
            print("\nAbgebrochen.")
            return 130
        except Exception as e:
            print(f"Login fehlgeschlagen: {e}", file=sys.stderr)
            return 1
        save_session(tok, args.region)
        print("Login erfolgreich, Session sicher gespeichert.")
        print(json.dumps(redact(tok), indent=2))
        return 0

    if args.cmd == "status":
        from .state import read_status

        st = read_status()
        if st is None:
            print("Kein Statuscache - Connector lief noch nicht.")
            return 1
        if args.json:
            print(json.dumps(st, ensure_ascii=False, indent=2))
        else:
            for k in sorted(st):
                print(f"{k}: {st[k]}")
        return 0

    if args.cmd == "vehicles":
        from .daemon import load_session
        from .telemetry import VehicleApi

        session = load_session(args.region)
        if session is None:
            print("Nicht eingeloggt - erst 'omarchy-mercedes login'.", file=sys.stderr)
            return 2
        api = VehicleApi(region=args.region)
        try:
            for i, v in enumerate(api.list_vehicles(session["access_token"]), 1):
                print(f"{i}. VIN {v.get('vin')} ({v.get('deviceCategory', '?')})")
        except Exception as e:
            print(f"Fehler: {e}", file=sys.stderr)
            return 1
        return 0

    if args.cmd == "daemon":
        from .daemon import main as daemon_main

        return daemon_main([
            "--region", args.region,
            *(["--vin", args.vin] if args.vin else []),
            "--poll-interval", str(args.poll_interval),
            "--timeout", str(args.timeout),
            *(["--once"] if args.once else []),
            *(["--debug"] if args.debug else []),
        ])

    if args.cmd == "waybar":
        from .waybar_module import main as wb_main

        argv2 = []
        if args.status_file:
            argv2 += ["--status-file", args.status_file]
        argv2 += ["--stale-after", str(args.stale_after)]
        if args.timezone:
            argv2 += ["--timezone", args.timezone]
        if args.compact:
            argv2 += ["--compact"]
        return wb_main(argv2)

    if args.cmd == "logout":
        from .daemon import clear_session

        try:
            clear_session()
        except (RuntimeError, OSError) as e:
            print(f"Logout unvollständig: {e}", file=sys.stderr)
            return 1
        # clear_session publishes no-session while holding the process lock.
        print("Session gelöscht.")
        return 0

    if args.cmd == "doctor":
        import shutil

        ok = True
        print(f"python: {sys.version.split()[0]}")
        try:
            import google.protobuf as pb

            print(f"protobuf: {pb.__version__}")
        except ImportError:
            print("protobuf: FEHLT (pip install protobuf)")
            ok = False
        try:
            import requests as rq

            print(f"requests: {rq.__version__}")
        except ImportError:
            print("requests: FEHLT (pip install requests)")
            ok = False
        try:
            import keyring

            kr_ver = getattr(keyring, "__version__", None)
            if not kr_ver:
                try:
                    from importlib.metadata import version as _v

                    kr_ver = _v("keyring")
                except Exception:
                    kr_ver = "installiert"
            print(f"keyring: {kr_ver}")
        except ImportError:
            print("keyring: FEHLT (optional; sonst 0600-Datei)")
        wb = shutil.which("waybar")
        print(f"waybar: {wb or 'nicht gefunden (ok wenn nicht dieser Host)'}")
        sd = shutil.which("systemctl")
        print(f"systemctl: {sd or 'fehlt'}")
        print("ALLES OK" if ok else "PROBLEM: Abhängigkeiten fehlen")
        return 0 if ok else 1

    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
