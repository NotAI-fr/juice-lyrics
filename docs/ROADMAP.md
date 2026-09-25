# Roadmap

The canonical current checkpoint is `PROJECT_STATE.md`. This file keeps
only the forward product sequence.

## Product rule

```text
common safe routine work → automatic/simple
ambiguous/destructive work → explicit user decision
```

Normal Library UX stays centered on **Sync Library** and **Issues**.
Advanced repair and recovery remain available without crowding routine use.

## Remaining sequence

1. Complete `BETA_RELEASE_CHECKLIST.md` manual acceptance
2. Review and merge `v2-redesign` through a pull request
3. Create the approved `v2.0.0b1` GitHub pre-release and attach artifacts

Do not force ambiguous tracks into identities. Do not combine these milestones
into a broad rewrite. Each milestone should preserve the safety invariants in
`../AGENTS.md`, add focused regressions, and update `PROJECT_STATE.md`.
