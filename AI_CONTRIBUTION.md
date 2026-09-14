# AI contribution record

Product: omarchy-mercedes 0.1.0 experimental, R1–R9 remediation candidate.
Record date: 2026-09-14. Responsible release role: repository maintainer.

## Development provenance (not a legal compliance assertion)

- Initial implementation: Hermes using GLM 5.3, according to the parent
  implementation handoff. OAuth/PKCE, read-only telemetry, daemon, cache,
  Waybar, installers and initial synthetic tests were AI-assisted.
- Initial independent QA: Hermes using gpt-6-astra. It reproduced security,
  freshness, installer, session and public-CLI defects despite the original
  test/CI suite passing. Its findings are the R1–R9 acceptance criteria.
- Remediation began with GLM 5.3; that worker crashed with uncommitted work.
  The operator explicitly authorized a gpt-6-astra implementation fallback.
  The fallback retained and corrected that work, added regression/PTY tests,
  replaced unsafe installer rollback with an ownership journal, and updated
  license/provenance documentation. No quantitative authorship percentages
  are available. A supplemental read-only agent review timed out and is NOT
  cited as approval.
- This candidate requires a separate downstream QA/integration/release pass.
  A language-feature branch and a login pull request are separate workstreams;
  they are not claimed merged or reviewed by this remediation candidate.
- No human code inspection or completed human live test is evidenced here.
  Operator authorization is not equivalent to human code review.

Verification commands, actual results and limits: [docs/VERIFICATION.md](docs/VERIFICATION.md).
No prompts, actual credentials, vehicle identifiers or user telemetry are included
in this record. Examples and regression fixtures are synthetic.

## Delivered product versus coding tools

The inspected Python package is deterministic OAuth/HTTP/protobuf/cache/UI code.
Its manifest includes requests/protobuf and optional keyring, not an inference
SDK. No runtime model, AI endpoint, chatbot, generated media, biometric inference,
training or model-dependent vehicle logic was identified. AI involvement in
writing code is documented separately from functionality of the shipped product.
A voluntary visible pointer is in README; no machine-readable AI-output marker
was added because no such runtime AI output was identified.

## Regulatory review status and limits

This is a technical provenance/inventory check, NOT an AI Act or CRA conformity
assessment, legal opinion, CE declaration or claim that all product obligations
are satisfied. The project is described as standalone non-commercial experimental
open source; commercial distribution, paid support, market role and future
features would require renewed qualified scope assessment. Runtime inspection
alone is not a legal exemption. Formal legal applicability remains unassessed.

Official starting sources consulted on 2026-09-14:

- Regulation (EU) 2024/1689, EUR-Lex published-act entry:
  https://eur-lex.europa.eu/eli/reg/2024/1689/oj/eng
- European Commission, AI Act overview (page last updated 2026-08-03):
  https://digital-strategy.ec.europa.eu/en/policies/regulatory-framework-ai
- European Commission, CRA implementation (page last updated 2026-07-27):
  https://digital-strategy.ec.europa.eu/en/factpages/cyber-resilience-act-implementation

The consulted overview/published-act entry is not claimed to be a complete
consolidated-law or Article-50 legal analysis. No legal conclusion is inferred
from coding-assistant use alone. License notices are in THIRD_PARTY_NOTICES.md;
that attribution is separate from regulatory compliance.

Owner of open review decisions: repository maintainer, with independent release
reviewer. Reassess before any stable release, commercial offering, runtime-AI or
material data-flow change; internal next review no later than 2027-03-14.
