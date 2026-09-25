from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pytest

from juice_lyrics.acquisition import integration as integration_module
from juice_lyrics.acquisition.integration import integrate_downloaded_mp3
from juice_lyrics.acquisition.jobs import JobStore
from juice_lyrics.acquisition.models import (
    AcquisitionFailureStage,
    AcquisitionItem,
    AcquisitionResult,
    AcquisitionState,
)
from juice_lyrics.acquisition.runner import AcquisitionRunSummary
from juice_lyrics.config.settings import Settings
from juice_lyrics.lyrics import engine
from juice_lyrics.services.download_queue import (
    DownloadExecutionStatus,
    DownloadRetryAction,
    DownloadRetryStatus,
    execute_download_all,
    execute_selected_download,
    execute_selected_retry,
    plan_download_all,
    plan_download_execution,
    plan_download_retry,
)


def _prepare_integration(monkeypatch, tmp_path):
    counter = 0

    def backup_root():
        nonlocal counter
        counter += 1
        root = tmp_path / "backups" / str(counter)
        root.mkdir(parents=True)
        return root

    def backup_file(source, root, base):
        target = root / source.name
        shutil.copy2(source, target)
        return target

    monkeypatch.setattr(integration_module, "make_backup_root", backup_root)
    monkeypatch.setattr(integration_module, "backup_file", backup_file)
    monkeypatch.setattr(integration_module, "write_manifest", lambda *args: None)
    monkeypatch.setattr(integration_module, "embed_lyrics", lambda *args: "SYLT")
    monkeypatch.setattr(integration_module, "verify_file", lambda path: (True, "verified"))
    monkeypatch.setattr(integration_module, "notify_rmpc_index", lambda paths: len(paths))
    monkeypatch.setattr(integration_module, "load_state", lambda: {"files": {}})
    monkeypatch.setattr(integration_module, "save_state", lambda state: None)
    monkeypatch.setattr(
        engine,
        "read_mp3_metadata",
        lambda *args: {
            "artist": "Juice WRLD",
            "title": "Song",
            "album": "",
            "length": "03:00.00",
        },
    )


def _song_fetcher(settings, song_id):
    return {
        "id": song_id,
        "name": "Song",
        "synced_lyrics": "[00:01.00] line",
        "lyrics": "line",
    }


def _runner(job, store, *, postprocess, item_indexes, **kwargs):
    completed = 0
    for index in sorted(item_indexes):
        entry = job.items[index]
        entry.item.destination.parent.mkdir(parents=True, exist_ok=True)
        if not entry.item.destination.exists():
            entry.item.destination.write_bytes(b"downloaded")
        result = AcquisitionResult(
            entry.item,
            AcquisitionState.COMPLETE,
            destination=entry.item.destination,
            bytes_written=entry.item.destination.stat().st_size,
        )
        postprocess(result)
        job.record_result(index, result)
        completed += 1
    store.save(job)
    return AcquisitionRunSummary(job.job_id, completed, 0, 0, len(item_indexes))


def _settings(tmp_path):
    return Settings(
        music_dir=tmp_path / "music",
        lyrics_dir=tmp_path / "legacy-central",
        lyrics_dir_explicit=True,
    )


def test_download_selected_writes_adjacent_sidecar(tmp_path, monkeypatch):
    _prepare_integration(monkeypatch, tmp_path)
    jobs = tmp_path / "jobs.json"
    destination = tmp_path / "music" / "Selected.mp3"
    job = JobStore(jobs).create(
        [AcquisitionItem("1", "Selected", "https://example.test/selected", destination)],
        job_id="selected",
    )
    plan = plan_download_execution(_settings(tmp_path), f"{job.job_id}:0", jobs_path=jobs).plan
    assert plan is not None

    result = execute_selected_download(
        _settings(tmp_path),
        plan,
        jobs_path=jobs,
        runner=_runner,
        integration=integrate_downloaded_mp3,
        song_fetcher=_song_fetcher,
    )

    assert result.status is DownloadExecutionStatus.COMPLETED
    assert destination.with_suffix(".lrc").is_file()
    assert not _settings(tmp_path).lyrics_dir.exists()


@pytest.mark.parametrize("count", [1, 3])
def test_download_all_writes_each_adjacent_sidecar(tmp_path, monkeypatch, count):
    _prepare_integration(monkeypatch, tmp_path)
    jobs = tmp_path / "jobs.json"
    items = [
        AcquisitionItem(
            str(index),
            f"Song {index}",
            f"https://example.test/{index}",
            tmp_path / "music" / f"Song {index}.mp3",
        )
        for index in range(count)
    ]
    JobStore(jobs).create(items, job_id="batch")
    settings = _settings(tmp_path)

    result = execute_download_all(
        settings,
        plan_download_all(settings, jobs_path=jobs),
        jobs_path=jobs,
        runner=_runner,
        integration=integrate_downloaded_mp3,
        song_fetcher=_song_fetcher,
    )

    assert result.completed_count == count
    assert all(item.destination.with_suffix(".lrc").is_file() for item in items)
    assert not settings.lyrics_dir.exists()


@pytest.mark.parametrize(
    ("stage", "existing_file", "expected_action"),
    [
        (AcquisitionFailureStage.LYRICS, True, DownloadRetryAction.PROCESS_ONLY),
        (AcquisitionFailureStage.TRANSPORT, False, DownloadRetryAction.DOWNLOAD_AGAIN),
    ],
)
def test_retry_modes_write_adjacent_sidecar(
    tmp_path, monkeypatch, stage, existing_file, expected_action
):
    _prepare_integration(monkeypatch, tmp_path)
    jobs = tmp_path / "jobs.json"
    destination = tmp_path / "music" / "Retry.mp3"
    if existing_file:
        destination.parent.mkdir(parents=True)
        destination.write_bytes(b"finalized")
    job = JobStore(jobs).create(
        [AcquisitionItem("9", "Retry", "https://example.test/retry", destination)],
        job_id="retry",
    )
    entry = job.items[0]
    entry.state = AcquisitionState.FAILED
    entry.failure_stage = stage
    entry.error = "previous failure"
    if existing_file:
        entry.retry_file_size = destination.stat().st_size
        entry.retry_file_sha256 = hashlib.sha256(destination.read_bytes()).hexdigest()
    JobStore(jobs).save(job)
    settings = _settings(tmp_path)
    planned = plan_download_retry(settings, "retry:0", jobs_path=jobs)
    assert planned.plan is not None
    assert planned.plan.action is expected_action

    result = execute_selected_retry(
        settings,
        planned.plan,
        jobs_path=jobs,
        runner=_runner,
        integration=integrate_downloaded_mp3,
        song_fetcher=_song_fetcher,
    )

    assert result.status is DownloadRetryStatus.COMPLETED
    assert destination.with_suffix(".lrc").is_file()
    assert not settings.lyrics_dir.exists()
