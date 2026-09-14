# AI development contribution record

## Installer language selection (2026-09-14)

Product: omarchy-mercedes 0.1.0, branch `feat/installer-language`.
Responsible role: repository maintainer. Status: implemented and self-tested;
independent review pending. No claim of human code review is made.

Development assistance:
- Hermes with GLM 5.3 drafted the German/English installer messages, language
  picker, CLI options, tests and installation documentation.
- Hermes with GPT-6 Astra continued after the earlier worker failed, under
  explicit maintainer authorization. It reviewed the patch, rejected empty
  and overwritten invalid language arguments, added localized failure
  diagnostics, isolated systemctl in tests and fixed slash-branch CI triggers.
- AI assistance was used for source development and verification, not shipped
  as a runtime model or an AI-backed installer feature. No dependency or
  Mercedes authentication/telemetry protocol was added by this change.

Evidence:
- `tests/test_language_selection.py`: automated sandbox and real PTY checks.
- `python3 -m unittest discover -s tests -v`: 62 tests passed on macOS
  (Python 3.9, Bash 3.2) and Linux (Python 3.13).
- Real Python package install, installed CLI and offline Waybar wrapper,
  followed by uninstall: passed for German, English and implicit non-TTY
  English in an unprivileged disposable `python:3.13-slim` container with
  separate temporary homes. No host user configuration was modified.
- `.github/workflows/ci.yml` repeats tests and isolated install smoke checks;
  exact-commit CI and independent review are release-handoff gates.

Limitations and review ownership:
- This branch only adds installer localization. Existing authentication,
  stale-data and Waybar integration findings are handled separately. This
  evidence is not a stable-release approval or a live Mercedes login test.
- External tools' technical diagnostics (for example pip) are not translated.
- No legal conformity, CE certification or complete security assessment is
  claimed. A runtime AI-system/product-transparency obligation is not
  established merely by this development record. Commercial CRA scope,
  support obligations and full product compliance remain for the maintainer's
  separate release review; this localization does not settle those questions.

Official reference pages checked on 2026-09-14 (context, not legal advice):
- https://digital-strategy.ec.europa.eu/en/policies/regulatory-framework-ai
- https://digital-strategy.ec.europa.eu/en/policies/cyber-resilience-act

Reassess at independent review, before a stable release, upon adding runtime
AI functionality or changing distribution/business scope, and no later than
2027-03-14. Do not publish prompts, credentials or real vehicle data in this
record.
