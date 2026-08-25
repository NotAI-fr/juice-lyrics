# Changelog

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
