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

Default rmpc lyric directory:

`~/Music/Juice WRLD/lyrics`

These paths are defaults only and must remain configurable and portable.

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
* Synced lyrics are embedded as ID3 SYLT.
* Synced lyrics also produce `.lrc` files for rmpc.
* If only API `lyrics` exists, embed them as ID3 USLT.
* Never invent timestamps or fake-sync plain lyrics.
* Plain lyrics without timestamps do not generate timed `.lrc` files.

## rmpc

Keep MPD + rmpc as the primary playback setup.

Default lyrics directory:

`~/Music/Juice WRLD/lyrics`

Preserve unrelated rmpc configuration when modifying configuration files.

Advanced commands:

```bash
juice-lyrics rmpc setup
juice-lyrics rmpc sync
juice-lyrics rmpc verify
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

First-time setup:

```bash
juice-lyrics setup
```

Normal maintenance:

```bash
juice-lyrics sync
```

Useful commands:

```bash
juice-lyrics status
juice-lyrics search
juice-lyrics info
juice-lyrics guide
juice-lyrics doctor
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
juice-lyrics acquire search "rental"
juice-lyrics acquire add "rental" --index 1
juice-lyrics acquire jobs
juice-lyrics acquire run <job-id>
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

## Acquisition → lyrics integration

After successful MP3 acquisition, an optional post-processing hook uses the existing lyrics engine.

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

Before modifying an MP3:

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
* Settings / Path CLI compatibility verified
* responsive terminal-native Textual shell with `ansi_color=True`
* functional read-only Dashboard, Browse, and Downloads screens
* canonical Category and Era selectors, filter-only searches, and correct case-sensitive API cache behaviour
* server-side catalogue pagination with scrollable 50-result pages and stable ID-based song details
* queue summaries, job navigation, track details, structured failure stages, and retry eligibility
* Library and Settings remain placeholders; TUI queue mutations and Browse download actions are not implemented
* legacy CLI remains the way to download, delete jobs, and sync
* 185 automated tests passing across the suite

The repository for this checkpoint is `/home/nobloat/Downloads/juice-lyrics-codex`
on branch `v2-redesign`. The planned product and executable name remains `999`,
but no rename or migration has been performed. Native FLAC support remains
planned.

Recommended next milestones are: read-only Library, Settings, Browse-to-download
job creation, Downloads Run/Retry/Delete actions, Library sync actions, the `999`
naming migration, native FLAC support, then beta polish and release testing.

To resume:

```bash
cd /home/nobloat/Downloads/juice-lyrics-codex
git switch v2-redesign
.venv/bin/pytest -q
.venv/bin/juice-lyrics tui
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
