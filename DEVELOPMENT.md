# Development Status

Last reviewed: 2026-10-02
Current development state: ACTIVE

## Purpose

This file is the common development ledger for both the user and AI agents. Existing project-specific planning documents remain valid; this file standardises status and completion evidence.

## Current objective

Improve the external-market research pipeline, evidence quality, per-unit analysis and reusable market-research capabilities.

## Existing planning and evidence sources

- `README.md`
- `docs/`
- `tests/`
- `GitHub Actions`

## Status values

- 🔵 PLANNED
- 🔨 IN PROGRESS
- 🚫 BLOCKED
- ⏳ AWAITING ACCEPTANCE
- ✅ COMPLETE
- 💤 DEFERRED

## Evidence standard

Do not mark an item COMPLETE because a person or AI says it is complete. Verify all applicable evidence:

1. implementation exists;
2. expected files changed;
3. a non-empty diff or equivalent implementation evidence exists;
4. tests exist or a reason for no test is recorded;
5. relevant tests pass;
6. CI passes where available;
7. commit/PR evidence is recorded;
8. the change is merged into the intended branch where required;
9. external/user acceptance is recorded separately.

If evidence is missing, use IN PROGRESS, BLOCKED or AWAITING ACCEPTANCE.

For coding work, an empty result, no write/edit action, unchanged branch HEAD, empty diff and missing requested validation are evidence that the task is not complete.

## Development ledger

### DEV-000 — Establish evidence-based development ledger

Status: ✅ COMPLETE

Requirement:
Give the user and AI agents one persistent place to see plans, progress and proof of completion.

Evidence:
- Files: `DEVELOPMENT.md`, `AGENTS.md`
- Git history records the commits creating this standard.
- Tests: not required for this documentation/process-only change.
- User acceptance: requested 2026-10-02.

Completion criteria:
- [x] Common statuses defined.
- [x] Evidence rules defined.
- [x] False-completion rule defined.
- [x] AI maintenance rule added.

## New item template

### DEV-XXX — Short title

Status: 🔵 PLANNED
Priority: Medium

Requirement:

Implementation:

Evidence:
- Commit:
- PR:
- Files:
- Tests:
- CI:
- Merged to intended branch:
- User/business acceptance:

Completion criteria:
- [ ] Implementation exists.
- [ ] Relevant files changed.
- [ ] Tests added/updated, or reason recorded.
- [ ] Relevant tests pass.
- [ ] CI passes where applicable.
- [ ] Commit/PR evidence recorded.
- [ ] Merged where required.
- [ ] External/user acceptance separated from development completion.

Notes:

## Maintenance rule

Update this file during the same development pass that changes implementation. When prose and repository evidence disagree, repository evidence wins.
