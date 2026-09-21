from collections import namedtuple
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from juice_lyrics import cli
from juice_lyrics.config.settings import Settings
from juice_lyrics.services.doctor import (
    DoctorCheck,
    DoctorReport,
    DoctorStatus,
    render_support_report,
    run_doctor,
)


Usage = namedtuple("Usage", "total used free")


def _paths(tmp_path):
    return {
        "config_path": tmp_path / "config" / "config.toml",
        "state_file": tmp_path / "data" / "state.json",
        "cache_dir": tmp_path / "cache",
        "backup_dir": tmp_path / "data" / "backups",
        "rmpc_config_path": tmp_path / "rmpc" / "config.ron",
    }


def _run(tmp_path, *, probe=lambda url, timeout: {"count": 1, "results": [{"id": 1}]}, finder=None):
    music = tmp_path / "music"
    music.mkdir(exist_ok=True)
    paths = _paths(tmp_path)
    return run_doctor(
        Settings(music_dir=music),
        **paths,
        api_probe=probe,
        command_finder=finder or (lambda name: f"/usr/bin/{name}"),
        disk_usage=lambda path: Usage(10_000_000_000, 1, 9_000_000_000),
        rmpc_probe=lambda executable: True,
    )


def _check(report, key):
    return next(item for item in report.checks if item.key == key)


def test_healthy_doctor_is_bounded_read_only_and_counts_supported_formats(tmp_path):
    music = tmp_path / "music"
    (music / "nested").mkdir(parents=True)
    for name in ("One.mp3", "nested/Two.FLAC", "Three.m4a"):
        path = music / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"untouched")
    paths = _paths(tmp_path)
    paths["config_path"].parent.mkdir(parents=True)
    paths["config_path"].write_text(f'music_dir = "{music}"\ntimeout = 2\n', encoding="utf-8")
    paths["state_file"].parent.mkdir(parents=True)
    paths["state_file"].write_text('{"files": {"One.mp3": {"song_id": 1}}}', encoding="utf-8")
    paths["cache_dir"].mkdir()
    (paths["cache_dir"] / "page.json").write_text('{"results": []}', encoding="utf-8")
    paths["rmpc_config_path"].parent.mkdir(parents=True)
    paths["rmpc_config_path"].write_text(
        f'lyrics_dir: Some("{music.parent}"),\nenable_lyrics_index: true,\nenable_lyrics_hot_reload: true,\n',
        encoding="utf-8",
    )
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    calls = []

    report = run_doctor(
        Settings(music_dir=music), **paths,
        api_probe=lambda url, timeout: calls.append((url, timeout)) or {"count": 1, "results": [{"id": 1}]},
        command_finder=lambda name: f"/usr/bin/{name}",
        disk_usage=lambda path: Usage(10_000_000_000, 1, 9_000_000_000),
        rmpc_probe=lambda executable: True,
    )

    assert report.failed == 0
    assert _check(report, "library").status is DoctorStatus.PASS
    assert "MP3 1, FLAC 1, M4A 1" in _check(report, "library").detail
    assert _check(report, "catalogue").status is DoctorStatus.PASS
    assert len(calls) == 1 and "page_size=1" in calls[0][0]
    assert {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()} == before


def test_offline_catalogue_is_warning_but_invalid_response_is_failure(tmp_path):
    def offline(url, timeout):
        raise RuntimeError("network timed out")

    offline_report = _run(tmp_path, probe=offline)
    assert _check(offline_report, "catalogue").status is DoctorStatus.WARN
    assert "offline or unreachable" in _check(offline_report, "catalogue").detail

    invalid_report = _run(tmp_path, probe=lambda url, timeout: {"unexpected": []})
    assert _check(invalid_report, "catalogue").status is DoctorStatus.FAIL
    assert "results list" in _check(invalid_report, "catalogue").detail


def test_malformed_state_and_cache_are_reported_without_repair(tmp_path):
    paths = _paths(tmp_path)
    paths["config_path"].parent.mkdir(parents=True)
    paths["config_path"].write_text("timeout = 'not a number'", encoding="utf-8")
    paths["state_file"].parent.mkdir(parents=True)
    paths["state_file"].write_text("{broken", encoding="utf-8")
    paths["cache_dir"].mkdir()
    (paths["cache_dir"] / "broken.json").write_text("not json", encoding="utf-8")
    original_state = paths["state_file"].read_bytes()
    original_cache = (paths["cache_dir"] / "broken.json").read_bytes()

    report = _run(tmp_path)

    assert _check(report, "state").status is DoctorStatus.FAIL
    assert _check(report, "cache").status is DoctorStatus.WARN
    assert _check(report, "config").status is DoctorStatus.FAIL
    assert paths["state_file"].read_bytes() == original_state
    assert (paths["cache_dir"] / "broken.json").read_bytes() == original_cache


def test_missing_and_unreadable_music_directories_are_clear_failures(tmp_path, monkeypatch):
    paths = _paths(tmp_path)
    missing = tmp_path / "missing"
    report = run_doctor(
        Settings(music_dir=missing), **paths,
        api_probe=lambda url, timeout: {"results": []},
        command_finder=lambda name: None,
        disk_usage=lambda path: Usage(1_000_000_000, 0, 900_000_000),
        rmpc_probe=lambda executable: True,
    )
    assert _check(report, "library").status is DoctorStatus.FAIL
    assert "does not exist" in _check(report, "library").detail

    music = tmp_path / "music"
    music.mkdir()
    import juice_lyrics.services.doctor as doctor_module
    real_access = doctor_module.os.access
    monkeypatch.setattr(doctor_module.os, "access", lambda path, mode: False if Path(path) == music else real_access(path, mode))
    report = _run(tmp_path)
    assert _check(report, "library").status is DoctorStatus.FAIL
    assert "not readable" in _check(report, "library").detail


def test_support_report_redacts_home_user_credentials_and_private_contents(tmp_path):
    home = Path("/home/alice")
    report = DoctorReport((
        DoctorCheck(
            "privacy", "Privacy", DoctorStatus.FAIL,
            "/home/alice/Music/private/song.mp3 token=super-secret https://bob:hunter2@example.test",
            "password: dont-print-this",
        ),
    ))

    text = render_support_report(report, home=home)
    parsed = json.loads(text)

    assert parsed["privacy"].startswith("Sanitized")
    for secret in ("alice", "private/song", "super-secret", "bob", "hunter2", "dont-print-this"):
        assert secret not in text
    assert "<HOME_PATH>" in text and "<REDACTED>" in text
    assert "song list" in parsed["privacy"]


def test_malformed_config_still_reaches_cli_doctor_and_support_report_save_is_explicit(tmp_path, monkeypatch, capsys):
    config = tmp_path / "config.toml"
    config.write_text("invalid = [", encoding="utf-8")
    destination = tmp_path / "support.json"
    captured = []
    report = DoctorReport((DoctorCheck("config", "Configuration", DoctorStatus.FAIL, "invalid token=secret"),))
    monkeypatch.setattr(cli, "CONFIG_FILE", config)
    monkeypatch.setattr(cli, "run_doctor", lambda settings, **kwargs: captured.append(settings) or report)

    result = cli.main(["--no-color", "doctor", "--save-report", str(destination)])

    assert result == 1
    assert captured
    assert destination.exists()
    assert "secret" not in destination.read_text(encoding="utf-8")
    output = capsys.readouterr().out
    assert "FAIL  Configuration" in output
    assert "Sanitized support report saved" in output


def test_doctor_parser_exposes_sanitized_report_options():
    args = cli.build_parser().parse_args(["doctor", "--support-report", "--save-report", "report.json"])
    assert args.command == "doctor"
    assert args.support_report is True
    assert args.save_report == "report.json"


def test_missing_required_and_optional_dependencies_are_distinguished(tmp_path, monkeypatch):
    import juice_lyrics.services.doctor as doctor_module

    monkeypatch.setattr(doctor_module.importlib.util, "find_spec", lambda name: None)
    report = _run(tmp_path, finder=lambda name: None)

    assert _check(report, "dependencies").status is DoctorStatus.FAIL
    assert _check(report, "rmpc").status is DoctorStatus.WARN
    assert "Optional" in _check(report, "rmpc").detail
