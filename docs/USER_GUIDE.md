# User Guide

## First-time setup

Run:

```bash
juice-lyrics setup
```

When rmpc is detected, setup generates synchronized LRC files and updates the
rmpc lyrics setting after its normal confirmation. Merely loading configuration
does not create the lyrics directory.

## Configuration

The application configuration is `~/.config/juice-lyrics/config.toml`. Embedded
lyrics remain inside each audio file. External synchronized LRC files use one
central directory shared across artists:

```toml
lyrics_dir = "~/Music/lyrics"
```

The default is `~/Music/lyrics`; an explicit `lyrics_dir` overrides it. Inspect
the effective value with `juice-lyrics config show`. Native FLAC support remains
planned separately.

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

Default external synchronized LRC directory:

```text
~/Music/lyrics
```

Both should remain configurable.

Existing LRC files from the previous default are not moved automatically. A
safe no-overwrite manual migration is:

```bash
mkdir -p ~/Music/lyrics
find ~/Music/Juice\ WRLD/lyrics -maxdepth 1 -type f -iname '*.lrc' -exec mv -n -t ~/Music/lyrics -- {} +
```
