# Changelog

## 0.1.1 (2026-09-24)

- Add the localized Connect to Mercedes action to the existing settings panel.
  Its terminal stays open for success, failure or missing-connector guidance.
- Validate OAuth callback and state before exchange; register and refresh the
  temporary desktop handler before opening the browser. Serialize logins, reject
  dead markers and clean callback files. Restore terminal input on all normal exits.
- Fix CLI login-to-session-store integration, including error reporting on failed
  persistence. No passwords, tokens or private vehicle fixtures are included.
- Preserve unknown/invalid vehicle attributes instead of displaying false zeroes.
- Align Python-version-dependent package pins with the existing hash lock and
  exercise the actual documented installation with `pip check`.

The Python connector and widget are separate installations. Existing users must
update the connector using the locked README steps as well as updating the
Omarchy plugin. No dependency installation runs on plugin enable/update.

Still experimental. Read-only requests only; no vehicle commands. Browser/portal
behavior and account availability vary. See `docs/VERIFICATION.md` for tested
paths and remaining limits. Marketplace verification is snapshot-specific, not
security certification.
