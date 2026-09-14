"""Bounded pre-publication audit. Never print matching secret/PII values.

Scans all reachable Git blob/commit objects plus tracked/nonignored working
files. Findings include location/category only and require manual triage.
Not a guarantee against all secret formats, license plates or telemetry.
"""
import json
from pathlib import Path
import re
import subprocess

PATTERNS = {
    'private-key': rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
    'provider-token': rb'(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|sk-(?:proj-)?[A-Za-z0-9_-]{30,})',
    'jwt': rb'eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}',
    'vin': rb'\b(?:WDD|W1N|W1K|WDB|4JG)[A-HJ-NPR-Z0-9]{14}\b',
    'personal-path': rb'/(?:Users|home)/[A-Za-z0-9._-]+',
    'email': rb'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}',
    'plate-like': rb'\b[A-Z]{1,3}-[A-Z]{1,2} ?[0-9]{1,4}E?\b',
}


def scan(label, data):
    found = []
    for category, pattern in PATTERNS.items():
        for match in re.finditer(pattern, data):
            value = match.group()
            if category == 'email' and (value.endswith(b'@example.com') or b'@users.noreply.github.com' in value):
                continue
            if category == 'personal-path' and value == b'/home/qa':
                continue  # explicitly synthetic Linux runner identity
            found.append({'location': label, 'category': category,
                          'line': data.count(b'\n', 0, match.start()) + 1})
    return found


def main():
    objects = subprocess.check_output(['git', 'rev-list', '--objects', '--all']).splitlines()
    findings = []
    counts = {'blob': 0, 'commit': 0, 'working_files': 0}
    seen = set()
    for item in objects:
        oid = item.split(b' ', 1)[0].decode()
        if oid in seen:
            continue
        seen.add(oid)
        kind = subprocess.check_output(['git','cat-file','-t',oid]).strip().decode()
        if kind not in ('blob','commit'):
            continue
        data = subprocess.check_output(['git','cat-file',kind,oid])
        counts[kind] += 1
        findings.extend(scan('git:' + oid, data))
    files = subprocess.check_output(['git','ls-files','-z','--cached','--others','--exclude-standard']).split(b'\0')
    for name in sorted(set(files)):
        if not name:
            continue
        path = Path(name.decode())
        if not path.is_file():
            continue
        counts['working_files'] += 1
        findings.extend(scan(str(path), path.read_bytes()))
    print(json.dumps({'counts': counts, 'findings': findings}, indent=2))


if __name__ == '__main__':
    main()
