# Development Guide

## Baseline

The 1.4.0 release is the known-good functional baseline.

Run:

```bash
pytest -q
```

The baseline test suite includes core parsing and rmpc configuration/LRC checks.

## Before changing architecture

Read:

1. `PROJECT_CONTEXT.md`
2. `docs/ROADMAP.md`
3. `docs/ARCHITECTURE.md`

Then inspect the current implementation and tests.

When working on acquisition, inspect the actual implementation before deciding which roadmap items are complete. Documentation records project intent and history; the current code and tests determine the actual implementation state.

## Change strategy

Prefer incremental, reviewable changes.

For large work:

1. refactor one responsibility
2. run tests
3. commit
4. implement the next responsibility
5. run tests again

Do not rewrite working behavior without a clear reason.

## Testing expectations

Do not make unit tests depend on the live Juice WRLD API.

Use fixed/mock API responses for deterministic tests.

New components should receive focused tests before being integrated into the main sync workflow.

## Packaging

The project uses `pyproject.toml` and exposes the `juice-lyrics` console script.

Keep the runtime dependency set small.

## Source of truth and Git workflow

The latest transferred project checkpoint/archive is the source of truth for ongoing development. The existing GitHub repository is not authoritative and should not be used as the development baseline.

When version control is introduced, create a fresh repository from a known-good checkpoint and make logical milestones so changes can be inspected or reverted independently. The user should be given copy/paste instructions rather than being expected to understand Git internals.

## Checkpoint workflow

Development checkpoints are distributed as source ZIPs. When applying one to a local Git checkout, keep `.git/` untouched, run the test suite, then commit the result as a single logical milestone.
