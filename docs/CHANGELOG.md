# Changelog

This project follows [Semantic Versioning](https://semver.org/) and uses PEP
440-compatible Python versions. Dates are added only when a release is
published.

## [2.0.0b3] - 2026-09-30

This beta makes routine local-library care easier to follow while keeping
catalogue choices and file changes explicit.

### Library and maintenance

- Added guided Maintenance that refreshes incrementally, summarizes library
  health, then walks through required decisions one song at a time.
- Simplified matching: existing matches are reused, uncertain recordings stay
  a human choice, and saved manual choices are preserved.
- Connected matching directly to lyric availability. After a match, Maintenance
  checks for lyrics and opens the existing preview and confirmation before a
  write. Missing lyrics can also be handled directly from Song Details.
- Added arrow-key and Enter actions in Song Details and More / Advanced, with
  clearer catalogue, lyric, and metadata status.
- Added skip, stop, and resume-by-rechecking behavior plus a completion summary;
  optional improvements do not block required work.
- Kept catalogue outages understandable and bounded. Existing trusted matches
  remain safe while online matching is skipped.

### Lyrics and reliability

- Included offline Local Lyrics Search from `v2.0.0b2`, covering embedded
  MP3/FLAC/M4A lyrics and adjacent plain or timed LRC files, with timestamps for
  timed matches and an incremental local index.
- Reused unchanged library and lyrics-index data across refreshes and searches;
  follow-up actions primarily refresh the affected song.
- Expanded isolated acceptance coverage with generated MP3, FLAC, and M4A
  fixtures, timed LRC, guided matching, protected lyric writes, skip/resume,
  and repeat-Maintenance checks.

### Installation

- Made the GitHub release and immutable tag the recommended installation path.
  `v2.0.0b2` and `v2.0.0b1` remain available as fallback releases; `main` is
  the moving development version.

## [2.0.0b2] - 2026-09-28

This beta promotes the offline Lyrics Search experiment into the main product.

### Library and lyrics

- Added local phrase search across embedded MP3, FLAC, and M4A lyrics and
  adjacent plain or timed LRC files. Timed LRC matches retain their timestamps.
- Added a rebuildable incremental lyrics index so unchanged tracks are reused,
  changed audio or sidecars are refreshed individually, and removed tracks
  disappear from results.
- Kept Lyrics Search offline and read-only for media, lyrics, state, backups,
  downloads, and player configuration.

### Documentation and installation

- Promoted `2.0.0b2` as the recommended beta with direct tag-based pipx install
  and troubleshooting guidance.
- Kept `v2.0.0b1` available as the previous immutable fallback.

## [2.0.0b1] - 2026-09-25

This is the first beta release of the redesigned `999` product.

### User experience

- Made `999` the primary command while retaining `juice-lyrics` as a legacy
  alias and preserving the existing `juice-lyrics` XDG data namespace.
- Added the keyboard-first Textual interface for Dashboard, Browse, Library,
  Downloads, and Settings, with global Help and consistent confirmations.
- Made **Sync Library** the routine one-button Library workflow and added
  focused Issues, Duplicates, Missing Library, backup/restore, manual match,
  and metadata-repair views.

### Library and lyrics

- Added native recursive MP3, FLAC, and M4A discovery and format-aware
  metadata, lyric, status, backup, restore, and verification behavior.
- Standardized synchronized external lyrics as atomic adjacent
  same-basename `.lrc` files. No audio conversion or centralized lyric output
  occurs.
- Added conservative catalogue backfill, manual identity locks, explicit
  identity rebuild, stale-state cleanup, and regression coverage for Bandit
  (`94107`) and 10 Feet (`94102`).
- Added transactional metadata repair for selected fields with backup,
  preservation checks, state-conflict protection, rollback, and post-edit
  manual-lock rebinding.

### Downloads and integration

- Added explicit catalogue browsing, a durable download queue, safe resume,
  response/size/checksum validation, retry, and post-processing.
- Kept queue addition separate from confirmed download execution.
- Added optional rmpc verification/setup and sidecar notification without
  rewriting rmpc configuration during normal startup or Library Sync.

### Operations and distribution

- Added bounded read-only `999 doctor` diagnostics with an optional sanitized
  support report.
- Added generated Bash, Zsh, and Fish completion from the actual CLI tree.
- Added deterministic wheel/sdist contents and clean-install acceptance for
  both console scripts without depending on the source checkout.
- Added incremental snapshot reuse and state-safety checks to avoid redundant
  hashing, metadata reads, API searches, and state writes.

### Compatibility and limitations

- Existing configuration, state, cache, backups, queue, and history remain in
  the `juice-lyrics` XDG namespace; no automatic migration is required.
- Acquisition/post-processing remains MP3-focused. FLAC and M4A support is for
  existing local-library files.
- Active download cancellation is not included in this beta candidate.

## [1.4.0] - 2026-08-25

### Backend and acquisition baseline

- Resolved live Juice WRLD API path resources into authorized download URLs
  with correct encoding and filename extraction.
- Preserved HTTPS-by-default transport with explicit HTTP fallback.
- Added safe catalogue search/info commands, multi-index and manifest queueing,
  persistent acquisition jobs, sequential execution, retry, and deletion.
- Added `.part` downloads, resume, size/checksum validation, maximum-size
  protection, destination checks, and atomic finalization.
- Added MP3 lyric post-processing with ID3 SYLT/USLT and rmpc-compatible LRC
  generation.
- Established the initial API, scanner, matching, lyrics, rmpc, backup,
  configuration, state, and acquisition service boundaries.

[2.0.0b2]: https://github.com/NotAI-fr/juice-lyrics/releases/tag/v2.0.0b2
[2.0.0b1]: https://github.com/NotAI-fr/juice-lyrics/releases/tag/v2.0.0b1
[2.0.0b3]: https://github.com/NotAI-fr/juice-lyrics/releases/tag/v2.0.0b3
[1.4.0]: https://github.com/NotAI-fr/juice-lyrics/releases/tag/v1.4.0-backend-complete
