from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest

from juice_lyrics.acquisition import runner
from juice_lyrics.acquisition.integration import integrate_downloaded_mp3
from juice_lyrics.acquisition.jobs import JobStore
from juice_lyrics.acquisition.models import AcquisitionItem, AcquisitionResult, AcquisitionState
from juice_lyrics.config.settings import Settings


def _item(path: Path) -> AcquisitionItem:
    return AcquisitionItem(
        identifier="101",
        title="Rental",
        url="https://example.invalid/Rental.mp3",
        destination=path,
    )


def _song(*, synced=True, plain=True):
    return {
        "id": 101,
        "name": "Rental",
        "synced_lyrics": "[00:01.00] line" if synced else "",
        "lyrics": "plain line" if plain else "",
    }


def _isolated_backup(monkeypatch, tmp_path):
    import juice_lyrics.acquisition.integration as integration

    root = tmp_path / "backups" / "checkpoint"

    def make_root():
        root.mkdir(parents=True, exist_ok=True)
        return root

    monkeypatch.setattr(integration, "make_backup_root", make_root)
    return root


@pytest.mark.parametrize(
    ("song", "expected_type"),
    [(_song(synced=True, plain=True), "SYLT"), (_song(synced=False, plain=True), "USLT")],
)
def test_success_backs_up_pristine_file_then_retains_verified_modification(
    tmp_path, monkeypatch, song, expected_type
):
    import juice_lyrics.acquisition.integration as integration

    root = _isolated_backup(monkeypatch, tmp_path)
    path = tmp_path / "music" / "Rental.mp3"
    path.parent.mkdir()
    pristine = b"pristine finalized audio"
    path.write_bytes(pristine)
    events = []

    def embed(target, synced, plain):
        backup = root / "Rental.mp3"
        assert backup.read_bytes() == pristine
        events.append("embed")
        target.write_bytes(b"verified metadata audio")
        return expected_type

    monkeypatch.setattr(integration, "embed_lyrics", embed)
    monkeypatch.setattr(integration, "verify_file", lambda target: (True, "verified"))

    result = integrate_downloaded_mp3(
        _item(path),
        song_fetcher=lambda _: song,
        state={},
        notify_rmpc=False,
    )

    assert events == ["embed"]
    assert result.lyric_type == expected_type
    assert result.backup_path == root / "Rental.mp3"
    assert result.backup_path.read_bytes() == pristine
    assert path.read_bytes() == b"verified metadata audio"
    assert (root / "manifest.json").is_file()


def test_acquisition_writes_adjacent_lrc_and_ignores_legacy_setting(tmp_path, monkeypatch):
    import juice_lyrics.acquisition.integration as integration

    _isolated_backup(monkeypatch, tmp_path)
    music = tmp_path / "Music" / "Juice WRLD" / "Unreleased"
    configured_lyrics = tmp_path / "Music" / "lyrics"
    old_derived_lyrics = tmp_path / "Music" / "Juice WRLD" / "lyrics"
    path = music / "Rental.mp3"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"pristine")

    monkeypatch.setattr(integration, "embed_lyrics", lambda *args: "SYLT")
    monkeypatch.setattr(integration, "verify_file", lambda target: (True, "verified"))

    def write_lrc(target, synced, song):
        result = target.with_suffix(".lrc")
        result.write_text("[00:01.00] line\n", encoding="utf-8")
        return result

    monkeypatch.setattr(integration, "write_lrc", write_lrc)

    result = integrate_downloaded_mp3(
        _item(path),
        song_fetcher=lambda _: _song(synced=True, plain=True),
        settings=Settings(music_dir=music, lyrics_dir=configured_lyrics),
        state={},
        notify_rmpc=False,
    )

    assert result.lrc_path == path.with_suffix(".lrc")
    assert result.lrc_path.is_file()
    assert not configured_lyrics.exists()
    assert not old_derived_lyrics.exists()


@pytest.mark.parametrize("failure_kind", ["verification_failure", "embed_exception", "verify_exception"])
def test_lyric_processing_failure_restores_byte_identical_pristine_file(
    tmp_path, monkeypatch, failure_kind
):
    import juice_lyrics.acquisition.integration as integration

    _isolated_backup(monkeypatch, tmp_path)
    path = tmp_path / "Rental.mp3"
    pristine = b"pristine downloaded bytes"
    path.write_bytes(pristine)

    def embed(target, synced, plain):
        target.write_bytes(b"partially modified")
        if failure_kind == "embed_exception":
            raise RuntimeError("embed exploded")
        return "USLT"

    def verify(target):
        if failure_kind == "verify_exception":
            raise RuntimeError("verify exploded")
        return False, "bad frame"

    monkeypatch.setattr(integration, "embed_lyrics", embed)
    monkeypatch.setattr(integration, "verify_file", verify)

    with pytest.raises(RuntimeError, match="restored from backup"):
        integrate_downloaded_mp3(
            _item(path),
            song_fetcher=lambda _: _song(synced=False, plain=True),
            state={},
        )

    assert path.read_bytes() == pristine


def test_backup_failure_prevents_metadata_mutation(tmp_path, monkeypatch):
    import juice_lyrics.acquisition.integration as integration

    path = tmp_path / "Rental.mp3"
    pristine = b"pristine"
    path.write_bytes(pristine)
    embedded = []
    monkeypatch.setattr(integration, "make_backup_root", lambda: (_ for _ in ()).throw(OSError("disk full")))
    monkeypatch.setattr(integration, "embed_lyrics", lambda *args: embedded.append(True))

    with pytest.raises(RuntimeError, match="backup failed before metadata modification"):
        integrate_downloaded_mp3(
            _item(path),
            song_fetcher=lambda _: _song(synced=False, plain=True),
            state={},
        )

    assert embedded == []
    assert path.read_bytes() == pristine


def test_restore_failure_is_clear_and_preserves_pristine_backup(tmp_path, monkeypatch):
    import juice_lyrics.acquisition.integration as integration

    root = _isolated_backup(monkeypatch, tmp_path)
    path = tmp_path / "Rental.mp3"
    pristine = b"pristine"
    path.write_bytes(pristine)

    def embed(target, synced, plain):
        target.write_bytes(b"partial")
        raise RuntimeError("embed failed")

    monkeypatch.setattr(integration, "embed_lyrics", embed)
    monkeypatch.setattr(integration, "restore_file", lambda *args: (_ for _ in ()).throw(OSError("restore denied")))

    with pytest.raises(RuntimeError, match="Automatic restore also failed") as exc_info:
        integrate_downloaded_mp3(
            _item(path),
            song_fetcher=lambda _: _song(synced=False, plain=True),
            state={},
        )

    assert "may be partially modified" in str(exc_info.value)
    assert (root / "Rental.mp3").read_bytes() == pristine
    assert path.read_bytes() == b"partial"


def test_no_lyrics_creates_no_backup_or_metadata_change(tmp_path, monkeypatch):
    import juice_lyrics.acquisition.integration as integration

    path = tmp_path / "Rental.mp3"
    pristine = b"pristine"
    path.write_bytes(pristine)
    monkeypatch.setattr(integration, "make_backup_root", lambda: (_ for _ in ()).throw(AssertionError("backup called")))

    result = integrate_downloaded_mp3(
        _item(path),
        song_fetcher=lambda _: _song(synced=False, plain=False),
        state={},
    )

    assert result.lyric_type == "NONE"
    assert result.backup_path is None
    assert path.read_bytes() == pristine


def test_lrc_failure_retains_verified_mp3_and_backup(tmp_path, monkeypatch):
    import juice_lyrics.acquisition.integration as integration

    root = _isolated_backup(monkeypatch, tmp_path)
    path = tmp_path / "Rental.mp3"
    pristine = b"pristine"
    path.write_bytes(pristine)
    def embed(target, *_):
        target.write_bytes(b"verified")
        return "SYLT"

    monkeypatch.setattr(integration, "embed_lyrics", embed)
    monkeypatch.setattr(integration, "verify_file", lambda target: (True, "verified"))
    monkeypatch.setattr(integration, "write_lrc", lambda *args: (_ for _ in ()).throw(OSError("LRC disk full")))

    with pytest.raises(RuntimeError, match="LRC integration failed"):
        integrate_downloaded_mp3(
            _item(path),
            song_fetcher=lambda _: _song(),
            lyrics_dir=tmp_path / "lyrics",
            state={},
        )

    assert path.read_bytes() == b"verified"
    assert (root / "Rental.mp3").read_bytes() == pristine


def test_rmpc_notification_failure_is_warning_and_keeps_success(tmp_path, monkeypatch):
    import juice_lyrics.acquisition.integration as integration

    _isolated_backup(monkeypatch, tmp_path)
    path = tmp_path / "Rental.mp3"
    path.write_bytes(b"pristine")
    def embed(target, *_):
        target.write_bytes(b"verified")
        return "SYLT"

    monkeypatch.setattr(integration, "embed_lyrics", embed)
    monkeypatch.setattr(integration, "verify_file", lambda target: (True, "verified"))
    monkeypatch.setattr(integration, "write_lrc", lambda *args: tmp_path / "lyrics" / "Rental.lrc")
    monkeypatch.setattr(integration, "notify_rmpc_index", lambda paths: (_ for _ in ()).throw(RuntimeError("rmpc unavailable")))

    result = integrate_downloaded_mp3(
        _item(path),
        song_fetcher=lambda _: _song(),
        lyrics_dir=tmp_path / "lyrics",
        state={},
    )

    assert result.lyric_type == "SYLT"
    assert result.rmpc_notified == 0
    assert "rmpc notification failed" in result.message
    assert path.read_bytes() == b"verified"


def test_state_failure_retains_verified_mp3_and_runner_marks_failed(tmp_path, monkeypatch):
    import juice_lyrics.acquisition.integration as integration

    _isolated_backup(monkeypatch, tmp_path)
    path = tmp_path / "Rental.mp3"
    item = _item(path)
    store = JobStore(tmp_path / "jobs.json")
    job = store.create([item], job_id="state-failure")

    def download(download_item, policy=None, *, progress=None):
        download_item.destination.write_bytes(b"pristine")
        return AcquisitionResult(download_item, AcquisitionState.COMPLETE, download_item.destination, 8)

    monkeypatch.setattr(runner, "download_to", download)
    def embed(target, *_):
        target.write_bytes(b"verified")
        return "USLT"

    monkeypatch.setattr(integration, "embed_lyrics", embed)
    monkeypatch.setattr(integration, "verify_file", lambda target: (True, "verified"))
    monkeypatch.setattr(integration, "save_state", lambda state: (_ for _ in ()).throw(OSError("state disk full")))

    summary = runner.run_job(
        job,
        store,
        postprocess=lambda result: integrate_downloaded_mp3(
            result.item,
            song_fetcher=lambda _: _song(synced=False, plain=True),
        ),
    )

    loaded = store.get("state-failure")
    assert summary.failed == 1
    assert loaded is not None
    assert loaded.items[0].state is AcquisitionState.FAILED
    assert "state update failed" in (loaded.items[0].error or "")
    assert path.read_bytes() == b"verified"


def test_duplicate_skip_creates_no_backup(tmp_path, monkeypatch):
    import juice_lyrics.acquisition.integration as integration

    path = tmp_path / "Rental.mp3"
    path.write_bytes(b"already present")
    store = JobStore(tmp_path / "jobs.json")
    job = store.create([_item(path)], job_id="duplicate")
    monkeypatch.setattr(integration, "make_backup_root", lambda: (_ for _ in ()).throw(AssertionError("backup called")))

    summary = runner.run_job(
        job,
        store,
        postprocess=lambda result: integrate_downloaded_mp3(result.item, song_fetcher=lambda _: _song()),
    )

    assert summary.skipped == 1
    assert job.items[0].state is AcquisitionState.SKIPPED
