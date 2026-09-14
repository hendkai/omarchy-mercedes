#!/usr/bin/env python3
"""User-only installer with write-ahead ownership journal and exact rollback.

No system pip fallback. Config edits preserve JSONC comments. An edited owned
file stops reinstall/uninstall before any destructive work; backups remain in
the private manifest for explicit manual reconciliation.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from omarchy_mercedes.private_io import private_dir, write_private
from waybar_integrate import integrate


def fingerprint(path):
    if path.is_symlink():
        raise RuntimeError(f'Refusing symlink: {path}')
    if not path.exists():
        return None
    if not path.is_file():
        raise RuntimeError(f'Expected regular file: {path}')
    return {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'mode': path.stat().st_mode & 0o777}


def safe_path(path):
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise RuntimeError(f'Refusing symlink path: {path}')


class Installer:
    def __init__(self, home=None):
        self.home = Path(home or Path.home()).absolute()
        self.data = self.home/'.local/share/omarchy-mercedes'
        self.state = self.home/'.local/state/omarchy-mercedes'
        self.manifest = self.state/'install-manifest.json'
        self.venv = self.data/'venv'
        self.bin = self.home/'.local/bin'
        self.unit = self.home/'.config/systemd/user/omarchy-mercedes.service'
        safe_path(self.state)
        safe_path(self.data)
        safe_path(self.manifest)
        self.record = json.loads(self.manifest.read_text()) if self.manifest.exists() else {'version': 1, 'files': {}, 'venv_owned': False}
        if self.record.get('version') != 1:
            raise RuntimeError('Unsupported install manifest')
        # The abandoned/pre-manifest installer cannot safely be auto-migrated.
        if (self.state/'manifest').exists():
            raise RuntimeError('Legacy manifest found. Reconcile legacy backups manually before installing.')

    def persist(self):
        write_private(self.manifest, json.dumps(self.record, indent=2))

    def preflight(self):
        for relative, entry in self.record['files'].items():
            path = self.home/relative
            if not path.is_relative_to(self.home) or '..' in Path(relative).parts:
                raise RuntimeError('Unsafe manifest target')
            safe_path(path)
            actual = fingerprint(path)
            # pending is a write-ahead journal: either old or new state is safe.
            allowed = [entry['installed']]
            if 'pending' in entry:
                allowed.append(entry['pending'])
            if actual not in allowed:
                raise RuntimeError(f'User change detected: {path}. Nothing overwritten; reconcile with {self.manifest}.')
        if self.venv.exists() and not self.record['venv_owned']:
            raise RuntimeError('Existing unowned venv; move it aside explicitly first')
        safe_path(self.venv)

    def put(self, path, content, mode=0o644):
        safe_path(path)
        relative = str(path.relative_to(self.home))
        entries = self.record['files']
        if relative not in entries:
            previous = fingerprint(path)
            entries[relative] = {'original': base64.b64encode(path.read_bytes()).decode() if previous else None,
                                 'original_mode': previous['mode'] if previous else None,
                                 'installed': previous}
        entry = entries[relative]
        desired = {'sha256': hashlib.sha256(content).hexdigest(), 'mode': mode}
        if fingerprint(path) == desired:
            entry['installed'] = desired
            self.persist()
            return
        entry['pending'] = desired
        self.persist()  # original + expected new hash durable BEFORE target write
        path.parent.mkdir(parents=True, exist_ok=True)
        import tempfile
        fd, name = tempfile.mkstemp(prefix='.omarchy-mercedes-', dir=path.parent)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(content)
                stream.flush()
                os.fchmod(stream.fileno(), mode)
                os.fsync(stream.fileno())
            os.replace(name, path)
        finally:
            Path(name).unlink(missing_ok=True)
        entry['installed'] = desired
        entry.pop('pending', None)
        self.persist()

    def plan(self):
        python = shlex.quote(str(self.venv/'bin/python'))
        changes = {
            self.bin/'omarchy-mercedes': (f'#!/bin/sh\nexec {python} -I -m omarchy_mercedes.cli "$@"\n'.encode(), 0o755),
            self.bin/'omarchy-mercedes-waybar': (f'#!/bin/sh\nexec {python} -I -m omarchy_mercedes.waybar_module --timezone "${{OMARCHY_MERCEDES_TZ:-Europe/Berlin}}" "$@"\n'.encode(), 0o755),
            self.unit: ((REPO/'systemd/omarchy-mercedes.service').read_bytes(), 0o644),
        }
        waybar = self.home/'.config/waybar'
        config = waybar/'config.jsonc'
        if not config.exists():
            config = waybar/'config'
        if config.exists():
            safe_path(config)
            definition = json.loads((REPO/'waybar/config.d/mercedes.jsonc').read_text())['custom/mercedes']
            changes[config] = (integrate(config.read_text(), definition).encode(), 0o644)
            style = waybar/'style.css'
            safe_path(style)
            text = style.read_text() if style.exists() else ''
            marker = '/* omarchy-mercedes managed style */'
            if marker not in text:
                text += '\n' + marker + '\n' + (REPO/'waybar/style.d/mercedes.css').read_text()
            changes[style] = (text.encode(), 0o644)
            # These are convenience copies, not relied on for implicit includes.
            for sub in ['config.d/mercedes.jsonc', 'style.d/mercedes.css']:
                changes[waybar/sub] = ((REPO/'waybar'/sub).read_bytes(), 0o644)
        else:
            print('No Waybar config found; no GUI configuration changed. Reinstall after creating config.')
        for path in changes:
            safe_path(path)
            fingerprint(path)
        return changes

    def systemctl(self, *args, required=False):
        if not shutil.which('systemctl'):
            if required:
                raise RuntimeError('systemctl unavailable')
            return False
        result = subprocess.run(['systemctl', '--user', *args], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if required and result.returncode:
            raise RuntimeError('systemctl --user ' + ' '.join(args) + ' failed; package retained')
        return result.returncode == 0

    def install(self):
        self.preflight()
        changes = self.plan()  # parse/check every target before installing anything
        if self.systemctl('is-active', '--quiet', 'omarchy-mercedes.service'):
            if str(self.unit.relative_to(self.home)) not in self.record['files']:
                raise RuntimeError('Existing active service is not owned by this installer; stop/reconcile it first')
            self.systemctl('stop', 'omarchy-mercedes.service', required=True)
        private_dir(self.data)
        private_dir(self.state)
        self.record['venv_owned'] = True
        self.persist()
        subprocess.run([sys.executable, '-m', 'venv', str(self.venv)], check=True)
        subprocess.run([str(self.venv/'bin/python'), '-m', 'pip', 'install', str(REPO) + '[keyring]'], check=True)
        for path, (content, mode) in changes.items():
            self.put(path, content, mode)
        self.systemctl('daemon-reload')
        print('Installed in isolated venv. No system Python changed; service NOT enabled/started.')
        print('Add ~/.local/bin to PATH. Run doctor, login, then systemctl --user enable --now omarchy-mercedes.')

    def uninstall(self, keep):
        self.preflight()  # fail closed if ANY owned file was changed by the user
        if not self.record['files'] and not self.record['venv_owned']:
            print('No owned installation found; no files or keyring changed.')
            return
        if self.systemctl('is-active', '--quiet', 'omarchy-mercedes.service'):
            self.systemctl('stop', 'omarchy-mercedes.service', required=True)
        if not keep:
            # Use the known venv, not a possibly pre-existing wrapper. Must succeed
            # BEFORE removing package/dependencies, otherwise leave cleanup retryable.
            subprocess.run([str(self.venv/'bin/python'), '-I', '-m', 'omarchy_mercedes.cli', 'logout'], check=True)
        unit_entry = self.record['files'].get(str(self.unit.relative_to(self.home)))
        if unit_entry and unit_entry['original'] is None:
            self.systemctl('disable', 'omarchy-mercedes.service')
        for relative, entry in list(self.record['files'].items()):
            path = self.home/relative
            if entry['original'] is None:
                path.unlink(missing_ok=True)
            else:
                self.put(path, base64.b64decode(entry['original']), entry['original_mode'])
            del self.record['files'][relative]
            self.persist()
        self.systemctl('daemon-reload')
        if self.record['venv_owned']:
            if self.venv.exists():
                shutil.rmtree(self.venv, ignore_errors=False)
            self.record['venv_owned'] = False
            self.persist()
        if not keep:
            (self.data/'session.json').unlink(missing_ok=True)
            (self.state/'status.json').unlink(missing_ok=True)
        self.manifest.unlink(missing_ok=True)
        print('Uninstalled; originals restored. ' + ('Both session stores retained.' if keep else 'Both token stores cleared.'))


def main():
    try:
        if any(os.environ.get(key) for key in ('OMARCHY_MERCEDES_DATA_DIR', 'OMARCHY_MERCEDES_STATE_DIR')):
            raise RuntimeError('Unset custom DATA_DIR/STATE_DIR for installer; scripts manage standard HOME paths only')
        installer = Installer()
        if sys.argv[1:] == ['install']:
            installer.install()
        elif sys.argv[1:] == ['uninstall']:
            print('Stop any manually launched daemon before continuing.')
            answer = input('Session (Tokens) und Statuscache belassen? [J/n] ').strip().lower()
            if answer not in ('', 'j', 'y', 'n'):
                raise RuntimeError('Expected J (retain) or n (delete)')
            installer.uninstall(keep=answer != 'n')
        else:
            raise RuntimeError('Expected install or uninstall')
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError, EOFError) as e:
        print(f'Installer stopped: {e}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
