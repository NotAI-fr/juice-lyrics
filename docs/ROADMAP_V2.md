# v2 Development Roadmap

This document defines the order of work for transforming juice-lyrics into a polished Juice WRLD music management application.

The existing backend is considered stable and should be preserved.

---

# Guiding Principles

## Do not rewrite working systems

The following are considered mature:

- Lyrics engine
- ID3 embedding
- Backup system
- API client
- Track matching
- Downloader
- Acquisition jobs
- rmpc integration

Future work should improve usability around these systems.

---

# Phase 0 — Planning (Complete)

Status: Complete

Goals:

- Preserve stable backend.
- Document architecture.
- Decide product direction.
- Prepare rename strategy.

Completed:

- GitHub repository created.
- Backend milestone saved.
- v2 design document created.
- Architecture decisions documented.

---

# Phase 1 — Cleanup and Preparation

Goal:

Make the codebase ready for a major frontend redesign.

Tasks:

- Remove unused legacy CLI code.
- Simplify CLI entrypoint.
- Improve internal interfaces.
- Review documentation.
- Add missing regression tests.

Important:

Do not change user-facing behaviour unless necessary.

---

# Phase 2 — Identity and Migration

Goal:

Introduce the new application identity.

Tasks:

- Choose final name.
- Update package metadata.
- Create new CLI command.
- Add migration from old configuration paths.
- Preserve juice-lyrics compatibility.

Example:

Old:


juice-lyrics sync


New:


999 sync


Both should work during transition.

---

# Phase 3 — CLI Experience

Goal:

Make common actions simple.

Current:


acquire search
acquire add
acquire run <uuid>


Future:


999 get "Rental"


Improvements:

- Friendly output.
- Remove unnecessary technical terms.
- Better error messages.
- Human-readable download queue.
- Better help screens.

---

# Phase 4 — Interactive TUI

Goal:

Create the main application interface.

Status: In progress. The responsive terminal-native shell and all five primary
sections are integrated as read-only screens. Mutating workflows remain CLI-only.

Screens:

## Browse

Features:

- Catalogue search.
- Filters.
- Song details.
- Lyrics preview.
- Download actions.

Status: Read-only functionality complete, including server-side pagination and
scrollable 50-result pages. Download actions remain planned.

---

## Library

Features:

- Local tracks.
- Lyrics status.
- Sync state.
- Metadata.

Status: Read-only functionality complete, including local search and status
filters, track details, and explicit non-mutating sync previews. Sync execution
remains planned.

---

## Downloads

Features:

- Active downloads.
- Progress.
- Completed items.
- Retry.

Status: Read-only queue view complete. Run, Retry, Delete, and Cancel actions
remain planned.

---

## Settings

Features:

- Music directory.
- rmpc settings.
- API settings.

Status: Read-only functionality complete, including effective configuration,
path existence, provenance where reliable, rmpc integration state, and current
capability limitations. Editing remains planned.

---

# Phase 5 — Advanced Features

Recommended implementation order after the current checkpoint:

1. Browse-to-download job creation
2. Downloads Run/Retry/Delete actions
3. Library sync actions
4. `999` command and naming migration
5. Native FLAC support
6. Beta polish, packaging, and release testing

Possible future improvements:

## Lyrics Improvements

- Better lyrics previews.
- Search within lyrics.
- More player integrations.

## Library Improvements

- Duplicate cleanup.
- Better sorting.
- Album/era organization.

## Acquisition Improvements

- Better batch workflows.
- Playlist-style downloads.
- Download history.

## TUI Improvements

- Themes.
- Custom keybindings.
- More customization.

---

# Features NOT Planned

Avoid feature creep.

The project should not become:

- A full music player replacement.
- A streaming service.
- A general-purpose downloader.
- A cloud music service.

The goal is:

"A beautiful Juice WRLD music management tool for Linux."

---

# Release Goals

## Version 2.0

Should include:

- New identity.
- Better CLI.
- Interactive TUI.
- Migration support.
- Stable backend.

---

# Success Criteria

The application succeeds when a user can:

1. Install it.
2. Open it.
3. Browse songs.
4. Download music.
5. Have lyrics embedded.
6. Play with rmpc.
7. Understand what is happening without reading documentation.

The technology should disappear behind the experience.
