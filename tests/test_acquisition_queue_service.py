import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest

from juice_lyrics.acquisition.jobs import JobStore
from juice_lyrics.acquisition.models import AcquisitionFailureStage, AcquisitionItem, AcquisitionState
from juice_lyrics.services.acquisition_queue import (
    QueueFailureStage,
    QueueReferenceError,
    QueueStatus,
    get_queue_snapshot,
    resolve_queue_reference,
)


def _item(tmp_path, title="Rental"):
    return AcquisitionItem(
        identifier=title.lower(),
        title=title,
        url=f"https://example.invalid/{title.lower()}.mp3",
        destination=tmp_path / f"{title}.mp3",
        expected_size=100,
    )


def test_empty_queue_is_read_only(tmp_path):
    path = tmp_path / "missing" / "jobs.json"
    snapshot = get_queue_snapshot(path)

    assert snapshot.jobs == ()
    assert snapshot.total_job_count == 0
    assert snapshot.active_job_count == 0
    assert snapshot.pending_job_count == 0
    assert snapshot.completed_job_count == 0
    assert snapshot.failed_job_count == 0
    assert not path.parent.exists()


def test_queue_orders_newest_first_and_resolves_references(tmp_path):
    path = tmp_path / "jobs.json"
    store = JobStore(path)
    older = store.create([_item(tmp_path, "Older")], job_id="older-uuid")
    newer = store.create([_item(tmp_path, "Newer")], job_id="newer-uuid")
    older.created_at = "2024-01-01T00:00:00+00:00"
    newer.created_at = "2025-01-01T00:00:00+00:00"
    store.save(older)
    store.save(newer)

    snapshot = get_queue_snapshot(path)

    assert [job.job_id for job in snapshot.jobs] == ["newer-uuid", "older-uuid"]
    assert [job.display_number for job in snapshot.jobs] == [1, 2]
    assert resolve_queue_reference(snapshot, 1).job_id == "newer-uuid"
    assert resolve_queue_reference(snapshot, "2").job_id == "older-uuid"
    assert resolve_queue_reference(snapshot, "latest").job_id == "newer-uuid"
    assert resolve_queue_reference(snapshot, "older-uuid").display_number == 2


def test_invalid_queue_references(tmp_path):
    snapshot = get_queue_snapshot(tmp_path / "missing.json")
    with pytest.raises(QueueReferenceError, match="empty"):
        resolve_queue_reference(snapshot, "latest")
    with pytest.raises(QueueReferenceError, match="out of range"):
        resolve_queue_reference(snapshot, 1)
    with pytest.raises(QueueReferenceError, match="not found"):
        resolve_queue_reference(snapshot, "unknown-uuid")


def test_mixed_states_counts_retry_and_deletion_rules(tmp_path):
    store = JobStore(tmp_path / "jobs.json")
    job = store.create(
        [_item(tmp_path, name) for name in ("Pending", "Active", "Done", "Skipped", "Failed")],
        job_id="mixed-uuid",
    )
    states = [
        AcquisitionState.PENDING,
        AcquisitionState.DOWNLOADING,
        AcquisitionState.COMPLETE,
        AcquisitionState.SKIPPED,
        AcquisitionState.FAILED,
    ]
    for entry, state in zip(job.items, states):
        entry.state = state
    job.items[1].bytes_written = 40
    job.items[4].error = "network failed"
    store.save(job)

    snapshot = get_queue_snapshot(store.path)
    view = snapshot.jobs[0]

    assert view.status is QueueStatus.FAILED
    assert view.pending_item_count == 1
    assert view.active_item_count == 1
    assert view.completed_item_count == 2
    assert view.failed_item_count == 1
    assert view.items[1].bytes_written == 40
    assert view.items[1].expected_bytes == 100
    assert view.items[4].error == "network failed"
    assert view.items[2].retryable is False
    assert view.items[3].retryable is False
    assert view.items[4].retryable is True
    assert view.retryable is True
    assert view.deletion_allowed is False
    assert snapshot.failed_job_count == 1


def test_completed_pending_and_transitional_job_statuses(tmp_path):
    store = JobStore(tmp_path / "jobs.json")
    completed = store.create([_item(tmp_path, "Complete")], job_id="complete")
    completed.items[0].state = AcquisitionState.COMPLETE
    store.save(completed)
    pending = store.create([_item(tmp_path, "Pending")], job_id="pending")
    transitional = store.create([_item(tmp_path, "Imported")], job_id="transitional")
    transitional.items[0].state = AcquisitionState.IMPORTED
    store.save(transitional)

    snapshot = get_queue_snapshot(store.path)
    by_id = {job.job_id: job for job in snapshot.jobs}

    assert by_id["complete"].status is QueueStatus.COMPLETED
    assert by_id["complete"].retryable is False
    assert by_id["complete"].deletion_allowed is True
    assert by_id["pending"].status is QueueStatus.PENDING
    assert by_id["transitional"].status is QueueStatus.POST_PROCESSING
    assert snapshot.completed_job_count == 1
    assert snapshot.pending_job_count == 1
    assert snapshot.active_job_count == 1


def test_unknown_state_and_malformed_optional_values_are_safe(tmp_path):
    path = tmp_path / "jobs.json"
    path.write_text(
        json.dumps({
            "jobs": {
                "unknown-uuid": {
                    "job_id": "unknown-uuid",
                    "created_at": None,
                    "items": [{
                        "state": "future_state",
                        "bytes_written": "bad",
                        "resumed": False,
                        "error": {"bad": "shape"},
                        "item": {
                            "title": None,
                            "destination": None,
                            "expected_size": "bad",
                        },
                    }],
                }
            }
        }),
        encoding="utf-8",
    )

    view = get_queue_snapshot(path).jobs[0]
    assert view.status is QueueStatus.UNKNOWN
    assert view.items[0].status is QueueStatus.UNKNOWN
    assert view.items[0].bytes_written == 0
    assert view.items[0].expected_bytes is None
    assert view.items[0].retryable is False
    assert view.label == "Untitled job"


def test_view_does_not_recover_or_rewrite_store(tmp_path):
    store = JobStore(tmp_path / "jobs.json")
    job = store.create([_item(tmp_path)], job_id="active-uuid")
    job.items[0].state = AcquisitionState.CHECKING_EXISTING
    store.save(job)
    before = store.path.read_bytes()

    snapshot = get_queue_snapshot(store.path)

    assert snapshot.jobs[0].items[0].status is QueueStatus.CHECKING_EXISTING
    assert store.path.read_bytes() == before
    loaded = store.get("active-uuid")
    assert loaded is not None
    assert loaded.items[0].state is AcquisitionState.CHECKING_EXISTING


def test_failure_stage_updated_time_and_safe_postprocessing_retry_are_exposed(tmp_path):
    store = JobStore(tmp_path / "jobs.json")
    job = store.create([_item(tmp_path)], job_id="lyrics-failure")
    destination = job.items[0].item.destination
    destination.write_bytes(b"finalized audio")
    job.items[0].state = AcquisitionState.FAILED
    job.items[0].failure_stage = AcquisitionFailureStage.LYRICS
    job.items[0].error = "lyrics verification failed"
    job.items[0].retry_file_size = destination.stat().st_size
    job.items[0].retry_file_sha256 = hashlib.sha256(destination.read_bytes()).hexdigest()
    store.save(job)

    view = get_queue_snapshot(store.path).jobs[0]

    assert view.updated_at is not None
    assert view.items[0].failure_stage is QueueFailureStage.LYRICS
    assert view.items[0].postprocessing_retryable is True

    destination.write_bytes(b"changed")
    assert get_queue_snapshot(store.path).jobs[0].items[0].postprocessing_retryable is False


def test_cli_jobs_uses_queue_view_and_preserves_output(tmp_path, monkeypatch, capsys):
    import juice_lyrics.cli as cli

    store = JobStore(tmp_path / "jobs.json")
    store.create([_item(tmp_path)], job_id="job-xyz")
    monkeypatch.setattr(cli, "JobStore", lambda: JobStore(store.path))

    args = cli.build_parser().parse_args(["acquire", "jobs"])
    result = cli.command_acquire(args, cli.load_settings(str(tmp_path), None), False)
    output = capsys.readouterr().out

    assert result == 0
    assert "job-xyz — pending — 1 item(s)" in output
    assert f"pending        Rental → {tmp_path / 'Rental.mp3'}" in output
