# 999 beta release checklist

Target: `2.0.0b1` (PEP 440) / Git tag `v2.0.0b1`.

This checklist prepares a release; it does not authorize publishing, tagging,
or merging. `main` remains the stable v1.4 baseline until the beta is accepted.

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
- Before/after manifests confirmed no change to `/home/nobloat/Music` or the
  real `juice-lyrics` config, data (including state/backups/queue), or cache.

Remaining manual acceptance:

- Run the installed app in a normal terminal and judge Help, navigation,
  pagination/details, queue/Retry, confirmed temporary download, and quit.
- Retry live `10 Feet` identification and confirm `94102`; two requests in this
  pass received HTTP 530, while the deterministic matcher regression passed.
- Exercise the Library workflows below on user-approved disposable copies,
  including one representative MP3, FLAC, and M4A plus a visible restore.
- Review rmpc verify/setup separately, inspect a support report before sharing,
  preview README links/image on GitHub, decide repository visibility, and get
  an independent supported-Linux pipx install/upgrade report.

## 1. Repository and metadata

- [ ] `v2-redesign` is clean, pushed, and reviewed against `main`.
- [x] `juice_lyrics.__version__`, `999 --version`, wheel metadata, and the
      changelog all say `2.0.0b1`.
- [ ] The changelog heading has the actual release date instead of
      `Unreleased`.
- [ ] README installation commands point to the intended immutable tag or
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
- [ ] TUI launches and exits from both artifacts.
- [x] Bash/Zsh/Fish completion generation succeeds; syntax is checked where
      the shell is installed.
- [x] Force-reinstall, uninstall, and reinstall leave the commands and imports
      in the expected state without touching application XDG data.
- [ ] The GitHub `Verify` workflow passes on supported oldest/current Python
      versions for the release pull request.

## 3. GitHub presentation settings

- [x] Keep `main` as the default/stable branch until the beta pull request is
      approved; do not point normal users at an unreviewed branch.
- [x] Set the repository description to “999 — a cautious Juice WRLD library
      and lyrics TUI for Linux”.
- [x] Add concise topics such as `linux`, `python`, `tui`, `music-library`,
      `lyrics`, `mpd`, and `rmpc`.
- [x] Confirm Issues are enabled and the repository license is detected as MIT.
- [ ] Decide explicitly when the currently private repository should become
      public; do not change visibility as a side effect of release prep.
- [ ] Preview README links and the synthetic screenshot on GitHub before merge.

## 4. Manual beta acceptance

Use an explicit backup and a small temporary copy of representative media
before testing any mutating workflow.

- [ ] Launch, Help, navigation, Browse search/pagination/details, queue Add,
      Downloads, Retry, and confirmed Download queue work.
- [ ] Sync Library handles unchanged/new/changed/removed files and remains
      usable offline.
- [ ] Bandit identifies as `94107`; 10 Feet identifies as `94102`.
- [ ] Manual match/lock, unlock, Issues, Duplicates, and Missing Library behave
      as documented.
- [ ] One copied MP3, FLAC, and M4A completes metadata preview/apply with its
      audio payload, artwork, lyrics, unrelated tags, sidecar, backup, and lock
      verified.
- [ ] Restore succeeds from a generated backup and does not delete the backup.
- [ ] rmpc verify works when installed; explicit setup is reviewed separately.
- [ ] `999 doctor --support-report` is manually reviewed for privacy before it
      is attached to an issue.
- [ ] A beta tester confirms clean pipx install and upgrade on the supported
      Linux environment.

## 5. Release procedure — only after explicit approval

1. Open and review a pull request from `v2-redesign` into `main`.
2. Resolve acceptance findings on `v2-redesign`; rerun the checks above.
3. Update the changelog date and replace moving-branch install examples with
   `v2.0.0b1` release/tag instructions.
4. Merge without rewriting published history.
5. Create the annotated tag `v2.0.0b1` on the accepted merge commit.
6. Build artifacts from a clean checkout of that tag and record SHA-256 sums.
7. Create a GitHub **pre-release**, paste the changelog section, and attach the
   wheel, sdist, and checksum file.
8. Install once from the attached wheel and run `999 doctor` before announcing
   the beta.

Package-index publication is a separate explicit decision. Do not upload to
PyPI merely because GitHub artifacts exist.

## 6. Stop/rollback conditions

Do not release if tests fail, artifact versions disagree, generated packages
depend on the checkout, privacy review fails, or a mutating acceptance test
cannot prove backup and preservation behavior. Fix on `v2-redesign`; do not
move an existing tag. If a published beta is defective, document it and issue
a new prerelease version rather than replacing its artifacts silently.
