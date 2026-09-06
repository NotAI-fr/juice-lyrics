# Project Decisions

This document records important architectural and product decisions.

The purpose is to prevent future redesigns from accidentally removing important behaviour.

---

# Lyrics Architecture

## Embedded lyrics remain supported

The application should preserve lyrics inside MP3, FLAC, and M4A files when possible.

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

- FLAC Vorbis `LYRICS`:
  - Standard plain-text embedded lyrics.
  - Used for plain lyrics and as a plain-text representation when synchronized
    source lyrics are available.
  - FLAC has no sane interoperable equivalent to ID3 SYLT. Timing is not
    invented or stored in a proprietary comment; the adjacent `.lrc` is authoritative.

- M4A/MP4 `©lyr`:
  - Standard plain-text embedded lyrics.
  - Used for plain lyrics and as a plain-text representation when synchronized
    source lyrics are available.
  - M4A has no interoperable equivalent to ID3 SYLT. Timing remains in the
    adjacent `.lrc`, not in a proprietary MP4 atom.

---

# LRC Files and rmpc

rmpc does not read embedded ID3 lyrics.

rmpc currently relies on external `.lrc` lyric files.

Audio and external synchronized lyrics stay together. Every LRC destination is
derived from the finalized audio path (`song.mp3`, `song.flac`, or `song.m4a` -> `song.lrc`) rather than a
global directory, title metadata, historical state, or rmpc configuration.
Read-only operations and plans create nothing. LRC writes generate complete
content first and atomically replace the adjacent sidecar where practical.

The old `lyrics_dir` setting remains accepted for configuration compatibility,
but is deprecated and does not direct current output. Existing centralized LRC
files are not moved automatically; migration remains a separate explicit task.

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

## Downloads are a track queue

Persistent acquisition jobs remain the durable backend mechanism for
resumability, validation, recovery, and CLI compatibility. They are not the
normal user-facing model. Frontends present one flat download queue containing
individual songs and hide job UUIDs from ordinary workflows.

Completed entries remain in durable storage but do not clutter the active
queue. Failed entries remain visible and actionable until a future retry or
remove action resolves them. Internal references may appear only in an advanced
troubleshooting detail.

Download selected, sequential Download all, Retry, Remove, Clear queue, and
Clear completed history each use an explicit cancel-first workflow. Active
download cancellation remains planned.

Browse selection is an in-memory set keyed by stable catalogue song ID. Marks
may span pages only within one logical search and are cleared when the search or
server-side filters change. Batch Add revalidates queue and destination
duplicates immediately before one atomic persistent write; it never starts a
download. Durable acquisition jobs remain hidden behind this song-oriented
operation.

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

---

# Product Identity and Compatibility

- Product name: `999`
- Primary executable: `999`
- Legacy compatibility executable: `juice-lyrics`
- Python package: `juice_lyrics`
- Distribution name: `juice-wrld-lyrics`
- XDG storage namespace: `juice-lyrics`

Both executable names call the same CLI implementation. Existing configuration,
cache, state, queue records, and backups are not renamed or duplicated. Normal
startup never rewrites rmpc configuration; only explicit `999 rmpc setup` may
do that.
