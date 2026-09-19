# 999 project state

This is the canonical detailed handoff for the current application. One-button
Sync, manual catalogue locking, snapshot-backed Library Issues, read-only
duplicate review, and metadata repair audit/preview are integrated. Read the
code and tests if a later working tree disagrees with this document.

## Repository checkpoint

- Repository: `/home/nobloat/Downloads/juice-lyrics-codex`
- Active development branch: `v2-redesign`
- Stable pre-redesign branch/tag: `main` / `v1.4.0-backend-complete`
- Product/primary executable: `999`
- Compatibility executable: `juice-lyrics`
- Python package: `juice_lyrics`
- Distribution: `juice-wrld-lyrics`
- XDG storage namespace: `juice-lyrics`
- One-button Sync baseline: `31ebaf2` (410 tests plus 14 isolated recovery
  smoke tests, compileall, and `git diff --check`).
- Manual identity-lock milestone verification: 424 full-suite tests and 34
  explicit temporary-HOME/XDG identity/state smoke tests passed; compileall and
  `git diff --check` passed.
- Library Issues milestone verification: 435 full-suite tests and 30 explicit
  temporary-HOME/XDG Issues/Sync/identity smoke tests passed; compileall and
  `git diff --check` passed.
- Duplicate detector milestone verification: 453 full-suite tests and 45
  explicit temporary-HOME/XDG duplicate/status/Sync smoke tests passed;
  compileall and `git diff --check` passed.
- Metadata audit/preview milestone verification: 470 full-suite tests and 50
  explicit temporary-HOME/XDG metadata/status/identity/Sync smoke tests passed;
  compileall and `git diff --check` passed.
- Metadata safe-apply foundation verification: 486 full-suite tests, 158
  affected regression tests, and 51 explicit temporary-HOME/XDG
  repair/audit/identity/Sync smoke tests passed; compileall and
  `git diff --check` passed.

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
a → Issues
d → Duplicates
e → Metadata repair preview for the selected track
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

The Library headline reports total tracks, healthy tracks, and issue rows. `a`
opens **Issues** immediately from the current snapshot: opening it performs no
scan, hash, or API request. There is at most one row per track, combining
catalogue, lyrics, verification, metadata, and state reasons. Unknown identities
appear because they may need a manual decision even when local lyrics are fully
covered. Valid file-bound manual locks stay out; an unavailable locked choice
appears after a catalogue-backed operation observes that failure, without
replacing the choice. Retired history stays out because it requires no routine
action.

Issue details reuse only existing safe actions: manual catalogue match,
selected lyric-refresh preview, read-only verification, or Sync Library. Every
completed Sync replaces the displayed snapshot, so resolved rows disappear and
newly discovered problems appear immediately.

## Duplicate review

`d` opens **Duplicates** immediately from the current Library snapshot. It does
not rescan, rehash, call the catalogue API, or mutate files/state merely to
render the view. Exact groups share the same saved whole-file SHA-256. Probable
groups require compatible recording-version evidence and either the same
catalogue identity or compatible title, artist, and known duration metadata.

The detail panel explains the evidence and lists every library-relative path.
Numbered versions and named variants such as live, remix, recording session,
extended, TV mix, acoustic, demo, instrumental, and stems remain distinct.
Detection is review-only: it never deletes, merges, moves, retags, or replaces
audio. Because the view deliberately reuses current snapshot data, running Sync
first provides the freshest paths, metadata, identities, and saved hashes.

## Metadata repair audit and preview

`e` prepares a read-only metadata repair preview for the selected MP3, FLAC, or
M4A in a background worker. Metadata Issues also expose the same action. The
service reads the exact supported local tags and only the already-confirmed
catalogue ID; Unknown identities short-circuit without guessing or making a
catalogue request. Repeated preview in the same unchanged snapshot reuses its
result.

Supported proposal fields are title, artist, album, and track number. A missing
local field with explicit trustworthy catalogue evidence is **Confident**. Any
different non-empty local value is **Review** and is not treated as an automatic
replacement. Recording/version markers remain significant, including live,
remix, session, extended, TV mix, and numbered versions. Missing catalogue
fields produce no proposal. Album inference from an API path is limited to a
normal released record; track number requires an explicit API value.

The preview checks that the local file fingerprint did not change while it was
read and displays before/after evidence, identity provenance, format, and path.
It writes no audio, state, embedded lyrics, sidecars, backups, downloads, or
rmpc configuration. The normal TUI intentionally has no Apply action yet.
`METADATA_REPAIR_DESIGN.md` records the implemented backend safety contract and
the remaining UI/acceptance work.

The backend safe-apply foundation is implemented in `metadata_repair.py` for
MP3, FLAC, and M4A. Planning accepts only an explicit subset of proposals from
the reviewed audit. Execution additionally requires explicit confirmation. It
pins the current path, whole-file hash/fingerprint, state bytes, catalogue ID,
encoded media payload, unrelated tags/artwork/lyrics, and adjacent sidecar.

Execution creates and manifests a normal backup before modifying a
same-filesystem temporary copy. It writes only the selected format-native tags,
fsyncs, reopens, and verifies the copy before atomic replacement. It then
updates the existing state entry's hash without discarding custom or lyric
fields. State conflict/failure restores the original audio; interruption paths
before/after media and state replacement are covered. A valid manual lock is
preserved and rebound only after the controlled edit verifies successfully.

This backend is deliberately **not exposed by the TUI yet**. The existing `e`
workflow remains preview-only. Per-field controls, a cancel-first confirmation,
background execution/result UX, and real-copy acceptance are the next metadata
repair step; no incomplete Apply action is visible to normal users.

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

## Manual catalogue identity

Select any Library track and press `c` to open **Match manually**. The
background catalogue search starts with the local title; `/` focuses a small
refinement field, arrows choose a candidate, Enter saves it, and Escape
cancels. Candidate rows show title, category, era, duration, and catalogue ID
so released/session/version variants remain distinguishable.

A saved choice adds `identity_source = "manual"` and `identity_locked =
true` alongside the existing `song_id`, `api_name`, and current audio
SHA-256. Missing fields in historical state continue to mean
automatic/unlocked. The lock is visible only in track details and survives
restart, normal Sync, backfill, cache refresh, local refresh, and ordinary
identity rebuild. Lyric maintenance also uses the exact locked catalogue ID and
refuses to substitute a different candidate.

Locks are bound to the scanned audio fingerprint/hash. Changed or replaced
audio does not inherit the old lock. Press `u` to unlock: because the existing
automatic pipeline reuses any valid identity, unlock deliberately clears only
the catalogue identity/provenance fields and leaves lyrics, history, and custom
state untouched. It does not immediately search; a later Sync may identify the
track automatically.

Ordinary full identity rebuild preserves valid manual locks. The technical CLI
`999 state rebuild-identities --include-locked --yes` explicitly opts into
reconsidering them.

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
- Metadata repair remains preview-only in the TUI. Its backend transaction is
  implemented, but selection/confirmation UI and real-copy acceptance remain.

## Roadmap

Product principle:

```text
common safe routine work → automatic/simple
ambiguous/destructive work → explicit user decision
```

Keep normal Library UX centered on **Sync Library** and **Issues**;
advanced repair/recovery must not overwhelm normal use.

1. Metadata repair apply UI integration and real-copy acceptance
2. Missing Library
3. `999 doctor` / diagnostics
4. Shell completion
5. Final performance/reliability acceptance
6. Packaging and clean installation
7. GitHub presentation/distribution
8. Beta release

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
