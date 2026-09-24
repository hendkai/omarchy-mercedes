# Verification — 0.1.1 candidate

Local verification on Linux/Hyprland, Omarchy 4.0.4, Qt 6.11.2 and Python 3.12:

- Full unittest suite: 115 tests passing after release metadata and security fixes.
- Real Qt widget tests exercise the pairing button, translations and layout.
- Synthetic callback through the real CLI and real isolated session storage:
  successful save, redaction, 0600 permissions, browser/password paths and all
  supported region arguments. A storage error returns failure, not false success.
- Real PTY: terminal attributes restored after success, timeout and SIGINT.
- Real GIO Desktop Exec: callback delivered; MIME cache registration/restoration
  tested with isolated XDG directories. GIO URL normalization is accepted.
- Concurrent login refusal, stale marker rejection and callback file cleanup.
- Empty temporary HOME: locked/hash-verified install, provenance check, pip check,
  update, overwrite refusal and uninstall retaining synthetic user data.
- Real authenticated read-only telemetry retrieved and displayed. No private
  telemetry values, account identifiers, tokens or screenshots are published.
- Live callback/token exchange was observed by the operator; an uncovered CLI
  persistence exception was fixed and reproduced with a regression test.

## Limits

- The extra automated full-browser smoke was interrupted (SIGINT), not passed.
  No claim is made that the new complete browser-to-persistence path has been
  freshly re-authenticated by the agent or tested on every browser/platform.
- Synthetic OAuth responses in tests do not represent real token exchange.
- GitHub CI, independent review and marketplace revalidation must refer to the
  exact pushed candidate SHA. Local passing tests are not listing approval.
- No formal legal/conformity assessment or security certification is claimed.

## Reproduce

```sh
PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring python -m unittest discover -s tests -v
bash tests/check_marketplace_setup.sh
omarchy plugin validate .
git diff --check
```

Credentials are never needed for the automated suite. Qt/GIO tests require the
corresponding desktop tools and explicitly skip when unavailable.
