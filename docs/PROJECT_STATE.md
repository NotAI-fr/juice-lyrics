# 999 project state

This is the canonical detailed handoff for the current application. One-button
Sync, manual catalogue locking, snapshot-backed Library Issues, read-only
duplicate review, and safe metadata repair are integrated. Read the
code and tests if a later working tree disagrees with this document.

## Current release: 2.0.0b2

`main` is the current product line. Published beta `v2.0.0b2` includes
**Search Lyrics**, promoted from the accepted `feature/lyrics-search`
development branch. That branch may remain temporarily for history/reference.
The previous beta `v2.0.0b1` remains an immutable, published fallback.

In Library, `f` opens **Search Lyrics**. Typing updates one logical result per
track; arrows navigate, Enter opens that track's Library details, and Escape
returns. Results include the first useful matching line, nearby context, a
compact hit count, and the real timestamp when the chosen representation is
timed.

Search reads the existing MP3 ID3 USLT/SYLT, FLAC Vorbis `LYRICS`, M4A `©lyr`,
and authoritative adjacent-LRC sources through the shared lyric readers and LRC
parser. Matching is substring/phrase based after case, whitespace, apostrophe,
and ordinary punctuation normalization; it is deliberately not fuzzy or
semantic. Equivalent embedded and sidecar lines produce one track result, with
the adjacent LRC representation preferred so timing is retained.

The rebuildable `lyrics-search-index-v1.json` lives under the existing XDG
cache namespace, never in authoritative state. It is built lazily on first
search from the current Library snapshot. Audio and sidecar replacement-aware
fingerprints reuse unchanged entries, re-read only new or changed tracks,
invalidate a track after either audio or LRC changes, and discard removed
paths. Corrupt, incompatible, or other-library cache data rebuilds safely.
Each query runs only against the loaded in-memory index and performs no media
read, scan, Sync, catalogue/API request, download, or mutation.

Lyrics Search has no CLI command; it is available in the TUI and through the
shared search service. It is included in `v2.0.0b2` and is not part of the
previous `v2.0.0b1` fallback.

## Repository checkpoint

- Repository: the current `juice-lyrics` checkout
- Active product branch: `main`.
- Accepted Lyrics Search history: `feature/lyrics-search` remains available
  temporarily as a reference branch.
- Previous stable tag: `v1.4.0-backend-complete`
- Product/primary executable: `999`
- Compatibility executable: `juice-lyrics`
- Python package: `juice_lyrics`
- Distribution: `juice-wrld-lyrics`
- XDG storage namespace: `juice-lyrics`
- Current recommended beta: `2.0.0b2`, annotated tag `v2.0.0b2` on the
  accepted `main` release commit, published as a GitHub pre-release.
- Previous immutable fallback: `2.0.0b1`, annotated tag `v2.0.0b1`, release
  commit `1d56661`, published as a GitHub pre-release on 2026-09-25.
- Public-launch preparation on 2026-09-26 audited the current tree and all
  reachable Git history for credential signatures, private URLs, host-specific
  paths, application data, media, and generated artifacts. No credential,
  private state/config, personal media, backup, cache, or hidden large blob was
  found. Host-specific paths were removed from the current tree; historical
  author metadata and former local-path references remain in the released
  history and were not rewritten. The public-facing README, screenshot plan,
  ignore rules, issue form, and `main` CI trigger were prepared. Repository
  visibility remains private pending an explicit user action.
- One-button Sync baseline: `31ebaf2` (410 tests plus 14 isolated recovery
  smoke tests, compileall, and `git diff --check`).
- Manual identity-lock milestone verification: 424 full-suite tests and 34
  explicit temporary-HOME/XDG identity/state smoke tests passed; compileall and
  `git diff --check` passed.
- Library Issues milestone verification: 435 full-suite tests and 30 explicit
  temporary-HOME/XDG Issues/Sync/identity smoke tests passed; compileall and
  `git diff --check` passed.
- Duplicate detector milestone verification: 453 full-suite tests and 45
  explicit temporary-HOME/XDG duplicate/status/Sync smoke tests passed;
  compileall and `git diff --check` passed.
- Metadata audit/preview milestone verification: 470 full-suite tests and 50
  explicit temporary-HOME/XDG metadata/status/identity/Sync smoke tests passed;
  compileall and `git diff --check` passed.
- Metadata safe-apply foundation verification: 486 full-suite tests, 158
  affected regression tests, and 51 explicit temporary-HOME/XDG
  repair/audit/identity/Sync smoke tests passed; compileall and
  `git diff --check` passed.
- Metadata safe-TUI-apply verification: 492 full-suite tests, 156 affected
  regression tests, and 51 explicit temporary-HOME/XDG
  repair/audit/identity/Sync smoke tests passed; compileall and
  `git diff --check` passed.
- Metadata real-copy acceptance used isolated copies of representative MP3,
  FLAC, and M4A files with embedded lyrics/artwork/unrelated tags and adjacent
  sidecars. Three repairs plus an injected post-replacement state-write
  rollback passed without changing the originals. The audit found and fixed
  ID3v1 false rejection/comment loss and same-second backup-directory reuse.
  Post-fix verification: 81 affected tests, 33 final targeted tests, and 494
  full-suite tests passed; compileall and `git diff --check` passed.
- Missing Library milestone verification: 108 focused catalogue/queue/Library
  tests, 502 full-suite tests, and 35 explicit temporary-HOME/XDG
  snapshot/Sync smoke tests passed; compileall and `git diff --check` passed.
- Doctor milestone verification: 47 focused CLI/diagnostic/state/cache/rmpc/
  backup tests, 510 full-suite tests, and 24 explicit temporary-HOME/XDG
  diagnostic/settings smoke tests passed; compileall and `git diff --check`
  passed.
- Shell-completion milestone verification: 20 focused completion/identity
  tests passed (one Fish syntax check skipped because Fish was not installed),
  523 full-suite tests passed with the same skip, and an explicit temporary-
  HOME/XDG generation smoke created no application directories. Bash and Zsh
  syntax checks, compileall, and `git diff --check` passed.
- Final performance/reliability acceptance: 276 broad workflow tests and 29
  focused repair/Sync/lock/Issues regressions passed; the final suite passed
  527 tests with one Fish-environment skip. All pytest paths used the guarded
  temporary HOME/XDG environment; compileall and `git diff --check` passed.
- Packaging and clean-install acceptance: 34 focused packaging/identity/
  doctor/completion tests passed with one Fish-environment skip; the full suite
  passed 533 tests with the same skip. Fresh wheel and sdist installs outside
  the checkout passed imports, both console scripts, help/version/Doctor,
  completion generation, TUI launch/exit, reinstall, uninstall, and reinstall
  checks. Their temporary application HOME/XDG roots remained untouched.
- GitHub/beta-readiness preparation selected `2.0.0b1`, consolidated the
  changelog, added a synthetic-data TUI preview and explicit release checklist,
  and kept `main` as the stable v1.4 default branch. The isolated build produced
  correctly versioned wheel/sdist artifacts; 34 focused tests passed with one
  Fish-environment skip and the full suite passed 533 tests with the same skip.
  GitHub's Ubuntu 24.04 matrix also passed the full checks on Python 3.11 and
  3.14. Publishing, tagging, and merging remain deliberately undone pending
  manual acceptance.
- A focused beta acceptance pass on 2026-09-23 used only temporary HOME/XDG
  roots, generated media fixtures, and an isolated live queue. It fixed
  `acquire search --refresh` incorrectly forwarding refresh as `page=True`.
  The focused pass completed 256 tests; the post-fix suite completed 534 tests
  with the expected missing-Fish skip. Fresh wheel/sdist installs, command and
  completion smoke checks, compileall, and diff hygiene passed. Before/after
  manifests proved the real music, config, state/backups/queue, and cache were
  unchanged. Live Bandit returned `94107`; live 10 Feet remained manual after
  two HTTP 530 responses. Detailed evidence and the remaining human checks are
  recorded in `docs/BETA_RELEASE_CHECKLIST.md`.
- A read-only real-library correctness audit on 2026-09-24 started from clean
  `v2-redesign` at `b3e740a`. The first stable snapshot found 187 readable
  tracks; concurrent external activity added eight MP3s during the later test
  run, so a
  final stable read-only snapshot found 195 (83 MP3, 43 FLAC, 69 M4A), with no
  scan/container/required-metadata failures, 141 fully covered tracks, ten
  local lyric follow-ups, 76 catalogue-Unknown tracks, 40 new state paths, and
  34 changed state paths. No pre-existing music entry changed. The old UI
  rendered all 76 combined follow-up rows as `!`, which misleadingly made
  conservative Unknown identity and stale state look like
  damaged media. The Library now separates follow-ups, genuine errors, lyrics
  to improve, full coverage, and Unknown identity; `!` is error-only and `~`
  marks a non-error follow-up. Sync summaries say what was recorded/refreshed,
  what remains Unknown, and whether catalogue checks failed. New/changed
  Unknown rows correctly recommend Sync before manual matching. A provider-
  wide 503/530, Cloudflare tunnel, DNS, or invalid-JSON failure now stops the
  current backfill pass instead of making one doomed request per track, while
  preserving every established identity and keeping the local snapshot usable.
  Before/after manifests proved each diagnostic was read-only and that config,
  data/state/backups/queue, and cache were unchanged. Focused verification
  passed 141 tests; the full suite passed 540 with the expected missing-Fish
  skip, followed by compileall and diff hygiene.
- Final automated release-candidate acceptance on 2026-09-25 started from
  clean `db1ef2c`. A small live pass confirmed catalogue pagination/details,
  Bandit `94107`, 10 Feet `94102`, one isolated completed download, and an
  actual isolated Sync that matched Bandit, retained an ambiguous Unknown,
  preserved manual locks, avoided repeat work, reported a changed path, and
  produced zero genuine health errors. The integrated Library/Browse/download/
  repair/backup/TUI/Doctor pass completed 385 tests. Representative real MP3,
  FLAC, and M4A copies preserved encoded audio, artwork, lyrics, unrelated
  tags, sidecars, and locks through metadata apply plus exact restore; the
  originals remained byte/stat identical. Wheel and sdist clean installs,
  command/completion checks, and wheel lifecycle passed outside the checkout;
  34 packaging/completion tests passed with the expected missing-Fish skip.
  The support report passed a forbidden-value privacy audit, GitHub Verify for
  `db1ef2c` was green, and before/after manifests proved real music and all real
  application XDG data were unchanged. No functional release blocker was
  demonstrated. Remaining limitations are manual visual polish, absent Fish
  runtime acceptance, no independent second-machine tester, and optional live
  rmpc notification acceptance. Detailed evidence and classification are in
  `docs/BETA_RELEASE_CHECKLIST.md`.

Test totals are checkpoint evidence, not a permanent promise. Run the current
suite before reporting a later code milestone.

## Product experience

The main download journey remains:

```text
Browse → Add → Downloads → Download queue → Done
```

Browse supports catalogue filters, pagination, details, stable-ID multi-select,
and immediate queue addition. Adding never starts a download. Downloads exposes
individual download/retry plus a confirmed whole-queue action while keeping
durable acquisition-job IDs out of the normal UI.

Library is the maintenance centre. The primary routine action is:

```text
s → Sync Library
a → Issues
d → Duplicates
g → Missing Library
e → Metadata repair preview for the selected track
```

`?` opens the complete scrollable key guide globally. Common actions remain in
screen shortcut lines. Harmless actions are immediate; high-impact operations
use a cancel-first confirmation where `y` executes immediately, `n`/Escape
cancels, and initial Enter cancels.

## One-button Library Sync

Sync Library runs in a background worker and cannot be started twice
concurrently. It uses persisted filesystem fingerprints and the current scan to
classify library-relative MP3, FLAC, and M4A paths as:

- **unchanged** — same path, size, and nanosecond mtime; reuse safe snapshot and
  identity information and avoid redundant hashes, metadata reads, and writes;
- **new** — newly discovered current-library audio;
- **changed** — filesystem evidence changed; reread metadata and do not trust a
  stale identity merely because the relative path is the same;
- **removed** — previously active path no longer exists in the current scan.

New, changed, and currently Unknown tracks are offered to the shared
conservative catalogue matcher. Confident identities are persisted; ambiguous
or empty-result tracks remain Unknown. Normal cache expiry governs retries, so
Sync does not force every catalogue request on every run. One failed lookup does
not prevent other confident matches from being saved. A broad/offline failure
leaves local health useful and does not wipe established identities.

Removed tracks are retired with current-library bookkeeping rather than having
their historical/custom state records destructively deleted. Clearly stale
external records remain the responsibility of explicit state cleanup.

Sync refreshes displayed local lyric health but does **not** edit audio,
embedded lyrics, sidecars, audio backups, queue/history, or rmpc configuration.
It does not download music. Optional rmpc absence/failure is not a Library Sync
failure.

## Library health and maintenance

Catalogue identity and local lyric health are separate axes. A locally covered
track may be catalogue Unknown without needing lyric attention. An adjacent `.lrc`
counts as synchronized only when it contains genuine timestamped lyric lines.

The Library headline reports total tracks, follow-up rows, genuine errors,
local lyrics to improve, and catalogue-Unknown tracks separately. Warning rows
use `~`; `!` is reserved for errors. `a`
opens **Issues** immediately from the current snapshot: opening it performs no
scan, hash, or API request. There is at most one row per track, combining
catalogue, lyrics, verification, metadata, and state reasons. Unknown identities
appear because they may need a manual decision even when local lyrics are fully
covered. Valid file-bound manual locks stay out; an unavailable locked choice
appears after a catalogue-backed operation observes that failure, without
replacing the choice. Retired history stays out because it requires no routine
action.

Issue details reuse only existing safe actions: manual catalogue match,
selected lyric-refresh preview, read-only verification, or Sync Library. Every
completed Sync replaces the displayed snapshot, so resolved rows disappear and
newly discovered problems appear immediately.

## Duplicate review

`d` opens **Duplicates** immediately from the current Library snapshot. It does
not rescan, rehash, call the catalogue API, or mutate files/state merely to
render the view. Exact groups share the same saved whole-file SHA-256. Probable
groups require compatible recording-version evidence and either the same
catalogue identity or compatible title, artist, and known duration metadata.

The detail panel explains the evidence and lists every library-relative path.
Numbered versions and named variants such as live, remix, recording session,
extended, TV mix, acoustic, demo, instrumental, and stems remain distinct.
Detection is review-only: it never deletes, merges, moves, retags, or replaces
audio. Because the view deliberately reuses current snapshot data, running Sync
first provides the freshest paths, metadata, identities, and saved hashes.

## Missing Library

`g` opens **Missing Library** from the current Library snapshot. Catalogue
pages load in a background worker through the existing TTL cache and pagination
service. Ownership is determined only by exact confirmed `song_id` values,
including valid manual locks; titles are never used as ownership evidence.
Duplicate titles and released, live, remix, session, demo, extended, TV mix,
and numbered-version records therefore remain distinct.

The view separately reports confirmed missing recordings, local Unknown tracks,
and catalogue coverage. A page/network failure produces **Partial** or
**Unavailable** coverage rather than a falsely complete list. `/` filters the
already-loaded records without rescanning or another API search. `a` sends the
selected exact recording through the existing queue planner and durable queue;
it never starts a download. Opening/filtering the view does not modify audio,
state, lyrics, sidecars, backups, or rmpc configuration.

## Metadata repair audit and safe apply

`e` prepares a metadata repair review for the selected MP3, FLAC, or M4A in a
background worker. Metadata Issues also expose the same action. The
service reads the exact supported local tags and only the already-confirmed
catalogue ID; Unknown identities short-circuit without guessing or making a
catalogue request. Repeated preview in the same unchanged snapshot reuses its
result.

Supported proposal fields are title, artist, album, and track number. A missing
local field with explicit trustworthy catalogue evidence is **Confident**. Any
different non-empty local value is **Review** and is not treated as an automatic
replacement. Recording/version markers remain significant, including live,
remix, session, extended, TV mix, and numbered versions. Missing catalogue
fields produce no proposal. Album inference from an API path is limited to a
normal released record; track number requires an explicit API value.

The review checks that the local file fingerprint did not change while it was
read and displays before/after evidence, identity provenance, format, and path.
It separates Confident missing-field proposals from Review differences. No
field is selected by default. Space/Enter toggles the current field; `a` moves
to a confirmation listing the exact changes and backup behavior. Cancel has
initial focus, initial Enter cancels, and duplicate submission is guarded.

The backend safe-apply foundation is implemented in `metadata_repair.py` for
MP3, FLAC, and M4A. Planning accepts only an explicit subset of proposals from
the reviewed audit. Execution additionally requires explicit confirmation. It
pins the current path, whole-file hash/fingerprint, state bytes, catalogue ID,
encoded media payload, unrelated tags/artwork/lyrics, and adjacent sidecar.

Execution creates and manifests a normal backup before modifying a
same-filesystem temporary copy. It writes only the selected format-native tags,
fsyncs, reopens, and verifies the copy before atomic replacement. It then
updates the existing state entry's hash without discarding custom or lyric
fields. State conflict/failure restores the original audio; interruption paths
before/after media and state replacement are covered. A valid manual lock is
preserved and rebound only after the controlled edit verifies successfully.

Confirmed execution runs in a background worker and reuses the backend without
duplicating tag logic. Success reports the backup path, clears cached audit
evidence, and refreshes the Library snapshot, health, and Issues. Safe failure
reports preserved/restored data; rollback failure is surfaced as needing
recovery with the backup retained. Opening, selecting, cancelling, and planning
remain non-mutating.

Repository tests use comprehensive generated MP3, FLAC, and M4A containers and
verify preservation of encoded audio, artwork, embedded lyrics, custom tags,
and sidecars through success and failure paths. A focused beta audit also ran
the same transaction against temporary copies of three representative real
files. It verified their encoded payloads, lyrics, artwork, unrelated tags,
sidecars, recoverable backups, state hashes, and manual locks, plus rollback
after an injected state-write failure. Source hashes, sizes, and mtimes remained
unchanged.

That audit exposed two production issues which are now regression-covered:
selected MP3 fields may legitimately change in both ID3v2 and ID3v1 while
unselected ID3v1 year/comment/genre fields must be explicitly preserved; and
rapid independent repairs must receive unique suffixed backup roots rather
than sharing a second-resolution directory.

- MP3 full coverage uses the existing format-aware ID3 requirements plus its
  synchronized sidecar behavior.
- FLAC full coverage requires supported embedded plain lyrics and a valid timed
  adjacent `.lrc`; MP3 SYLT is not required.
- M4A full coverage requires supported embedded plain lyrics and a valid timed
  adjacent `.lrc`; MP3 SYLT is not required.

`m` previews lyric maintenance without mutation, then requires explicit
confirmation before applying the shared sync/backup/verification pipeline.
`v` verifies read-only. Track details, selected lyric refresh, backup browsing
and confirmed restore, rmpc verify/explicit setup, identity rebuild, and stale
state cleanup remain available as contextual or advanced operations.

## Catalogue identity and matcher

Normal discovery does not depend on historical state: unknown MP3, FLAC, and
M4A tracks can be identified through the shared backfill/matcher path. Only a
confident `song_id` and `api_name` are merged; lyric state is never fabricated.
Known compatible persisted identities are reused until file-change evidence
invalidates them.

Matching remains conservative and uses normalized titles/collaboration credits,
artist evidence, meaningful version/named-variant penalties, category evidence,
album/API-path evidence, duration tolerance, a narrow released-album duration
grace, a confidence threshold, and an ambiguity margin. Key live-shaped
regressions are:

```text
Bandit  → song_id 94107
10 Feet → song_id 94102
```

A wrong confident result is worse than Unknown. Do not weaken safeguards merely
to reduce the Unknown count.

## Manual catalogue identity

Select any Library track and press `c` to open **Match manually**. The
background catalogue search starts with the local title; `/` focuses a small
refinement field, arrows choose a candidate, Enter saves it, and Escape
cancels. Candidate rows show title, category, era, duration, and catalogue ID
so released/session/version variants remain distinguishable.

A saved choice adds `identity_source = "manual"` and `identity_locked =
true` alongside the existing `song_id`, `api_name`, and current audio
SHA-256. Missing fields in historical state continue to mean
automatic/unlocked. The lock is visible only in track details and survives
restart, normal Sync, backfill, cache refresh, local refresh, and ordinary
identity rebuild. Lyric maintenance also uses the exact locked catalogue ID and
refuses to substitute a different candidate.

Locks are bound to the scanned audio fingerprint/hash. Changed or replaced
audio does not inherit the old lock. Press `u` to unlock: because the existing
automatic pipeline reuses any valid identity, unlock deliberately clears only
the catalogue identity/provenance fields and leaves lyrics, history, and custom
state untouched. It does not immediately search; a later Sync may identify the
track automatically.

Ordinary full identity rebuild preserves valid manual locks. The technical CLI
`999 state rebuild-identities --include-locked --yes` explicitly opts into
reconsidering them.

Full identity rebuild is an explicit recovery transaction. Preview is
non-mutating; apply rematches current files in memory, preserves non-identity
state, creates a complete state backup, audits changed IDs, and atomically
replaces state. A provider-wide outage aborts rather than erasing identities.

Explicit stale-state cleanup previews first, makes a state backup, and
atomically removes only clearly stale nonexistent external records. Historical
relative paths and uncertain legacy duplicates are deliberately preserved.

## Media, lyrics, backups, and rmpc

- MP3, FLAC, and M4A are recursively discovered case-insensitively.
- MP3 retains ID3 USLT/SYLT behavior.
- FLAC stores plain lyrics in standard Vorbis `LYRICS`.
- M4A stores plain lyrics in standard MP4 `©lyr`.
- Synchronized external lyrics always use the exact adjacent same-basename
  `.lrc`; no format conversion or centralized lyrics output occurs.
- Media metadata mutation is preceded by backup and followed by verification;
  failure restores the original. Backup retention keeps the newest 10 valid
  backups, and historical manifests remain readable.
- rmpc receives the actual adjacent sidecar path. Normal startup, status,
  refresh, and Sync never rewrite rmpc configuration; setup is explicit.

## State and filesystem safety

State/LRC writes are atomic. State updates retain conflict protection so an
operation does not silently overwrite a concurrently changed state file.
Restore uses safe replacement/rollback semantics. Tests install isolated HOME
and XDG paths before application imports and guard against the real home.

Never run automated library work against the user's real music directory or
real config, state, backups, queue, sidecars, or rmpc configuration.

## Doctor diagnostics

`999 doctor` is a bounded, read-only diagnostic command. It emits `PASS`,
`WARN`, and `FAIL` checks for the installed command/Python/package version,
Mutagen, configuration validity, state shape, a capped cache JSON sample,
music-directory readability and MP3/FLAC/M4A filename counts, one one-record
catalogue request, valid backup count/free storage, and optional rmpc setup.
Offline catalogue access is a warning because local features remain usable;
an invalid catalogue response is a failure.

Doctor does not hash or parse every audio file, enumerate the full catalogue,
run Library Sync, invoke rmpc/MPD, download anything, or write application
paths. `--support-report` prints sanitized JSON and `--save-report PATH`
deliberately writes it. The report excludes song lists and state contents and
redacts home paths and common credential forms by default.

## Shell completion

`999 completion bash`, `999 completion zsh`, and `999 completion fish`
generate shell-native completion from the same argparse tree used by the CLI.
Current top-level commands, nested actions, option names, fixed choices, and
path-valued options are therefore covered without maintaining separate static
command lists. The scripts bind both `999` and the legacy `juice-lyrics` name.

Completion generation exits before settings are loaded. It does not read or
write application state, access the catalogue, scan music, or alter the normal
CLI startup path. Users deliberately redirect the generated output into their
shell's completion directory and regenerate it after CLI upgrades.

## Packaging and clean installation

The installable distribution remains `juice-wrld-lyrics`; its primary console
script is `999`, the `juice-lyrics` console script remains a compatibility
alias, and the import/XDG namespaces remain `juice_lyrics` and `juice-lyrics`.
The package version has one code authority (`juice_lyrics.__version__`) and is
resolved dynamically into wheel/sdist metadata. Current version `2.0.0b2` is
published from `main` at tag `v2.0.0b2`; `2.0.0b1` remains the immutable
fallback at tag `v2.0.0b1`.

`python -m build` produces a platform-independent wheel and a source
distribution containing the runtime Python packages, README, license, and
build metadata. Repository-only tests, detailed handoff documents, caches, and
generated bytecode are excluded. Runtime UI styling and completion templates
are Python resources, so there are no separate package-data files or checkout
paths required after installation.

The recommended beta pipx install uses the immutable `v2.0.0b2` Git tag; the
previous `v2.0.0b1` tag remains available as fallback. Repeat either command
with `--force` to switch an installed snapshot. Editable installation is a
development workflow only. Installing or uninstalling the distribution does
not rename or intentionally delete existing `juice-lyrics` XDG user data.

Acceptance also corrected Doctor's executable-location probe: an explicitly
invoked isolated `999`/`juice-lyrics` script is now reported instead of a stale
same-named command elsewhere on `PATH`. Bash and Zsh parsed installed generated
completion successfully. Fish generation passed deterministic coverage, but
the acceptance host does not have Fish installed for an external syntax pass.

## GitHub and beta readiness

The main README now recommends `2.0.0b2` by immutable tag, identifies
`v2.0.0b1` as the previous fallback, explains the major user-facing features,
and includes troubleshooting, uninstall, reporting, and screenshot guidance.
Its linked TUI image uses synthetic data and contains no real user information.

`docs/CHANGELOG.md` records both published beta releases. The executable release gate is
`docs/BETA_RELEASE_CHECKLIST.md`: it covers version/date consistency, clean
artifacts, isolated installs, manual media safety acceptance, privacy review,
release notes/checksums, and explicit stop conditions.

GitHub's default branch is `main`, which contains the accepted Lyrics Search
product and the `v2.0.0b2` release. Both beta releases are pre-releases with
their wheel, sdist, and `SHA256SUMS` attached. The `v2.0.0b1` tag and release
remain unchanged. The repository description/topics are populated, Issues are
enabled, and GitHub detects the MIT license. No package-index publication
occurred.

The public-facing README installs directly from immutable beta tags through
pipx, so users do not need to clone the repository. It includes the beta
status, supported formats, core workflows, safety model, Doctor, limitations,
reporting guidance, license, and disclaimer without duplicating detailed
manuals. A privacy-conscious bug-report form and a sanitized screenshot plan
are present.

## Final performance and reliability acceptance

The normal launch/navigation, Browse and queue, Library Sync, manual identity,
Issues, Duplicates, metadata repair, Missing Library, backup/restore, doctor,
and completion workflows have a combined focused acceptance pass. Catalogue,
filesystem, and UI work remains backgrounded where designed; the audit found
no reason to weaken matcher, downloader, backup, or state-conflict safeguards.

One measured Library refresh bottleneck was fixed. Previously, changing any
part of `state.json` invalidated cached status for every track, so one manual
match or metadata repair caused every unchanged audio file to be rehashed and
its metadata/lyrics rechecked. Snapshots now retain a canonical signature of
the resolved state entry that affects each track. A changed entry rechecks only
that track; a top-level or unrelated-entry change reuses safe unchanged track
results. File and sidecar fingerprints, whole-state conflict signatures, and
same-path replacement detection remain mandatory, so this does not trust stale
identity after an actual media change.

Cross-feature acceptance now explicitly covers verified MP3, FLAC, and M4A
metadata repairs followed by snapshot refresh and Sync. The updated whole-file
hash stays current, valid manual locks survive, catalogue search is skipped,
and stale State/Catalogue Issues do not remain after the controlled edit.

## Known limitations and risks

- Active download cancellation is not implemented.
- Acquisition/post-processing remains MP3-focused; FLAC/M4A support is for
  existing local-library files.
- Configuration editing remains primarily CLI-based.
- `cli.py` still contains a second equivalent `load_settings()` plus later
  service-adapter definitions that shadow older local `search_api`,
  `search_api_advanced`, and `get_song` implementations. This
  compatibility-era layering is maintenance debt; consolidate only with
  focused CLI/API tests.
- `tui/screens/placeholder.py` is still exported but no current screen uses it.
  Remove it only as a small tested code-cleanup change.
- The old `lyrics_dir` configuration is compatibility-only and does not migrate
  historical centralized files.
- Manual visual polish has not been exhaustively reviewed, Fish runtime
  validation was unavailable locally, independent second-machine pipx testing
  has not occurred, and optional rmpc live notification remains unverified.
  These are recorded non-blocking beta limitations. The isolated tagged-wheel
  install passed; a post-release pipx-from-tag attempt in a disposable HOME
  could not authenticate to the intentionally private repository.
- Metadata repair has safe TUI selection/apply integration and passed isolated
  real-copy acceptance for MP3, FLAC, and M4A. Wider beta use should remain
  conservative because tag combinations in the wild are unbounded.

## Roadmap

Product principle:

```text
common safe routine work → automatic/simple
ambiguous/destructive work → explicit user decision
```

Keep normal Library UX centered on **Sync Library** and **Issues**;
advanced repair/recovery must not overwhelm normal use.

1. Make the repository public only after the explicit final visibility action.
2. Collect beta feedback without weakening safety or conservative matching.
3. Prioritize demonstrated reliability and usability defects.

## Resume safely

```bash
cd /path/to/juice-lyrics
git switch main
git status --short
pytest -q
.venv/bin/999
```

Read `AGENTS.md` first, then this file, then the relevant architecture/user
document. Update this file after substantial milestones.
