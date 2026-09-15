# 999 project state

This is the canonical detailed handoff for the current application. It records
the repository state after `31ebaf2 Add one-button Library Sync`. Read the code
and tests if a later working tree disagrees with this document.

## Repository checkpoint

- Repository: `/home/nobloat/Downloads/juice-lyrics-codex`
- Active development branch: `v2-redesign`
- Stable pre-redesign branch/tag: `main` / `v1.4.0-backend-complete`
- Product/primary executable: `999`
- Compatibility executable: `juice-lyrics`
- Python package: `juice_lyrics`
- Distribution: `juice-wrld-lyrics`
- XDG storage namespace: `juice-lyrics`
- Last verified product commit: `31ebaf2`
- Verification at that commit: 410 tests passed; 14 isolated recovery smoke
  tests passed; compileall and `git diff --check` passed.

Test totals are checkpoint evidence, not a permanent promise. Run the current
suite before reporting a later code milestone.

## Product experience

The main download journey remains:

```text
Browse → Add → Downloads → Download queue → Done
```

Browse supports catalogue filters, pagination, details, stable-ID multi-select,
and immediate queue addition. Adding never starts a download. Downloads exposes
individual download/retry plus a confirmed whole-queue action while keeping
durable acquisition-job IDs out of the normal UI.

Library is the maintenance centre. The primary routine action is:

```text
s → Sync Library
```

`?` opens the complete scrollable key guide globally. Common actions remain in
screen shortcut lines. Harmless actions are immediate; high-impact operations
use a cancel-first confirmation where `y` executes immediately, `n`/Escape
cancels, and initial Enter cancels.

## One-button Library Sync

Sync Library runs in a background worker and cannot be started twice
concurrently. It uses persisted filesystem fingerprints and the current scan to
classify library-relative MP3, FLAC, and M4A paths as:

- **unchanged** — same path, size, and nanosecond mtime; reuse safe snapshot and
  identity information and avoid redundant hashes, metadata reads, and writes;
- **new** — newly discovered current-library audio;
- **changed** — filesystem evidence changed; reread metadata and do not trust a
  stale identity merely because the relative path is the same;
- **removed** — previously active path no longer exists in the current scan.

New, changed, and currently Unknown tracks are offered to the shared
conservative catalogue matcher. Confident identities are persisted; ambiguous
or empty-result tracks remain Unknown. Normal cache expiry governs retries, so
Sync does not force every catalogue request on every run. One failed lookup does
not prevent other confident matches from being saved. A broad/offline failure
leaves local health useful and does not wipe established identities.

Removed tracks are retired with current-library bookkeeping rather than having
their historical/custom state records destructively deleted. Clearly stale
external records remain the responsibility of explicit state cleanup.

Sync refreshes displayed local lyric health but does **not** edit audio,
embedded lyrics, sidecars, audio backups, queue/history, or rmpc configuration.
It does not download music. Optional rmpc absence/failure is not a Library Sync
failure.

## Library health and maintenance

Catalogue identity and local lyric health are separate axes. A healthy track
may be catalogue Unknown without needing lyric attention. An adjacent `.lrc`
counts as synchronized only when it contains genuine timestamped lyric lines.

- MP3 full coverage uses the existing format-aware ID3 requirements plus its
  synchronized sidecar behavior.
- FLAC full coverage requires supported embedded plain lyrics and a valid timed
  adjacent `.lrc`; MP3 SYLT is not required.
- M4A full coverage requires supported embedded plain lyrics and a valid timed
  adjacent `.lrc`; MP3 SYLT is not required.

`m` previews lyric maintenance without mutation, then requires explicit
confirmation before applying the shared sync/backup/verification pipeline.
`v` verifies read-only. Track details, selected lyric refresh, backup browsing
and confirmed restore, rmpc verify/explicit setup, identity rebuild, and stale
state cleanup remain available as contextual or advanced operations.

## Catalogue identity and matcher

Normal discovery does not depend on historical state: unknown MP3, FLAC, and
M4A tracks can be identified through the shared backfill/matcher path. Only a
confident `song_id` and `api_name` are merged; lyric state is never fabricated.
Known compatible persisted identities are reused until file-change evidence
invalidates them.

Matching remains conservative and uses normalized titles/collaboration credits,
artist evidence, meaningful version/named-variant penalties, category evidence,
album/API-path evidence, duration tolerance, a narrow released-album duration
grace, a confidence threshold, and an ambiguity margin. Key live-shaped
regressions are:

```text
Bandit  → song_id 94107
10 Feet → song_id 94102
```

A wrong confident result is worse than Unknown. Do not weaken safeguards merely
to reduce the Unknown count.

Full identity rebuild is an explicit recovery transaction. Preview is
non-mutating; apply rematches current files in memory, preserves non-identity
state, creates a complete state backup, audits changed IDs, and atomically
replaces state. A provider-wide outage aborts rather than erasing identities.

Explicit stale-state cleanup previews first, makes a state backup, and
atomically removes only clearly stale nonexistent external records. Historical
relative paths and uncertain legacy duplicates are deliberately preserved.

## Media, lyrics, backups, and rmpc

- MP3, FLAC, and M4A are recursively discovered case-insensitively.
- MP3 retains ID3 USLT/SYLT behavior.
- FLAC stores plain lyrics in standard Vorbis `LYRICS`.
- M4A stores plain lyrics in standard MP4 `©lyr`.
- Synchronized external lyrics always use the exact adjacent same-basename
  `.lrc`; no format conversion or centralized lyrics output occurs.
- Media metadata mutation is preceded by backup and followed by verification;
  failure restores the original. Backup retention keeps the newest 10 valid
  backups, and historical manifests remain readable.
- rmpc receives the actual adjacent sidecar path. Normal startup, status,
  refresh, and Sync never rewrite rmpc configuration; setup is explicit.

## State and filesystem safety

State/LRC writes are atomic. State updates retain conflict protection so an
operation does not silently overwrite a concurrently changed state file.
Restore uses safe replacement/rollback semantics. Tests install isolated HOME
and XDG paths before application imports and guard against the real home.

Never run automated library work against `/home/nobloat/Music` or the user's
real config, state, backups, queue, sidecars, or rmpc configuration.

## Known limitations and risks

- The conservative matcher intentionally leaves ambiguous/no-result songs
  Unknown; manual match and identity locking are not implemented yet.
- Library has attention/details but not a consolidated Issues experience.
- Active download cancellation is not implemented.
- Acquisition/post-processing remains MP3-focused; FLAC/M4A support is for
  existing local-library files.
- Configuration editing remains primarily CLI-based.
- `cli.py` still contains a second equivalent `load_settings()` plus later
  service-adapter definitions that shadow older local `search_api`,
  `search_api_advanced`, and `get_song` implementations. This
  compatibility-era layering is maintenance debt; consolidate only with
  focused CLI/API tests.
- `tui/screens/placeholder.py` is still exported but no current screen uses it.
  Remove it only as a small tested code-cleanup change.
- The old `lyrics_dir` configuration is compatibility-only and does not migrate
  historical centralized files.
- Packaging/install acceptance and public GitHub presentation still need a
  final release pass.

## Roadmap

Product principle:

```text
common safe routine work → automatic/simple
ambiguous/destructive work → explicit user decision
```

Keep normal Library UX centered on **Sync Library** and future **Issues**;
advanced repair/recovery must not overwhelm normal use.

1. Manual catalogue match and identity locking
2. Library Issues / Health experience
3. Duplicate detector
4. Metadata repair
5. Missing Library
6. `999 doctor` / diagnostics
7. Shell completion
8. Final performance/reliability acceptance
9. Packaging and clean installation
10. GitHub presentation/distribution
11. Beta release

## Resume safely

```bash
cd /home/nobloat/Downloads/juice-lyrics-codex
git switch v2-redesign
git status --short
pytest -q
.venv/bin/999
```

Read `AGENTS.md` first, then this file, then the relevant architecture/user
document. Update this file after substantial milestones.
