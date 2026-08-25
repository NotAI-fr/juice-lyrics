# User Guide

## First-time setup

Run:

```bash
juice-lyrics setup
```

This creates/updates configuration and, when rmpc is detected, prepares the lyric directory and relevant rmpc settings.

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
* an `.lrc` file for rmpc

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

MP3 metadata changes create timestamped backups under:

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

Default rmpc lyrics directory:

```text
~/Music/Juice WRLD/lyrics
```

Both should remain configurable.
