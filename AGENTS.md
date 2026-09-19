# 999 agent handoff

Start with [docs/PROJECT_STATE.md](docs/PROJECT_STATE.md). It is the canonical
current-state handoff. Use `PROJECT_CONTEXT.md` for durable product context and
the other `docs/` files for architecture, decisions, workflows, and UI detail.

## Identity and purpose

- Product and primary command: `999`
- Legacy command alias: `juice-lyrics`
- Python package: `juice_lyrics`
- Distribution: `juice-wrld-lyrics`
- XDG storage namespace: `juice-lyrics` (do not rename or duplicate it)
- Active development branch: `v2-redesign`
- Purpose: a Linux CLI/TUI for a local Juice WRLD library, catalogue browsing,
  safe lyric maintenance, downloads, backups, and optional rmpc integration.

## Non-negotiable safety rules

- Never let automated tests touch the user's real music, config, state,
  backups, queue, sidecars, or rmpc configuration.
- Tests that use application paths must isolate `HOME`, `XDG_CONFIG_HOME`,
  `XDG_DATA_HOME`, and `XDG_CACHE_HOME`. Preserve the guard in
  `tests/conftest.py`.
- Never run library operations against `/home/nobloat/Music` during automated
  work.
- Preserve atomic state/LRC writes, backup-before-media-mutation, restore
  rollback, state-conflict checks, and newest-10 valid backup retention.
- Wrong confident catalogue matches are worse than `Unknown`. Do not weaken
  matcher thresholds, version/variant safeguards, duration rules, or ambiguity
  handling without a reproduced generic bug and regression tests.
- Automatic Sync, backfill, refresh, cache changes, and ordinary identity
  rebuilds must not overwrite a valid file-bound manual identity lock.
- Preserve downloader destination checks, `.part` handling, response/content
  validation, checksums, resume safety, and atomic finalization.
- Do not make normal Sync modify audio, lyrics, backups, downloads, or rmpc
  configuration.

## Supported media and lyrics

- MP3: native discovery/metadata, ID3 USLT/SYLT, adjacent timed `.lrc`.
- FLAC: native discovery/metadata, plain Vorbis `LYRICS`, adjacent timed `.lrc`.
- M4A: native discovery/metadata, plain MP4 `©lyr`, adjacent timed `.lrc`.
- No conversion occurs. `sidecar_lrc_path(audio_path)` is authoritative.
- The deprecated `lyrics_dir` may load for compatibility but cannot redirect
  new output.

## Development entry points

- TUI/CLI: `.venv/bin/999`
- CLI: `src/juice_lyrics/cli.py`
- TUI: `src/juice_lyrics/tui/app.py`, `src/juice_lyrics/tui/screens/`
- Incremental Library Sync: `src/juice_lyrics/services/library_index_sync.py`
- Status/maintenance: `src/juice_lyrics/services/library_status.py` and
  `library_sync.py`
- Read-only duplicate analysis: `src/juice_lyrics/services/library_duplicates.py`
- Read-only metadata proposals: `src/juice_lyrics/services/metadata_audit.py`
- Matching/identity: `src/juice_lyrics/library/matching.py` and
  `src/juice_lyrics/services/library_identity.py`
- State: `src/juice_lyrics/state.py`
- Media/sidecars/backups: `src/juice_lyrics/library/media.py`,
  `src/juice_lyrics/lyrics/sidecar.py`, `src/juice_lyrics/backup/manager.py`

## Verification

Use focused tests while developing, then one full run before declaring a code
milestone complete:

```bash
pytest -q tests/test_library_index_sync.py tests/test_tui_library.py
pytest -q
python -m compileall -q src
git diff --check
```

Normal Library use is `999` → Library → `s` (**Sync Library**). Press `?` for
the implemented key map. Common safe routine work should be automatic/simple;
ambiguous or destructive work requires an explicit user decision.
Duplicate findings are evidence for review only; never auto-delete, merge,
move, retag, or replace media.
Metadata repair is preview-only until the apply transaction in
`docs/METADATA_REPAIR_DESIGN.md` is implemented and verified.

## Roadmap discipline

The current roadmap is in `docs/PROJECT_STATE.md` and `docs/ROADMAP.md`. Keep
normal Library UX centered on **Sync Library** and **Issues**; keep
repair/recovery tools secondary. After substantial milestones, update
`docs/PROJECT_STATE.md` and any directly affected design/user documentation.
