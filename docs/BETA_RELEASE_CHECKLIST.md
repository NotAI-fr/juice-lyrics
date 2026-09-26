# 999 beta release checklist

Target: `2.0.0b1` (PEP 440) / Git tag `v2.0.0b1`.

This checklist records the accepted candidate and completed release procedure.
The explicit release operation was authorized and completed on 2026-09-25.

## Release result — 2026-09-25

- PR #1 merged `v2-redesign` into `main` without deleting the source branch.
- Annotated tag `v2.0.0b1` points to release commit `1d56661`.
- The GitHub release is marked pre-release and includes the tagged wheel,
  sdist, and `SHA256SUMS`; downloaded assets re-verified locally.
- The tagged wheel passed a fresh isolated install, version/help/Doctor,
  Bash/Zsh/Fish completion generation, Bash/Zsh syntax, and TUI launch/quit.
- Repository visibility remains private by explicit decision. No PyPI or other
  package-index publication occurred.
- The post-release pipx-from-tag check in a disposable HOME could not
  authenticate to the private repository. The clean wheel install passed, and
  the independent second-machine pipx check remains a non-blocking limitation.

## Final automated release-candidate acceptance — 2026-09-25

This pass started from clean `v2-redesign` at `db1ef2c`, equal to
`origin/v2-redesign`. No production regression was found and no production
code changed.

Live and isolated acceptance results:

- A deliberately small live catalogue pass verified search, refresh parameter
  handling, two distinct five-item pages with correct next/previous metadata,
  and stable-ID details. The catalogue reported 2,741 records. Released Bandit
  resolved to `94107`; released 10 Feet resolved to `94102` without weakening
  matcher rules.
- A four-file disposable live-Sync library recorded two new paths, matched
  Bandit to `94107`, kept one deliberately ambiguous healthy MP3 Unknown, and
  preserved two file-bound manual locks. The exact summary was `2 new recorded
  · 1 newly matched · 1 catalogue unknown`. Repeat Sync changed neither state
  nor cache and reported local state up to date; a later mtime-only change was
  accurately reported as `1 changed refreshed`. All health rows were warning
  follow-ups (`~`), with zero genuine errors (`!`). Deterministic 503/530,
  malformed JSON, empty-result, and offline regressions remain green.
- One explicitly selected Bandit item was queued and downloaded to `/tmp`.
  The service streamed 8,392,557 bytes, finalized and postprocessed one MP3,
  persisted the complete queue result, left no `.part`, and a retry correctly
  performed no second download. Local-server regressions cover progress,
  resume, 503 retry, exhausted/404/403 failures, checksum/size/content
  rejection, and duplicate suppression.
- The integrated focused suite covered Sync, Library, Issues, manual lock and
  unlock, Duplicates, metadata preview/apply/cancel, Missing Library,
  backup/restore, Browse/Downloads, Help/navigation/quit, Doctor, and rmpc
  helpers: **385 passed**.
- Temporary copies of representative real MP3, FLAC, and M4A files completed
  metadata preview, confirmed apply, backup, and exact restore. Encoded media,
  artwork, embedded lyrics, unrelated tags, adjacent sidecars, and manual locks
  were preserved. Original file hashes, sizes, mtimes, and ctimes were unchanged.
- The isolated support report was valid JSON and an automated forbidden-value
  audit found no username, absolute home/acceptance path, token/credential,
  job ID, song title/list, or private state contents. Paths were redacted.
- Fresh wheel and sdist builds installed independently outside the checkout
  with no `PYTHONPATH`. Both provided `999` and `juice-lyrics` at `2.0.0b1`,
  help, Doctor, Bash/Zsh/Fish completion generation, and installed-package TUI
  startup. In both installed harnesses `q` set the app to stopped; the external
  Textual harness process itself still required a timeout during teardown.
  The wheel upgrade/no-op, uninstall, command removal, reinstall, and import
  lifecycle passed. Packaging/completion checks passed **34 tests** with the
  understood missing-Fish skip. Artifact SHA-256 values were recorded in the
  acceptance log; artifacts remain temporary and were not published.
- GitHub Verify for `db1ef2c` passed. `main` remains the private default branch;
  visibility, merge, tag, release, and publication were not changed.
- Before/after manifests matched exactly for the real music tree and real
  config, state/backups/queue, and cache. The global pipx installation was not
  replaced.

Release-blocker classification:

- **BLOCKER:** none demonstrated.
- **NON-BLOCKING BETA LIMITATION:** manual visual polish was not independently
  confirmed; Fish is unavailable for runtime syntax acceptance, although
  deterministic generation is green; no independent second-machine pipx
  tester was available.
- **OPTIONAL / POST-BETA:** rmpc and MPD executables are installed but no live
  rmpc TUI socket was available. The installed rmpc accepts the query target
  `activetab`, while the optional notification probe currently uses the older
  `active-tab` spelling, so live notification acceptance remains unverified.
  Explicit rmpc setup was not run and real player configuration was untouched.

Candidate verdict: **READY FOR 2.0.0b1 RELEASE**. Release procedure steps,
including date/link updates, visibility decision, merge, tag, and publishing,
still require explicit authorization.

## Real-library correctness evidence — 2026-09-24

This pass started from clean `v2-redesign` at `b3e740a`, equal to
`origin/v2-redesign`. The installed pipx commands were inspected only: `999`
and `juice-lyrics` both reported `2.0.0b1`; neither was replaced.

The real library diagnostic was strictly read-only and made no catalogue
requests. Before/after SHA-256 and filesystem-metadata manifests confirmed each
diagnostic made no changes to real music, config, data (including state,
backups, and queue), or cache. Concurrent external activity added eight MP3s
during the long test run; no pre-existing music entry changed, and the final read-only
snapshot was stable. Sanitized final aggregate findings:

- 195 readable tracks: 83 MP3, 43 FLAC, and 69 M4A; zero scan warnings,
  unreadable/damaged containers, missing required title/artist metadata,
  unavailable durations, or verification errors.
- 141 tracks were fully covered and 185 had no local lyric follow-up. The ten
  local lyric follow-ups were nine optional unmanaged embedded lyrics and one
  invalid existing LRC; none was evidence of damaged audio.
- 76 tracks had Unknown catalogue identity. State classified 121 current, 40
  new, 34 changed, and zero invalid tracks. All 76 Unknown checks were due;
  none was hidden by a retry TTL or an API-unavailable marker.
- The old UI produced 76 `!` rows even though every row was warning severity
  and there were zero genuine errors.
  It also replaced the Sync action on new/changed Unknown tracks with manual
  matching. Those misleading behaviors are fixed: warnings use `~`, `!` is
  error-only, the headline separates follow-ups/errors/local lyrics/Unknown
  identity, and new/changed rows retain the Sync action.
- Normal Sync can record the 74 new/changed paths and attempt 76 due Unknown
  identities when the catalogue is available. It does not repair the
  ten lyric/LRC conditions, modify media, or delete historical state. There
  were zero explicit safe stale-state cleanup candidates among 235 stored
  records.
- Offline/provider-wide 503, 530, Cloudflare tunnel, DNS, and invalid-JSON
  failures now stop repeated requests for the rest of that Sync pass. Local
  health remains available, pending/Unknown counts are reported, and trusted
  identities and state are not erased. Ambiguous or genuinely empty searches
  still remain conservatively Unknown and use the normal retry TTL.

Focused regressions passed **141 tests**. The one required post-change full
suite passed **540 tests with one understood skip** because Fish is not
installed. `compileall` and `git diff --check` passed.

Remaining human judgment is unchanged: visually assess the revised Library
labels/markers and keyboard flow in a normal terminal; perform an explicitly
approved temporary download; retry live 10 Feet when the provider is healthy;
review rmpc setup and a support report; preview GitHub presentation/privacy;
and obtain an independent supported-Linux pipx installation report.

## Focused acceptance evidence — 2026-09-23

Automation is appropriate for repository/version checks, guarded test suites,
isolated builds and installs, generated completion syntax, generated media
fixtures, read-only live catalogue requests, queue creation that does not run a
download, and before/after integrity manifests. Human involvement remains
required for visual/keyboard UX judgment, an actual explicitly approved
temporary download, GitHub rendering and privacy review, local rmpc setup,
support-report disclosure review, repository visibility, and an independent
pipx tester.

Verified in this pass:

- Starting point was clean `v2-redesign` at `55b4b4b`, equal to
  `origin/v2-redesign`. The existing pipx commands at
  `~/.local/share/pipx/venvs/juice-wrld-lyrics/bin/` were inspected only; both
  reported `999 2.0.0b1` and were not replaced.
- Live `999 search Bandit --refresh` returned the released recording as
  `94107`. A live isolated acquisition search and queue add created one pending
  job under `/tmp` and no media file. This exposed and fixed incorrect
  positional forwarding of acquisition `--refresh`, which had sent
  `page=True` and received HTTP 404.
- The isolated focused workflow pass covered Browse/Downloads, confirmed
  whole-queue control flow with non-network executors, Sync new/changed/
  unchanged/removed/offline behavior, manual locks, Issues, Duplicates,
  Missing Library, MP3/FLAC/M4A metadata repair, backup/restore, and the
  Bandit/10 Feet matcher regressions: **256 passed**.
- The post-fix full suite passed **534 tests with one understood skip** because
  Fish is not installed. `compileall` and `git diff --check` passed.
- Fresh wheel and sdist builds were inspected and installed independently
  outside the checkout. Both commands, help/version, Doctor, imports,
  Bash/Zsh/Fish completion generation, Bash/Zsh syntax, and wheel
  force-reinstall/uninstall/reinstall passed. Fish syntax and independent
  artifact `q` exit still need an installed Fish shell/manual terminal check.
- Both artifact TUIs visibly launched against empty temporary libraries. The
  automated suite covers normal launch/quit, but this pass's PTY harness could
  not reliably inject `q`; manual launch/navigation/exit remains below.
- The synthetic screenshot was visually inspected and searched for embedded
  sensitive strings; it contains only synthetic counts and `Music/Juice WRLD`.
  Artifact contents contain the license, README, metadata, and runtime modules
  with no tests, docs, caches, bytecode, secrets, or checkout paths.
- Before/after manifests confirmed no change to the real music directory or
  real `juice-lyrics` config, data (including state/backups/queue), or cache.

Subsequent final acceptance resolved the live `10 Feet`, temporary download,
Library workflow, representative MP3/FLAC/M4A copy, and support-report checks.
Remaining non-blocking limitations are exhaustive manual visual polish, Fish
runtime validation, optional live rmpc notification, GitHub-rendered README
preview, and an independent supported-Linux pipx install/upgrade report.

## 1. Repository and metadata

- [x] `v2-redesign` is clean, pushed, and reviewed against `main`.
- [x] `juice_lyrics.__version__`, `999 --version`, wheel metadata, and the
      changelog all say `2.0.0b1`.
- [x] The changelog heading has the actual release date instead of
      `Unreleased`.
- [x] README installation commands point to the intended immutable tag or
      attached wheel, not the moving development branch. Before any package-
      index publication, give its long description an immutable public image
      URL or omit the screenshot there.
- [x] The synthetic screenshot contains no username, home path, token, state,
      song list, or real-library data.
- [x] Distribution contents contain the license, README, metadata, and every
      runtime module, with no tests, caches, secrets, or checkout paths.

## 2. Automated release candidate checks

Run from a clean checkout with isolated build and application paths:

```bash
pytest -q
python -m compileall -q src
git diff --check
python -m build
```

- [x] Full test suite passes with only understood environment skips.
- [x] Wheel and sdist install independently in new environments outside the
      checkout, with no source tree on `PYTHONPATH`.
- [x] `999 --help`, `999 --version`, `juice-lyrics --version`, and
      `999 doctor` work from both artifacts.
- [x] TUI launches from both artifacts and `q` transitions each installed app
      to stopped; manual visual polish and the harness teardown limitation are
      documented above.
- [x] Bash/Zsh/Fish completion generation succeeds; syntax is checked where
      the shell is installed.
- [x] Force-reinstall, uninstall, and reinstall leave the commands and imports
      in the expected state without touching application XDG data.
- [x] The GitHub `Verify` workflow passes on supported oldest/current Python
      versions for the release pull request.

## 3. GitHub presentation settings

- [x] Keep `main` as the default/stable branch until the beta pull request is
      approved; do not point normal users at an unreviewed branch.
- [x] Set the repository description to “999 — a cautious Juice WRLD library
      and lyrics TUI for Linux”.
- [x] Add concise topics such as `linux`, `python`, `tui`, `music-library`,
      `lyrics`, `mpd`, and `rmpc`.
- [x] Confirm Issues are enabled and the repository license is detected as MIT.
- [x] Keep the repository private for this release; any later visibility
      change remains a separate explicit decision.
- [ ] Preview README links and the synthetic screenshot on GitHub before merge.

## 4. Beta acceptance

Use an explicit backup and a small temporary copy of representative media
before testing any mutating workflow.

- [x] Launch, Help, navigation, Browse search/pagination/details, queue Add,
      Downloads, Retry, and confirmed Download queue work.
- [x] Sync Library handles unchanged/new/changed/removed files and remains
      usable offline.
- [x] Bandit identifies as `94107`; 10 Feet identifies as `94102`.
- [x] Manual match/lock, unlock, Issues, Duplicates, and Missing Library behave
      as documented.
- [x] One copied MP3, FLAC, and M4A completes metadata preview/apply with its
      audio payload, artwork, lyrics, unrelated tags, sidecar, backup, and lock
      verified.
- [x] Restore succeeds from a generated backup and does not delete the backup.
- [ ] rmpc verify works when installed; explicit setup is reviewed separately.
- [x] `999 doctor --support-report` passes an automated forbidden-value privacy
      audit; review the particular report again before attaching it publicly.
- [ ] A beta tester confirms clean pipx install and upgrade on the supported
      Linux environment.

## 5. Release procedure — completed after explicit approval

- [x] Open and review a pull request from `v2-redesign` into `main`.
- [x] Resolve acceptance findings and verify the release-candidate checks.
- [x] Finalize the changelog date and immutable `v2.0.0b1` install links.
- [x] Merge without rewriting published history.
- [x] Create and push the annotated tag on the accepted merge commit.
- [x] Build clean tagged artifacts and verify their SHA-256 sums.
- [x] Create the GitHub **pre-release** with wheel, sdist, and checksum file.
- [x] Install the tagged wheel in isolation and run `999 doctor`.

Package-index publication is a separate explicit decision. Do not upload to
PyPI merely because GitHub artifacts exist.

## 6. Stop/rollback conditions

Do not release if tests fail, artifact versions disagree, generated packages
depend on the checkout, privacy review fails, or a mutating acceptance test
cannot prove backup and preservation behavior. Fix on a development branch; do not
move an existing tag. If a published beta is defective, document it and issue
a new prerelease version rather than replacing its artifacts silently.
