# Development Guide

## Baseline

The 1.4.0 release is the known-good functional baseline.

Run:

```bash
pytest -q
```

The baseline test suite includes core parsing and rmpc configuration/LRC checks.

## Before changing architecture

Read:

1. `PROJECT_CONTEXT.md`
2. `docs/ROADMAP.md`
3. `docs/ARCHITECTURE.md`

Then inspect the current implementation and tests.

When working on acquisition, inspect the actual implementation before deciding which roadmap items are complete. Documentation records project intent and history; the current code and tests determine the actual implementation state.

## Change strategy

Prefer incremental, reviewable changes.

For large work:

1. refactor one responsibility
2. run tests
3. commit
4. implement the next responsibility
5. run tests again

Do not rewrite working behavior without a clear reason.

## Testing expectations

Do not make unit tests depend on the live Juice WRLD API.

Use fixed/mock API responses for deterministic tests.

New components should receive focused tests before being integrated into the main sync workflow.

## Packaging

The project uses `pyproject.toml` and exposes the `juice-lyrics` console script.

Keep the runtime dependency set small.

### Experimental Textual interface

From the repository's editable installation, launch the TUI with:

```bash
.venv/bin/juice-lyrics tui
```

Use `command -v juice-lyrics` before manual regression testing. A separately
installed pipx copy is a frozen package snapshot and does not follow this working
tree; reinstall it deliberately after a checkpoint or use the explicit `.venv`
command above.

The experimental shell provides functional Dashboard, Browse, Library,
Downloads, and Settings screens. Its primary journey is **Browse → Add →
Downloads → Download queue**. Browse supports both direct single-song Add and
optional batch selection; Downloads makes `A` Download queue primary and keeps
individual download, Retry, and cleanup actions in Help. Press `/` to focus catalogue search and Enter to
submit. Category and Era are keyboard-usable selectors populated from API
metadata; choose All for no filter. Filter-only searches are supported. Results
use the API's 50-song pages and show a permanently visible page, range, and
total bar. Use `n` for the next API page and `p` for the previous one. Arrows or
`j`/`k` move one result, PageDown/PageUp move through the loaded page, and
Home/End select its first/last result. The list scrolls to keep that selection
visible. Enter loads full details and a lyric preview, while `r` refreshes the
current API page. Space marks or unmarks the highlighted result, `M` toggles all
downloadable songs on the current page, and `u` clears the marks. Marks may span
pages of the same search; changing the title, Category, or Era clears them.
Press `a` to review and add the marked songs, or the highlighted song when none
are marked. The cancel-first dialog reports eligible and skipped songs and
states that adding does not start a download. Global keys remain `1`–`5` for
sections, `?` for help, and `q` to quit. Browse does not run downloads, sync
lyrics, edit settings, or modify the local library.
It uses Textual's ANSI-color mode and ANSI palette names rather than a bundled
theme. Exact terminal-background transparency can still vary with Textual's
alternate-screen rendering and the terminal emulator.

In Downloads, press `A` to download the eligible waiting queue sequentially.
Use arrows or `j`/`k` to select an individual queued song,
Home/End for the first or last song, and PageUp/PageDown for longer queues.
Enter opens track details and Escape returns to the queue. Press `r` to refresh.
Completed backend records are counted but hidden from the active queue; failed
songs remain visible. Press `d` to review a cancel-first confirmation for the
selected queued song. Confirming runs the existing download, validation, lyric,
LRC, state, backup, and rmpc pipeline; no download starts before confirmation.
Press `t` on a failed song for a cancel-first Retry confirmation. A verified
finalized file may reuse the existing media safely; otherwise the downloader
resume/redownload path is used. Active-download cancellation remains unavailable.
Use `x` to remove a waiting/failed song, `c` to clear waiting and failed songs,
and `H` to clear completed history. These record-only actions never delete
downloaded music or lyrics; active downloads cannot be cancelled yet.
Failed and active entries are skipped and remain available for their explicit
actions. The one-line footer advertises only the primary action and context;
`?` keeps Remove, Clear, history cleanup, Refresh, and Retry discoverable
without making the normal workflow look like queue administration.

In Library, arrows or `j`/`k` select local MP3 tracks, Home/End select the first
or last track, and PageUp/PageDown move through longer lists. Press `/` for a
local title/filename search and use the Status selector for Matched, Unmatched,
Synced lyrics, Plain lyrics, No lyrics, or Needs attention. These filters operate
on the loaded snapshot and do not contact the catalogue API or rescan files.
Press Enter for track details in narrow terminals, Escape to return, and `r` to
refresh the read-only snapshot. Press `s` explicitly to generate an API-backed
sync plan. It is a preview only: no audio, state, backup, LRC, configuration, or
rmpc changes are made. The existing API cache may be updated by that explicit
preview. Actual library sync remains CLI-only via `juice-lyrics sync`. The
scanner is currently MP3-focused; native FLAC support remains planned.

In Settings, the Music folder, Download folder, sidecar lyric behavior, and rmpc status are
shown before the Advanced configuration, provenance, cache, and state details.
Arrows or `j`/`k` inspect values; Home/End and PageUp/PageDown navigate longer content.
The view reports the active config file, reliable default/config/runtime source
labels, that external lyrics live beside each song, path existence, and whether
rmpc indexes the music tree containing those sidecars. Press `r`
to refresh. The screen is strictly read-only: configuration changes and setup
remain CLI-only, no missing XDG paths are created, the scanner remains MP3-only,
and native FLAC support remains planned.

External synchronized LRC files use the finalized audio path: `song.mp3` maps to
`song.lrc` in the same directory. Content is generated before an atomic replace,
and read-only inspection or planning creates nothing. The legacy `lyrics_dir`
setting remains parseable but cannot redirect current output; neither historical
state nor rmpc configuration is an output-path authority. Existing centralized
files are not migrated by the application.

## Source of truth and Git workflow

The latest transferred project checkpoint/archive is the source of truth for ongoing development. The existing GitHub repository is not authoritative and should not be used as the development baseline.

When version control is introduced, create a fresh repository from a known-good checkpoint and make logical milestones so changes can be inspected or reverted independently. The user should be given copy/paste instructions rather than being expected to understand Git internals.

## Checkpoint workflow

Development checkpoints are distributed as source ZIPs. When applying one to a local Git checkout, keep `.git/` untouched, run the test suite, then commit the result as a single logical milestone.
