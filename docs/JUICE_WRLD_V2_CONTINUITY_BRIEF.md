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

The current name no longer fully represents the project scope.

---

# Current Backend Status

The backend is considered stable.

Milestone reached:

## Current verified checkpoint

The current development branch is `v2-redesign` in
`/home/nobloat/Downloads/juice-lyrics-codex`. The complete automated suite has
220 passing tests.

Completed and integrated:

Verified systems:

- API client
- search
- metadata lookup
- track matching
- lyric parsing
- ID3 SYLT embedding
- ID3 USLT embedding
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
stages, retry eligibility, and an explicit Browse Add to queue flow that never
starts a download, a read-only Library screen with local
track browsing, filters, details, and explicit sync previews, and a read-only
Settings screen with effective configuration, paths, provenance, and rmpc state.

All five primary TUI sections are functional. Browse may add one explicitly
confirmed song to the queue; Downloads execution, retry, remove, clear, and
cancel actions, configuration editing, and sync execution are not implemented.
Durable jobs remain an internal backend detail and completed entries are hidden
from the active track queue. The legacy CLI remains the way to run downloads,
delete jobs, and sync. Native FLAC support remains planned. The planned
product/executable name remains `999`; package, distribution, and data paths
have not been renamed.

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


The project is in incremental v2 implementation. The backend remains stable and
the TUI is intentionally read-only.

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
previews, canonical filters, and pagination. Download actions are not yet
implemented.

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

- sync
- verify
- open details

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

The current Downloads implementation is a read-only flat track queue. It shows
queue totals, individual songs, structured failures, and retry eligibility;
internal jobs are hidden except for optional troubleshooting references. Browse
can add one explicitly confirmed song without starting it. Download execution,
retry, cancel, remove, clear, and other queue mutations are not yet implemented.

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

Therefore:

## Synced lyrics

Do:

1. Embed SYLT into MP3
2. Generate LRC
3. Put LRC into lyrics directory
4. rmpc displays lyrics

## Plain lyrics

Do:

1. Embed USLT into MP3

Do NOT:

- invent timestamps
- generate fake LRC

Result:

Android players can read embedded lyrics.

rmpc cannot display them.

This is accepted as a player limitation.

---

# Future CLI Direction

The CLI should become simpler.

Current:


juice-lyrics acquire search Rental

juice-lyrics acquire add Rental --index 1

juice-lyrics acquire run UUID


Future:


999 search Rental

999 get Rental


The old commands can remain as compatibility commands.

---

# Possible Rename

The application probably needs a new name.

Current favourite ideas:

## 999

Pros:
- Juice WRLD connection
- memorable
- short command
- fits terminal culture

Possible command:


999


or:


999 search Rental


Other possibilities:

- Abyss
- JuiceBox

No final decision yet.

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
Migration

- new package name
- new command
- compatibility layer
- preserve old data


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
