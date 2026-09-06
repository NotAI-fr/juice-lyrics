# 999 Design Proposal

## Vision

The project has grown beyond the original `juice-lyrics` lyrics-tagging scope.

The project is becoming a complete Juice WRLD music management application for Linux:

- Discover music from the Juice WRLD API catalogue.
- Manage a local music library.
- Embed lyrics into MP3 files.
- Generate compatibility files for players like rmpc.
- Acquire and organize tracks.
- Provide a clean, beautiful terminal experience.

Version 2 should transform the project from a powerful developer tool into a polished application.

---

# New Identity

## Problem

The product is now named `999`; `juice-lyrics` remains a compatibility command.

The project now includes:

- Music discovery.
- Library management.
- Downloads.
- Metadata.
- Player integration.
- Terminal UI.

A new name should represent a complete Juice WRLD music hub rather than only lyrics.

---

# Possible Names

## 999

Concept:

Juice WRLD's iconic "999" philosophy.

Advantages:

- Instantly recognizable to fans.
- Short command.
- Easy to remember.
- Fits a Linux CLI aesthetic.

Possible command:


999


or:


999 search "Rental"
999 sync
999 get "Rental"


---

## Abyss

Concept:

Inspired by Juice WRLD themes and darker aesthetics.

Advantages:

- Professional sounding.
- Fits terminal applications.
- Unique identity.

Possible command:


abyss


---

## JuiceBox

Concept:

A friendly music library hub.

Advantages:

- Easy to understand.
- More approachable.

Possible command:


jbox


---

# Recommended Direction

999 is currently the strongest candidate.

Final naming decision should happen after exploring branding, logo ideas, and command usability.

---

# User Experience Goals

## Current Problem

The current application is powerful but technical.

Example:

Current workflow:


999 acquire search "Rental"

999 acquire add "Rental" --index 1

999 acquire run <long-job-id>


This works, but it feels like developer tooling.

---

## v2 Goal

The user should think:

"I want this song."

Not:

"I need to understand acquisition jobs."

---

# New CLI Philosophy

The CLI should support two levels:

## Simple commands

For normal users:


999 search "Rental"

999 get "Rental"

999 sync

999 status


---

## Advanced commands

For power users:


999 queue

999 doctor

999 restore

999 config


The powerful backend should remain available without forcing complexity on beginners.

---

# Proposed Command Structure

## Open Application


999


Launches the interactive TUI.

---

## Search Catalogue


999 search "Rental"


Shows:

- Song title.
- Era.
- Category.
- Lyrics availability.
- Download availability.

Example:


Rental (v1)

Era: DRFL
Lyrics: Synced
Download: Available

[d] Download
[i] Info
[l] Lyrics


---

## Download Music

Simple:


999 get "Rental"


Should:

1. Search catalogue.
2. Select best match.
3. Download.
4. Validate file.
5. Embed lyrics.
6. Generate a same-basename LRC beside the audio if possible.
7. Add to library.

---

## Library Sync


999 sync


Should:

- Scan music folder.
- Find new files.
- Match metadata.
- Embed lyrics.
- Update rmpc files.

---

## Library Status


999 status


Example:


Library

Tracks: 250

Lyrics:
Synced: 180
Plain: 50
Missing: 20

rmpc:
LRC files: 180


---

# TUI Vision

The main interface should be a terminal dashboard.

Goals:

- Fast.
- Keyboard driven.
- Beautiful.
- Linux friendly.

---

# Main Screens

## 1. Browse

Purpose:

Discover songs.

Features:

- Search.
- Filters.
- Era selection.
- Lyrics preview.
- Download button.

Example:


999 — Browse

Search: rental

Rental v1
DRFL
Synced Lyrics
Download Available

Rental v2
POST
No Lyrics


---

## 2. Library

Purpose:

Manage local music.

Shows:

- Track list.
- Lyrics status.
- Sync status.
- Missing metadata.

---

## 3. Downloads

Purpose:

Manage acquisition queue.

Shows:

- Active downloads.
- Completed downloads.
- Failed downloads.
- Retry options.

Avoid exposing raw UUID job IDs.

Use:


Download #1
Download #2


---

## 4. Song Details

Shows:

- Title.
- Era.
- Producers.
- Metadata.
- Lyrics preview.
- File information.

---

# Lyrics Design

The application must preserve the existing philosophy.

## Embedded lyrics

Primary source.

Used for:

- Android players.
- Portable files.
- Long-term storage.

Formats:

- SYLT for synced lyrics.
- USLT for plain lyrics.

---

## LRC

Compatibility layer.

Used for:

- rmpc.
- External lyric players.

Rules:

- Only generate from timestamped lyrics.
- Never invent timestamps.
- Keep each LRC beside its audio file with the same basename.
- Do not derive current output from the deprecated global `lyrics_dir` setting.

---

# Visual Style

The application should fit Linux terminal workflows.

Design goals:

- Minimal.
- Fast.
- Keyboard focused.
- Customizable.

Influences:

- rmpc.
- lazygit.
- terminal file managers.
- modern TUI applications.

---

# Technical Rules

The v2 interface must remain separate from the backend.

The TUI should not:

- Modify ID3 tags directly.
- Handle API requests directly.
- Manage downloads directly.

Instead:

UI
 |
 v
Backend services
 |
 v
Files/API/Players

---

# Development Order

## Phase 1

Design:

- Final name.
- Branding.
- CLI commands.
- TUI layout.

## Phase 2

Migration:

- New command.
- Backwards compatibility.
- Data migration.

## Phase 3

CLI improvements:

- Friendly commands.
- Better output.
- Simplified workflows.

## Phase 4

TUI:

- Browse.
- Library.
- Queue.
- Settings.

## Phase 5

Release:

- Version 2.0.
- Documentation.
- Packaging.

---

# Current Status

Backend is considered stable.

Before v2 implementation:

- 80 tests passing.
- Acquisition verified.
- Lyrics engine verified.
- rmpc integration verified.

The next major milestone is turning the stable engine into a polished user experience.
