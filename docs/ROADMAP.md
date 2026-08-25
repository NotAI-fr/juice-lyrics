# Roadmap

## Current baseline: 1.4.0

The project already provides a working local-library lyrics workflow:

* API song search and metadata lookup
* version-aware local/API matching
* alias-aware matching
* duration-aware matching
* synced lyrics parsing
* ID3 SYLT embedding
* ID3 USLT fallback
* rmpc `.lrc` generation
* safe rmpc config patching
* incremental state tracking
* timestamped MP3 backups
* verification and restore
* XDG-aware config/cache/data locations
* `setup`, `sync`, `status`, `scan`, `embed`, `verify`, `restore`, `doctor`, `guide`, `search`, `info`, `config`, and `rmpc` commands

## Phase 1 — Safety net and architecture

* Keep project documentation current.
* Separate API, library, lyrics, rmpc, backup, configuration, UI, and acquisition responsibilities.
* Reduce reusable logic living in `cli.py`.
* Keep all currently working behavior intact.
* Increase unit/integration test coverage before major feature work.

## Phase 2 — Acquisition foundation

For explicitly selected resources:

* normalized acquisition models ✅
* resource resolution with live API path support ✅
* single-item download foundation ✅
* temporary-file downloads ✅
* atomic finalization ✅
* content/size validation ✅
* retries and resumable downloads where supported ✅
* duplicate detection ✅
* explicit overwrite policy ✅
* progress reporting ✅
* persistent acquisition state/jobs ✅
* job execution/orchestration ✅
* post-download MP3 lyrics/rmpc integration ✅

## Phase 3 — Acquisition UX and bulk workflows

Completed milestones:

* real API/resource validation ✅
* multi-index explicit selection (`--index 1,2,4`) ✅
* manifest-driven bulk selection (`acquire manifest`) ✅
* retry failed/pending items (`acquire retry`) ✅
* job record deletion (`acquire delete`) ✅
* interrupted-item recovery on startup ✅
* duplicate detection and skip policy ✅
* per-item status and run summaries ✅

Bulk operations operate on explicitly selected resources rather than silently turning catalogue searches into acquisition jobs.

## Phase 4 — Post-download library integration

* metadata matching ✅
* canonical filename handling ✅
* synced/plain lyric embedding ✅
* rmpc LRC generation ✅
* verification and rollback ✅
* incremental state updates (`state.json`) ✅
* automated backups ✅

The existing lyrics pipeline remains the implementation used for acquired MP3s.

## Phase 5 — Browse/search frontend

Build an interactive TUI using the same backend services:

* interactive API search
* result browsing
* song details
* category/era filters
* random discovery
* explicit acquisition actions

Do not duplicate acquisition or matching logic inside the TUI.

## Phase 6 — Project rename / hub UX

Only after the core architecture is stable:

* consider a broader Juice WRLD API hub name
* polish the interactive frontend
* update package/executable/docs carefully
* preserve compatibility where practical

## Explicitly not planned right now

* custom streaming engine
* fake lyric synchronization
* unexplained popularity rankings
* unnecessary heavyweight GUI dependencies

## Current status

Completed:

* core engine modularization
* acquisition models & live API resource resolution
* duplicate detection
* persistent jobs & transient state recovery
* sequential job execution & resume support
* acquisition CLI (`search`, `add`, `manifest`, `jobs`, `run`, `retry`, `delete`)
* MP3 post-download lyrics/rmpc integration
* Settings/Path CLI compatibility across all commands
* 80 automated unit and integration tests passing

Current focus:

1. freeze the backend and verify CLI stability
2. proceed to application rename and interactive TUI frontend development
