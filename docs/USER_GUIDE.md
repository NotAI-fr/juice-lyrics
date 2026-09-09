# User Guide

## First run

Run:

```bash
999
```

This opens the terminal interface. It does not download anything or rewrite
rmpc configuration. If the default library is missing, Settings shows the
configured path and the next action without a traceback.

Configuration is optional. `999 config init` writes a starter config only.
`999 setup` remains a compatibility shortcut for an initial library lyric sync;
it does not configure rmpc. Only the explicit `999 rmpc setup` command changes
rmpc configuration.

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

## Manage your local library

Open `999`, choose **Library**, and use:

* **Refresh** to rescan MP3, FLAC, and M4A files without changing them;
* **Maintain lyrics** to preview needed changes, then explicitly approve them;
* **Verify** for a read-only health check and attention list;
* **Backups** to inspect valid backups and restore one with confirmation;
* **Player** to check rmpc and explicitly configure its sidecar indexing.

Select a song and press `l` to refresh lyrics for only that song. The CLI
equivalent, `999 sync`, remains useful for scripting and automation.

## Check health

```bash
999 status
```

Use this when you simply want to know whether the library is up to date.

## Find songs in the API catalogue

```bash
999 search "rental"
999 info "Rental"
```

Search and info provide catalogue metadata and discovery.

## Acquisition

The acquisition workflow is explicit: a resource must first be selected before it can be added to an acquisition job.

The workflow commands:

```bash
# Search for downloadable candidates
999 acquire search "rental"

# Add one or more items (1-based index, e.g. 1 or 1,2,4)
999 acquire add "rental" --index 1

# Add from a plain-text manifest file
999 acquire manifest manifest.txt

# List queued acquisition jobs
999 acquire jobs

# Run an acquisition job
999 acquire run <job-id>

# Retry failed or pending items in a job
999 acquire retry <job-id>

# Delete a job record
999 acquire delete <job-id>
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
999 doctor
```

For detailed matching:

```bash
999 scan
```

For metadata verification:

```bash
999 verify
```

For advanced or scripted rmpc checks:

```bash
999 rmpc verify
```

## Backups

MP3, FLAC, and M4A metadata changes create timestamped backups under:

```text
~/.local/share/juice-lyrics/backups/
```

Backups can be browsed and restored from **Library → Backups**. For scripted or
unusual recovery, restore the most recent backup with:

```bash
999 restore
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

## Compatibility names and data

`999` is the product and primary executable. `juice-lyrics` remains a legacy
compatibility command and invokes the same Python CLI. The internal package is
still `juice_lyrics`, while existing XDG data remains under `juice-lyrics`:

```text
~/.config/juice-lyrics/
~/.cache/juice-lyrics/
~/.local/share/juice-lyrics/
```

No duplicate `999` data tree is created and no migration is required.
