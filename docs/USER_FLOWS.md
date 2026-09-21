# 999 User Flow Specification

## Purpose

This document defines the main user journeys inside 999.

The goal is to make complex backend features feel simple and natural.

The user should think in terms of:

- finding music
- managing a library
- downloading songs
- viewing lyrics
- keeping everything organized

The user should not need to understand:

- API requests
- acquisition jobs
- ID3 tags
- metadata matching
- file processing

---

# Core User Experience

The main loop of 999:


Discover
↓
Inspect
↓
Acquire
↓
Organize
↓
Listen
↓
Maintain


---

# Flow 1: First Launch

## Goal

A new user opens 999 for the first time.

The application must open safely even when configuration or the default library
is missing.

---

## Experience

User runs:


999


The Dashboard opens without downloading, modifying media, creating a
centralized lyrics folder, or rewriting rmpc. Missing paths are shown in plain
language. Settings exposes the configured locations; `999 config init` is the
optional CLI path for writing starter configuration, and rmpc setup remains an
explicit action.


---

# Flow 2: Daily Opening

## Goal

User opens 999 normally.

Command:


999


---

Expected:

No long startup.

Show dashboard immediately.

Example:


999

Library
542 tracks

Lyrics
510 synced
32 missing

Downloads
1 active

rmpc
Connected ✓


Available actions:


Browse
Library
Downloads
Sync


---

# Flow 3: Finding a Song

## Goal

User wants to find a Juice WRLD song.

---

User:


Press /


Search opens.

Input:


rental


Results appear:


Rental (v1)

DRFL

Synced Lyrics
Download Available

Rental (v2)

DRFL

No Lyrics
Download Available


---

User actions:


Enter


opens details.


d


downloads.


l


opens lyrics.

---

# Flow 4: Downloading a Song

## Goal

Downloading should feel instant and simple.

Current:


search
add
copy UUID
run job


Problem:

Too technical.

---

v2 primary user-facing model:

Browse → press `a` to Add → open Downloads → press `A` to Download queue

Adding a song creates durable internal acquisition state but does not begin a
download. The Downloads screen shows individual tracks, not jobs or UUIDs.
Completed tracks are hidden from the active queue; failed tracks remain visible
for future Retry or Remove actions.

Marking is optional. Space toggles the highlighted song, `M` toggles downloadable songs on the
visible API page, and `u` clears all marks. Marks may span pages of the same
logical search, but a title, Category, or Era change clears them. `a` immediately
adds the marked set, or the highlighted song when nothing is marked. Adding
never starts a download and the application
does not bulk-fetch an unbounded catalogue merely to fill the queue.

Download queue is the primary Downloads action. Download selected, Retry,
Remove, Clear queue, and Clear completed history remain available as secondary
actions. Active-download cancellation remains future work.

v2:

User selects:


Rental (v1)


Presses:


d


---

Application:


Download Rental (v1)?

Destination:

~/Music/Juice WRLD/Unreleased

[Download] Confirm
[Esc] Cancel


---

After confirming:


Downloads

Rental (v1)

Downloading...

████████░░ 80%

Lyrics:
Synced

After completion:

✓ Added to library
✓ Lyrics embedded
✓ Sidecar lyrics ready

The confirmation defaults to Cancel and explains that the operation may write
the media file, embed lyrics, create an LRC file, update library state, and
notify rmpc. Failed downloads remain in the queue with a readable failure;
completed downloads leave the active queue but remain counted and durable.
When synchronized lyrics exist, the external LRC is written beside the finalized
audio with the same basename. Audio and external lyrics therefore travel
together when the music folder is synchronized.


---

# Flow 5: Viewing Song Details

## Goal

Users can understand a track before downloading.

---

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

Local:
Not downloaded


Actions:


d Download
l Lyrics
esc Back


---

# Flow 6: Managing Local Library

## Goal

Users can inspect and safely maintain their own collection.

---

Library view:


My Library

Rental.mp3
Synced Lyrics ✓

Robbery.mp3
Plain Lyrics

Unknown Track
Missing Lyrics


---

Actions:


s Sync Library

a Issues

g Missing Library

d Duplicates

e Metadata repair

r Refresh

m Maintain lyrics

v Verify

b Backups

enter Details; l refresh selected lyrics

c Match manually; u unlock manual match


---

# Flow 7: Syncing Library

## Goal

Bring 999's view of the current library up to date without understanding scan,
backfill, verification, or state internals.

---

User:


Press s


---

Progress:


Syncing library...


---

Summary:


Library synced

181 tracks
4 new
1 changed
2 removed
37 newly matched
15 need attention


---

Sync runs in the background without confirmation. It avoids expensive work for
unchanged files, identifies only confident Unknowns, retires removed paths in
state, and refreshes local health. It never edits audio, embedded lyrics,
sidecars, backups, downloads, or rmpc configuration. Offline or ambiguous
catalogue results remain Unknown without making the local Library unusable.

To change lyrics, the separate `m` action first presents a non-mutating
maintenance preview and uses cancel-first confirmation before applying changes.

When automatic identity remains Unknown or is wrong, `c` opens a catalogue
chooser. The user may refine the query with `/`, choose with arrows, and save
with Enter. That explicit choice becomes a file-bound manual lock; normal Sync
and rebuild preserve it. `u` clears the identity lock without touching lyrics
and leaves automatic reconsideration for a later Sync.

`a` opens Issues from the current snapshot without another scan or catalogue
request. One row per track combines the reasons that still require attention.
Arrows select a row; its detail explains the problem; `c`, `l`, `v`, and `s`
reuse manual match, lyric preview, verification, and Sync.

`d` opens a read-only duplicate review from that same snapshot. Exact groups
share a saved whole-file hash; probable groups show the catalogue, metadata,
duration, and version evidence that connected them. Distinct live, remix,
session, extended, TV mix, and numbered versions stay separate. No files are
deleted, merged, moved, retagged, or replaced.

`e` reads the selected track's supported tags and confirmed catalogue record.
The preview shows before/after values and separates confidently repairable
missing fields from existing differences requiring review. Nothing is selected
by default. Space/Enter toggles a field and `a` opens a cancel-first summary of
the exact changes. Confirmed work runs in the background through the shared
backup, temporary-copy verification, atomic replacement, rollback, and state
conflict service. Unknown identities are not guessed.


---

# Flow 8: Managing Downloads

## Goal

Replace job management with a friendly queue.

---

Downloads screen:


Queue

✓ Rental

Complete

↓ Lemon Glow

Downloading 52%

! Track

Failed


---

Current actions:

`A` Download queue

`d` Download selected queued song

`t` Try selected failed song again

`?` Secondary queue management and help

Completed history and cleanup are intentionally not part of the primary
journey. Active-download cancellation remains planned.


---

# Flow 9: Lyrics Viewing

## Goal

Allow users to inspect lyrics.

---

For synced lyrics:

Show timestamps.

Example:


Rental

[00:01]
Lyrics line

[00:05]
Lyrics line


---

For plain lyrics:

Show text only.

Never invent timestamps.

---

# Flow 10: Error Handling

## Goal

Errors should explain what happened.

Avoid:


HTTPError 404


Prefer:


Unable to download.

The file is no longer available on the server.

[Retry]
[Back]


---

# Important UX Rules

## Never expose unnecessary technical details

Avoid showing:

- UUIDs
- API paths
- stack traces
- ID3 frame names

---

## Always show current state

Users should know:

- what is happening
- what finished
- what failed
- what they can do next

---

## Avoid unnecessary confirmations

Do not ask:

"Are you sure?"

for harmless actions.

Ask only before:

- deleting files
- changing configuration
- destructive actions

---

# Forward flows

Sync Library, Issues, Missing Library, duplicate review, and manual catalogue matching form the normal Library
workflow. The ordered remaining roadmap lives in `PROJECT_STATE.md`;
speculative screen lists are intentionally not duplicated here.
