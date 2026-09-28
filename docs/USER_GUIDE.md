# User Guide

## First run

Run:

```bash
999
```

This opens the terminal interface. It does not download anything or rewrite
rmpc configuration. If the default library is missing, Settings shows the
configured path and the next action without a traceback.

Press `?` from any section for the scrollable keyboard guide. The bottom lines
show the most common actions for the current section. Use `1`–`5` to switch
sections when not typing, `↑`/`↓` to move, `Enter` for details, `Esc` to return,
and `q` to quit. Digits and `q` type normally in a focused search field; Enter
submits the search and returns focus to the results.
Browse uses `Space` to mark songs and `a` to add the current or marked songs
directly to Downloads; adding does not start a download. In Downloads, `d`
downloads one selected song, `t` retries a failed song, and `A` starts the
whole queue after confirmation. Library Sync, local refresh, verification, and
maintenance preview do not change audio or lyrics. Applying maintenance,
restoring, rebuilding catalogue
matches, and changing rmpc setup remain cancel-first confirmations: `y`
confirms immediately, `n`/`Esc` cancels, and initial `Enter` cancels.

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

* **Sync Library** (`s`) for the normal update: discover MP3, FLAC, and M4A changes, retire known removed entries, and identify safe catalogue matches without changing audio or lyrics;
* **Search Lyrics** (`f`) to find a local track from remembered lyric words, entirely offline;
* **Issues** (`a`) to see only tracks still needing a decision or repair;
* **Duplicates** (`d`) to review exact file copies and conservative probable recordings without changing anything;
* **Missing Library** (`g`) to compare confirmed local recording IDs with the paginated catalogue and optionally queue one exact recording;
* **Metadata repair** (`e`) on the selected track to compare supported tags, explicitly select fields, and review a cancel-first Apply confirmation;
* **Maintain lyrics** to preview needed changes, then explicitly approve them;
* **Verify** for a read-only health check and attention list;
* **Backups** to inspect valid backups and restore one with confirmation;
* **Player** to check rmpc and explicitly configure its sidecar indexing.

Press `?` in Library to see the infrequent **Rebuild catalogue matches** action.
It previews current tracks and existing identities, then uses a cancel-first
confirmation. The rebuild changes application identity state only; it does not
modify audio or lyrics.

Sync Library keeps unchanged tracks fast and checks unknown tracks against the
catalogue in the background. Only confident identities are saved. A recent
empty or ambiguous search is retried after the normal catalogue cache window.
The separate **Refresh** key remains available for a direct local rescan.
Audio, embedded lyrics, sidecars, audio backups, and rmpc configuration are not
changed. If the catalogue is unavailable, local health remains usable and the
track stays **Unknown**.

### Search local lyrics (2.0.0b2)

Press `f` in Library and type remembered words or a
phrase. Results update as you type. Use ↑/↓ to choose a track, Enter to return
to that track's Library details, or Escape to return without selecting.

Search covers embedded MP3, FLAC, and M4A lyrics plus adjacent plain or timed
`.lrc` text. It ignores case, repeated whitespace, apostrophe differences, and
ordinary punctuation, then performs a predictable substring match. It does not
guess similar wording. One row is shown per track even when a chorus matches
several times. If embedded text duplicates an adjacent LRC line, the LRC form
is shown so its real timestamp is retained.

The first search lazily refreshes a rebuildable cache. Later openings reuse
unchanged tracks; changed audio or LRC files are re-read individually and
removed tracks disappear. Typing never rescans media. Search makes no catalogue
or API request and does not run Sync or modify audio, lyrics, state, backups,
downloads, or rmpc configuration. This feature is included in `v2.0.0b2`; it
is not part of the previous `v2.0.0b1` fallback.

Duplicates opens immediately from the current Library snapshot. Exact groups
share the same recorded whole-file SHA-256. Probable groups use compatible
catalogue identity, duration, title, artist, and recording-version evidence.
Live, remix, session, extended, TV mix, and numbered versions are not treated
as interchangeable. The view shows its evidence and every path, but never
deletes, merges, moves, retags, or replaces audio. Run Sync Library first when
you want the snapshot and saved fingerprints brought up to date.

Missing Library loads cached/paginated catalogue data in the background. It
uses stable catalogue IDs only: duplicate titles and live, remix, session,
demo, extended, or numbered versions remain separate. Local Unknown tracks are
shown as a separate count and never used as loose-title proof of ownership. If
pages cannot be loaded, coverage is labelled partial or unavailable. `/`
filters loaded results and `a` adds the selected recording to the normal
Downloads queue without starting it.

Metadata repair reads the selected MP3, FLAC, or M4A tags and its confirmed
catalogue record. It can propose title, artist, album, and track number where
the catalogue actually supplies those fields. Missing local values are marked
**Confident**; differences from existing values are marked **Review**. Unknown
tracks receive no guesses, and version distinctions are preserved. No fields
are selected by default. Space or Enter toggles one field; `a` reviews the exact
selection; the final confirmation starts on Cancel. A confirmed repair runs in
the background, creates a complete audio backup, writes a temporary copy, and
verifies the encoded audio, artwork, embedded lyrics, unrelated tags, and
adjacent sidecar before replacing the file. Failure restores the original where
replacement began. Success updates the saved whole-file hash and refreshes the
Library and Issues view. Normal repair does not change lyrics or player config.

Issues opens instantly from the current Library snapshot and does not rescan or
contact the catalogue merely to display the list. Each affected track appears
once with its combined catalogue, lyric, verification, metadata, or state
reasons. From an issue, use `c` for manual matching, `l` for the existing
selected lyric-refresh preview, `v` to verify, or `s` to Sync Library. A valid
manual lock stays out of follow-ups; if a catalogue-backed action later
observes that its
chosen recording is unavailable, the lock is preserved and an Issue explains
the problem.

To resolve an Unknown track—or correct a wrong automatic match—select it and
press `c`. The **Match manually** chooser searches using the local title; press
`/` to refine the search, use the arrow keys to choose a clearly identified
candidate, and press Enter to save it. This saves only catalogue identity state
and marks the choice as manual and locked. It does not modify the audio,
lyrics, sidecar, backups, downloads, or rmpc configuration.

A valid manual lock survives normal Sync, automatic backfill, restart, and an
ordinary identity rebuild. It is tied to the current audio content, so a
changed or replaced file does not inherit it. Press `u` on a manually matched
track to unlock and clear its catalogue identity; lyric and custom state remain
untouched, and a later Sync may match it automatically again.

Select a song and press `l` to refresh lyrics for only that song. The CLI
`999 sync` command is the separate scriptable lyric-maintenance workflow; it
may modify lyrics and should not be confused with the TUI's state-only Sync
Library action.

**Fully covered** describes local lyric health, not catalogue identity. A FLAC
or M4A file is fully covered when it has embedded plain lyrics and its adjacent
`.lrc` contains timestamped lyric lines. MP3 keeps its existing synchronized
embedded-lyrics requirement. A locally covered track may still show **Catalogue match:
Unknown**; that only means automatic refresh cannot identify a safe catalogue
record yet. It appears in Issues as an identity decision, not as a claim that
the existing lyrics are broken.

## Check health

```bash
999 status
```

Use this when you simply want to know whether the library is up to date.

`999 scan` is the advanced catalogue-matching diagnostic. Its **Catalogue
uncertain** count means identity could not be established safely; it does not by
itself mean that local lyrics are missing or broken.

## Clean clearly stale state records

Preview first:

```bash
999 state clean
```

If the listed records are genuinely obsolete, apply the cleanup:

```bash
999 state clean --yes
```

The apply command writes a timestamped `state.json.pre-clean-...bak` safety
copy before an atomic state update. It removes no audio or LRC files. Ordinary
missing relative entries are retained because they may describe music moved
within the configured library.

## Rebuild catalogue matches

If older persisted matches were created by an outdated matcher, preview a full
current-library rebuild:

```bash
999 state rebuild-identities
```

Apply it only after reviewing the counts:

```bash
999 state rebuild-identities --yes --details
```

Use `--refresh` as well when cached catalogue search responses must be fetched
again. The rebuild reconsiders MP3, FLAC, and M4A files, preserves all lyric and
other state fields, preserves valid manual locks, ignores stale external
records, makes a complete state backup, and commits the result atomically.
Ambiguous tracks become Unknown. The advanced `--include-locked` option is the
explicit way to reconsider manual choices too.
An individual API failure preserves that track's old identity; a catalogue-wide
failure aborts without changing state.

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

Doctor reports clear `PASS`, `WARN`, and `FAIL` results for the installed
command/Python package, configuration, state and cache JSON, the configured
music directory and supported-format counts, one small catalogue connectivity
probe, backup storage, and optional rmpc integration. It does not hash the
library, run Sync, write cache/state, invoke downloads, or change rmpc.

For support, print or deliberately save a JSON report:

```bash
999 doctor --support-report
999 doctor --save-report ./999-support.json
```

The report is sanitized by default: it contains no song list or state content,
and home paths and common credential forms are redacted. Review any report
before sharing it, as unusual third-party error text cannot be guaranteed to
follow common formats.

## Shell completion

`999` generates completion directly from its current command definitions, so
the suggestions cover the installed commands, nested actions, and options.
Generation is read-only and does not load application configuration, state, or
catalogue data.

Bash (requires the normal `bash-completion` setup):

```bash
mkdir -p ~/.local/share/bash-completion/completions
999 completion bash > ~/.local/share/bash-completion/completions/999
```

Zsh:

```zsh
mkdir -p ~/.zfunc
999 completion zsh > ~/.zfunc/_999
```

Ensure `fpath=(~/.zfunc $fpath)` appears before `autoload -Uz compinit &&
compinit` in `~/.zshrc`.

Fish:

```fish
mkdir -p ~/.config/fish/completions
999 completion fish > ~/.config/fish/completions/999.fish
```

Open a new shell after installation, and regenerate the file after updating
`999`. Each generated script also binds the legacy `juice-lyrics` command.

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
