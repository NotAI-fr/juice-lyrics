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

## Current sequence

1. Complete and evaluate the unreleased `feature/lyrics-search` offline local
   lyric-search experiment without changing `v2.0.0b1`.
2. Make the repository public only after the explicit final visibility action.
3. Collect beta feedback without weakening safety or conservative matching.
4. Prioritize demonstrated reliability and usability defects.

## Post-beta experiment: local lyrics search

The current experiment adds Library → `f` → **Search Lyrics** over existing
embedded MP3/FLAC/M4A lyrics and adjacent LRC files. It uses a rebuildable XDG
cache with incremental audio/sidecar fingerprint invalidation; query typing is
in-memory and offline. It remains unreleased until separately accepted.

Do not force ambiguous tracks into identities. Do not combine these milestones
into a broad rewrite. Each milestone should preserve the safety invariants in
`../AGENTS.md`, add focused regressions, and update `PROJECT_STATE.md`.
