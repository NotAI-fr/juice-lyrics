# Development Guide

## Baseline

The `main` branch and `v1.4.0-backend-complete` tag are the stable v1.4
baseline. Development of the redesigned product remains on `v2-redesign`; its
current unreleased beta candidate version is `2.0.0b1`.

Run:

```bash
pytest -q
```

The baseline test suite includes core parsing and rmpc configuration/LRC checks.

## Before changing architecture

Read:

1. `AGENTS.md`
2. `docs/PROJECT_STATE.md`
3. the relevant architecture, decision, or user document

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

The project uses `pyproject.toml` and exposes `999` as its primary console
script. `juice-lyrics` is a legacy compatibility alias; both entry points call
`juice_lyrics.cli:main`.

The distribution remains `juice-wrld-lyrics`, the import package remains
`juice_lyrics`, and XDG storage remains under `juice-lyrics` for compatibility.

Keep the runtime dependency set small.

### Experimental Textual interface

From the repository's editable installation, launch the TUI with:

```bash
.venv/bin/999
```

Use `command -v 999` before manual regression testing. A separately
installed pipx copy is a frozen package snapshot and does not follow this working
tree; reinstall it deliberately after a checkpoint or use the explicit `.venv`
command above.

For a deterministic pipx installation that does not depend on the checkout
after installation:

```bash
pipx install --force "git+https://github.com/NotAI-fr/juice-lyrics.git@v2-redesign"
hash -r
command -v 999
999 --version
999 doctor
```

Use `pip install -e .` inside `.venv` for development. A local wheel can be
tested or installed with `pipx install --force /absolute/path/to/wheel.whl`.
Build release artifacts with `python -m build`; both the wheel and source
distribution must be clean-installed outside the repository before release.

The terminal interface provides functional Dashboard, Browse, Library,
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
Press `a` to add the marked songs, or the highlighted song when none are
marked. Addition is immediate, reports eligible/skipped songs, and does not
start a download. Global keys remain `1`–`5` for
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
songs remain visible. Press `d` to start the explicitly selected queued song;
the whole-queue `A` action remains cancel-first. The runner uses the existing
download, validation, lyric, LRC, state, backup, and rmpc pipeline. Press `t`
on a failed song to retry it immediately. A verified
finalized file may reuse the existing media safely; otherwise the downloader
resume/redownload path is used. Active-download cancellation remains unavailable.
Use `x` to remove a waiting/failed song, `c` to clear waiting and failed songs,
and `H` to clear completed history. These record-only actions never delete
downloaded music or lyrics; active downloads cannot be cancelled yet.
Failed and active entries are skipped and remain available for their explicit
actions. The one-line footer advertises only the primary action and context;
`?` keeps Remove, Clear, history cleanup, Refresh, and Retry discoverable
without making the normal workflow look like queue administration.

In Library, arrows or `j`/`k` select local MP3, FLAC, and M4A tracks, Home/End select the first
or last track, and PageUp/PageDown move through longer lists. Press `/` for a
local title/filename search and use the Status selector for Matched, Unmatched,
Synced lyrics, Plain lyrics, No lyrics, or Needs attention. These filters operate
on the loaded snapshot and do not contact the catalogue API or rescan files.
Press Enter for track details in narrow terminals, Escape to return, and `r` to
refresh the read-only snapshot. Press `s` explicitly to generate an API-backed
sync plan. It is a preview only: no audio, state, backup, LRC, configuration, or
rmpc changes are made. The existing API cache may be updated by that explicit
preview. Actual library sync remains CLI-only via `999 sync`. The
scanner recursively supports MP3, FLAC, and M4A. FLAC and M4A matching reads
native title, artist, album, and duration metadata and conservatively leaves
tracks with missing title or artist metadata unmatched.

In Settings, the Music folder, Download folder, sidecar lyric behavior, and rmpc status are
shown before the Advanced configuration, provenance, cache, and state details.
Arrows or `j`/`k` inspect values; Home/End and PageUp/PageDown navigate longer content.
The view reports the active config file, reliable default/config/runtime source
labels, that external lyrics live beside each song, path existence, and whether
rmpc indexes the music tree containing those sidecars. Press `r`
to refresh. The screen is strictly read-only: configuration changes and setup
remain CLI-only, and no missing XDG paths are created.

External synchronized LRC files use the finalized audio path: `song.mp3`,
`song.flac`, and `song.m4a` map to `song.lrc` in the same directory. Content is generated before an atomic replace,
and read-only inspection or planning creates nothing. The legacy `lyrics_dir`
setting remains parseable but cannot redirect current output; neither historical
state nor rmpc configuration is an output-path authority. Existing centralized
files are not migrated by the application.

FLAC and M4A files are never converted. Mutagen writes standard plain-text
Vorbis `LYRICS` for FLAC and MP4 `©lyr` for M4A while preserving unrelated
metadata and the audio stream. Synchronized timing is kept in the adjacent LRC
because neither container provides an interoperable SYLT equivalent. Backups
and restore support MP3, FLAC, and M4A.

## Source of truth and Git workflow

The `v2-redesign` branch in this repository is the active development source
of truth. Keep milestones inspectable, run the documented verification, and
push completed work to `origin/v2-redesign`. Do not merge into `main`, tag, or
publish a distribution as part of an ordinary development milestone.
