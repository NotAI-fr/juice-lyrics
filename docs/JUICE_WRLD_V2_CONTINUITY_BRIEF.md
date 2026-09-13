# Juice WRLD TUI Project Continuity Brief (v2)

## Purpose

This document exists as a handoff/context file for continuing development of the Juice WRLD music management application after a chat reset.

It describes:
- current project state
- architectural decisions
- future direction
- UX goals
- important constraints

---

# Current Project Identity

The project started as:

`juice-lyrics`

Originally it was a CLI tool for:

- finding Juice WRLD lyrics through the Juice WRLD API
- embedding lyrics into MP3 ID3 tags
- generating rmpc-compatible LRC files
- syncing local music libraries

It has evolved into a much larger application:

A Juice WRLD music management hub containing:

- catalogue search
- metadata browsing
- local library management
- lyric management
- acquisition/download workflows
- rmpc integration
- backup and recovery systems

The product is now named `999`. The primary console command is `999`, while
`juice-lyrics` remains a legacy compatibility command.

---

# Current Backend Status

The backend is considered stable.

Milestone reached:

## Current verified checkpoint

The current development branch is `v2-redesign` in
`/home/nobloat/Downloads/juice-lyrics-codex`. The complete automated suite has
386 passing tests.

Completed and integrated:

Verified systems:

- API client
- search
- metadata lookup
- track matching
- lyric parsing
- ID3 SYLT embedding
- ID3 USLT embedding
- native FLAC discovery, metadata matching, Vorbis lyric embedding, and verification
- native M4A discovery, MP4 metadata matching, standard `©lyr` embedding, and verification
- LRC generation
- rmpc integration
- backups
- restore system
- downloader
- resume support
- persistent acquisition jobs
- duplicate detection
- CLI workflows

The v2 frontend now also includes a responsive terminal-native Textual shell,
functional Dashboard and Browse screens, canonical Category and Era
selectors, correct case-sensitive API cache behavior, server-side catalogue
pagination with scrollable 50-result pages, stable ID-based song details, and a
Downloads screen with a flat track queue, song navigation, details, failure
stages, retry eligibility, an immediate Browse Add to queue flow that never
starts a download, and Download selected for one
eligible queued song, a Library maintenance centre with local track browsing,
filters, details, read-only refresh/verification, confirmed lyric maintenance,
backup/restore, and rmpc checks, and a read-only
Settings screen with effective configuration, paths, provenance, and rmpc state.
Library Help also exposes a cancel-first, state-only catalogue identity rebuild
for rerunning the latest matcher across current MP3, FLAC, and M4A files.

All five primary TUI sections are functional. Browse supports immediate single
and batch queue additions. Downloads supports immediate Download selected,
sequential Download queue, Retry, Remove, Clear queue, and Clear completed history.
Active-download cancellation and general configuration editing are not implemented.
The global `?` key opens a scrollable guide to the implemented keymap. Common
movement, details, Add, maintenance, and Help actions remain visible in screen
shortcut lines. Harmless queue actions no longer prompt; bulk downloading,
maintenance apply, restore, catalogue rebuild, and rmpc setup remain confirmed.
Durable jobs remain an internal backend detail and completed entries are hidden
from the active track queue. The CLI remains available for automation,
diagnostics, and internal job recovery. Existing local FLAC and M4A files are first-class library
tracks; acquisition remains MP3-focused. The product and primary executable are
`999`; the internal package, distribution identifier, and XDG data namespace
remain compatible with existing installations.

Live API acquisition was tested successfully.

The project has reached the point where the backend should be frozen before major redesign.

---

# Important Architecture Rule

DO NOT rewrite the backend during v2 redesign.

The backend already works.

The future TUI must be a presentation layer only.

The architecture should remain:


Textual TUI
|
|
Application services
|
|
Backend modules
|
|
API / Files / MP3 / rmpc


The UI should call existing systems.

The UI should NOT:
- edit ID3 tags directly
- handle downloads itself
- contain matching logic
- contain API logic

---

# Current Repository State

GitHub repository exists.

Current branch:

`v2-redesign`

Important files:


PROJECT_CONTEXT.md

docs/
├── V2_DESIGN.md
├── DECISIONS.md
└── this file


The project is in incremental v2 implementation. The backend remains stable.
High-impact TUI mutations are explicit and cancel-first; harmless queue actions
are immediate. Library uses shared services
for maintenance and restore; Settings remains read-only.
Library lyric health is independent of catalogue identity: format-appropriate
embedded lyrics plus a parsed timestamped sidecar can be fully covered even
when catalogue matching is unknown. Catalogue uncertainty remains visible but
does not itself create lyric attention.

---

# v2 Vision

The goal is to transform the project from:

"lyrics downloader/tagger"

into:

"A polished Juice WRLD music hub for Linux"

The application should feel like a real Linux application.

Inspired by:

- rmpc
- superfile
- modern terminal applications

---

# TUI Technology

Preferred framework:

## Textual

Reasons:

- modern Python ecosystem
- proper widgets
- colors
- keyboard navigation
- layouts
- dialogs
- responsive terminal UI
- feels like a real application

The goal is NOT a menu-driven CLI.

The goal is a proper TUI.

---

# UX Philosophy

The user should not need to understand technical internals.

Avoid exposing:

- SYLT
- USLT
- job UUIDs
- API paths
- complicated flags

Prefer:

- Synced Lyrics
- Plain Lyrics
- Downloads
- Queue
- Library
- Songs

The application should feel approachable.

---

# Proposed Screens

## 1. Dashboard

Purpose:

The home screen.

Shows:

- library size
- lyric coverage
- rmpc status
- download status
- quick actions


Example:


999 Music Hub

Library
39 Tracks

Lyrics
19 Synced
20 Plain
0 Missing

Downloads
1 Active

[Browse]
[Sync]
[Queue]
[Settings]


---

## 2. Browse/Search

Purpose:

Discover songs.

Features:

- search bar
- live filtering
- eras:
  - GBGR
  - WOD
  - DRFL
  - JW3
  - POST

Categories:

- Released
- Unreleased
- Sessions

Results show:


Rental (v1)

Era:
DRFL

Lyrics:
Synced

Download:
Available


The current Browse implementation supports result selection, details, lyrics
previews, canonical filters, pagination, and immediate single or marked Add to
queue actions. Adding never starts a download.

---

## 3. Library

Purpose:

Manage local music.

Shows:

- songs
- lyric status
- sync status
- missing metadata

Actions:

- refresh and verify without writes
- preview and confirm lyric maintenance
- open details and refresh one selected song
- browse and restore valid backups
- verify or explicitly configure rmpc

---

## 4. Download Queue

Purpose:

Replace confusing job management.

Instead of:


job-id:
2fc704cce61b4774868...


Use:


Downloads

Rental
Downloading 65%
Lemon Glow
Complete

The Downloads implementation is a flat track queue. It shows queue totals,
individual songs, structured failures, and retry eligibility; internal jobs are
hidden except for optional troubleshooting references. Browse can add
single or marked songs without starting downloads. Downloads can run the selected
song or eligible queue sequentially, retry failures, and perform record-only
cleanup. Active-download cancellation remains unavailable.

---

## 5. Song Details

Shows:

- title
- era
- category
- producers
- lyrics status
- lyrics preview

Actions:

- download
- add lyrics
- view metadata

---

## 6. Settings

Controls:

- music directory
- API settings
- rmpc settings
- backup settings

---

# rmpc Important Information

Current situation:

rmpc only supports external LRC files.

It does NOT read embedded lyrics.

Current application architecture keeps each same-basename LRC beside its MP3, FLAC, or M4A audio
file. The finalized audio path is authoritative; the legacy centralized
`lyrics_dir` configuration is accepted only for compatibility and does not
direct new output. Existing centralized files require a separate explicit
migration and are never moved automatically by `999`.

Therefore:

## Synced lyrics

Do:

1. Embed SYLT into MP3, standard Vorbis `LYRICS` into FLAC, or standard MP4 `©lyr` into M4A
2. Generate LRC
3. Put the same-basename LRC beside the audio file
4. rmpc displays lyrics

## Plain lyrics

Do:

1. Embed USLT into MP3, standard Vorbis `LYRICS` into FLAC, or standard MP4 `©lyr` into M4A

Do NOT:

- invent timestamps
- generate fake LRC

Result:

Android players can read embedded lyrics.

rmpc cannot display them as timed lyrics.

FLAC and M4A have no interoperable embedded equivalent to ID3 SYLT. The
application does not invent one: synchronized timing remains authoritative in
the adjacent `.lrc`, and audio is never converted.

This is accepted as a player limitation.

---

# Command Direction

The normal product entry point is simply:

```bash
999
```

Advanced compatibility commands remain available under `999 acquire`.
`juice-lyrics` is an executable alias to the same CLI implementation.

---

# Product Identity

The naming decision for beta is:

- product: `999`
- primary command: `999`
- legacy command: `juice-lyrics`
- Python package: `juice_lyrics`
- distribution: `juice-wrld-lyrics`
- XDG storage namespace: `juice-lyrics`

These compatibility names avoid breaking imports, installed-package upgrades,
or existing config, state, queue, cache, and backup data.

---

# Development Order

Do not immediately code.

Recommended order:

## Phase 1
Design

- branding
- naming
- screens
- user flows
- terminology


## Phase 2
Command compatibility

- primary `999` command
- legacy command alias
- preserve old data and internal package paths


## Phase 3
CLI improvements

Add:

- simpler commands
- friendly queue system
- better output


## Phase 4
Textual TUI

Build:

- dashboard
- browser
- library
- queue
- settings


## Phase 5

Release v2.

---

# Development Rules

Always:

- preserve backend
- keep tests passing
- make reversible changes
- document decisions

Never:

- rewrite working systems
- mix UI and business logic
- remove features without discussion

---

# User Preferences

The user wants:

- a real TUI, not a fake CLI menu
- a polished Arch Linux style application
- something that fits a rice setup
- keyboard-driven workflow
- modern terminal aesthetics

The user is not a programmer.

Instructions should be clear and guided.

The goal is to create something that feels like a finished Linux application, not just a script.
