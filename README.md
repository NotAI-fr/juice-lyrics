# 999

A terminal-native Juice WRLD music hub for Linux, with cautious lyrics management for local MP3, FLAC, and M4A libraries and synchronized `.lrc` sidecars for rmpc.

It uses the Juice WRLD API as a metadata/lyrics source, prefers synchronized lyrics (`SYLT`), and falls back to ordinary embedded lyrics (`USLT`) when timestamps are unavailable.

## The simple workflow

### First time

```bash
999
```

This opens the TUI. Missing configuration or library folders are reported in
the interface without changing rmpc or starting a download.

Configuration is optional. To write a starter configuration, or explicitly
configure rmpc later:

```bash
999 config init
999 rmpc setup
```

Your Juice WRLD folder is kept together:

```text
~/Music/Juice WRLD/
├── Unreleased/
│   ├── Bottle.mp3
│   ├── Bottle.lrc
│   ├── Rental.mp3
│   ├── Rental.lrc
│   └── ...
```

### Normal use

After adding or changing songs:

```bash
999 sync
```

`sync` remembers the files it has already processed. Unchanged, verified files are skipped, so normal updates are much faster than a full rescan.

Useful status command:

```bash
999 status
```

Built-in guide:

```bash
999 guide
```

## What `sync` does

```text
local MP3, FLAC, or M4A
   │
   ├── match to API using title + version + API path + duration
   │
   ├── synced lyrics available ──► MP3: ID3 SYLT
   │                               FLAC: plain-text Vorbis LYRICS
   │                               M4A: plain-text MP4 ©lyr
   │                               └── adjacent rmpc .lrc (timing authority)
   │
   └── only ordinary lyrics ─────► MP3: ID3 USLT / FLAC: Vorbis LYRICS / M4A: MP4 ©lyr
```

Songs without synchronized lyrics still receive ordinary embedded lyrics. rmpc's synchronized Lyrics pane cannot display those as timed lyrics unless timestamps are available.

## Search the public catalogue

The API's catalogue can be searched without downloading media:

```bash
999 search "red dead"
999 search --category unreleased --era DRFL "moncler"
999 info "Rental"
```

`search` shows useful catalogue metadata, lyric availability, era, duration, and file path information. `info` fetches the detailed song record when possible.

The project avoids untargeted catalogue scraping; media acquisition is explicit, opt-in, and managed through persistent acquisition jobs. The media-management workflow operates on local media or explicitly acquired tracks.

## Project documentation

The repository keeps its development and continuity context in version-controlled documentation so work can safely continue across chats or coding agents:

- `PROJECT_CONTEXT.md` — user/project context and major decisions
- `docs/ROADMAP.md` — current and planned work
- `docs/ARCHITECTURE.md` — component responsibilities and dependency direction
- `docs/USER_GUIDE.md` — straightforward user workflows
- `docs/DEVELOPMENT.md` — development and testing guidance
- `docs/CHANGELOG.md` — release and milestone history

Before major changes, read `PROJECT_CONTEXT.md`, `docs/ROADMAP.md`, and `docs/ARCHITECTURE.md`.

## Commands

| Command | Purpose |
|---|---|
| `setup` | Compatibility shortcut for an initial library sync; never rewrites rmpc |
| `sync` | Normal day-to-day library update |
| `status` | Show current library state without API calls |
| `scan` | Detailed API scan/troubleshooting |
| `embed` | Lower-level embed-only command |
| `verify` | Validate supported MP3/FLAC/M4A embedded lyrics |
| `restore` | Restore a previous audio backup |
| `doctor` | Diagnose Python, Mutagen, API, and paths |
| `guide` | Show this workflow in the terminal |
| `search` | Search the public song catalogue |
| `info` | Inspect a song's API metadata |
| `acquire` | Explicitly select, queue, and acquire API media resources |
| `rmpc setup/sync/verify` | Explicit advanced rmpc operations |
| `config` | Manage persistent configuration |
| `cache clear` | Clear cached API responses |

## Safety

Before modifying MP3, FLAC, or M4A metadata, the tool creates timestamped backups under:

```text
~/.local/share/juice-lyrics/backups/
```

Each modified file is verified after writing. If verification fails for that file, it is immediately restored from its backup.

The audio stream is never decoded/re-encoded by this tool. It edits MP3 ID3,
FLAC Vorbis, or M4A MP4 metadata and writes separate adjacent LRC text files.

For MP3, only lyric frames created by this tool (`desc = "Juice WRLD API"`) are
replaced. For FLAC, the standard `LYRICS` field is updated while unrelated
Vorbis comments are preserved. For M4A, standard `©lyr` is updated while
unrelated MP4 atoms are preserved.

## Matching

The matcher intentionally uses several signals rather than trusting a title alone:

- explicit version (`v1`, `v2`, etc.)
- exact API filename
- exact API path filename
- title/original key
- known Juice WRLD aliases
- local audio duration vs API duration
- category preference

This prevents common version mix-ups such as selecting `Starstruck (v1)` for `Starstruck (v2)`.

## rmpc

Audio and external synchronized lyrics stay together. A synchronized song gets
a same-basename sidecar beside its audio file:

```text
song.mp3
song.lrc
```

The old `lyrics_dir` configuration key is accepted for compatibility but is
deprecated and does not direct new output. Existing centralized files are not
moved automatically; migration is a separate, explicit operation. Sidecars work
naturally when the music tree is synchronized between devices. Embedded lyrics
remain supported.

The advanced commands remain available:

```bash
999 rmpc setup
999 rmpc sync
999 rmpc verify
```

## Configuration

Defaults are designed for the user's common Linux layout, but the library can be overridden globally:

```bash
999 config init
999 config show
```

or for a single command:

```bash
999 --path ~/Music/MyLibrary status
```

The tool follows XDG locations for its config, cache, state, and backups.

## Installation

### Recommended pipx editable install

```bash
pipx install --editable /absolute/path/to/juice-lyrics-codex
command -v 999
999 --help
```

The distribution remains named `juice-wrld-lyrics` for update compatibility.
If pipx already has an older copy, replace it deliberately:

```bash
pipx install --force --editable /absolute/path/to/juice-lyrics-codex
hash -r
command -v 999
999 --help
```

### Editable development install

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e .
```

For development checkpoints, invoke the repository environment explicitly:

```bash
.venv/bin/999
```

If `command -v 999` points at an older pipx installation, that command will not
contain current checkout changes. Reinstall it deliberately or keep using
`.venv/bin/999`; changing the repository cannot update an installed copy.

`juice-lyrics` remains available as a legacy compatibility command. Both names
run the same CLI. Existing config, state, queue, cache, and backups continue to
use the `juice-lyrics` XDG namespace so no data migration is required.

## Development

Run the test suite with:

```bash
pytest -q
```


## Acquisition (Explicit Workflow)

The project includes an acquisition subsystem for explicitly selected API resources:

```bash
# 1. Search the catalogue and check downloadable resources
999 acquire search "rental"

# 2. Queue selected item(s) by 1-based index (or use --manifest)
999 acquire add "rental" --index 1

# 3. Queue from a plain-text manifest file
999 acquire manifest manifest.txt

# 4. View queued persistent jobs
999 acquire jobs

# 5. Run a persistent job (with automatic resume, size/hash checks, and post-processing)
999 acquire run <job-id>

# 6. Retry failed/pending items or delete job records
999 acquire retry <job-id>
999 acquire delete <job-id>
```

Acquisition is intentionally opt-in and operates only on explicitly selected resources. The transport downloader streams via temporary `.part` files, supports HTTP range resume, validates payload size and checksums, and integrates acquired MP3s directly with the synced/plain lyrics and rmpc workflow.
