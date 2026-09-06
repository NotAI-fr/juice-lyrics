# Architecture

## Design goal

Keep the application lightweight and easy to use while preventing the CLI from becoming a giant module that owns every responsibility.

The user-facing CLI should be a thin layer over reusable services.

## Desired dependency direction

```text
CLI / TUI
   |
   +--> API
   +--> Library
   +--> Lyrics
   +--> rmpc
   +--> Acquisition
   +--> Backup
   +--> Config
```

Reusable modules should not import application commands from `cli.py` merely to reuse helper functions.

## API layer

Responsibilities:

* HTTP requests
* API base URL handling
* timeouts
* retry behavior
* search
* song lookup
* pagination
* response normalization
* caching

The API layer should not know about terminal prompts, MP3 tagging, or rmpc UI.

## Library layer

Responsibilities:

* scan local MP3, FLAC, and M4A files recursively
* extract metadata
* duration handling
* fingerprints/state
* duplicate detection
* matching local files to API records
* incremental sync decisions

Matching must remain version-aware, alias-aware, and duration-aware.

## Lyrics layer

Responsibilities:

* parse API LRC-style `synced_lyrics`
* produce MP3 SYLT frames
* produce MP3 USLT frames
* write standard plain-text FLAC/Vorbis `LYRICS` comments
* write standard plain-text M4A/MP4 `©lyr` atoms
* verify lyric frames
* write `.lrc` text when synchronized lyrics exist

It must never manufacture timestamps for plain lyrics.

## rmpc layer

Responsibilities:

* generate same-basename `.lrc` sidecars beside audio for synced lyrics
* locate/configure the user's rmpc config safely
* preserve unrelated rmpc settings/layout/keybinds
* trigger lyric re-indexing where supported
* provide diagnostics

The finalized audio path is authoritative for external lyrics. Historical state,
rmpc configuration, and the deprecated `lyrics_dir` setting cannot redirect a
new write. A generated sidecar is passed to rmpc's individual-path indexing
boundary.

## Backup layer

Responsibilities:

* timestamped backups
* manifests
* restore
* rollback after verification failures

## Configuration layer

Responsibilities:

* XDG config paths
* persistent settings
* validation
* default values

Do not hard-code a particular user's home directory.

## State layer

Track enough information to skip unchanged files safely.

State should include a local file identity/fingerprint and enough processing information to know whether lyrics/rmpc output are current.

Losing state must be recoverable: the application should be able to rescan and reconstruct it.

## Acquisition layer

Responsibilities:

* resource models
* explicit resource selection
* acquisition items
* transport/download
* manifests
* persistent job state
* progress
* temporary files
* validation
* retry/resume
* duplicate handling
* post-download coordination

Acquisition should not directly perform lyric embedding or rmpc configuration. It should hand successfully acquired local files to the existing library/post-processing workflow.

### Acquisition flow

```text
resource/API result
       ↓
explicit selection
       ↓
resource resolver
       ↓
AcquisitionItem
       ↓
persistent job
       ↓
job runner
       ↓
downloader
       ↓
validation/finalization
       ↓
post-processing
       ↓
library / lyrics / rmpc
```

### Downloader

`downloader.py` is responsible for transport only.

Its responsibilities include:

* HTTPS transport
* streaming
* timeout handling
* ordinary HTTP error handling
* retry handling
* temporary `.part` files
* resumable transfers where supported
* size validation
* checksum validation
* progress reporting
* atomic finalization
* failure cleanup

It must not perform:

* catalogue searching
* resource discovery
* local/API matching
* lyrics embedding
* rmpc configuration

### Persistent jobs

`jobs.py` provides persistent acquisition state.

Jobs are JSON-backed under the XDG data directory and are written atomically.

Job state includes the selected `AcquisitionItem` and per-item state/progress/error information.

Interrupted transient states can be recovered without losing successful completed items.

### Duplicate detection

Duplicate detection prefers:

1. SHA-256 identity when available
2. consistent destination
3. normalized title/version matching

Interrupted `.part` files are not treated as completed resources.

Different explicit versions, such as v1 and v2, must not automatically be considered duplicates.

## CLI layer

Responsibilities:

* parse arguments
* choose commands
* call services
* render friendly output
* collect explicit user confirmation where needed

Normal user commands should be easy to remember.

The product and primary executable are named `999`. The legacy
`juice-lyrics` console script resolves to the same `juice_lyrics.cli:main`
function. The import namespace remains `juice_lyrics`, and persisted XDG paths
remain under `juice-lyrics`; branding must not create a second storage tree.

## UI layer

Long term, an interactive TUI can sit on top of the same services.

The TUI must not contain business logic itself.

Both CLI and TUI should reuse the same API, acquisition, library, and lyrics services.

## Important existing behaviors to preserve

* explicit version matching
* known aliases
* duration matching
* SYLT first / USLT fallback
* rmpc `.lrc` generation only for synced lyrics
* backups before MP3, FLAC, or M4A metadata changes
* verification after writes
* incremental sync

## Acquisition → library integration

Acquisition owns transport and persistent job state.

After a successfully acquired MP3 is written, the optional post-processing hook passes the file through the existing lyrics engine.

For MP3, synced lyrics become ID3 SYLT and a same-basename `.lrc` beside the audio.

MP3 plain lyrics become ID3 USLT. FLAC embeds standard plain-text Vorbis
`LYRICS`; synchronized timing remains in the adjacent `.lrc` because Vorbis
comments have no interoperable equivalent to ID3 SYLT. M4A embeds standard
plain-text MP4 `©lyr`; its synchronized timing likewise remains in the adjacent
`.lrc`. No audio format is converted.

Acquisition post-processing remains MP3-only. Native FLAC and M4A support
applies to existing local-library files.

Post-processing errors fail the individual job item and are persisted.
