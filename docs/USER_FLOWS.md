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

Current problem:

The old CLI requires understanding setup, configuration, directories, and integrations.

v2 goal:

The application should guide the user.

---

## Experience

User runs:


999


Application checks:

- configuration exists
- music directory exists
- rmpc availability
- existing library

---

Example:


Welcome to 999

First-time setup detected.

Music folder:
~/Music/Juice WRLD

rmpc:
Detected ✓

Existing tracks:
39

Would you like to continue?

[Enter] Setup
[Esc] Exit


---

After setup:


Setup complete.

Library:
39 tracks

Lyrics:
39 processed

Ready.

Press Enter to continue.


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
logical search, but a title, Category, or Era change clears them. `a` adds the
marked set, or the highlighted song when nothing is marked, through a
cancel-first confirmation. Adding never starts a download and the application
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
✓ rmpc lyrics ready

The confirmation defaults to Cancel and explains that the operation may write
the media file, embed lyrics, create an LRC file, update library state, and
notify rmpc. Failed downloads remain in the queue with a readable failure;
completed downloads leave the active queue but remain counted and durable.


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

Users can inspect their own collection.

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

v Verify Lyrics

enter Details


---

# Flow 7: Syncing Library

## Goal

Update new or changed files.

---

User:


Press s


---

Confirmation:


Sync library?

Found:

12 new files

Continue?

[Enter]


---

Progress:


Syncing...

Rental.mp3
Matching...

Lyrics found ✓

Embedding...

Complete


---

Summary:


Sync Complete

Updated:
12

Synced Lyrics:
8

Plain Lyrics:
4

Failed:
0


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

# Future User Flows

Possible later additions:

- playlists
- favourites
- statistics
- automatic library monitoring
- album/era exploration
- lyrics-only mode

These are not required for the first v2 release.
