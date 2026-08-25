# Project Decisions

This document records important architectural and product decisions.

The purpose is to prevent future redesigns from accidentally removing important behaviour.

---

# Lyrics Architecture

## Embedded lyrics are the primary source of truth

The application should always preserve lyrics inside the MP3 file when possible.

Reasons:

- Embedded lyrics travel with the file.
- Android music players commonly support embedded ID3 lyrics.
- Users may move files between devices.
- The MP3 should remain self-contained.

Supported embedded formats:

- ID3 SYLT:
  - Synchronized lyrics with timestamps.
  - Preferred when synced lyrics are available.

- ID3 USLT:
  - Plain unsynchronized lyrics.
  - Used when only normal text lyrics are available.

---

# LRC Files and rmpc

rmpc does not read embedded ID3 lyrics.

rmpc currently relies on external `.lrc` lyric files.

Therefore:

- SYLT lyrics should generate `.lrc` files.
- USLT-only lyrics should remain embedded but cannot produce valid `.lrc` files.

Reason:

An LRC file requires timestamped lines.

Example:


[00:12.00] First lyric line
[00:15.00] Second lyric line


Plain lyrics do not contain timing information.

The application must never invent timestamps to make LRC files.

---

# Lyrics Priority

The lyric pipeline should behave like this:

API synced lyrics
        |
        v
Embed SYLT
        |
        v
Generate LRC for rmpc


API plain lyrics only
        |
        v
Embed USLT
        |
        v
No LRC generated

---

# Player Choice

rmpc remains the preferred desktop player integration.

Reasons:

- Lightweight.
- Fast.
- Terminal UI fits the Linux workflow.
- Highly configurable.
- Works well with custom Linux setups.

The application should support rmpc without making it the only playback target.

---

# UX Principle

Technical details should not leak unnecessarily to users.

Avoid showing:

- SYLT
- USLT
- job UUIDs
- internal API terminology

Prefer:

- Synced Lyrics
- Plain Lyrics
- Downloads
- Queue
- Library

The backend can remain technical while the user interface becomes friendly.

---

# Backend Stability

The current modular backend should be preserved.

Major systems:

- API client
- lyrics engine
- acquisition system
- downloader
- library matching
- rmpc integration
- backup system

Future redesigns should build on these systems rather than replacing them.
