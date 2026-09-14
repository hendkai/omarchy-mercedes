#!/usr/bin/env bash
# User-space only; Python owns the journal and safe rollback.
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${OMARCHY_MERCEDES_PYTHON:-python3}" "$REPO_DIR/tools/installer.py" uninstall
