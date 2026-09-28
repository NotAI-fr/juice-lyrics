# 999

![999 dashboard with synthetic demonstration data](docs/assets/screenshots/dashboard-synthetic.png)

[![GitHub release](https://img.shields.io/github/v/release/NotAI-fr/juice-lyrics?include_prereleases&label=current%20beta)](https://github.com/NotAI-fr/juice-lyrics/releases/tag/v2.0.0b2)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

A keyboard-first Linux app for browsing, understanding, and maintaining a
local Juice WRLD music library.

## Quick Install

Requires Linux, Python 3.11 or newer, and
[`pipx`](https://pipx.pypa.io/) on your `PATH`.

### Recommended: 2.0.0b2

Install the current recommended beta directly from its immutable Git tag:

```bash
pipx install --force "git+https://github.com/NotAI-fr/juice-lyrics.git@v2.0.0b2"
```

You do not need to clone the repository. Check the install, then launch 999:

```bash
999 --version
999 doctor
999
```

### Previous stable fallback: 2.0.0b1

If `2.0.0b2` gives you trouble, switch to the previous known-good beta. The
published `v2.0.0b1` tag and release remain immutable:

```bash
pipx install --force "git+https://github.com/NotAI-fr/juice-lyrics.git@v2.0.0b1"
```

Use `pipx install --force` with either command to switch between versions.
Some pipx versions that use the `uv` backend do not replace an existing Git
tag install in place. If pipx reports that it cannot switch, run
`pipx uninstall juice-wrld-lyrics`, then install the other tag command.
See [Troubleshooting](#troubleshooting) or [Uninstall](#uninstall) for help.

## Why 999?

999 brings catalogue discovery, downloads, local-library health, lyrics,
matching, careful repairs, and diagnostics into one terminal interface. It is
designed to replace a pile of one-off file and tagging scripts—not your music
player.

## Features

### 🔎 Find and discover

**Search by Lyrics** — Remember a line but not the title? Open **Library →
Search Lyrics** and type part of the lyric. 999 searches embedded MP3, FLAC,
and M4A lyrics plus adjacent plain or timed `.lrc` files; timed matches can
show their real timestamp. Search is local, offline, and does not rescan media
as you type.

Lyrics Search is part of the current `2.0.0b2` beta. It is **not** included in
the previous `v2.0.0b1` fallback release.

**Browse and Catalogue Search** — Search and filter the Juice WRLD catalogue,
inspect recording details, and connect local files with the correct catalogue
recording. Local-library features remain useful if the catalogue service is
offline; catalogue-backed results naturally require it to be available.

**Missing Library** — Compare confirmed local catalogue identities with the
catalogue to see recordings that appear to be missing. Unknown local tracks
are kept separate, and a selected missing recording can be added to the normal
download queue without starting a download.

### 📚 Manage your library

**Local Library** — Scan and manage a local Juice WRLD collection from one
place. Library inspection, metadata, and lyric workflows support MP3, FLAC,
and M4A without converting the audio.

**Library Sync** — Detect new, changed, unchanged, and removed tracks, then
update 999's local view of the collection. Sync reuses what it already knows
about unchanged files and does not rewrite audio, embedded lyrics, sidecars,
backups, downloads, or rmpc configuration.

**Lyrics and LRC Management** — Inspect, verify, preview, and explicitly apply
supported lyric maintenance. 999 handles embedded plain and synchronized MP3
lyrics, plain FLAC and M4A lyrics, and adjacent timed `.lrc` files where
supported.

**Downloads and Queue** — Add one or several catalogue selections to a durable
queue, review them, then explicitly start one download or the eligible queue.
Failed items remain visible for retry, and adding an item never starts a
download. Acquisition and download post-processing are currently MP3-focused.

**Library Issues** — See catalogue identity, lyric, verification, metadata,
and state follow-ups together, with one combined entry per affected track.
Warnings and Unknown identities may simply need review; they do not
automatically mean the audio file is damaged.

**Manual Catalogue Matching** — When automatic matching is uncertain, choose
the correct catalogue recording yourself and lock that identity to the current
file. Normal Sync preserves a valid manual choice until you explicitly unlock
it or the audio is replaced.

**Duplicate Detection** — Review exact file copies and conservative probable
recording matches with the evidence and paths shown. Detection is read-only:
999 never automatically deletes, merges, moves, retags, or replaces files.

### 🛡️ Repair and safety

**Metadata Repair** — Preview supported title, artist, album, and track-number
proposals for a confirmed track, then select only the fields you want to
change. Applying a repair creates a full audio backup, writes and verifies a
temporary copy, and preserves unrelated media data. Replacement and state
updates use rollback safeguards; if automatic recovery cannot complete, the
retained backup is clearly surfaced for recovery.

**Backups and Restore** — Important media-mutation workflows create timestamped
backups before changing a file. Browse valid backups in the Library and restore
one through an explicit confirmation; scripted recovery is also available with
`999 restore`.

### 🩺 Diagnostics and integration

**Doctor and Support Reports** — `999 doctor` performs bounded, read-only
checks of the installation, configuration, local storage, one small catalogue
request, backups, and optional player integration. It reports clear PASS,
WARN, and FAIL results. Support reports omit song lists and state contents and
redact home paths and common credential forms by default; always review one
before sharing it.

**Optional rmpc Integration** — 999 can check rmpc and explicitly configure it
to use adjacent timed lyric sidecars. rmpc is not required, and normal startup
or Library Sync does not rewrite its configuration. Plain lyrics without
timestamps do not appear as synchronized lyrics in rmpc's Lyrics pane.

### Supported local formats

| Format | Embedded lyrics | Timed lyrics |
| --- | --- | --- |
| MP3 | ID3 USLT and SYLT | ID3 SYLT and adjacent `.lrc` |
| FLAC | Vorbis `LYRICS` | Adjacent `.lrc` |
| M4A | MP4 `©lyr` | Adjacent `.lrc` |

An adjacent sidecar uses the audio file's basename and directory, such as
`song.flac` with `song.lrc`.

## Screenshots

The dashboard at the top of this page was rendered by the real TUI using
synthetic data and a generic path. It is the only screenshot currently checked
into the repository, so the planned real captures below are deliberately not
linked yet:

- `dashboard.png` — overview and library health;
- `browse-search.png` — catalogue browsing and search;
- `library-health.png` — local collection status;
- `issues.png` — combined follow-ups;
- `downloads-queue.png` — explicit download queue;
- `metadata-repair-preview.png` — review before applying a repair;
- `lyrics-search.png` — offline lyric phrase search and timed results.

Lyrics Search will be featured prominently when the real captures are added.
See the [screenshot plan](docs/assets/screenshots/README.md) for capture rules.

## Usage

Press `?` anywhere in the TUI for the complete key map. The usual Library
routine is:

```text
Library → s Sync Library → a Issues
```

To find a local track from remembered words:

```text
Library → f Search Lyrics → type a phrase → Enter
```

Useful read-only command-line checks:

```bash
999 --version
999 status
999 doctor
999 guide
```

Catalogue search is also available from the command line when the service is
available:

```bash
999 search "Bandit"
999 info "10 Feet"
```

To inspect a different library for one command:

```bash
999 --path ~/Music/Juice-WRLD status
```

The detailed [user guide](docs/USER_GUIDE.md) covers configuration, keyboard
controls, acquisition, recovery, and advanced commands.

## Troubleshooting

Confirm which build is installed, then run the read-only diagnostic:

```bash
999 --version
999 doctor
pipx list
```

To create a report you can inspect before sharing:

```bash
999 doctor --support-report
999 doctor --save-report ./999-support.json
```

If the current beta is not working for you, use the `v2.0.0b1` fallback
command in [Quick Install](#previous-stable-fallback-200b1).

Current limitations:

- Acquisition and download post-processing are MP3-focused; local library,
  metadata, lyrics, backup, and restore workflows support MP3, FLAC, and M4A.
- Active download cancellation is not implemented.
- Configuration editing is primarily command-line based.
- Appearance can vary between terminal emulators.

For deeper detail, see the [user guide](docs/USER_GUIDE.md),
[changelog](docs/CHANGELOG.md), and
[development guide](docs/DEVELOPMENT.md).

## Uninstall

```bash
pipx uninstall juice-wrld-lyrics
```

Uninstalling the pipx app removes the command and its isolated environment. It
does not intentionally remove your music or normal `juice-lyrics` library,
configuration, state, cache, or backups.

## Reporting bugs

Use the [GitHub issue tracker](https://github.com/NotAI-fr/juice-lyrics/issues).
Include `999 --version`, your Linux distribution, installation method, steps
to reproduce, expected result, and actual result.

Do not attach music, lyric collections, credentials, tokens, private
configuration/state files, or unreviewed support reports. Prefer synthetic
names and paths.

999 is an unofficial fan-made project. It is not affiliated with or endorsed
by Juice WRLD's estate, record labels, or the Juice WRLD API. This repository
contains no music or lyric collection.

999 is available under the [MIT License](LICENSE). Users are responsible for
the media, lyrics, and services they access and for complying with applicable
law and service terms.
