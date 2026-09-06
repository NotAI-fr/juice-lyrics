# Changelog

## Unreleased — 999 beta identity and packaging

* Made `999` the primary product name and console entry point while retaining
  `juice-lyrics` as an alias to the same CLI implementation.
* Kept the internal `juice_lyrics` package, `juice-wrld-lyrics` distribution,
  and `juice-lyrics` XDG storage namespace stable for compatibility.
* Made no-argument startup open the existing TUI and kept startup read-only with
  respect to rmpc configuration and deprecated centralized lyrics paths.
* Clarified setup responsibilities: `config init` writes starter configuration,
  `setup` synchronizes the library, and only explicit `rmpc setup` changes rmpc.
* Added isolated entry-point, first-run, storage compatibility, shell, and
  editable-install verification.
* Verified 318 automated tests with isolated temporary HOME/XDG paths.

## Unreleased — Native M4A library support

* Added recursive, case-insensitive `.m4a` library discovery without broadening
  support to other MP4-family extensions.
* Added native M4A title, artist, album, and duration reading through Mutagen.
* Reused the normal version/title/path/duration matcher and conservatively leaves
  M4A files without title or artist metadata unmatched.
* Added standard plain-text MP4 `©lyr` embedding while preserving unrelated atoms,
  the media payload, and the original audio format.
* Kept synchronized M4A timing in the authoritative adjacent `.lrc`; no
  proprietary timing atom or conversion is used.
* Extended verification/status, state, backup/restore, retention recognition,
  and rmpc sidecar notification to local M4A files.
* Verified 310 automated tests with isolated temporary HOME/XDG paths.

## Unreleased — Native FLAC library support

* Added recursive, case-insensitive MP3 and FLAC library discovery.
* Added native FLAC title, artist, album, and duration reading through Mutagen.
* Reused version/title/path/duration matching for FLAC and conservatively leaves
  FLAC files without title or artist metadata unmatched.
* Added standard plain-text Vorbis `LYRICS` embedding while preserving unrelated
  FLAC metadata and the audio stream; no audio conversion occurs.
* Kept synchronized FLAC timing in the authoritative adjacent `.lrc` because
  FLAC/Vorbis comments have no interoperable ID3 SYLT equivalent.
* Extended library sync, verification/status, state, backup/restore, and rmpc
  sidecar notification to local FLAC files.
* Generalized rolling backup recognition and restore for FLAC without changing
  the newest-10 retention policy or invalidating historical MP3 manifests.
* Verified 298 automated tests with isolated temporary HOME/XDG paths.

## Unreleased — 2026-08-25

### Live API path resolution and backend polish

* Resolved live Juice WRLD API `path` resources into authorized download URLs (`/files/download/?path=...`) with correct URL encoding and destination filename extraction.
* Preserved default HTTPS security policy with opt-in HTTP fallback.
* Fixed CLI `Settings` vs `Path` regression in `library.scanner.find_mp3s()`, restoring stability across `status`, `setup`, `sync`, `scan`, `embed`, `verify`, and `rmpc` commands.
* Fixed safe era metadata formatting in `search` and `info` commands.
* Added multi-index selection (`--index 1,2,4`), manifest-based bulk acquisition (`acquire manifest`), retry (`acquire retry`), and job deletion (`acquire delete`).
* Verified end-to-end live API acquisition and CLI workflows.
* Reached 80 automated unit and integration tests passing.

### Existing acquisition milestones

* Added the acquisition resource resolver for explicitly selected resources.
* Added HTTPS-by-default URL validation and safe destination filename handling.
* Added propagation/validation of expected size and SHA-256 metadata.
* Added acquisition resolver tests; the project test suite then passed 11 tests.
* Added duplicate detection for existing resources using checksum, safe destination checks, and title/version matching; the project test suite then passed 15 tests.
* Added persistent acquisition jobs backed by atomic JSON saves, per-item progress/state, job listing/lookup/deletion, and recovery of interrupted transient states; the project test suite then passed 20 tests.
* Added a conservative sequential acquisition job runner.
* Added duplicate checks before download, atomic per-item persistence, progress callbacks, and failure isolation.
* Added runner tests; the project test suite then passed 23 tests.
* Added the first integrated acquisition CLI workflow: `acquire search`, `acquire add`, `acquire jobs`, and `acquire run`.
* Acquisition does not silently crawl the catalogue.
* Added CLI workflow tests; the project test suite then passed 26 tests.
* Added post-download integration for acquired MP3s.
* Reused the established synced/plain lyric embedding and verification pipeline.
* Generated rmpc-compatible `.lrc` files for acquired files with synced lyrics.
* Post-processing failures are persisted as job failures.

## Unreleased — Architecture

* Began separating reusable engine code from the CLI entrypoint.
* Added dedicated API, library matching/scanning, lyrics, rmpc, backup, config, and state modules.
* Kept existing CLI commands compatible through adapters.

## Unreleased — Acquisition foundation

* Added an isolated `acquisition/` package.
* Added acquisition item/result/state models.
* Added explicit-selection manifests.
* Added a generic HTTPS downloader with temporary `.part` files, retries, optional resume, size/checksum validation, maximum-size protection, and atomic finalization.
* Added acquisition foundation tests.
* Kept acquisition transport independent from lyrics/rmpc post-processing.
