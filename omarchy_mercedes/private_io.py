"""Private local files on Linux/macOS; never follow token/temp symlinks."""
from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path


def private_dir(path: Path) -> None:
    # Reject symlink components rather than chmod/write through an alias.
    for part in reversed((path, *path.parents)):
        if part.is_symlink():
            raise OSError('symlink in private directory path')
    for part in reversed((path, *path.parents)):
        if not part.exists():
            part.mkdir(mode=0o700, exist_ok=True)
    if path.stat().st_uid != os.getuid():
        raise OSError('private directory belongs to another user')
    path.chmod(0o700)


def write_private(path: Path, data: str) -> None:
    private_dir(path.parent)
    fd, name = tempfile.mkstemp(prefix='.' + path.name + '-', dir=path.parent)
    try:
        # mkstemp creates 0600 atomically before the first byte is written.
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def read_private(path: Path) -> str:
    if any(p.is_symlink() for p in path.parents):
        raise OSError('symlink in private directory path')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'r', encoding='utf-8') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
            raise OSError('unsafe private file')
        os.fchmod(stream.fileno(), 0o600)
        return stream.read(1024 * 1024)
