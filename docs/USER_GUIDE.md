# User Guide

## First-time setup

Run:

```bash
juice-lyrics setup
```

When rmpc is detected, setup generates synchronized LRC sidecars and updates
rmpc to index the configured music tree after its normal confirmation. Merely
loading configuration creates no directories or files.

## Configuration

The application configuration is `~/.config/juice-lyrics/config.toml`. Embedded
lyrics remain inside each audio file. External synchronized lyrics are written
beside the audio with the same basename:

```text
song.mp3
song.lrc
another-song.flac
another-song.lrc
third-song.m4a
third-song.lrc
```

The legacy `lyrics_dir` key remains readable so old configurations continue to
load, but it is deprecated and ignored for new LRC output. Existing centralized
files are not moved automatically. Local FLAC and M4A files are scanned and
synchronized natively without conversion. FLAC embeds plain-text Vorbis
`LYRICS`; M4A embeds standard MP4 `©lyr`; synchronized timing remains in the
adjacent `.lrc`.

## Normal day-to-day use

After adding or changing local songs:

```bash
juice-lyrics sync
```

`sync` should be the main command to remember.

It matches songs, fetches lyrics, embeds metadata, generates rmpc LRC files when synchronized lyrics exist, verifies results, and updates state.

## Check health

```bash
juice-lyrics status
```

Use this when you simply want to know whether the library is up to date.

## Find songs in the API catalogue

```bash
juice-lyrics search "rental"
juice-lyrics info "Rental"
```

Search and info provide catalogue metadata and discovery.

## Acquisition

The acquisition workflow is explicit: a resource must first be selected before it can be added to an acquisition job.

The workflow commands:

```bash
# Search for downloadable candidates
juice-lyrics acquire search "rental"

# Add one or more items (1-based index, e.g. 1 or 1,2,4)
juice-lyrics acquire add "rental" --index 1

# Add from a plain-text manifest file
juice-lyrics acquire manifest manifest.txt

# List queued acquisition jobs
juice-lyrics acquire jobs

# Run an acquisition job
juice-lyrics acquire run <job-id>

# Retry failed or pending items in a job
juice-lyrics acquire retry <job-id>

# Delete a job record
juice-lyrics acquire delete <job-id>
```

The acquisition system maintains persistent job state, skips already-present files, supports HTTP range download resumption, validates payloads, and automatically applies the lyrics and rmpc pipeline to downloaded MP3s.

## rmpc lyrics behavior

Songs with API synchronized lyrics get:

* embedded ID3 SYLT
* a same-basename `.lrc` beside the audio for rmpc

Songs with only ordinary API lyrics get:

* embedded ID3 USLT

Those plain-only songs are still tagged correctly, but rmpc's synchronized Lyrics pane does not display them without timestamps.

## Troubleshooting

```bash
juice-lyrics doctor
```

For detailed matching:

```bash
juice-lyrics scan
```

For metadata verification:

```bash
juice-lyrics verify
```

For rmpc-specific problems:

```bash
juice-lyrics rmpc verify
```

## Backups

MP3, FLAC, and M4A metadata changes create timestamped backups under:

```text
~/.local/share/juice-lyrics/backups/
```

Restore the most recent backup with:

```bash
juice-lyrics restore
```

## Paths

Default local library:

```text
~/Music/Juice WRLD/Unreleased
```

External synchronized lyrics:

```text
song.mp3
song.lrc
another-song.flac
another-song.lrc
third-song.m4a
third-song.lrc
```

The audio path is authoritative; no global LRC destination is configured.
Existing centralized LRC files are not moved automatically. Use the separate
explicit migration utility if migration is required.
