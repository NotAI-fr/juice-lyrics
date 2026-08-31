from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest

from juice_lyrics.acquisition.manifests import load_manifest
from juice_lyrics.acquisition.downloader import DownloadPolicy
from juice_lyrics.acquisition.models import AcquisitionItem, AcquisitionResult, AcquisitionState
from juice_lyrics.acquisition.resolver import ResourceResolutionError, resolve_resource


def test_manifest_ignores_comments_and_duplicates(tmp_path):
    manifest = tmp_path / "wanted.txt"
    manifest.write_text("# comment\nRental\n\nBottle\nRental\n", encoding="utf-8")
    assert load_manifest(manifest) == ["Rental", "Bottle"]


def test_models_default_state():
    item = AcquisitionItem(
        identifier="123",
        title="Example",
        url="https://example.invalid/song.mp3",
        destination=Path("song.mp3"),
    )
    assert item.identifier == "123"
    assert AcquisitionState.PENDING.value == "pending"
    assert DownloadPolicy().retries == 3


def test_resolve_resource_from_download_url(tmp_path):
    resource = {
        "id": 123,
        "name": "Rental",
        "download_url": "https://cdn.example.invalid/music/rental.mp3?token=test",
        "size": "42",
        "sha256": "a" * 64,
        "category": "unreleased",
        "version": "v2",
    }

    item = resolve_resource(resource, destination_dir=tmp_path)

    assert item.identifier == "123"
    assert item.title == "Rental"
    assert item.url.startswith("https://")
    assert item.destination == tmp_path / "rental.mp3"
    assert item.expected_size == 42
    assert item.expected_sha256 == "a" * 64
    assert item.metadata == {"category": "unreleased", "version": "v2"}


def test_resolve_resource_rejects_http_by_default(tmp_path):
    with pytest.raises(ResourceResolutionError, match="requires HTTPS"):
        resolve_resource(
            {"id": 1, "name": "Example", "url": "http://example.invalid/song.mp3"},
            destination_dir=tmp_path,
        )


def test_resolve_resource_requires_absolute_url(tmp_path):
    with pytest.raises(ResourceResolutionError, match=r"absolute HTTP\(S\) URL"):
        resolve_resource(
            {"id": 1, "name": "Example", "url": "/media/song.mp3"},
            destination_dir=tmp_path,
        )


def test_resolve_resource_sanitizes_filename(tmp_path):
    item = resolve_resource(
        {
            "id": 1,
            "name": "Example",
            "url": "https://example.invalid/files/%2E%2E%2Fsecret.mp3",
        },
        destination_dir=tmp_path,
    )
    assert item.destination == tmp_path / "secret.mp3"


def test_resolve_resource_rejects_bad_checksum(tmp_path):
    with pytest.raises(ResourceResolutionError, match="SHA-256"):
        resolve_resource(
            {
                "id": 1,
                "name": "Example",
                "url": "https://example.invalid/song.mp3",
                "sha256": "not-a-checksum",
            },
            destination_dir=tmp_path,
        )


def test_resolve_resource_from_live_api_path(tmp_path):
    resource = {
        "id": 94902,
        "name": "Lemon Glow",
        "category": "unreleased",
        "era": {"id": 8, "name": "WOD"},
        "length": "2:19",
        "path": "Compilation/2. Unreleased Discography/8. WRLD ON DRUGS (Sessions)/Lemon Glow.mp3",
        "lyrics": "plain lyrics",
    }

    item = resolve_resource(resource, destination_dir=tmp_path)

    assert item.identifier == "94902"
    assert item.title == "Lemon Glow"
    # Destination filename extracted from the original path
    assert item.destination == tmp_path / "Lemon Glow.mp3"
    # Download URL synthesized using default API base and correctly URL-encoded
    expected_url = (
        "https://juicewrldapi.com/juicewrld/files/download/?path="
        "Compilation/2.%20Unreleased%20Discography/8.%20WRLD%20ON%20DRUGS%20%28Sessions%29/Lemon%20Glow.mp3"
    )
    assert item.url == expected_url
    assert item.metadata.get("category") == "unreleased"
    assert item.metadata.get("era") == "WOD"


def test_resolve_resource_from_api_path_custom_api_base(tmp_path):
    resource = {
        "id": 100,
        "name": "Custom Track",
        "path": "Tracks/Custom Track.mp3",
    }

    item = resolve_resource(resource, destination_dir=tmp_path, api_base="https://custom.api.example/v1")
    assert item.url == "https://custom.api.example/v1/files/download/?path=Tracks/Custom%20Track.mp3"
    assert item.destination == tmp_path / "Custom Track.mp3"


def test_resolve_resource_from_api_path_rejects_http_by_default(tmp_path):
    resource = {
        "id": 100,
        "name": "Insecure Track",
        "path": "Tracks/Track.mp3",
    }

    with pytest.raises(ResourceResolutionError, match="requires HTTPS"):
        resolve_resource(resource, destination_dir=tmp_path, api_base="http://insecure.example.invalid/juicewrld")


def test_resolve_resource_from_api_path_allows_http_when_explicit(tmp_path):
    resource = {
        "id": 100,
        "name": "Insecure Track",
        "path": "Tracks/Track.mp3",
    }

    item = resolve_resource(
        resource,
        destination_dir=tmp_path,
        api_base="http://insecure.example.invalid/juicewrld",
        allow_http=True,
    )
    assert item.url.startswith("http://insecure.example.invalid")


def test_resolve_resource_rejects_missing_url_and_path(tmp_path):
    with pytest.raises(ResourceResolutionError, match=r"no downloadable URL or path"):
        resolve_resource(
            {"id": 100, "name": "No URL Or Path"},
            destination_dir=tmp_path,
        )


def test_resolve_resource_from_api_path_preserves_size_and_checksum(tmp_path):
    resource = {
        "id": 100,
        "name": "Track With Metadata",
        "path": "Tracks/Track.mp3",
        "size": 54321,
        "sha256": "c" * 64,
    }

    item = resolve_resource(resource, destination_dir=tmp_path)
    assert item.expected_size == 54321
    assert item.expected_sha256 == "c" * 64

from juice_lyrics.acquisition.duplicates import find_duplicate


def test_duplicate_detects_matching_checksum_under_different_name(tmp_path):
    original = tmp_path / "renamed.mp3"
    original.write_bytes(b"same audio")
    import hashlib
    checksum = hashlib.sha256(original.read_bytes()).hexdigest()

    item = AcquisitionItem(
        identifier="1",
        title="Rental",
        url="https://example.invalid/rental.mp3",
        destination=tmp_path / "Rental.mp3",
        expected_sha256=checksum,
    )

    match = find_duplicate(item)
    assert match is not None
    assert match.path == original
    assert "SHA-256" in match.reason


def test_duplicate_does_not_confuse_versions(tmp_path):
    (tmp_path / "Starstruck v1.mp3").write_bytes(b"v1")

    item = AcquisitionItem(
        identifier="v2",
        title="Starstruck v2",
        url="https://example.invalid/starstruck-v2.mp3",
        destination=tmp_path / "Starstruck v2.mp3",
        metadata={"version": "v2"},
    )

    assert find_duplicate(item) is None


def test_duplicate_detects_exact_title_and_version(tmp_path):
    existing = tmp_path / "Rental.mp3"
    existing.write_bytes(b"audio")

    item = AcquisitionItem(
        identifier="rental",
        title="Rental",
        url="https://example.invalid/rental.mp3",
        destination=tmp_path / "different-name.mp3",
    )

    match = find_duplicate(item)
    assert match is not None
    assert match.path == existing
    assert "title and version" in match.reason


def test_duplicate_ignores_part_files(tmp_path):
    partial = tmp_path / "Rental.mp3.part"
    partial.write_bytes(b"audio")

    item = AcquisitionItem(
        identifier="rental",
        title="Rental",
        url="https://example.invalid/rental.mp3",
        destination=tmp_path / "Rental.mp3",
    )

    assert find_duplicate(item) is None

from juice_lyrics.acquisition.jobs import AcquisitionJob, JobStore, JobStoreError


def _job_item(tmp_path, name="Rental.mp3"):
    return AcquisitionItem(
        identifier="rental",
        title="Rental",
        url="https://example.invalid/rental.mp3",
        destination=tmp_path / name,
        expected_size=4,
        metadata={"version": "v1"},
    )


def test_job_store_create_and_round_trip(tmp_path):
    store = JobStore(tmp_path / "jobs.json")
    item = _job_item(tmp_path)
    job = store.create([item], job_id="job-123")

    loaded = store.get("job-123")
    assert loaded is not None
    assert loaded.job_id == job.job_id
    assert loaded.items[0].item.destination == item.destination
    assert loaded.items[0].state is AcquisitionState.PENDING
    assert loaded.state is AcquisitionState.PENDING


def test_job_store_records_result(tmp_path):
    store = JobStore(tmp_path / "jobs.json")
    job = store.create([_job_item(tmp_path)], job_id="job-123")
    result = AcquisitionResult(
        item=job.items[0].item,
        state=AcquisitionState.COMPLETE,
        destination=job.items[0].item.destination,
        bytes_written=4,
        resumed=True,
    )

    job.record_result(0, result)
    store.save(job)

    loaded = store.get("job-123")
    assert loaded is not None
    assert loaded.items[0].state is AcquisitionState.COMPLETE
    assert loaded.items[0].bytes_written == 4
    assert loaded.items[0].resumed is True
    assert loaded.state is AcquisitionState.COMPLETE


def test_job_store_recovers_interrupted_states(tmp_path):
    store = JobStore(tmp_path / "jobs.json")
    job = store.create([_job_item(tmp_path)], job_id="job-123")
    job.items[0].state = AcquisitionState.DOWNLOADING
    store.save(job)

    recovered = store.recover_interrupted()
    assert [item.job_id for item in recovered] == ["job-123"]

    loaded = store.get("job-123")
    assert loaded is not None
    assert loaded.items[0].state is AcquisitionState.PENDING
    assert loaded.items[0].error


def test_job_store_lists_newest_first(tmp_path):
    store = JobStore(tmp_path / "jobs.json")
    store.create([_job_item(tmp_path, "a.mp3")], job_id="a")
    store.create([_job_item(tmp_path, "b.mp3")], job_id="b")
    assert [job.job_id for job in store.list()] == ["b", "a"]


def test_job_store_invalid_json_is_reported(tmp_path):
    path = tmp_path / "jobs.json"
    path.write_text("not json", encoding="utf-8")
    with pytest.raises(JobStoreError):
        JobStore(path).list()

from juice_lyrics.acquisition.runner import run_job


def test_run_job_skips_existing_duplicate(tmp_path):
    store = JobStore(tmp_path / "jobs.json")
    existing = tmp_path / "Rental.mp3"
    existing.write_bytes(b"test")
    job = store.create([_job_item(tmp_path)])

    summary = run_job(job, store)

    assert summary.ok
    assert summary.skipped == 1
    assert job.items[0].state is AcquisitionState.SKIPPED
    assert job.items[0].bytes_written == len(b"test")


def test_run_job_executes_and_persists_download_result(tmp_path, monkeypatch):
    store = JobStore(tmp_path / "jobs.json")
    job = store.create([_job_item(tmp_path)])

    def fake_download(item, policy, *, progress=None):
        item.destination.parent.mkdir(parents=True, exist_ok=True)
        item.destination.write_bytes(b"audio")
        if progress:
            progress(5, 5)
        return AcquisitionResult(
            item=item,
            state=AcquisitionState.COMPLETE,
            destination=item.destination,
            bytes_written=5,
            resumed=False,
        )

    monkeypatch.setattr("juice_lyrics.acquisition.runner.download_to", fake_download)
    summary = run_job(job, store)

    assert summary.completed == 1
    assert summary.failed == 0
    assert job.items[0].state is AcquisitionState.COMPLETE
    loaded = store.get(job.job_id)
    assert loaded is not None
    assert loaded.items[0].state is AcquisitionState.COMPLETE
    assert loaded.items[0].bytes_written == 5


def test_run_job_contains_failure_and_continues(tmp_path, monkeypatch):
    store = JobStore(tmp_path / "jobs.json")
    first = _job_item(tmp_path, "first.mp3")
    second = _job_item(tmp_path, "second.mp3")
    job = store.create([first, second])

    calls = []

    def fake_download(item, policy, *, progress=None):
        calls.append(item.destination.name)
        if item.destination.name == "first.mp3":
            raise RuntimeError("network exploded")
        item.destination.write_bytes(b"done!")
        return AcquisitionResult(
            item=item,
            state=AcquisitionState.COMPLETE,
            destination=item.destination,
            bytes_written=5,
        )

    monkeypatch.setattr("juice_lyrics.acquisition.runner.download_to", fake_download)
    summary = run_job(job, store)

    assert calls == ["first.mp3", "second.mp3"]
    assert summary.failed == 1
    assert summary.completed == 1
    assert job.items[0].state is AcquisitionState.FAILED
    assert "network exploded" in (job.items[0].error or "")
    assert job.items[1].state is AcquisitionState.COMPLETE


def test_run_job_can_execute_only_one_selected_item(tmp_path, monkeypatch):
    store = JobStore(tmp_path / "jobs.json")
    items = [_job_item(tmp_path, "first.mp3"), _job_item(tmp_path, "selected.mp3")]
    items[0].identifier = "1"
    items[1].identifier = "2"
    job = store.create(items)
    calls = []

    monkeypatch.setattr("juice_lyrics.acquisition.runner.find_duplicate", lambda item: None)

    def fake_download(item, policy, *, progress=None):
        calls.append(item.identifier)
        return AcquisitionResult(
            item=item,
            state=AcquisitionState.COMPLETE,
            destination=item.destination,
            bytes_written=10,
        )

    monkeypatch.setattr("juice_lyrics.acquisition.runner.download_to", fake_download)

    summary = run_job(job, store, item_indexes={1})

    assert calls == ["2"]
    assert job.items[0].state is AcquisitionState.PENDING
    assert job.items[1].state is AcquisitionState.COMPLETE
    assert summary.completed == 1
    assert summary.pending == 1



def test_cli_acquire_parser_exposes_user_workflow():
    from juice_lyrics.cli import build_parser

    parser = build_parser()
    args = parser.parse_args(["acquire", "search", "rental"])
    assert args.command == "acquire"
    assert args.action == "search"
    assert args.query == "rental"


def test_cli_acquire_add_creates_persistent_job(tmp_path, monkeypatch, capsys):
    import juice_lyrics.cli as cli

    resource = {
        "id": 123,
        "title": "Rental",
        "download_url": "https://example.invalid/rental.mp3",
        "version": "v1",
    }
    monkeypatch.setattr(cli, "search_api_advanced", lambda *a, **k: {"results": [resource]})
    monkeypatch.setattr(cli, "JobStore", lambda: JobStore(tmp_path / "jobs.json"))

    args = cli.build_parser().parse_args([
        "--path", str(tmp_path),
        "acquire", "add", "rental",
        "--index", "1",
    ])
    settings = cli.load_settings(str(tmp_path), None)
    result = cli.command_acquire(args, settings, False)

    assert result == 0
    output = capsys.readouterr().out
    assert "Acquisition job created" in output
    assert "Rental" in output
    assert "Run it with" in output
    assert len(JobStore(tmp_path / "jobs.json").list()) == 1


def test_cli_acquire_search_with_api_path_shows_downloadable(tmp_path, monkeypatch, capsys):
    import juice_lyrics.cli as cli

    live_resource = {
        "id": 94902,
        "name": "Lemon Glow",
        "category": "unreleased",
        "era": {"id": 8, "name": "WOD"},
        "path": "Compilation/2. Unreleased Discography/8. WRLD ON DRUGS (Sessions)/Lemon Glow.mp3",
        "lyrics": "plain lyrics",
    }
    monkeypatch.setattr(cli, "search_api_advanced", lambda *a, **k: {"results": [live_resource]})

    args = cli.build_parser().parse_args([
        "--path", str(tmp_path),
        "acquire", "search", "Lemon Glow",
    ])
    settings = cli.load_settings(str(tmp_path), None)
    result = cli.command_acquire(args, settings, False)

    assert result == 0
    output = capsys.readouterr().out
    assert "Lemon Glow" in output
    assert "DOWNLOADABLE" in output
    assert "NO DOWNLOAD URL" not in output


def test_cli_acquire_add_with_live_api_path_creates_job(tmp_path, monkeypatch, capsys):
    import juice_lyrics.cli as cli

    live_resource = {
        "id": 94902,
        "name": "Lemon Glow",
        "category": "unreleased",
        "era": {"id": 8, "name": "WOD"},
        "path": "Compilation/2. Unreleased Discography/8. WRLD ON DRUGS (Sessions)/Lemon Glow.mp3",
    }
    monkeypatch.setattr(cli, "search_api_advanced", lambda *a, **k: {"results": [live_resource]})
    monkeypatch.setattr(cli, "JobStore", lambda: JobStore(tmp_path / "jobs.json"))

    args = cli.build_parser().parse_args([
        "--path", str(tmp_path),
        "acquire", "add", "Lemon Glow",
        "--index", "1",
    ])
    settings = cli.load_settings(str(tmp_path), None)
    result = cli.command_acquire(args, settings, False)

    assert result == 0
    output = capsys.readouterr().out
    assert "Acquisition job created" in output
    assert "Lemon Glow" in output
    assert "Lemon Glow.mp3" in output

    jobs = JobStore(tmp_path / "jobs.json").list()
    assert len(jobs) == 1
    job = jobs[0]
    assert job.items[0].item.title == "Lemon Glow"
    assert job.items[0].item.destination == tmp_path / "Lemon Glow.mp3"
    assert "https://juicewrldapi.com/juicewrld/files/download/?path=" in job.items[0].item.url


def test_cli_acquire_jobs_lists_persistent_jobs(tmp_path, monkeypatch, capsys):
    import juice_lyrics.cli as cli

    store = JobStore(tmp_path / "jobs.json")
    store.create([_job_item(tmp_path)], job_id="job-xyz")
    monkeypatch.setattr(cli, "JobStore", lambda: JobStore(tmp_path / "jobs.json"))

    args = cli.build_parser().parse_args(["acquire", "jobs"])
    settings = cli.load_settings(str(tmp_path), None)
    result = cli.command_acquire(args, settings, False)

    assert result == 0
    output = capsys.readouterr().out
    assert "job-xyz" in output
    assert "Rental" in output

from juice_lyrics.acquisition.integration import integrate_downloaded_mp3
from juice_lyrics.acquisition.runner import run_job


def test_integrate_downloaded_mp3_embeds_synced_lyrics_and_lrc(tmp_path):
    mp3 = tmp_path / "Rental.mp3"
    mp3.write_bytes(b"not-a-real-mp3")
    item = AcquisitionItem(
        identifier="123",
        title="Rental",
        url="https://example.invalid/rental.mp3",
        destination=mp3,
    )

    result = integrate_downloaded_mp3(
        item,
        song_fetcher=lambda song_id: {
            "id": song_id,
            "name": "Rental",
            "credited_artists": "Juice WRLD",
            "length": "01:00",
            "synced_lyrics": "[00:01.00] hello\\n[00:02.00] world",
            "lyrics": "hello\\nworld",
        },
        lyrics_dir=tmp_path / "lyrics",
    )

    assert result.lyric_type == "SYLT"
    assert result.lrc_path == tmp_path / "lyrics" / "Rental.lrc"
    assert result.lrc_path.is_file()


def test_integrate_downloaded_mp3_skips_non_mp3(tmp_path):
    path = tmp_path / "Rental.m4a"
    path.write_bytes(b"audio")
    item = AcquisitionItem(
        identifier="123",
        title="Rental",
        url="https://example.invalid/rental.m4a",
        destination=path,
    )

    called = False
    def fetcher(_: int):
        nonlocal called
        called = True
        return {}

    result = integrate_downloaded_mp3(item, song_fetcher=fetcher, lyrics_dir=tmp_path / "lyrics")

    assert "skipped" in result.message
    assert called is False


def test_runner_postprocess_failure_marks_item_failed(tmp_path, monkeypatch):
    from juice_lyrics.acquisition import runner

    destination = tmp_path / "Rental.mp3"
    item = AcquisitionItem(
        identifier="123",
        title="Rental",
        url="https://example.invalid/rental.mp3",
        destination=destination,
    )
    store = JobStore(tmp_path / "jobs.json")
    job = store.create([item], job_id="integration-failure")

    def fake_download(item, policy=None, *, progress=None):
        item.destination.write_bytes(b"downloaded")
        return AcquisitionResult(item=item, state=AcquisitionState.COMPLETE, destination=item.destination, bytes_written=10)

    monkeypatch.setattr(runner, "download_to", fake_download)

    summary = run_job(job, store, postprocess=lambda _: (_ for _ in ()).throw(RuntimeError("lyrics failed")))
    loaded = store.get("integration-failure")
    assert summary.failed == 1
    assert loaded is not None
    assert loaded.items[0].state is AcquisitionState.FAILED
    assert "lyrics failed" in (loaded.items[0].error or "")


def test_cli_acquire_add_multiple_indexes_creates_single_job(tmp_path, monkeypatch, capsys):
    import juice_lyrics.cli as cli

    resources = [
        {"id": 101, "title": "Rental (v1)", "download_url": "https://example.invalid/rental_v1.mp3"},
        {"id": 102, "title": "Rental (v2)", "download_url": "https://example.invalid/rental_v2.mp3"},
        {"id": 103, "title": "Rental (Studio)", "download_url": "https://example.invalid/rental_studio.mp3"},
    ]
    monkeypatch.setattr(cli, "search_api_advanced", lambda *a, **k: {"results": resources})
    monkeypatch.setattr(cli, "JobStore", lambda: JobStore(tmp_path / "jobs.json"))

    args = cli.build_parser().parse_args([
        "--path", str(tmp_path),
        "acquire", "add", "rental",
        "--index", "1,3",
    ])
    settings = cli.load_settings(str(tmp_path), None)
    result = cli.command_acquire(args, settings, False)

    assert result == 0
    output = capsys.readouterr().out
    assert "Acquisition job created" in output
    assert "Items (2):" in output
    assert "Rental (v1)" in output
    assert "Rental (Studio)" in output
    assert "Run it with" in output

    jobs = JobStore(tmp_path / "jobs.json").list()
    assert len(jobs) == 1
    assert len(jobs[0].items) == 2
    assert jobs[0].items[0].item.title == "Rental (v1)"
    assert jobs[0].items[1].item.title == "Rental (Studio)"


def test_cli_acquire_add_deduplicates_repeated_indexes(tmp_path, monkeypatch):
    import juice_lyrics.cli as cli

    resources = [
        {"id": 101, "title": "Rental (v1)", "download_url": "https://example.invalid/rental_v1.mp3"},
        {"id": 102, "title": "Rental (v2)", "download_url": "https://example.invalid/rental_v2.mp3"},
    ]
    monkeypatch.setattr(cli, "search_api_advanced", lambda *a, **k: {"results": resources})
    monkeypatch.setattr(cli, "JobStore", lambda: JobStore(tmp_path / "jobs.json"))

    args = cli.build_parser().parse_args([
        "--path", str(tmp_path),
        "acquire", "add", "rental",
        "--index", "1, 2, 1",
    ])
    settings = cli.load_settings(str(tmp_path), None)
    result = cli.command_acquire(args, settings, False)

    assert result == 0
    jobs = JobStore(tmp_path / "jobs.json").list()
    assert len(jobs) == 1
    assert len(jobs[0].items) == 2


def test_cli_acquire_add_rejects_out_of_range_indexes(tmp_path, monkeypatch):
    import juice_lyrics.cli as cli

    resources = [
        {"id": 101, "title": "Rental (v1)", "download_url": "https://example.invalid/rental_v1.mp3"},
        {"id": 102, "title": "Rental (v2)", "download_url": "https://example.invalid/rental_v2.mp3"},
    ]
    monkeypatch.setattr(cli, "search_api_advanced", lambda *a, **k: {"results": resources})
    monkeypatch.setattr(cli, "JobStore", lambda: JobStore(tmp_path / "jobs.json"))

    # Single out-of-range index
    args_single = cli.build_parser().parse_args([
        "--path", str(tmp_path),
        "acquire", "add", "rental",
        "--index", "5",
    ])
    settings = cli.load_settings(str(tmp_path), None)
    with pytest.raises(RuntimeError, match=r"--index must be between 1 and 2"):
        cli.command_acquire(args_single, settings, False)

    # Multi-index with one out-of-range
    args_multi = cli.build_parser().parse_args([
        "--path", str(tmp_path),
        "acquire", "add", "rental",
        "--index", "1,5",
    ])
    with pytest.raises(RuntimeError, match=r"--index 5 is out of range"):
        cli.command_acquire(args_multi, settings, False)


def test_cli_acquire_add_rejects_invalid_index_values(tmp_path, monkeypatch):
    import juice_lyrics.cli as cli

    resources = [{"id": 101, "title": "Rental", "download_url": "https://example.invalid/rental.mp3"}]
    monkeypatch.setattr(cli, "search_api_advanced", lambda *a, **k: {"results": resources})
    monkeypatch.setattr(cli, "JobStore", lambda: JobStore(tmp_path / "jobs.json"))
    settings = cli.load_settings(str(tmp_path), None)

    for bad in ("abc", "0", "-1", "1,invalid"):
        args = cli.build_parser().parse_args([
            "--path", str(tmp_path),
            "acquire", "add", "rental",
            "--index", bad,
        ])
        with pytest.raises(RuntimeError, match=r"Invalid --index"):
            cli.command_acquire(args, settings, False)


def test_cli_acquire_add_requires_index_when_multiple_results(tmp_path, monkeypatch):
    import juice_lyrics.cli as cli

    resources = [
        {"id": 101, "title": "Rental (v1)", "download_url": "https://example.invalid/rental_v1.mp3"},
        {"id": 102, "title": "Rental (v2)", "download_url": "https://example.invalid/rental_v2.mp3"},
    ]
    monkeypatch.setattr(cli, "search_api_advanced", lambda *a, **k: {"results": resources})
    monkeypatch.setattr(cli, "JobStore", lambda: JobStore(tmp_path / "jobs.json"))
    settings = cli.load_settings(str(tmp_path), None)

    args = cli.build_parser().parse_args([
        "--path", str(tmp_path),
        "acquire", "add", "rental",
    ])
    with pytest.raises(RuntimeError, match=r"Found 2 results\. Use --index"):
        cli.command_acquire(args, settings, False)


def test_cli_acquire_add_deduplicates_duplicate_destination_items(tmp_path, monkeypatch):
    import juice_lyrics.cli as cli

    resources = [
        {"id": 101, "title": "Rental", "download_url": "https://example.invalid/rental.mp3"},
        {"id": 102, "title": "Rental Alt", "download_url": "https://example.invalid/mirror/rental.mp3"},
    ]
    monkeypatch.setattr(cli, "search_api_advanced", lambda *a, **k: {"results": resources})
    monkeypatch.setattr(cli, "JobStore", lambda: JobStore(tmp_path / "jobs.json"))
    settings = cli.load_settings(str(tmp_path), None)

    args = cli.build_parser().parse_args([
        "--path", str(tmp_path),
        "acquire", "add", "rental",
        "--index", "1,2",
    ])
    result = cli.command_acquire(args, settings, False)
    assert result == 0

    jobs = JobStore(tmp_path / "jobs.json").list()
    assert len(jobs) == 1
    # Both URLs resolve to the same filename rental.mp3; deduplication retains only the first item
    assert len(jobs[0].items) == 1


def test_cli_acquire_run_executes_multi_item_job(tmp_path, monkeypatch, capsys):
    import juice_lyrics.cli as cli

    store = JobStore(tmp_path / "jobs.json")
    item1 = AcquisitionItem(
        identifier="101",
        title="First",
        url="https://example.invalid/first.mp3",
        destination=tmp_path / "first.mp3",
    )
    item2 = AcquisitionItem(
        identifier="102",
        title="Second",
        url="https://example.invalid/second.mp3",
        destination=tmp_path / "second.mp3",
    )
    job = store.create([item1, item2], job_id="multi-run-test")

    def fake_download(item, policy=None, *, progress=None):
        item.destination.write_bytes(b"audio")
        return AcquisitionResult(
            item=item,
            state=AcquisitionState.COMPLETE,
            destination=item.destination,
            bytes_written=5,
        )

    monkeypatch.setattr("juice_lyrics.acquisition.runner.download_to", fake_download)
    monkeypatch.setattr(cli, "JobStore", lambda: JobStore(tmp_path / "jobs.json"))
    monkeypatch.setattr(cli, "_api_get_song", lambda *a, **k: {"id": 1, "name": "Test"})

    args = cli.build_parser().parse_args(["acquire", "run", "multi-run-test"])
    settings = cli.load_settings(str(tmp_path), None)
    result = cli.command_acquire(args, settings, False)

    assert result == 0
    output = capsys.readouterr().out
    assert "Completed: 2" in output
    assert "Failed:    0" in output

    loaded = JobStore(tmp_path / "jobs.json").get("multi-run-test")
    assert loaded is not None
    assert loaded.state is AcquisitionState.COMPLETE
    assert all(entry.state is AcquisitionState.COMPLETE for entry in loaded.items)


def test_cli_acquire_manifest_command_creates_job(tmp_path, monkeypatch, capsys):
    import juice_lyrics.cli as cli

    manifest_file = tmp_path / "wanted.txt"
    manifest_file.write_text("# Comment\nRental\n\nBottle\nRental\n", encoding="utf-8")

    def mock_search(settings, query, category=None, era=None, refresh=False):
        if query == "Rental":
            return {"results": [{"id": 101, "title": "Rental", "download_url": "https://example.invalid/rental.mp3"}]}
        if query == "Bottle":
            return {"results": [{"id": 102, "title": "Bottle", "download_url": "https://example.invalid/bottle.mp3"}]}
        return {"results": []}

    monkeypatch.setattr(cli, "search_api_advanced", mock_search)
    monkeypatch.setattr(cli, "JobStore", lambda: JobStore(tmp_path / "jobs.json"))

    args = cli.build_parser().parse_args([
        "--path", str(tmp_path),
        "acquire", "manifest", str(manifest_file),
    ])
    settings = cli.load_settings(str(tmp_path), None)
    result = cli.command_acquire(args, settings, False)

    assert result == 0
    output = capsys.readouterr().out
    assert "Acquisition job created from manifest" in output
    assert "wanted.txt" in output
    assert "Items (2):" in output
    assert "Rental" in output
    assert "Bottle" in output

    jobs = JobStore(tmp_path / "jobs.json").list()
    assert len(jobs) == 1
    assert len(jobs[0].items) == 2
    assert jobs[0].items[0].item.title == "Rental"
    assert jobs[0].items[1].item.title == "Bottle"


def test_cli_acquire_add_with_manifest_option(tmp_path, monkeypatch):
    import juice_lyrics.cli as cli

    manifest_file = tmp_path / "wanted.txt"
    manifest_file.write_text("Rental\n", encoding="utf-8")

    monkeypatch.setattr(
        cli,
        "search_api_advanced",
        lambda *a, **k: {"results": [{"id": 101, "title": "Rental", "download_url": "https://example.invalid/rental.mp3"}]},
    )
    monkeypatch.setattr(cli, "JobStore", lambda: JobStore(tmp_path / "jobs.json"))

    args = cli.build_parser().parse_args([
        "--path", str(tmp_path),
        "acquire", "add", "--manifest", str(manifest_file),
    ])
    settings = cli.load_settings(str(tmp_path), None)
    result = cli.command_acquire(args, settings, False)

    assert result == 0
    jobs = JobStore(tmp_path / "jobs.json").list()
    assert len(jobs) == 1
    assert len(jobs[0].items) == 1


def test_cli_acquire_manifest_rejects_missing_file(tmp_path):
    import juice_lyrics.cli as cli

    args = cli.build_parser().parse_args([
        "--path", str(tmp_path),
        "acquire", "manifest", str(tmp_path / "nonexistent.txt"),
    ])
    settings = cli.load_settings(str(tmp_path), None)
    with pytest.raises(RuntimeError, match=r"Manifest does not exist"):
        cli.command_acquire(args, settings, False)


def test_cli_acquire_manifest_rejects_empty_manifest(tmp_path):
    import juice_lyrics.cli as cli

    empty_manifest = tmp_path / "empty.txt"
    empty_manifest.write_text("# only comments\n\n", encoding="utf-8")

    args = cli.build_parser().parse_args([
        "--path", str(tmp_path),
        "acquire", "manifest", str(empty_manifest),
    ])
    settings = cli.load_settings(str(tmp_path), None)
    with pytest.raises(RuntimeError, match=r"Manifest contains no valid entries"):
        cli.command_acquire(args, settings, False)


def test_cli_acquire_manifest_unresolvable_raises_error(tmp_path, monkeypatch):
    import juice_lyrics.cli as cli

    manifest_file = tmp_path / "wanted.txt"
    manifest_file.write_text("UnknownTrack\n", encoding="utf-8")

    monkeypatch.setattr(cli, "search_api_advanced", lambda *a, **k: {"results": []})
    monkeypatch.setattr(cli, "JobStore", lambda: JobStore(tmp_path / "jobs.json"))

    args = cli.build_parser().parse_args([
        "--path", str(tmp_path),
        "acquire", "manifest", str(manifest_file),
    ])
    settings = cli.load_settings(str(tmp_path), None)
    with pytest.raises(RuntimeError, match=r"Could not resolve any manifest entries"):
        cli.command_acquire(args, settings, False)


def test_cli_acquire_manifest_exact_match_disambiguation(tmp_path, monkeypatch):
    import juice_lyrics.cli as cli

    manifest_file = tmp_path / "wanted.txt"
    manifest_file.write_text("Rental\n", encoding="utf-8")

    candidates = [
        {"id": 101, "title": "Rental", "download_url": "https://example.invalid/rental.mp3"},
        {"id": 102, "title": "Rental (v2)", "download_url": "https://example.invalid/rental_v2.mp3"},
    ]
    monkeypatch.setattr(cli, "search_api_advanced", lambda *a, **k: {"results": candidates})
    monkeypatch.setattr(cli, "JobStore", lambda: JobStore(tmp_path / "jobs.json"))

    args = cli.build_parser().parse_args([
        "--path", str(tmp_path),
        "acquire", "manifest", str(manifest_file),
    ])
    settings = cli.load_settings(str(tmp_path), None)
    result = cli.command_acquire(args, settings, False)

    assert result == 0
    jobs = JobStore(tmp_path / "jobs.json").list()
    assert len(jobs) == 1
    assert len(jobs[0].items) == 1
    assert jobs[0].items[0].item.identifier == "101"


def test_cli_acquire_retry_reexecutes_failed_items_and_preserves_completed(tmp_path, monkeypatch, capsys):
    import juice_lyrics.cli as cli

    store = JobStore(tmp_path / "jobs.json")
    item1 = AcquisitionItem(identifier="101", title="Item 1", url="https://example.invalid/1.mp3", destination=tmp_path / "1.mp3")
    item2 = AcquisitionItem(identifier="102", title="Item 2", url="https://example.invalid/2.mp3", destination=tmp_path / "2.mp3")
    job = store.create([item1, item2], job_id="retry-test-job")

    # Mark item1 as COMPLETE, item2 as FAILED
    job.items[0].state = AcquisitionState.COMPLETE
    job.items[0].bytes_written = 100
    job.items[1].state = AcquisitionState.FAILED
    job.items[1].error = "previous timeout"
    store.save(job)

    downloaded = []

    def fake_download(item, policy=None, *, progress=None):
        downloaded.append(item.destination.name)
        item.destination.write_bytes(b"audio")
        return AcquisitionResult(item=item, state=AcquisitionState.COMPLETE, destination=item.destination, bytes_written=5)

    monkeypatch.setattr("juice_lyrics.acquisition.runner.download_to", fake_download)
    monkeypatch.setattr(cli, "JobStore", lambda: JobStore(tmp_path / "jobs.json"))
    monkeypatch.setattr(cli, "_api_get_song", lambda *a, **k: {"id": 102, "name": "Item 2"})

    args = cli.build_parser().parse_args(["acquire", "retry", "retry-test-job"])
    settings = cli.load_settings(str(tmp_path), None)
    result = cli.command_acquire(args, settings, False)

    assert result == 0
    # Crucial: item1 was COMPLETE and was NOT redownloaded
    assert downloaded == ["2.mp3"]

    loaded = JobStore(tmp_path / "jobs.json").get("retry-test-job")
    assert loaded is not None
    assert loaded.state is AcquisitionState.COMPLETE
    assert loaded.items[0].state is AcquisitionState.COMPLETE
    assert loaded.items[1].state is AcquisitionState.COMPLETE


def test_cli_acquire_retry_when_already_complete(tmp_path, monkeypatch, capsys):
    import juice_lyrics.cli as cli

    store = JobStore(tmp_path / "jobs.json")
    item = AcquisitionItem(identifier="101", title="Item 1", url="https://example.invalid/1.mp3", destination=tmp_path / "1.mp3")
    job = store.create([item], job_id="complete-job")
    job.items[0].state = AcquisitionState.COMPLETE
    store.save(job)

    monkeypatch.setattr(cli, "JobStore", lambda: JobStore(tmp_path / "jobs.json"))

    args = cli.build_parser().parse_args(["acquire", "retry", "complete-job"])
    settings = cli.load_settings(str(tmp_path), None)
    result = cli.command_acquire(args, settings, False)

    assert result == 0
    output = capsys.readouterr().out
    assert "already completed or skipped" in output


def test_cli_acquire_retry_nonexistent_job(tmp_path):
    import juice_lyrics.cli as cli

    args = cli.build_parser().parse_args(["acquire", "retry", "does-not-exist"])
    settings = cli.load_settings(str(tmp_path), None)
    with pytest.raises(RuntimeError, match=r"Acquisition job not found"):
        cli.command_acquire(args, settings, False)


def test_cli_acquire_delete_removes_job_and_preserves_audio_files(tmp_path, monkeypatch, capsys):
    import juice_lyrics.cli as cli

    store = JobStore(tmp_path / "jobs.json")
    dest = tmp_path / "downloaded_track.mp3"
    dest.write_bytes(b"downloaded audio data")
    item = AcquisitionItem(identifier="101", title="Track", url="https://example.invalid/track.mp3", destination=dest)
    job = store.create([item], job_id="delete-job")
    job.items[0].state = AcquisitionState.COMPLETE
    store.save(job)

    monkeypatch.setattr(cli, "JobStore", lambda: JobStore(tmp_path / "jobs.json"))

    args = cli.build_parser().parse_args(["acquire", "delete", "delete-job"])
    settings = cli.load_settings(str(tmp_path), None)
    result = cli.command_acquire(args, settings, False)

    assert result == 0
    output = capsys.readouterr().out
    assert "Acquisition job deleted" in output
    assert "delete-job" in output

    # Job record is removed
    assert JobStore(tmp_path / "jobs.json").get("delete-job") is None
    # Downloaded file on disk is preserved
    assert dest.is_file()
    assert dest.read_bytes() == b"downloaded audio data"


def test_cli_acquire_delete_active_job_requires_force(tmp_path, monkeypatch):
    import juice_lyrics.cli as cli

    store = JobStore(tmp_path / "jobs.json")
    item = AcquisitionItem(identifier="101", title="Track", url="https://example.invalid/track.mp3", destination=tmp_path / "track.mp3")
    job = store.create([item], job_id="active-job")
    job.items[0].state = AcquisitionState.DOWNLOADING
    store.save(job)

    monkeypatch.setattr(cli, "JobStore", lambda: JobStore(tmp_path / "jobs.json"))
    settings = cli.load_settings(str(tmp_path), None)

    # Without --force
    args_no_force = cli.build_parser().parse_args(["acquire", "delete", "active-job"])
    with pytest.raises(RuntimeError, match=r"marked as actively in-progress"):
        cli.command_acquire(args_no_force, settings, False)

    # With --force
    args_force = cli.build_parser().parse_args(["acquire", "delete", "active-job", "--force"])
    result = cli.command_acquire(args_force, settings, False)
    assert result == 0
    assert JobStore(tmp_path / "jobs.json").get("active-job") is None


def test_cli_acquire_delete_nonexistent_job(tmp_path):
    import juice_lyrics.cli as cli

    args = cli.build_parser().parse_args(["acquire", "delete", "does-not-exist"])
    settings = cli.load_settings(str(tmp_path), None)
    with pytest.raises(RuntimeError, match=r"Acquisition job not found"):
        cli.command_acquire(args, settings, False)


def test_integrate_acquired_mp3_updates_state_json(tmp_path, monkeypatch):
    import juice_lyrics.state as state_mod
    from juice_lyrics.config.settings import Settings

    state_file = tmp_path / "state.json"
    monkeypatch.setattr(state_mod, "STATE_FILE", state_file)

    mp3 = tmp_path / "Rental.mp3"
    mp3.write_bytes(b"dummy mp3 payload")
    item = AcquisitionItem(identifier="101", title="Rental", url="https://example.invalid/rental.mp3", destination=mp3)

    settings = Settings(music_dir=tmp_path, lyrics_dir=tmp_path / "lyrics")
    result = integrate_downloaded_mp3(
        item,
        song_fetcher=lambda song_id: {
            "id": song_id,
            "name": "Rental",
            "credited_artists": "Juice WRLD",
            "length": "01:00",
            "synced_lyrics": "[00:01.00] hello\n[00:02.00] world",
            "lyrics": "hello\nworld",
        },
        lyrics_dir=tmp_path / "lyrics",
        settings=settings,
    )

    assert result.lyric_type == "SYLT"
    assert state_file.is_file()
    state = state_mod.load_state()
    assert "Rental.mp3" in state["files"]
    entry = state["files"]["Rental.mp3"]
    assert entry["song_id"] == 101
    assert entry["api_name"] == "Rental"
    assert entry["lyric_type"] == "SYLT"
    assert entry["sha256"] == state_mod.sha256_file(mp3)
    assert entry["lrc"] == str(tmp_path / "lyrics" / "Rental.lrc")


def test_later_sync_recognizes_acquired_file_as_already_processed(tmp_path, monkeypatch):
    import juice_lyrics.cli as cli
    import juice_lyrics.state as state_mod
    from juice_lyrics.config.settings import Settings

    state_file = tmp_path / "state.json"
    monkeypatch.setattr(state_mod, "STATE_FILE", state_file)
    monkeypatch.setattr(cli, "STATE_FILE", state_file)

    mp3 = tmp_path / "Rental.mp3"
    mp3.write_bytes(b"dummy mp3 payload")
    item = AcquisitionItem(identifier="101", title="Rental", url="https://example.invalid/rental.mp3", destination=mp3)

    settings = Settings(music_dir=tmp_path, lyrics_dir=tmp_path / "lyrics")
    integrate_downloaded_mp3(
        item,
        song_fetcher=lambda song_id: {
            "id": song_id,
            "name": "Rental",
            "credited_artists": "Juice WRLD",
            "length": "01:00",
            "synced_lyrics": "[00:01.00] hello\n[00:02.00] world",
            "lyrics": "hello\nworld",
        },
        lyrics_dir=tmp_path / "lyrics",
        settings=settings,
    )

    # Verify state recognizes it as current
    state = state_mod.load_state()
    assert cli.state_is_current(state, mp3, settings, want_rmpc=True) is True


def test_synchronized_acquired_lyrics_trigger_rmpc_notification(tmp_path, monkeypatch):
    import juice_lyrics.acquisition.integration as integ
    import juice_lyrics.state as state_mod

    state_file = tmp_path / "state.json"
    monkeypatch.setattr(state_mod, "STATE_FILE", state_file)

    notified = []

    def mock_notify(paths):
        notified.append(paths)
        return len(paths)

    monkeypatch.setattr(integ, "notify_rmpc_index", mock_notify)

    mp3 = tmp_path / "Rental.mp3"
    mp3.write_bytes(b"dummy mp3 payload")
    item = AcquisitionItem(identifier="101", title="Rental", url="https://example.invalid/rental.mp3", destination=mp3)

    result = integrate_downloaded_mp3(
        item,
        song_fetcher=lambda song_id: {
            "id": song_id,
            "name": "Rental",
            "credited_artists": "Juice WRLD",
            "length": "01:00",
            "synced_lyrics": "[00:01.00] hello\n[00:02.00] world",
            "lyrics": "hello\nworld",
        },
        lyrics_dir=tmp_path / "lyrics",
    )

    assert result.rmpc_notified == 1
    assert len(notified) == 1
    assert notified[0] == [tmp_path / "lyrics" / "Rental.lrc"]
    assert "rmpc notified: 1" in result.message


def test_plain_lyrics_only_does_not_trigger_rmpc_notification(tmp_path, monkeypatch):
    import juice_lyrics.acquisition.integration as integ
    import juice_lyrics.state as state_mod

    state_file = tmp_path / "state.json"
    monkeypatch.setattr(state_mod, "STATE_FILE", state_file)

    notified = []

    def mock_notify(paths):
        notified.append(paths)
        return len(paths)

    monkeypatch.setattr(integ, "notify_rmpc_index", mock_notify)

    mp3 = tmp_path / "Rental.mp3"
    mp3.write_bytes(b"dummy mp3 payload")
    item = AcquisitionItem(identifier="101", title="Rental", url="https://example.invalid/rental.mp3", destination=mp3)

    result = integrate_downloaded_mp3(
        item,
        song_fetcher=lambda song_id: {
            "id": song_id,
            "name": "Rental",
            "credited_artists": "Juice WRLD",
            "length": "01:00",
            "synced_lyrics": "",
            "lyrics": "only plain lyrics here",
        },
        lyrics_dir=tmp_path / "lyrics",
    )

    assert result.lyric_type == "USLT"
    assert result.lrc_path is None
    assert result.rmpc_notified == 0
    assert len(notified) == 0


def test_state_synchronization_failure_marks_acquisition_item_failed(tmp_path, monkeypatch):
    import juice_lyrics.acquisition.integration as integ
    from juice_lyrics.acquisition import runner

    mp3 = tmp_path / "Rental.mp3"
    item = AcquisitionItem(identifier="101", title="Rental", url="https://example.invalid/rental.mp3", destination=mp3)

    store = JobStore(tmp_path / "jobs.json")
    job = store.create([item], job_id="state-sync-fail-job")

    def fake_download(item, policy=None, *, progress=None):
        item.destination.write_bytes(b"audio data")
        return AcquisitionResult(item=item, state=AcquisitionState.COMPLETE, destination=item.destination, bytes_written=10)

    monkeypatch.setattr(runner, "download_to", fake_download)
    monkeypatch.setattr(integ, "save_state", lambda s: (_ for _ in ()).throw(OSError("Disk full writing state.json")))

    def failing_postprocess(result):
        return integrate_downloaded_mp3(
            result.item,
            song_fetcher=lambda song_id: {"id": song_id, "name": "Rental", "lyrics": "test"},
        )

    summary = run_job(job, store, postprocess=failing_postprocess)
    assert summary.failed == 1
    loaded = store.get("state-sync-fail-job")
    assert loaded is not None
    assert loaded.items[0].state is AcquisitionState.FAILED
    assert "Failed to synchronize library state" in (loaded.items[0].error or "")


