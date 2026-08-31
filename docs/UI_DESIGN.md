# 999 TUI Design Specification

## Purpose

This document defines the user interface and interaction design for 999.

999 is a Juice WRLD music management hub designed for Linux terminals.

It combines:

- catalogue browsing
- local music management
- lyric management
- acquisition/downloads
- rmpc integration

The goal is to feel like a native Linux terminal application similar to tools like rmpc and superfile.

---

# Design Philosophy

## Principles

### Keyboard First

The entire application should be usable without a mouse.

Common actions should be reachable through:

- arrows
- enter
- escape
- single-key shortcuts

---

### Terminal Native

999 should respect the user's terminal environment.

The application should:

- use terminal colours
- avoid forcing a custom theme
- work with existing rice setups

Examples:

- Catppuccin
- Tokyo Night
- Gruvbox
- Dracula
- Nord
- custom ANSI themes

The application should feel like it belongs inside the user's terminal.

---

### Simple Frontend, Powerful Backend

The user should not need to understand:

- API paths
- UUID job IDs
- ID3 frame names
- internal processing steps

The interface should translate technical complexity into simple actions.

Use:

"Synced Lyrics"

instead of:

"SYLT"

Use:

"Downloads"

instead of:

"Acquisition Jobs"

---

# Global Layout

The application uses a persistent layout.

Example:


┌──────────────────────────────────────┐
│ 999 — Juice WRLD Music Hub │
├──────────────────────────────────────┤
│ │
│ CONTENT │
│ │
│ │
├──────────────────────────────────────┤
│ ? Help / Search q Quit │
└──────────────────────────────────────┘


---

# Main Navigation

Primary sections:


[1] Dashboard
[2] Browse
[3] Library
[4] Downloads
[5] Settings


Navigation should be possible with:

- number keys
- shortcuts
- tab switching

---

# Dashboard

Purpose:

The first screen when opening 999.

Shows a quick overview.

Example:


┌──────────────────────────────────────┐
│ Dashboard │
├──────────────────────────────────────┤
│ │
│ Library │
│ │
│ 542 Tracks │
│ 510 With Lyrics │
│ 32 Missing │
│ │
│ Downloads │
│ 2 Active │
│ │
│ Player │
│ rmpc Connected ✓ │
│ │
├──────────────────────────────────────┤
│ Browse Library Sync Downloads │
└──────────────────────────────────────┘


Questions:

- Should dashboard open by default?
- Should recent songs/downloads appear?
- Should it show rmpc status?

---

# Browse Screen

Purpose:

Discover songs from the Juice WRLD catalogue.

Features:

- search
- filtering
- sorting
- song preview

Example:


Search:
[rental________________]

Results:

Rental (v1)
DRFL
Synced Lyrics
Download Available

Rental (v2)
DRFL
No Lyrics
Download Available

Preview:

Rental (v1)

Era:
Death Race For Love

Producer:
Seezyn

[d] Download
[enter] Details


---

# Song Details Screen

Purpose:

Show complete information.

Example:


Rental (v1)

Category:
Unreleased

Era:
DRFL

Length:
4:13

Producer:
Seezyn

Lyrics:
Synced

Actions:

d Download

l View Lyrics

esc Back


---

# Library Screen

Purpose:

Manage local files.

Example:


My Library

Rental.mp3

Lyrics:
Synced

rmpc:
Ready

Robbery.mp3

Lyrics:
Plain

rmpc:
Unavailable


Actions:


s Sync
v Verify
enter Details


---

# Downloads Screen

Purpose:

Replace technical job management.

The user should never need UUIDs.

The primary view is a flat queue of songs. Persistent acquisition jobs remain
an internal durability and execution detail; an internal reference may be shown
only under troubleshooting details. Completed records contribute to the summary
but are hidden from the active queue, while failed songs remain visible.

Browse uses `a` to open an explicit Add to queue confirmation. The dialog shows
the resolved destination and states that adding will not start a download.
Future queue actions are Download selected, Download all, Remove, Clear, Retry,
and Cancel.

Example:


Downloads

✓ Rental
Complete

↓ Lemon Glow
Downloading 54%

! Track
Failed

Retry


Actions:


r Retry
d Delete
enter Details


---

# Settings Screen

Purpose:

Manage configuration.

Example:


Settings

Music Directory

~/Music/Juice WRLD

Lyrics Directory

~/Music/lyrics

Player

rmpc detected ✓


---

# Keybindings

## Global


q Quit
esc Back
? Help
/ Search


## Lists


↑ ↓ Navigate
enter Select


## Browse


d Download
l Lyrics


## Library


s Sync
v Verify


## Downloads


r Retry
d Remove


---

# Future Screens

Possible later additions:

- lyrics viewer
- playlist manager
- statistics
- album/era explorer
- advanced metadata editor

These are not required for the first release.

---

# First Release Priority

The first usable TUI version should contain:

1. Dashboard
2. Browse/Search
3. Song Details
4. Download Queue
5. Library View

Settings and advanced tools can follow.
