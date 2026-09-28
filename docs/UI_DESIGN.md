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


The Dashboard opens by default and summarizes the current local snapshot and
download state without waiting for network work. It links users toward Browse,
Library Sync, and Downloads rather than becoming a second control panel.

---

# Browse Screen

Purpose:

Discover songs from the Juice WRLD catalogue.

The default path is intentionally direct: search, highlight a song, press `a`,
then open Downloads with `4`. Marking is optional. Empty selection boxes are
hidden until Space marks the first song; `M` page selection and `u` clearing
remain secondary actions in Help.

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

[a] Add to Downloads
[4] Open Downloads
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


Library

315 tracks · 15 follow-ups · 2 errors
Lyrics to improve 9 · Fully covered 287 · Catalogue unknown 6 · MP3 170 · FLAC 85 · M4A 60

Rental.flac
Catalogue match  ✓
Embedded lyrics  ✓
Synced LRC       ✓


Actions:


s Sync Library
f Search Lyrics
a Issues
g Missing Library
d Duplicates
e Metadata repair
r Refresh
m Maintain lyrics
v Verify
b Backups
p Player integration
c Match manually
u Unlock manual match
enter Details; l refresh selected lyrics


---

# Downloads Screen

Purpose:

Replace technical job management.

The user should never need UUIDs.

The primary view is a flat queue of songs. Persistent acquisition jobs remain
an internal durability and execution detail; an internal reference may be shown
only under troubleshooting details. Completed records contribute to the summary
but are hidden from the active queue, while failed songs remain visible.

Browse uses Space to mark stable song IDs, `M` to toggle downloadable songs on
the visible page, and `u` to clear marks. Marks may span pages of one logical
search; search or filter changes clear them. `a` immediately adds the marked
set, or the current song when nothing is marked. The status line reports the
result and reminds the user that adding does not start a download.

The persistent Browse shortcut line shows movement, details, marking, adding,
and Help. `?` opens a scrollable keyboard guide from any section, including all
secondary actions and the shared confirmation keys. Harmless actions execute
immediately; high-impact actions use a cancel-first dialog. In those dialogs,
`y` confirms immediately, `n`/`Esc` cancels, and initial `Enter` cancels.

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

`A` Download queue is the primary action. `d` downloads only the highlighted
song and `t` tries a failed song again. Remove, clear, history cleanup, and
refresh remain available through `?` rather than filling the persistent bar.


---

# Settings Screen

Purpose:

Inspect configuration, with everyday folders and rmpc status before advanced
cache, state, provenance, and diagnostic paths.

Example:


Settings

Music folder

~/Music/Juice WRLD

Download location

~/Music/Juice WRLD

External lyrics

Beside each song (.lrc)

Player

rmpc detected ✓


---

# Keybindings

The running app's `?` Help screen is the complete key guide and is derived
from the maintained TUI action inventory. The visible shortcut lines prioritize
movement, details, and the main action for each section. Core bindings:

| Section | Common keys |
| --- | --- |
| Global | `1`–`5` sections, `?` Help, `q` Quit, `Esc` back/close, `r` refresh |
| Browse | `↑`/`↓` move, `Enter` details, `/` search, `Space` mark, `a` add, `M` mark page, `u` clear marks |
| Library | `↑`/`↓` move, `Enter` details, `s` Sync Library, `f` Search Lyrics, `a` Issues, `g` Missing Library, `d` Duplicates, `e` metadata repair, `c` manual match; `u` unlock, `m`, `r`, `v`, `b`, `p` are secondary |
| Downloads | `↑`/`↓` move, `Enter` details, `d` selected download, `t` retry, `A` whole queue |
| Settings | `↑`/`↓` inspect, `PgUp`/`PgDn` scroll, `r` refresh |

`y` immediately accepts a high-impact confirmation. `n`/`Esc` cancels.
`Enter` chooses the focused action, which is Cancel initially. `Tab`,
`Shift+Tab`, and left/right move between actions.


---

# Current scope

Dashboard, Browse, Library, Downloads, Settings, song details, and global Help
are implemented. Forward product work is tracked in `PROJECT_STATE.md` rather
than as speculative screens here.
