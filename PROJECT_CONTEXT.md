# Project Context

This file preserves the human/project context needed to continue development across chats and coding agents.

## User / environment context

* Primary OS: Arch Linux.
* The user prefers lightweight Linux tools and CLI/TUI workflows.
* The user uses MPD + rmpc for music playback.
* The user is comfortable running commands, but is not a Python developer.
* Normal workflows should use straightforward commands, friendly output, sensible defaults, and safe automation.
* The user should not be expected to understand Python internals to use the application.

## Music setup

Default local library:

`~/Music/Juice WRLD/Unreleased`

External synchronized lyrics use same-basename sidecars beside each MP3, FLAC, or M4A song. The
music path remains configurable and portable.

## Existing proven behavior

The 1.4.0 release was tested against a 35-song local library:

* 35/35 API matches
* 18 songs with synchronized lyrics
* 17 songs with plain lyrics only
* 18 rmpc LRC files generated
* 35/35 lyric embeddings verified
* version-aware matching works for v1/v2 tracks
* backups and restore work
* rmpc integration works

The existing lyrics workflow is proven and should not be unnecessarily redesigned.

## Lyrics behavior

* Prefer API `synced_lyrics`.
* Synced lyrics are embedded as ID3 SYLT in MP3 files.
* Synced lyrics also produce `.lrc` files for rmpc.
* If only API `lyrics` exists, embed them as ID3 USLT in MP3 files.
* FLAC files store standard plain-text Vorbis `LYRICS`; synchronized timing
  remains in the adjacent `.lrc` because FLAC has no interoperable SYLT equivalent.
* M4A files store standard plain-text MP4 `©lyr`; synchronized timing remains
  in the adjacent `.lrc` rather than a proprietary tag.
* Never invent timestamps or fake-sync plain lyrics.
* Plain lyrics without timestamps do not generate timed `.lrc` files.

## rmpc

Keep MPD + rmpc as the primary playback setup.

Audio and external synchronized lyrics stay together: `song.mp3`, `song.flac`, or `song.m4a`
maps to `song.lrc` in the same directory. The finalized audio path is the sole write
authority. The legacy `lyrics_dir` key remains readable but is deprecated and
cannot redirect current output. Read-only inspection and planning create
nothing; rmpc configuration and historical state paths cannot redirect new
output. During development use the repository entry
point (`.venv/bin/999`) so a stale separately installed package is not
mistaken for the current working tree.

Preserve unrelated rmpc configuration when modifying configuration files.

Advanced commands:

```bash
999 rmpc setup
999 rmpc sync
999 rmpc verify
```

## Matching

Matching intentionally uses several signals rather than trusting a title alone:

* explicit version (`v1`, `v2`, etc.)
* exact API filename
* exact API path filename
* title/original key
* known Juice WRLD aliases
* local audio duration vs API duration
* category preference

This helps prevent version mix-ups such as selecting `Starstruck (v1)` for a local `Starstruck (v2)` file.

## Normal workflow

Open the application:

```bash
999
```

Normal maintenance:

```bash
999 sync
```

Useful commands:

```bash
999 status
999 search
999 info
999 guide
999 doctor
```

## Project direction

The project is evolving from a focused lyrics utility into a polished Juice WRLD API frontend/hub while retaining the existing CLI functionality.

Long-term direction includes:

* interactive browse/search TUI
* API search and discovery
* explicit resource acquisition
* bulk acquisition from explicitly selected resources
* richer local library management
* improved user-facing UX

Do not replace MPD/rmpc with a custom streaming system.

## Acquisition subsystem

The project contains an acquisition subsystem for resources represented by the application's resource/API layer and explicitly selected by the user.

The intended flow is:

```text
resource/API result
       ↓
explicit user selection
       ↓
AcquisitionItem
       ↓
persistent acquisition job
       ↓
downloader
       ↓
validation/finalization
       ↓
post-processing
       ↓
existing lyrics/library workflow
```

The acquisition layer is deliberately separated into:

* resource resolution
* selection
* acquisition item modelling
* duplicate detection
* persistent jobs
* transport/download
* validation
* post-processing

The downloader is a transport component. It should not perform catalogue discovery, matching, or lyrics processing.

## Acquisition components

The current architecture includes:

* `models.py` for acquisition item/result/job state data
* `manifests.py` for explicit selection manifests
* `resolver.py` for converting selected resources into normalized acquisition items
* `downloader.py` for transport
* `jobs.py` for persistent acquisition jobs
* duplicate detection
* job execution/orchestration
* MP3 post-processing integration

The repository must be inspected to determine which of these components are complete, incomplete, or require refinement.

## Downloader expectations

The downloader is responsible for normal transport concerns such as:

* HTTPS transport
* streaming
* connection/read timeouts
* normal HTTP error handling
* retries for transient failures
* temporary `.part` files
* resumable transfers where the server supports them
* expected-size validation when supplied
* SHA-256 validation when supplied
* duplicate/existing destination handling
* progress reporting
* atomic finalization
* cleanup after failed transfers

It receives an already-resolved `AcquisitionItem`.

It should not:

* crawl the catalogue
* discover unrelated resources
* perform lyric matching
* modify MP3 metadata
* configure rmpc

## Acquisition CLI

The initial acquisition workflow is:

```bash
999 acquire search "rental"
999 acquire add "rental" --index 1
999 acquire jobs
999 acquire run <job-id>
```

The selection model must remain explicit. A search operation should not silently create acquisition jobs for every result.

## Persistent acquisition jobs

Jobs are stored persistently under the application's XDG data location.

The job system should:

* save atomically
* preserve per-item progress/state
* record errors
* recover interrupted states
* avoid losing successful completed items when another item fails

Persistent jobs are an internal durability and execution mechanism. The normal
product model is a flat download queue of songs; UUIDs should stay out of common
workflows. Browse can mark stable song IDs across pages of one search and
explicitly add the marked set (or the current song) without starting it.
Completed items remain stored but are hidden from the active queue,
and failed items remain visible for future retry or removal.

## Acquisition → lyrics integration

After successful MP3 acquisition, an optional post-processing hook uses the existing lyrics engine.
Acquisition remains MP3-focused; native FLAC and M4A support applies to existing local-library files.

The existing behavior remains:

```text
acquired MP3
     ↓
API metadata/lyrics
     ↓
SYLT or USLT
     ↓
verification
     ↓
rmpc .lrc when synced lyrics exist
```

Non-MP3 resources remain acquisition-only for now.

A post-processing failure must be persisted as an item failure rather than reported as full success.

## File safety

Before modifying an MP3, FLAC, or M4A file:

* create a timestamped backup
* write metadata safely
* verify the result
* restore the backup immediately if verification fails

Backups:

`~/.local/share/juice-lyrics/backups/`

Only lyric frames created by this tool are replaced.

Other unrelated lyric frames remain untouched.

## Current checkpoint

The latest development checkpoint reports:

* live API resource resolution implemented and verified
* multi-index selection and manifest-based bulk acquisition implemented
* retry and job deletion commands implemented
* persistent acquisition jobs and transient state recovery verified
* generic transport downloader with HTTP range resume and validation verified
* MP3 post-processing with ID3 SYLT/USLT and rmpc LRC integration verified
* native recursive FLAC discovery, metadata matching, Vorbis lyric embedding,
  verification, backup/restore, state, adjacent LRC, and rmpc notification verified
* native recursive M4A discovery, MP4 metadata matching, standard `©lyr`
  embedding, verification, backup/restore, state, adjacent LRC, and rmpc notification verified
* Settings / Path CLI compatibility verified
* responsive terminal-native Textual shell with `ansi_color=True`
* all five main TUI sections are functional; Browse can explicitly add one or several stable-ID selections to the queue
* Downloads can explicitly run one selected queued song after a cancel-first confirmation
* canonical Category and Era selectors, filter-only searches, and correct case-sensitive API cache behaviour
* server-side catalogue pagination with scrollable 50-result pages and stable ID-based song details
* flat track-queue summaries, song navigation, details, structured failure stages, and retry eligibility
* Library provides local track browsing, format-aware coverage summaries,
  read-only refresh/verification, confirmed lyric maintenance, selected-song
  refresh, valid backup browsing/restore, and rmpc verification/setup
* local lyric health is classified independently from catalogue identity;
  timestamped adjacent LRC content is validated rather than inferred from file
  existence, and healthy unmatched tracks do not require maintenance
* Settings reports effective configuration, sidecar lyrics behavior, provenance where reliable, application paths, and rmpc integration without creating or changing files
* TUI Download selected, Download queue, Retry, Remove, Clear queue, and Clear
  completed history are implemented; active-download cancel and general
  configuration editing are not implemented
* advanced CLI remains available for scripting, diagnostics, internal records,
  and unusual recovery
* 339 automated tests pass across the suite

The repository for this checkpoint is `/home/nobloat/Downloads/juice-lyrics-codex`
on branch `v2-redesign`. The product and primary executable are `999`.
`juice-lyrics` remains a legacy command alias; the internal `juice_lyrics`
package, `juice-wrld-lyrics` distribution, and existing `juice-lyrics` XDG
storage namespace remain stable for compatibility.

Recommended next milestone is final beta polish and release testing.

To resume:

```bash
cd /home/nobloat/Downloads/juice-lyrics-codex
git switch v2-redesign
.venv/bin/pytest -q
.venv/bin/999
```

## Development rules

Before major architectural changes, read:

* `PROJECT_CONTEXT.md`
* `docs/ROADMAP.md`
* `docs/ARCHITECTURE.md`

Prefer incremental, testable changes.

Preserve proven behavior.

Avoid unnecessary rewrites.

Add/update tests whenever behavior changes.

Update this file, `docs/ROADMAP.md`, and `docs/CHANGELOG.md` at meaningful milestones.

## Continuity

The latest transferred project archive is the current development source of truth.

The existing GitHub repository is not authoritative.

When documentation conflicts with the actual implementation, inspect the code and tests and resolve the discrepancy deliberately.
