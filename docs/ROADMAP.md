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

1. Collect `2.0.0b2` beta feedback without weakening safety or conservative
   matching.
2. Prioritize demonstrated reliability and usability defects.

## Released beta: local lyrics search

`2.0.0b2` adds Library → `f` → **Search Lyrics** over existing embedded
MP3/FLAC/M4A lyrics and adjacent LRC files. It uses a rebuildable XDG cache
with incremental audio/sidecar fingerprint invalidation; query typing is
in-memory and offline. The previous `v2.0.0b1` release remains immutable and
available as the fallback.

Do not force ambiguous tracks into identities. Do not combine these milestones
into a broad rewrite. Each milestone should preserve the safety invariants in
`../AGENTS.md`, add focused regressions, and update `PROJECT_STATE.md`.
