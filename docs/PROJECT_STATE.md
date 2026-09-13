# 999 Project State

## Current Status
Backend services remain stable. The `999` Textual interface supports
immediate single- and multi-song Browse Add to queue actions and
selected or whole-queue downloads. The interface now prioritizes the streamlined
Browse → Add → Downloads → Download queue journey. The current working-tree
checkpoint has 386 passing tests.

## Current Branch
v2-redesign

## Repository

`/home/nobloat/Downloads/juice-lyrics-codex`

## Completed and integrated

- Typed read-only library-status, catalogue, acquisition-queue, and library-sync services.
- Responsive terminal-native Textual shell with all five main sections functional; Browse adds one or marked songs without a confirmation or starting a download.
- Canonical Category and Era selectors, filter-only searches, correct case-sensitive API cache behavior, server-side catalogue pagination, scrollable 50-result pages, and stable ID-based song details.
- Track-oriented Downloads queue summaries, song navigation, details, structured failures, and retry eligibility; durable jobs are hidden as an internal mechanism.
- Stable-ID Browse marks span pages within one logical search; Space toggles a song, `M` toggles the page, `u` clears marks, and search/filter changes clear hidden marks.
- Immediate Browse batch Add flow persists eligible songs atomically and never starts downloading.
- Downloads `d` starts one explicitly selected eligible queued song without an extra prompt, delegated to the existing acquisition runner with responsive Downloading and Processing states.
- Explicit cancel-first Downloads `A` flow for sequentially downloading all eligible queued songs; failed and active entries are skipped.
- Simplified primary shortcut bars, optional Browse selection indicators,
  Dashboard journey prompts, and Settings folders before advanced diagnostics.
  A scrollable global `?` guide inventories all TUI actions; common actions stay
  visible. Bulk/destructive/config-changing operations remain cancel-first.
- Library is the normal maintenance centre: format-aware summary, track details,
  read-only refresh/verification, non-mutating maintenance preview, confirmed
  shared-service execution, selected-song refresh, backup browsing/restore, and
  rmpc verification/setup.
- Library lyric health is independent of catalogue identity: valid local
  embedded lyrics plus a genuinely timestamped adjacent sidecar can be fully
  covered even when the catalogue match is unknown. Catalogue-unmatched totals
  remain visible separately and do not inflate lyric-attention totals.
- Library Refresh now backfills confident catalogue identities for newly
  discovered MP3, FLAC, and M4A files through the shared conservative matcher,
  without modifying audio or lyrics; offline failure leaves local health usable.
- `999 state clean` previews clearly stale external records, while explicit
  `--yes` creates a timestamped state safety copy and atomically prunes only the
  reviewed records. Valid relative history and ambiguous duplicates are kept.
- Catalogue identities can be rebuilt for all current tracks through an
  explicit cancel-first Library action or `999 state rebuild-identities`.
  Rebuilds preserve lyric state, audit changed IDs, back up state, and commit
  atomically without touching media.
- Settings configuration provenance, XDG/application paths, sidecar external-lyrics behavior, rmpc integration status, and current capability limitations.
- Existing MP3 lyric embedding, verification, backup/restore, synchronized LRC generation, and rmpc integration remain supported.
- Local FLAC files are recursively discovered and matched using native title,
  artist, album, and duration metadata. FLAC lyric writes use standard Vorbis
  `LYRICS`, preserve unrelated metadata, and are backed up before mutation.
- FLAC synchronized timing uses the adjacent `.lrc`; there is no proprietary
  embedded timing format and no audio conversion.
- Local M4A files are recursively discovered and matched using native MP4 title,
  artist, album, and duration metadata. Plain lyrics use standard `©lyr` metadata.
- M4A synchronized timing uses the adjacent `.lrc`; unrelated atoms and the
  audio stream are preserved and no conversion occurs.
- External synchronized LRC files live beside each audio file with the same
  basename; the finalized audio path is authoritative.
- The legacy `lyrics_dir` setting remains readable but deprecated. Historical
  state paths and rmpc configuration cannot redirect new LRC output, and
  read-only operations create no sidecars or directories.

## Available through the CLI

The advanced CLI remains supported for scripting, whole acquisition records,
low-level recovery, diagnostics, and durable acquisition-record operations.

## Current limitations

- Configuration editing remains CLI-only.
- Active-download Cancel remains unimplemented; `x` removes
  a waiting/failed song, `c` clears waiting/failed records, and `H` clears
  completed history without deleting downloaded files.
- Acquisition post-processing remains MP3-only; native FLAC and M4A support
  targets existing local-library files.
- `999` is the primary product and executable name. `juice-lyrics` remains a
  legacy compatibility command. The Python namespace remains `juice_lyrics`,
  the distribution remains `juice-wrld-lyrics`, and existing XDG data remains
  under `juice-lyrics` without migration.

## Important Decisions
- Keep embedded lyrics
- Keep LRC generation for rmpc
- Use terminal-native colours
- Use Textual
- Keep backend separate from UI

## Recommended next milestones

1. Final beta polish and release testing
2. Active-download cancellation, if still desired
3. Post-beta enhancements only after real-user feedback

## Resume development

```bash
cd /home/nobloat/Downloads/juice-lyrics-codex
git switch v2-redesign
.venv/bin/pytest -q
.venv/bin/999
```
