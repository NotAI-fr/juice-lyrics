import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from juice_lyrics.acquisition import runner
from juice_lyrics.acquisition.integration import integrate_downloaded_mp3
from juice_lyrics.acquisition.integration import IntegrationResult
from juice_lyrics.acquisition.jobs import JobStore
from juice_lyrics.acquisition.models import (
    AcquisitionFailureStage,
    AcquisitionItem,
    AcquisitionPostProcessingError,
    AcquisitionResult,
    AcquisitionState,
)


def _item(tmp_path, *, destination=None):
    return AcquisitionItem(
        identifier="101",
        title="Rental",
        url="https://example.invalid/Rental.mp3",
        destination=destination or tmp_path / "Rental.mp3",
    )


def _complete_download(calls, payload=b"finalized audio"):
    def download(item, policy=None, *, progress=None):
        calls.append(item.destination)
        item.destination.parent.mkdir(parents=True, exist_ok=True)
        item.destination.write_bytes(payload)
        return AcquisitionResult(
            item=item,
            state=AcquisitionState.COMPLETE,
            destination=item.destination,
            bytes_written=len(payload),
        )

    return download


def test_postprocessing_failure_retries_exact_file_without_downloader(tmp_path, monkeypatch):
    item = _item(tmp_path)
    store = JobStore(tmp_path / "jobs.json")
    job = store.create([item], job_id="post-retry")
    downloads = []
    monkeypatch.setattr(runner, "download_to", _complete_download(downloads))

    first = runner.run_job(
        job,
        store,
        postprocess=lambda result: (_ for _ in ()).throw(
            AcquisitionPostProcessingError(AcquisitionFailureStage.STATE, "state failed")
        ),
    )
    assert first.failed == 1
    failed = store.get("post-retry")
    assert failed is not None
    assert failed.items[0].failure_stage is AcquisitionFailureStage.STATE
    assert failed.items[0].retry_file_size == item.destination.stat().st_size
    assert failed.items[0].retry_file_sha256

    postprocess_calls = []
    retried = runner.run_job(
        failed,
        store,
        postprocess=lambda result: postprocess_calls.append(
            (result.item.destination, result.postprocessing_retry)
        ),
    )

    assert downloads == [item.destination]
    assert postprocess_calls == [(item.destination, True)]
    assert retried.completed == 1
    loaded = store.get("post-retry")
    assert loaded is not None
    assert loaded.items[0].state is AcquisitionState.COMPLETE
    assert loaded.items[0].failure_stage is None
    assert loaded.items[0].retry_file_sha256 is None


def test_failed_postprocessing_retry_remains_failed_and_rolls_back(tmp_path, monkeypatch):
    import juice_lyrics.acquisition.integration as integration

    backup_counter = 0

    def backup_root():
        nonlocal backup_counter
        backup_counter += 1
        root = tmp_path / "backups" / str(backup_counter)
        root.mkdir(parents=True)
        return root

    monkeypatch.setattr(integration, "make_backup_root", backup_root)
    monkeypatch.setattr(integration, "verify_file", lambda path: (False, "bad lyrics"))

    def embed(path, synced, plain):
        path.write_bytes(b"partial metadata")
        return "USLT"

    monkeypatch.setattr(integration, "embed_lyrics", embed)
    downloads = []
    monkeypatch.setattr(runner, "download_to", _complete_download(downloads, b"pristine finalized"))
    item = _item(tmp_path)
    store = JobStore(tmp_path / "jobs.json")
    job = store.create([item], job_id="rollback-retry")

    def postprocess(result):
        return integrate_downloaded_mp3(
            result.item,
            song_fetcher=lambda _: {"id": 101, "name": "Rental", "lyrics": "plain"},
            state={},
        )

    assert runner.run_job(job, store, postprocess=postprocess).failed == 1
    assert item.destination.read_bytes() == b"pristine finalized"
    failed = store.get("rollback-retry")
    assert failed is not None
    assert runner.run_job(failed, store, postprocess=postprocess).failed == 1
    assert downloads == [item.destination]
    assert item.destination.read_bytes() == b"pristine finalized"
    loaded = store.get("rollback-retry")
    assert loaded is not None
    assert "Post-processing retry from existing finalized file failed" in (loaded.items[0].error or "")


def test_missing_retry_file_falls_back_to_download(tmp_path, monkeypatch):
    item = _item(tmp_path)
    store = JobStore(tmp_path / "jobs.json")
    job = store.create([item], job_id="missing-file")
    downloads = []
    monkeypatch.setattr(runner, "download_to", _complete_download(downloads))
    runner.run_job(
        job,
        store,
        postprocess=lambda result: (_ for _ in ()).throw(
            AcquisitionPostProcessingError(AcquisitionFailureStage.LRC, "lrc failed")
        ),
    )
    item.destination.unlink()
    failed = store.get("missing-file")
    assert failed is not None

    result = runner.run_job(failed, store, postprocess=lambda result: None)

    assert len(downloads) == 2
    assert result.completed == 1


def test_transport_failure_uses_downloader_again(tmp_path, monkeypatch):
    item = _item(tmp_path)
    store = JobStore(tmp_path / "jobs.json")
    job = store.create([item], job_id="transport-retry")
    calls = []

    def fail_download(download_item, policy=None, *, progress=None):
        calls.append("failed")
        return AcquisitionResult(
            download_item,
            AcquisitionState.FAILED,
            error="timeout",
            failure_stage=AcquisitionFailureStage.TRANSPORT,
        )

    monkeypatch.setattr(runner, "download_to", fail_download)
    assert runner.run_job(job, store).failed == 1
    failed = store.get("transport-retry")
    assert failed is not None
    monkeypatch.setattr(runner, "download_to", _complete_download(calls))

    assert runner.run_job(failed, store).completed == 1
    assert calls == ["failed", item.destination]


def test_unrelated_duplicate_is_still_skipped(tmp_path, monkeypatch):
    unrelated = tmp_path / "elsewhere" / "Rental.mp3"
    unrelated.parent.mkdir()
    unrelated.write_bytes(b"unrelated existing audio")
    item = _item(tmp_path, destination=tmp_path / "elsewhere" / "Wanted.mp3")
    store = JobStore(tmp_path / "jobs.json")
    job = store.create([item], job_id="unrelated-duplicate")
    monkeypatch.setattr(
        runner,
        "download_to",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("download called")),
    )

    summary = runner.run_job(job, store)

    assert summary.skipped == 1
    assert unrelated.read_bytes() == b"unrelated existing audio"
    assert not item.destination.exists()


def test_changed_exact_destination_does_not_bypass_duplicate_check(tmp_path, monkeypatch):
    item = _item(tmp_path)
    store = JobStore(tmp_path / "jobs.json")
    job = store.create([item], job_id="changed-destination")
    downloads = []
    monkeypatch.setattr(runner, "download_to", _complete_download(downloads))
    runner.run_job(
        job,
        store,
        postprocess=lambda result: (_ for _ in ()).throw(
            AcquisitionPostProcessingError(AcquisitionFailureStage.STATE, "state failed")
        ),
    )
    item.destination.write_bytes(b"replacement unrelated file")
    failed = store.get("changed-destination")
    assert failed is not None
    postprocess_calls = []

    summary = runner.run_job(
        failed,
        store,
        postprocess=lambda result: postprocess_calls.append(result),
    )

    assert summary.skipped == 1
    assert postprocess_calls == []
    assert downloads == [item.destination]
    assert item.destination.read_bytes() == b"replacement unrelated file"


def test_failure_metadata_round_trip_and_old_record_compatibility(tmp_path):
    item = _item(tmp_path)
    store = JobStore(tmp_path / "jobs.json")
    job = store.create([item], job_id="new-record")
    entry = job.items[0]
    entry.state = AcquisitionState.FAILED
    entry.failure_stage = AcquisitionFailureStage.LRC
    entry.retry_file_size = 42
    entry.retry_file_sha256 = "a" * 64
    store.save(job)

    loaded = store.get("new-record")
    assert loaded is not None
    assert loaded.items[0].failure_stage is AcquisitionFailureStage.LRC
    assert loaded.items[0].retry_file_size == 42
    assert loaded.items[0].retry_file_sha256 == "a" * 64

    raw = json.loads(store.path.read_text(encoding="utf-8"))
    old_item = raw["jobs"]["new-record"]["items"][0]
    old_item.pop("failure_stage")
    old_item.pop("retry_file_size")
    old_item.pop("retry_file_sha256")
    store.path.write_text(json.dumps(raw), encoding="utf-8")

    old = store.get("new-record")
    assert old is not None
    assert old.items[0].failure_stage is None
    assert old.items[0].retry_file_size is None
    assert old.items[0].retry_file_sha256 is None


def test_completed_skipped_and_no_lyrics_items_remain_compatible(tmp_path, monkeypatch):
    completed_item = _item(tmp_path, destination=tmp_path / "complete.mp3")
    skipped_item = _item(tmp_path, destination=tmp_path / "skip.mp3")
    store = JobStore(tmp_path / "jobs.json")
    job = store.create([completed_item, skipped_item], job_id="terminals")
    job.items[0].state = AcquisitionState.COMPLETE
    job.items[1].state = AcquisitionState.SKIPPED
    store.save(job)
    monkeypatch.setattr(
        runner,
        "download_to",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("download called")),
    )
    assert runner.run_job(job, store).completed == 1
    assert runner.run_job(job, store).skipped == 1

    no_lyrics = _item(tmp_path, destination=tmp_path / "none.mp3")
    no_lyrics_job = store.create([no_lyrics], job_id="no-lyrics")
    downloads = []
    monkeypatch.setattr(runner, "download_to", _complete_download(downloads))
    summary = runner.run_job(
        no_lyrics_job,
        store,
        postprocess=lambda result: integrate_downloaded_mp3(
            result.item,
            song_fetcher=lambda _: {"id": 101, "name": "Rental", "lyrics": "", "synced_lyrics": ""},
            state={},
        ),
    )
    assert summary.completed == 1
    assert downloads == [no_lyrics.destination]


def test_cli_retry_reports_existing_file_postprocessing_path(tmp_path, monkeypatch, capsys):
    import juice_lyrics.cli as cli

    item = _item(tmp_path)
    item.destination.write_bytes(b"finalized")
    store = JobStore(tmp_path / "jobs.json")
    job = store.create([item], job_id="cli-post-retry")
    entry = job.items[0]
    entry.state = AcquisitionState.FAILED
    entry.failure_stage = AcquisitionFailureStage.STATE
    entry.retry_file_size = item.destination.stat().st_size
    entry.retry_file_sha256 = runner._sha256(item.destination)
    entry.bytes_written = item.destination.stat().st_size
    store.save(job)

    monkeypatch.setattr(cli, "JobStore", lambda: JobStore(store.path))
    monkeypatch.setattr(
        runner,
        "download_to",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("download called")),
    )
    monkeypatch.setattr(
        cli,
        "integrate_downloaded_mp3",
        lambda integration_item, **kwargs: IntegrationResult(
            integration_item.destination,
            message="USLT; verified",
        ),
    )

    args = cli.build_parser().parse_args(["acquire", "retry", "cli-post-retry"])
    result = cli.command_acquire(args, cli.load_settings(str(tmp_path), None), False)
    output = capsys.readouterr().out

    assert result == 0
    assert "Retrying post-processing from existing finalized file" in output
    assert "Completed: 1" in output
