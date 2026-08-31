# 999 Project State

## Current Status
Backend services remain stable. The experimental Textual frontend remains
read-only except for one explicit, confirmed Add to queue action. The current
checkpoint has 220 passing tests.

## Current Branch
v2-redesign

## Repository

`/home/nobloat/Downloads/juice-lyrics-codex`

## Completed and integrated

- Typed read-only library-status, catalogue, acquisition-queue, and library-sync services.
- Responsive terminal-native Textual shell with all five main sections functional; inspection remains read-only and Browse has one explicit Add to queue mutation.
- Canonical Category and Era selectors, filter-only searches, correct case-sensitive API cache behavior, server-side catalogue pagination, scrollable 50-result pages, and stable ID-based song details.
- Track-oriented Downloads queue summaries, song navigation, details, structured failures, and retry eligibility; durable jobs are hidden as an internal mechanism.
- Explicit cancel-first Browse Add to queue flow; adding persists one queued song but never starts downloading.
- Library summary, local track navigation, typed lyric/match/LRC/state details, local filters, and explicit read-only sync preview.
- Settings configuration provenance, XDG/application paths, path-existence checks, rmpc integration status, and current capability limitations.
- Existing MP3 lyric embedding, verification, backup/restore, synchronized LRC generation, and rmpc integration remain supported.

## Available through the CLI

The legacy CLI remains the supported way to run downloads, delete durable
acquisition records, and sync the library.

## Current limitations

- Configuration editing remains CLI-only.
- TUI Download, Remove, Clear, Retry, and Cancel actions are not implemented.
- Browse currently adds one song at a time; multi-select remains planned.
- Native FLAC support remains planned; lyric post-processing is currently MP3-only.
- The planned executable/product name remains `999`; package, distribution, and
  data paths remain named `juice-lyrics`.

## Important Decisions
- Keep embedded lyrics
- Keep LRC generation for rmpc
- Use terminal-native colours
- Use Textual
- Keep backend separate from UI

## Recommended next milestones

1. Downloads Download selected / Download all execution
2. Downloads Remove / Clear / Retry actions
3. Library sync actions
4. `999` command and naming migration
5. Native FLAC support
6. Beta polish, packaging, and release testing

## Resume development

```bash
cd /home/nobloat/Downloads/juice-lyrics-codex
git switch v2-redesign
.venv/bin/pytest -q
.venv/bin/juice-lyrics tui
```
