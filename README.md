# juice-lyrics 1.4.0

A small, cautious Linux CLI for managing lyrics metadata in local MP3, FLAC, and M4A libraries and generating synced `.lrc` files for rmpc.

It uses the Juice WRLD API as a metadata/lyrics source, prefers synchronized lyrics (`SYLT`), and falls back to ordinary embedded lyrics (`USLT`) when timestamps are unavailable.

## The simple workflow

### First time

```bash
juice-lyrics setup
```

This configures the library, embeds available lyrics, and configures rmpc automatically when rmpc and its config are detected.

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
juice-lyrics sync
```

`sync` remembers the files it has already processed. Unchanged, verified files are skipped, so normal updates are much faster than a full rescan.

Useful status command:

```bash
juice-lyrics status
```

Built-in guide:

```bash
juice-lyrics guide
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
juice-lyrics search "red dead"
juice-lyrics search --category unreleased --era DRFL "moncler"
juice-lyrics info "Rental"
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
| `setup` | First-time setup and rmpc integration |
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
| `rmpc setup/sync/verify` | Advanced rmpc-only operations |
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
juice-lyrics rmpc setup
juice-lyrics rmpc sync
juice-lyrics rmpc verify
```

## Configuration

Defaults are designed for the user's common Linux layout, but the library can be overridden globally:

```bash
juice-lyrics config init
juice-lyrics config show
```

or for a single command:

```bash
juice-lyrics --path ~/Music/MyLibrary status
```

The tool follows XDG locations for its config, cache, state, and backups.

## Installation

### pipx

```bash
pipx install .
```

### Editable development install

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e .
```

For development checkpoints, invoke the repository environment explicitly:

```bash
.venv/bin/juice-lyrics tui
```

If `command -v juice-lyrics` points at an older pipx installation, that command
will not contain current uncommitted source changes. Reinstall it deliberately or
keep using `.venv/bin/juice-lyrics`; changing the repository cannot update an
already installed copy.

## Development

Run the test suite with:

```bash
pytest -q
```


## Acquisition (Explicit Workflow)

The project includes an acquisition subsystem for explicitly selected API resources:

```bash
# 1. Search the catalogue and check downloadable resources
juice-lyrics acquire search "rental"

# 2. Queue selected item(s) by 1-based index (or use --manifest)
juice-lyrics acquire add "rental" --index 1

# 3. Queue from a plain-text manifest file
juice-lyrics acquire manifest manifest.txt

# 4. View queued persistent jobs
juice-lyrics acquire jobs

# 5. Run a persistent job (with automatic resume, size/hash checks, and post-processing)
juice-lyrics acquire run <job-id>

# 6. Retry failed/pending items or delete job records
juice-lyrics acquire retry <job-id>
juice-lyrics acquire delete <job-id>
```

Acquisition is intentionally opt-in and operates only on explicitly selected resources. The transport downloader streams via temporary `.part` files, supports HTTP range resume, validates payload size and checksums, and integrates acquired MP3s directly with the synced/plain lyrics and rmpc workflow.
