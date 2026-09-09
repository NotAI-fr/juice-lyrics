import json
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest

from juice_lyrics.config.settings import Settings
from juice_lyrics.services.library_sync import (
    LibrarySyncDependencies,
    LibrarySyncOptions,
    MatchOutcome,
    SyncEventKind,
    SyncLyricType,
    execute_library_sync,
    execute_library_sync_preview,
    get_library_sync_preview,
    plan_library_sync,
)


def _candidate(kind="synced"):
    return {
        "id": 101,
        "name": "Track",
        "synced_lyrics": "[00:01.00] line" if kind == "synced" else "",
        "lyrics": "plain line" if kind == "plain" else "",
    }


def _dependencies(tmp_path, candidates=None):
    candidates = candidates or {}
    state = {"files": {}, "updated": None}
    saved = []
    backup_root = tmp_path / "backups" / "run"

    def scanner(settings):
        return sorted(Path(settings.music_dir).glob("*.mp3"))

    def searcher(settings, title, refresh=False):
        value = candidates.get(title)
        if isinstance(value, Exception):
            raise value
        return [] if value is None else [value]

    def matcher(settings, path, results, title):
        candidate = results[0] if results else None
        return candidate, 100.0 if candidate else 0.0, [], []

    def make_backup_root():
        backup_root.mkdir(parents=True, exist_ok=True)
        return backup_root

    def backup(path, root, base):
        destination = root / path.relative_to(base)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        return destination

    dependencies = LibrarySyncDependencies(
        scanner=scanner,
        searcher=searcher,
        matcher=matcher,
        search_title=lambda path: path.stem,
        lyric_parser=lambda raw: [("line", 1000)] if raw else [],
        backup_root_factory=make_backup_root,
        backup_writer=backup,
        restorer=lambda backup_path, path: shutil.copy2(backup_path, path),
        manifest_writer=lambda root, entries: (root / "manifest.json").write_text(json.dumps(entries)),
        state_loader=lambda: state,
        state_saver=lambda value: saved.append(json.loads(json.dumps(value))),
        hasher=lambda path: __import__("hashlib").sha256(path.read_bytes()).hexdigest(),
    )
    return dependencies, state, saved, backup_root


def _options(tmp_path, **kwargs):
    settings = Settings(music_dir=tmp_path)
    return LibrarySyncOptions.from_settings(settings, **kwargs)


def test_empty_library_and_existing_state_are_supported(tmp_path):
    deps, state, saved, _ = _dependencies(tmp_path)
    state["legacy"] = "preserved"
    plan = plan_library_sync(_options(tmp_path), dependencies=deps)
    result = execute_library_sync(plan, dependencies=deps)

    assert plan.total_files == 0
    assert result.updated_files == 0
    assert saved[0]["legacy"] == "preserved"


def test_completely_unchanged_library_is_not_backed_up_or_modified(tmp_path):
    path = tmp_path / "Track.mp3"
    path.write_bytes(b"current")
    deps, state, saved, backup_root = _dependencies(tmp_path, {"Track": _candidate()})
    state["files"]["Track.mp3"] = {"sha256": deps.hasher(path), "lyric_type": "USLT", "lrc": None}
    deps.verifier = lambda path: (True, "USLT")
    deps.embedder = lambda *args: (_ for _ in ()).throw(AssertionError("embed called"))

    plan = plan_library_sync(_options(tmp_path), dependencies=deps)
    result = execute_library_sync(plan, dependencies=deps)

    assert plan.unchanged_files == 1
    assert result.tracks[0].outcome is MatchOutcome.UNCHANGED
    assert not backup_root.exists()
    assert path.read_bytes() == b"current"


def test_historical_central_lrc_state_cannot_redirect_or_invalidate_sidecar(tmp_path):
    path = tmp_path / "Track.mp3"
    path.write_bytes(b"current")
    path.with_suffix(".lrc").write_text("[00:01.00] line\n", encoding="utf-8")
    deps, state, _, backup_root = _dependencies(tmp_path, {"Track": _candidate()})
    state["files"]["Track.mp3"] = {
        "sha256": deps.hasher(path),
        "lyric_type": "SYLT",
        "lrc": str(tmp_path / "old-central" / "Track.lrc"),
    }
    deps.verifier = lambda target: (True, "SYLT")

    plan = plan_library_sync(
        _options(tmp_path, rmpc_enabled=True),
        dependencies=deps,
    )

    assert plan.unchanged_files == 1
    assert not backup_root.exists()
    assert not (tmp_path / "old-central").exists()


@pytest.mark.parametrize(("kind", "lyric_type"), [("synced", SyncLyricType.SYNCED), ("plain", SyncLyricType.PLAIN)])
def test_new_synced_and_plain_files_are_backed_up_verified_and_saved(tmp_path, kind, lyric_type):
    path = tmp_path / "Track.mp3"
    original = b"original"
    path.write_bytes(original)
    deps, state, saved, backup_root = _dependencies(tmp_path, {"Track": _candidate(kind)})
    events = []

    def embed(target, synced, plain):
        assert (backup_root / "Track.mp3").read_bytes() == original
        target.write_bytes(b"modified")
        return lyric_type.value

    deps.embedder = embed
    deps.verifier = lambda target: (True, "verified")
    plan = plan_library_sync(_options(tmp_path), dependencies=deps, progress=events.append)
    result = execute_library_sync(plan, dependencies=deps, progress=events.append)

    assert result.updated_files == 1
    assert result.tracks[-1].lyric_type is lyric_type
    assert path.read_bytes() == b"modified"
    assert saved[0]["files"]["Track.mp3"]["lyric_type"] == lyric_type.value
    kinds = [event.kind for event in events]
    assert kinds.index(SyncEventKind.BACKUP_CREATED) < kinds.index(SyncEventKind.LYRICS_EMBEDDED)
    assert kinds.index(SyncEventKind.LYRICS_EMBEDDED) < kinds.index(SyncEventKind.VERIFICATION_SUCCEEDED)
    assert kinds.index(SyncEventKind.STATE_UPDATED) < kinds.index(SyncEventKind.TRACK_COMPLETED)


def test_unresolved_no_lyrics_and_analysis_failure_are_structured(tmp_path):
    for name in ("Unknown", "Empty", "Broken"):
        (tmp_path / f"{name}.mp3").write_bytes(name.encode())
    deps, _, _, _ = _dependencies(
        tmp_path,
        {"Empty": _candidate("none"), "Broken": RuntimeError("API unavailable")},
    )
    plan = plan_library_sync(_options(tmp_path), dependencies=deps)
    outcomes = {track.path.stem: track.outcome for track in plan.tracks}

    assert outcomes == {
        "Broken": MatchOutcome.FAILED,
        "Empty": MatchOutcome.NO_LYRICS,
        "Unknown": MatchOutcome.UNRESOLVED,
    }
    assert plan.unresolved_files == 1
    assert plan.no_lyrics_files == 1
    assert plan.analysis_failures == 1


def test_dry_run_and_refresh_are_non_mutating(tmp_path):
    path = tmp_path / "Track.mp3"
    path.write_bytes(b"original")
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({"files": {}}))
    before = state_file.read_bytes()
    calls = []
    deps, _, saved, backup_root = _dependencies(tmp_path, {"Track": _candidate()})
    deps.state_loader = lambda: (_ for _ in ()).throw(AssertionError("mutating loader called"))
    original_searcher = deps.searcher
    deps.searcher = lambda settings, title, refresh=False: calls.append(refresh) or original_searcher(settings, title, refresh=refresh)
    deps.embedder = lambda *args: (_ for _ in ()).throw(AssertionError("embed called"))
    deps.rmpc_notifier = lambda paths: (_ for _ in ()).throw(AssertionError("rmpc called"))
    options = _options(
        tmp_path,
        dry_run=True,
        refresh=True,
        rmpc_enabled=True,
        lyrics_dir=tmp_path / "lyrics",
        state_file=state_file,
    )

    plan = plan_library_sync(options, dependencies=deps)
    result = execute_library_sync(plan, dependencies=deps)

    assert calls == [True]
    assert result.updated_files == 0
    assert path.read_bytes() == b"original"
    assert state_file.read_bytes() == before
    assert saved == []
    assert not backup_root.exists()
    assert not (tmp_path / "lyrics").exists()


def test_frontend_preview_helper_is_dry_run_and_non_mutating(tmp_path):
    path = tmp_path / "Track.mp3"
    path.write_bytes(b"original")
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({"files": {}}), encoding="utf-8")
    deps, _, saved, backup_root = _dependencies(tmp_path, {"Track": _candidate()})
    deps.state_loader = lambda: (_ for _ in ()).throw(AssertionError("mutating state loader called"))
    deps.embedder = lambda *args: (_ for _ in ()).throw(AssertionError("embed called"))

    configured_lyrics = tmp_path / "central-lyrics"
    plan = get_library_sync_preview(
        Settings(music_dir=tmp_path, lyrics_dir=configured_lyrics),
        rmpc_enabled=True,
        state_file=state_file,
        dependencies=deps,
    )

    assert plan.options.dry_run is True
    assert plan.ready_files == 1
    assert plan.synced_files == 1
    assert plan.options.lyrics_dir is None
    assert plan.tracks[0].lrc_path == path.with_suffix(".lrc")
    assert saved == []
    assert path.read_bytes() == b"original"
    assert not backup_root.exists()
    assert not (tmp_path / "lyrics").exists()


def test_frontend_preview_can_scope_one_track_and_force_refresh(tmp_path):
    selected = tmp_path / "Selected.mp3"
    other = tmp_path / "Other.mp3"
    selected.write_bytes(b"selected")
    other.write_bytes(b"other")
    calls = []
    deps, _, _, _ = _dependencies(tmp_path, {"Selected": _candidate(), "Other": _candidate()})
    original_searcher = deps.searcher
    deps.searcher = lambda settings, title, refresh=False: calls.append((title, refresh)) or original_searcher(settings, title, refresh=refresh)

    plan = get_library_sync_preview(
        Settings(music_dir=tmp_path),
        rmpc_enabled=True,
        state_file=tmp_path / "missing-state.json",
        dependencies=deps,
        refresh=True,
        selected_paths=(selected,),
    )

    assert [track.path for track in plan.tracks] == [selected]
    assert calls == [("Selected", True)]


def test_frontend_preview_protects_locally_covered_unmatched_track(tmp_path):
    path = tmp_path / "Bandit.mp3"
    path.write_bytes(b"covered audio")
    path.with_suffix(".lrc").write_text("[00:05.77]Oh-oh\n", encoding="utf-8")
    deps, _, _, backup_root = _dependencies(tmp_path)
    deps.searcher = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("covered track was searched")
    )

    plan = get_library_sync_preview(
        Settings(music_dir=tmp_path),
        rmpc_enabled=True,
        state_file=tmp_path / "missing-state.json",
        dependencies=deps,
        protected_paths=(path,),
    )

    assert plan.unchanged_files == 1
    assert plan.tracks[0].outcome is MatchOutcome.UNCHANGED
    assert path.read_bytes() == b"covered audio"
    assert not backup_root.exists()


def test_explicit_refresh_of_unmatched_covered_track_preserves_existing_files(tmp_path):
    path = tmp_path / "Bandit.mp3"
    sidecar = path.with_suffix(".lrc")
    path.write_bytes(b"covered audio")
    sidecar.write_text("[00:05.77]Oh-oh\n", encoding="utf-8")
    deps, _, saved, backup_root = _dependencies(tmp_path)

    preview = get_library_sync_preview(
        Settings(music_dir=tmp_path),
        rmpc_enabled=True,
        state_file=tmp_path / "missing-state.json",
        dependencies=deps,
        refresh=True,
        selected_paths=(path,),
    )
    result = execute_library_sync_preview(preview, dependencies=deps)

    assert preview.tracks[0].outcome is MatchOutcome.UNRESOLVED
    assert result.updated_files == 0
    assert path.read_bytes() == b"covered audio"
    assert sidecar.read_text(encoding="utf-8") == "[00:05.77]Oh-oh\n"
    assert not backup_root.exists()
    assert saved


def test_current_synced_state_requires_a_parseable_timed_sidecar(tmp_path):
    path = tmp_path / "Track.mp3"
    path.write_bytes(b"current")
    path.with_suffix(".lrc").write_text("plain lyrics only\n", encoding="utf-8")
    deps, state, _, _ = _dependencies(tmp_path, {"Track": _candidate()})
    state["files"]["Track.mp3"] = {
        "sha256": deps.hasher(path),
        "lyric_type": "SYLT",
        "lrc": str(path.with_suffix(".lrc")),
    }
    deps.verifier = lambda target: (True, "SYLT")
    deps.lyric_parser = lambda raw: [("line", 1000)] if "[00:" in raw else []

    plan = plan_library_sync(_options(tmp_path, rmpc_enabled=True), dependencies=deps)

    assert plan.ready_files == 1
    assert plan.tracks[0].outcome is MatchOutcome.MATCHED


def test_reviewed_preview_executes_through_existing_sync_engine(tmp_path):
    path = tmp_path / "Track.mp3"
    path.write_bytes(b"original")
    deps, _, saved, backup_root = _dependencies(tmp_path, {"Track": _candidate("plain")})
    deps.embedder = lambda target, *_: target.write_bytes(b"updated") or "USLT"
    deps.verifier = lambda target: (True, "USLT")
    preview = get_library_sync_preview(
        Settings(music_dir=tmp_path),
        rmpc_enabled=False,
        state_file=tmp_path / "missing-state.json",
        dependencies=deps,
    )

    result = execute_library_sync_preview(preview, dependencies=deps)

    assert result.updated_files == 1
    assert path.read_bytes() == b"updated"
    assert (backup_root / "Track.mp3").read_bytes() == b"original"
    assert saved[0]["files"]["Track.mp3"]["lyric_type"] == "USLT"


def test_execution_boundary_rejects_unreviewed_live_plan(tmp_path):
    deps, _, _, _ = _dependencies(tmp_path)
    live = plan_library_sync(_options(tmp_path), dependencies=deps)
    with pytest.raises(ValueError, match="dry-run preview"):
        execute_library_sync_preview(live, dependencies=deps)


def test_no_rmpc_suppresses_lrc_and_notification_for_synced_track(tmp_path):
    path = tmp_path / "Track.mp3"
    path.write_bytes(b"original")
    deps, _, _, _ = _dependencies(tmp_path, {"Track": _candidate()})
    deps.embedder = lambda target, *_: target.write_bytes(b"modified") and "SYLT"
    deps.verifier = lambda target: (True, "verified")
    deps.lrc_writer = lambda *args: (_ for _ in ()).throw(AssertionError("LRC called"))
    deps.rmpc_notifier = lambda *args: (_ for _ in ()).throw(AssertionError("rmpc called"))

    result = execute_library_sync(
        plan_library_sync(_options(tmp_path, rmpc_enabled=False), dependencies=deps),
        dependencies=deps,
    )
    assert result.lrc_files_generated == 0
    assert result.rmpc_notifications == 0


def test_synced_generates_lrc_but_plain_never_does(tmp_path):
    synced = tmp_path / "Synced.mp3"
    plain = tmp_path / "Plain.mp3"
    synced.write_bytes(b"synced")
    plain.write_bytes(b"plain")
    deps, _, _, _ = _dependencies(tmp_path, {"Synced": _candidate("synced"), "Plain": _candidate("plain")})
    deps.embedder = lambda target, synced_lines, plain_text: "SYLT" if synced_lines else "USLT"
    deps.verifier = lambda target: (True, "verified")
    lrc_calls = []

    def write_lrc(path, synced_lines, candidate):
        lrc_calls.append(path)
        result = path.with_suffix(".lrc")
        result.write_text("lrc")
        return result

    deps.lrc_writer = write_lrc
    deps.rmpc_notifier = lambda paths: len(paths)
    configured_lyrics = tmp_path / "central-lyrics"
    options = LibrarySyncOptions.from_settings(
        Settings(music_dir=tmp_path, lyrics_dir=configured_lyrics),
        rmpc_enabled=True,
    )
    result = execute_library_sync(plan_library_sync(options, dependencies=deps), dependencies=deps)

    assert lrc_calls == [synced]
    assert synced.with_suffix(".lrc").is_file()
    assert not configured_lyrics.exists()
    assert result.lrc_files_generated == 1
    assert result.rmpc_notifications == 1


@pytest.mark.parametrize("mode", ["verification", "embed"])
def test_embedding_or_verification_failure_restores_original(tmp_path, mode):
    path = tmp_path / "Track.mp3"
    original = b"original bytes"
    path.write_bytes(original)
    deps, _, saved, _ = _dependencies(tmp_path, {"Track": _candidate("plain")})

    def embed(target, synced, plain):
        target.write_bytes(b"partial")
        if mode == "embed":
            raise RuntimeError("embed failed")
        return "USLT"

    deps.embedder = embed
    deps.verifier = lambda target: (False, "bad frame")
    result = execute_library_sync(plan_library_sync(_options(tmp_path), dependencies=deps), dependencies=deps)

    assert result.processing_failed_files == 1
    assert path.read_bytes() == original
    assert "Track.mp3" not in saved[0]["files"]


def test_restore_failure_is_structured_and_other_tracks_continue(tmp_path):
    bad = tmp_path / "Bad.mp3"
    good = tmp_path / "Good.mp3"
    bad.write_bytes(b"bad original")
    good.write_bytes(b"good original")
    deps, _, _, _ = _dependencies(tmp_path, {"Bad": _candidate("plain"), "Good": _candidate("plain")})

    def embed(target, synced, plain):
        target.write_bytes(b"modified")
        if target == bad:
            raise RuntimeError("embed failed")
        return "USLT"

    deps.embedder = embed
    deps.verifier = lambda target: (True, "verified")
    deps.restorer = lambda backup, target: (_ for _ in ()).throw(OSError("restore failed"))
    result = execute_library_sync(plan_library_sync(_options(tmp_path), dependencies=deps), dependencies=deps)

    assert result.updated_files == 1
    assert result.processing_failed_files == 1
    failure = next(track for track in result.tracks if track.path == bad)
    assert "restore failed" in (failure.error or "")
    assert good.read_bytes() == b"modified"


def test_cli_sync_delegates_and_preserves_empty_output(tmp_path, monkeypatch, capsys):
    import argparse
    import juice_lyrics.cli as cli

    deps, _, _, _ = _dependencies(tmp_path)
    plan = plan_library_sync(_options(tmp_path), dependencies=deps)
    monkeypatch.setattr(cli, "plan_library_sync", lambda options, progress=None: plan)
    monkeypatch.setattr(cli, "execute_library_sync", lambda service_plan, progress=None: execute_library_sync(service_plan, dependencies=deps))
    args = argparse.Namespace(no_rmpc=True, dry_run=False, refresh=False, yes=True)

    result = cli.command_sync(args, Settings(music_dir=tmp_path), False)
    output = capsys.readouterr().out

    assert result == 0
    assert "Library Sync" in output
    assert "Changed/new:     0" in output
    assert "Nothing needs updating." in output


def test_cli_sync_dry_run_reports_exact_sidecar_destination(tmp_path, monkeypatch, capsys):
    import argparse
    import juice_lyrics.cli as cli

    path = tmp_path / "Rental (v1).mp3"
    path.write_bytes(b"audio")
    deps, _, _, _ = _dependencies(tmp_path, {path.stem: _candidate()})
    plan = plan_library_sync(
        _options(tmp_path, dry_run=True, rmpc_enabled=True),
        dependencies=deps,
    )
    monkeypatch.setattr(cli, "plan_library_sync", lambda options, progress=None: plan)
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/bin/rmpc")
    monkeypatch.setattr(cli, "DEFAULT_RMPC_CONFIG", tmp_path / "rmpc.ron")
    cli.DEFAULT_RMPC_CONFIG.write_text("()", encoding="utf-8")

    result = cli.command_sync(
        argparse.Namespace(no_rmpc=False, dry_run=True, refresh=False, yes=False),
        Settings(music_dir=tmp_path),
        False,
    )

    assert result == 0
    assert f"  - {path.with_suffix('.lrc')}" in capsys.readouterr().out
    assert not path.with_suffix(".lrc").exists()
