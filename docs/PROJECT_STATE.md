# 999 Project State

## Current Status
Backend services remain stable. The experimental Textual frontend supports one
explicit confirmed Browse Add to queue action and one explicit confirmed
Download selected action. The current working-tree checkpoint has 250 passing
tests.

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
- Explicit cancel-first Downloads `d` flow for one eligible queued song, delegated to the existing acquisition runner with responsive Downloading and Processing states.
- Explicit cancel-first Downloads `A` flow for sequentially downloading all eligible queued songs; failed and active entries are skipped.
- Library summary, local track navigation, typed lyric/match/LRC/state details, local filters, and explicit read-only sync preview.
- Settings configuration provenance, XDG/application paths, path-existence checks, rmpc integration status, and current capability limitations.
- Existing MP3 lyric embedding, verification, backup/restore, synchronized LRC generation, and rmpc integration remain supported.
- External synchronized LRC files use the authoritative `lyrics_dir` setting, defaulting to the shared `~/Music/lyrics` directory.
- Historical state paths and rmpc configuration cannot redirect new LRC output;
  read-only operations do not create either the central or legacy directory.

## Available through the CLI

The legacy CLI remains the supported way to run whole acquisition records,
retry failures, delete durable acquisition records, and sync the library.

## Current limitations

- Configuration editing remains CLI-only.
- TUI Cancel and multi-select remain unimplemented; `x` removes
  a waiting/failed song, `c` clears waiting/failed records, and `H` clears
  completed history without deleting downloaded files.
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

1. Downloads Download all execution
2. Downloads Download all, Cancel, and multi-select actions
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
