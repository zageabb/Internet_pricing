# AGENTS.md

## Project
Repository: `zageabb/Internet_pricing`

This file is the persistent working agreement for ChatGPT, Codex, and other coding agents operating on this repository.

## Start here
Before changing code:
1. Read this file.
2. Read the repository README and relevant documentation.
3. Read `TODO.md`, `DESIGN.md`, roadmap, phase, audit, and development notes when present.
4. Inspect the existing implementation before proposing replacement architecture.
5. Continue the next incomplete task or phase unless the user explicitly asks for something else.

## Development rules
- Preserve the existing architecture, UI conventions, and working behaviour unless a change is required.
- Prefer extending existing modules over rewriting working code.
- Keep modules focused and independently testable.
- Maintain backwards compatibility where practical.
- Keep business logic separate from UI, storage, integration, and transport layers.
- Do not hard-code passwords, tokens, API keys, server addresses, ports, or environment-specific paths when configuration can be used.
- Never commit production secrets.
- Update README/docs/TODO when implementation changes make them inaccurate.
- Clearly mark scaffolds, placeholders, limitations, and unfinished features.

## Shared research architecture
This repository is part of the shared search/research stack.

- `research-core` is the reusable shared research/search package.
- `general-search` is the general-purpose research application.
- `Internet_pricing` adds pricing-specific acquisition and analysis behaviour.
- `should-cost-intelligence` consumes shared research capability for market evidence and should-cost workflows.

Generic search, retrieval, extraction, evidence, ranking, citation, cache, and research orchestration logic should normally live in `research-core` when it is genuinely reusable.

Domain-specific pricing behaviour should remain in `Internet_pricing`.
Should-cost-specific business logic should remain in `should-cost-intelligence`.
Do not duplicate shared research logic across consuming applications.

Consumers should pin a known working release or commit of shared modules rather than depending blindly on a moving `main` branch.

## Reuse before duplication
Before building a capability from scratch, inspect relevant existing repositories and reuse proven patterns or modules where appropriate, especially:
- `research-core`
- `general-search`
- `Internet_pricing`
- `should-cost-intelligence`
- `context-studio`
- `tender_designer`
- `system-knowledge-designer`
- `olladex`

## Testing and quality
- Run relevant automated tests before committing.
- Add or update tests for material behaviour changes.
- Run build, lint, type-check, migration, or validation commands used by the repository when available.
- Do not claim a feature is complete if tests fail or only a scaffold exists.
- Fix regressions introduced by the change before moving on.

## Git workflow
- Verify the default branch before acting.
- Do not force-push the default branch.
- Do not rewrite published history unless explicitly requested.
- Keep commits focused and use clear commit messages.
- Do not push known failing changes unless explicitly requested as work in progress.

## Agent behaviour
- Make the smallest coherent change that fully satisfies the task.
- Prefer implementation over speculative redesign.
- Use repository evidence as the source of truth.
- If documentation and code disagree, identify the mismatch and update the appropriate source.
- Do not invent completed work, test results, files, endpoints, or integrations.
