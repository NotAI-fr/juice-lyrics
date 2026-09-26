# 999

[![GitHub release](https://img.shields.io/github/v/release/NotAI-fr/juice-lyrics?include_prereleases&label=release)](https://github.com/NotAI-fr/juice-lyrics/releases/tag/v2.0.0b1)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

`999` is a keyboard-first Linux CLI and TUI for managing a local Juice WRLD
music library. It combines catalogue browsing, conservative track matching,
lyrics maintenance, explicit downloads, backups, and optional rmpc integration
without trying to replace your music player.

> **Current release:** [`2.0.0b1`](https://github.com/NotAI-fr/juice-lyrics/releases/tag/v2.0.0b1)
> is a beta. Keep an independent backup of valuable media and review every
> proposed metadata or lyric change before applying it.

999 is an unofficial fan-made project. It is not affiliated with or endorsed
by Juice WRLD's estate, record labels, or the Juice WRLD API. This repository
contains no music or lyric collection.

## Screenshots

![999 dashboard with synthetic demonstration data](docs/assets/screenshots/dashboard-synthetic.png)

_The image above was rendered by the real TUI using synthetic counts and a
generic path. Additional real screenshots will be added after manual capture;
the planned filenames are documented in
[`docs/assets/screenshots/README.md`](docs/assets/screenshots/README.md)._

## Highlights

- Browse and search the Juice WRLD catalogue without downloading anything.
- Sync a local library incrementally while leaving ambiguous matches Unknown.
- Review Issues, exact/probable Duplicates, and Missing Library recordings.
- Manually match and lock catalogue identities when automatic matching should
  not decide.
- Preview selected metadata repairs before a cancel-first confirmation.
- Maintain embedded lyrics and adjacent timed `.lrc` files without converting
  or re-encoding audio.
- Queue downloads explicitly; adding an item never starts a download.
- Create backups before media metadata changes and verify every result.
- Diagnose installation, configuration, storage, catalogue, and optional rmpc
  integration with the read-only `999 doctor` command.

## Supported media

| Format | Local metadata and lyrics | Synchronized lyrics |
|---|---|---|
| MP3 | ID3 metadata, USLT and SYLT | ID3 SYLT and adjacent `.lrc` |
| FLAC | Vorbis metadata and plain `LYRICS` | Adjacent `.lrc` |
| M4A | MP4 metadata and plain `©lyr` | Adjacent `.lrc` |

999 never converts audio. A timed sidecar always uses the audio file's own
basename and directory, such as `song.flac` with `song.lrc`.

## Install

Requirements:

- a supported Linux system;
- Python 3.11 or newer;
- [`pipx`](https://pipx.pypa.io/) installed and on `PATH`.

After this repository is public, install the immutable beta wheel directly
from its GitHub release—no clone or GitHub account is required:

```bash
pipx install "https://github.com/NotAI-fr/juice-lyrics/releases/download/v2.0.0b1/juice_wrld_lyrics-2.0.0b1-py3-none-any.whl"
999 --version
999 doctor
```

To replace an older installation with this exact beta:

```bash
pipx install --force "https://github.com/NotAI-fr/juice-lyrics/releases/download/v2.0.0b1/juice_wrld_lyrics-2.0.0b1-py3-none-any.whl"
```

An immutable Git-tag install is also available:

```bash
pipx install "git+https://github.com/NotAI-fr/juice-lyrics.git@v2.0.0b1"
```

The legacy `juice-lyrics` command remains available. Both commands use the
existing `juice-lyrics` XDG namespace so upgrades do not create a second state
tree.

## Quick start

Launch the interface:

```bash
999
```

The default library path can be changed with a starter configuration:

```bash
999 config init
999 config show
```

Or override it for one command:

```bash
999 --path ~/Music/Juice-WRLD status
```

Press `?` anywhere in the TUI for the complete key map. The normal routine is:

```text
Library → s Sync Library → a Issues
```

Sync records new and changed paths, retires removed paths, and attempts only
conservative catalogue matches. It does **not** edit audio, lyrics, backups,
downloads, or rmpc configuration.

## Main TUI workflows

| Area | Typical workflow |
|---|---|
| Browse | Search/filter → inspect details → Add to queue |
| Downloads | Review queue → confirm one item or the eligible queue → inspect result/retry |
| Library | Sync → filter/select → inspect health and identity |
| Issues | Review genuine errors, lyric follow-ups, stale state, and Unknown identities |
| Manual match | Search → select an exact recording → lock; unlock later if needed |
| Duplicates | Review evidence and paths only; 999 never deletes or merges files |
| Metadata repair | Preview → choose individual fields → confirm → verify backup/result |
| Missing Library | Compare confirmed catalogue IDs → optionally add one recording to the queue |

The command line remains useful for diagnostics and scripting:

```bash
999 status
999 search "Bandit"
999 info "10 Feet"
999 guide
```

Acquisition is always explicit:

```bash
999 acquire search "Rental"
999 acquire add "Rental" --index 1
999 acquire jobs
999 acquire run <job-id>
```

## Safety and backups

- Automatic matching prefers Unknown over a risky confident identity.
- Normal Library Sync never modifies media or starts downloads.
- Metadata repair changes only selected fields after a preview and confirmation.
- Before an in-place media metadata change, 999 creates a full backup under
  `~/.local/share/juice-lyrics/backups/`.
- Post-write verification checks that encoded audio, artwork, lyrics,
  unrelated tags, and adjacent sidecars were preserved. A failed write is
  rolled back.
- State and `.lrc` writes are atomic, and state updates detect conflicting
  concurrent changes.
- Duplicate results are evidence for review only—never an instruction to
  delete, move, merge, or replace media.

## Doctor and support reports

Run bounded, read-only diagnostics with:

```bash
999 doctor
```

If an issue needs more detail, generate a sanitized report and inspect it
before sharing:

```bash
999 doctor --save-report ./999-support.json
```

Doctor does not run Sync, enumerate the full catalogue, modify application
data, invoke rmpc/MPD, or inspect every audio file. Support reports redact home
paths and common credential forms and exclude song lists and state contents.

## Known beta limitations

- Acquisition and download post-processing are currently MP3-focused; local
  library inspection, metadata, lyrics, backup, and restore support MP3, FLAC,
  and M4A.
- Active download cancellation is not implemented.
- Configuration editing is primarily command-line based.
- Visual polish has not been exhaustively reviewed across terminal emulators.
- Fish completion generation is tested, but this beta did not receive a local
  Fish runtime syntax pass.
- Independent second-machine pipx acceptance and optional live rmpc
  notification remain limited.

See the [2.0.0b1 release notes](https://github.com/NotAI-fr/juice-lyrics/releases/tag/v2.0.0b1)
for the accepted beta scope.

## Reporting issues

Use the [GitHub issue tracker](https://github.com/NotAI-fr/juice-lyrics/issues)
for reproducible bugs. Include the `999 --version` output, Linux distribution,
installation method, steps to reproduce, expected result, and actual result.

Please do **not** attach music, lyric collections, credentials, tokens, private
configuration/state files, or unreviewed support reports. Use synthetic names
and paths where possible.

## Documentation and development

- [User guide](docs/USER_GUIDE.md)
- [Changelog](docs/CHANGELOG.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Development guide](docs/DEVELOPMENT.md)

For a development checkout:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e .
pytest -q
```

## License

999 is available under the [MIT License](LICENSE).

Users are responsible for the media, lyrics, and services they access and for
complying with applicable law and service terms. The project does not grant
rights to Juice WRLD recordings, artwork, or lyrics.
